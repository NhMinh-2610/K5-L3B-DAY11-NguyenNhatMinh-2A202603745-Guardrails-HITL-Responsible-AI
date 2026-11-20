"""Bounded provider retries never replay guards or disguise daily quota failures."""
import asyncio
import json

import httpx
from openai import OpenAI, RateLimitError
import pytest

from agents.agent import create_blue_agent
from assignment.pipeline import build_production_plugins
from core.openai_runtime import OpenAIRunner


@pytest.mark.parametrize("headers,source,expected_delay", [
    ({"retry-after": "3"}, "upstream_provider_shared_pool", 3),
    ({"x-ratelimit-reset": "105000"}, "openrouter_free_tier_per_minute", 6),
    ({}, "openrouter_free_tier_daily", None),
    ({"retry-after": "120"}, "openrouter_free_tier_per_minute", None),
])
def test_retry_respects_limits_without_replaying_plugins(monkeypatch, headers, source, expected_delay):
    requests, waits = [], []

    async def sleep(delay):
        waits.append(delay)

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, headers=headers, json={"error": {
                "message": "rate limited", "metadata": {"limit_source": source},
            }})
        return httpx.Response(200, json={
            "id": "test", "object": "chat.completion", "created": 0,
            "model": "test", "choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": "A savings account holds deposits."}}],
        })

    monkeypatch.setattr("core.openai_runtime.time.time", lambda: 100)
    monkeypatch.setattr("core.openai_runtime.asyncio.sleep", sleep)
    with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
        with OpenAI(api_key="dummy", base_url="https://openrouter.test/v1", max_retries=0, http_client=transport) as client:
            monkeypatch.setattr(OpenAIRunner, "_client", lambda self: client)
            plugins = build_production_plugins()
            agent, runner = create_blue_agent(plugins)
            if expected_delay is None:
                with pytest.raises(RateLimitError):
                    asyncio.run(runner.chat(agent, "What is a savings account?"))
                assert len(requests) == 1 and waits == []
            else:
                assert asyncio.run(runner.chat(agent, "What is a savings account?"))
                assert len(requests) == 2 and waits == [expected_delay]
                assert plugins[2].total_count == 1
            assert plugins[0].total_count == plugins[1].total_count == 1
            assert all(json.loads(request.content)["model"] == runner.model for request in requests)


def test_retry_is_bounded(monkeypatch):
    calls, waits = [], []

    async def sleep(delay):
        waits.append(delay)

    def handler(request):
        calls.append(request)
        return httpx.Response(429, json={"error": {"message": "busy", "metadata": {"limit_source": "upstream_provider_shared_pool"}}})

    monkeypatch.setattr("core.openai_runtime.asyncio.sleep", sleep)
    with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
        with OpenAI(api_key="dummy", base_url="https://openrouter.test/v1", max_retries=0, http_client=transport) as client:
            monkeypatch.setattr(OpenAIRunner, "_client", lambda self: client)
            agent, runner = create_blue_agent(build_production_plugins())
            with pytest.raises(RateLimitError):
                asyncio.run(runner.chat(agent, "What is a savings account?"))
    assert len(calls) == 4 and waits == [10, 20, 40]
