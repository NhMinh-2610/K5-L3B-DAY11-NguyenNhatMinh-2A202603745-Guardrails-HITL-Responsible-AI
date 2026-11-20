"""Shared pacing and bounded retries for Gemini ADK and NeMo calls."""
from __future__ import annotations

import asyncio
from email.utils import parsedate_to_datetime
import math
import os
import time
from weakref import WeakKeyDictionary


class GeminiQuotaError(RuntimeError):
    """Safe-to-log reason for pausing a run; never includes API response bodies."""

    def __init__(self, reason: str, retry_after: float | None = None):
        self.reason = reason
        self.retry_after = retry_after
        super().__init__(f"Gemini run paused: {reason}. Check AI Studio quota and rerun with --resume.")


def output_token_limit() -> int:
    value = int(os.environ.get("GEMINI_MAX_OUTPUT_TOKENS", "1024"))
    if value < 1:
        raise ValueError("GEMINI_MAX_OUTPUT_TOKENS must be positive")
    return value


def _limit_info(error):
    """Understand both google-genai and NeMo's wrapped HTTP errors."""
    seen = set()
    while isinstance(error, BaseException) and id(error) not in seen:
        seen.add(id(error))
        inner = getattr(error, "inner_exception", None)
        if isinstance(inner, BaseException) and id(inner) not in seen:
            error = inner
            continue
        status = getattr(error, "code", None) or getattr(error, "status_code", None) or getattr(error, "status", None)
        if status in (429, 503):
            body = getattr(error, "details", None) or getattr(error, "body", None) or {}
            body = body.get("error", body) if isinstance(body, dict) else {}
            details = body.get("details", []) if isinstance(body, dict) else []
            daily = False
            zero = False
            delay = None
            for detail in details if isinstance(details, list) else []:
                if not isinstance(detail, dict):
                    continue
                for violation in detail.get("violations", []):
                    identifier = (str(violation.get("quotaId", "")) + str(violation.get("quotaMetric", ""))).lower()
                    daily |= any(marker in identifier for marker in ("perday", "per_day", "daily"))
                    zero |= str(violation.get("quotaValue", "")) == "0"
                retry = detail.get("retryDelay")
                if isinstance(retry, str) and retry.endswith("s"):
                    try:
                        delay = float(retry[:-1])
                    except ValueError:
                        pass
            headers = getattr(error, "response_headers", None) or getattr(getattr(error, "response", None), "headers", {})
            retry_after = headers.get("retry-after") or headers.get("Retry-After")
            if retry_after:
                try:
                    delay = float(retry_after)
                except ValueError:
                    try:
                        delay = parsedate_to_datetime(retry_after).timestamp() - time.time()
                    except (ValueError, TypeError, OverflowError):
                        pass
            if delay is not None and (not math.isfinite(delay) or delay < 0):
                delay = None
            return daily, zero, delay
        error = getattr(error, "inner_exception", None) or error.__cause__
    return None


class GeminiQuotaPolicy:
    def __init__(self, interval=None, retries=None):
        self.interval = float(os.environ.get("GEMINI_MIN_INTERVAL_SECONDS", "15")) if interval is None else interval
        self.retries = int(os.environ.get("GEMINI_MAX_RETRIES", "2")) if retries is None else retries
        if not math.isfinite(self.interval) or self.interval < 0 or not 0 <= self.retries <= 5:
            raise ValueError("Gemini interval must be nonnegative; retry count must be 0..5")
        self._last_started = None
        self._lock = asyncio.Lock()
        self.stopped = None

    async def run(self, operation):
        async with self._lock:
            if self.stopped:
                raise self.stopped
            for attempt in range(self.retries + 1):
                if self._last_started is not None:
                    wait = self.interval - (time.monotonic() - self._last_started)
                    if wait > 0:
                        await asyncio.sleep(wait)
                self._last_started = time.monotonic()
                try:
                    return await operation()
                except Exception as error:
                    info = _limit_info(error)
                    if info is None:
                        raise
                    daily, zero, delay = info
                    reason = "daily_quota" if daily else "quota_unavailable" if zero else "retry_exhausted"
                    if daily or zero or attempt == self.retries or (delay is not None and delay > 60):
                        if not (daily or zero) and delay is not None and delay > 60:
                            reason = "wait_exceeds_60s"
                        self.stopped = GeminiQuotaError(reason, delay)
                        raise self.stopped from None
                    delay = delay if delay is not None else min(15 * 2 ** attempt, 60)
                    print(f"Gemini busy/quota window: retry {attempt + 1}/{self.retries} after {delay:.1f}s.", flush=True)
                    await asyncio.sleep(delay)


_policies = WeakKeyDictionary()


def get_gemini_policy() -> GeminiQuotaPolicy:
    loop = asyncio.get_running_loop()
    if loop not in _policies:
        _policies[loop] = GeminiQuotaPolicy()
    return _policies[loop]


def create_gemini_model(model: str):
    """Wrap the actual ADK model call, outside before/after-model guardrails."""
    from google.adk.models.google_llm import Gemini
    from google.genai import types

    class QuotaAwareGemini(Gemini):
        async def generate_content_async(self, llm_request, stream=False):
            parent = super().generate_content_async

            async def request():
                return [event async for event in parent(llm_request, stream=stream)]

            for event in await get_gemini_policy().run(request):
                yield event

    # One retry layer only; SDK retries would otherwise multiply quota use.
    return QuotaAwareGemini(model=model, retry_options=types.HttpRetryOptions(attempts=1))
