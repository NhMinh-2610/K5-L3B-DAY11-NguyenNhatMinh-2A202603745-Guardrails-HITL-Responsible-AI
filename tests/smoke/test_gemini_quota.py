"""Quota behavior uses a fake clock and fake API errors, never live keys."""
import asyncio
from types import SimpleNamespace

from google.genai.errors import ClientError, ServerError
import httpx
import pytest

from core.gemini_quota import GeminiQuotaError, GeminiQuotaPolicy, create_gemini_model


def quota_error(quota_id="GenerateRequestsPerMinute", retry="0s", value=None):
    violation = {"quotaId": quota_id}
    if value is not None:
        violation["quotaValue"] = value
    return ClientError(429, {"error": {"details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [violation]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": retry},
    ]}})


@pytest.fixture
def fake_clock(monkeypatch):
    now, waits = [100.0], []

    async def sleep(delay):
        waits.append(delay)
        now[0] += delay

    monkeypatch.setattr("core.gemini_quota.time.monotonic", lambda: now[0])
    monkeypatch.setattr("core.gemini_quota.asyncio.sleep", sleep)
    return now, waits


def test_paces_sequential_requests(fake_clock):
    now, waits = fake_clock
    calls = []

    async def request():
        calls.append(now[0])
        return "ok"

    async def run():
        policy = GeminiQuotaPolicy(interval=15)
        await policy.run(request)
        await policy.run(request)

    asyncio.run(run())
    assert calls == [100, 115] and waits == [15]


def test_temporary_limit_respects_google_retry_info(fake_clock):
    calls = []

    async def request():
        calls.append(1)
        if len(calls) == 1:
            raise quota_error(retry="7.5s")
        return "ok"

    async def run():
        assert await GeminiQuotaPolicy(interval=0).run(request) == "ok"

    asyncio.run(run())
    assert len(calls) == 2 and fake_clock[1] == [7.5]


@pytest.mark.parametrize("identifier,value,reason", [
    ("GenerateRequestsPerDayPerProjectPerModel-FreeTier", None, "daily_quota"),
    ("GenerateRequestsPerMinute", "0", "quota_unavailable"),
])
def test_hard_quota_stops_without_retries_or_later_requests(fake_clock, identifier, value, reason):
    calls = []

    async def request():
        calls.append(1)
        raise quota_error(identifier, retry="120s", value=value)

    async def run():
        policy = GeminiQuotaPolicy(interval=0)
        for _ in range(2):
            with pytest.raises(GeminiQuotaError) as caught:
                await policy.run(request)
            assert caught.value.reason == reason

    asyncio.run(run())
    assert len(calls) == 1 and fake_clock[1] == []


def test_503_retry_is_bounded(fake_clock):
    calls = []

    async def request():
        calls.append(1)
        raise ServerError(503, {"error": {"message": "unavailable"}})

    async def run():
        with pytest.raises(GeminiQuotaError, match="retry_exhausted"):
            await GeminiQuotaPolicy(interval=0, retries=2).run(request)

    asyncio.run(run())
    assert len(calls) == 3 and fake_clock[1] == [15, 30]


def test_retry_after_header(fake_clock):
    calls = []

    async def request():
        calls.append(1)
        if len(calls) == 1:
            raise ClientError(429, {"error": {}}, httpx.Response(429, headers={"retry-after": "4"}))
        return "ok"

    asyncio.run(GeminiQuotaPolicy(interval=0).run(request))
    assert fake_clock[1] == [4]


def test_long_wait_and_authentication_do_not_retry(fake_clock):
    async def request():
        raise quota_error(retry="120s")

    with pytest.raises(GeminiQuotaError, match="wait_exceeds_60s"):
        asyncio.run(GeminiQuotaPolicy(interval=0).run(request))

    async def denied():
        raise ClientError(403, {"error": {"message": "denied"}})

    with pytest.raises(ClientError):
        asyncio.run(GeminiQuotaPolicy(interval=0).run(denied))
    assert fake_clock[1] == []


def test_adk_retry_discards_partial_events(monkeypatch, fake_clock):
    from google.adk.models.google_llm import Gemini

    monkeypatch.setenv("GEMINI_MIN_INTERVAL_SECONDS", "0")
    calls = []

    async def generate(self, llm_request, stream=False):
        calls.append(1)
        if len(calls) == 1:
            yield SimpleNamespace(text="partial")
            raise quota_error()
        yield SimpleNamespace(text="final")

    monkeypatch.setattr(Gemini, "generate_content_async", generate)
    model = create_gemini_model("gemini-3.5-flash")

    async def run():
        return [event.text async for event in model.generate_content_async(None)]

    assert asyncio.run(run()) == ["final"] and len(calls) == 2
    assert model.retry_options.attempts == 1


def test_nemo_quota_failure_remains_fail_closed(monkeypatch, fake_clock):
    from agents.red_advance_nemo import NemoRailsGuard
    from nemoguardrails.exceptions import LLMCallException, LLMRateLimitError
    from nemoguardrails.testing import FakeLLMModel

    monkeypatch.setenv("GEMINI_MIN_INTERVAL_SECONDS", "0")
    guard = NemoRailsGuard(llm=FakeLLMModel(responses=[]))
    guard._use_gemini_quota = True
    body = {"error": {"details": [{"violations": [{"quotaId": "RequestsPerDay"}]}]}}

    async def check(*args, **kwargs):
        raise LLMCallException(LLMRateLimitError(429, "limited", body=body), status=429)

    monkeypatch.setattr(guard.rails, "check_async", check)
    verdict = asyncio.run(guard.check_input("What is a savings account?"))
    assert not verdict.allowed and verdict.error == "GeminiQuotaError"
    assert guard.stats["errors"] == 1 and "Fail-closed" in verdict.message
