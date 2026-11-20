"""
OpenAI SDK runtime — dùng cho:

  Blue Team → OpenRouter liquid/lfm-3-1.7b:free (create_blue_pair)
  Red Team  → OpenAI gpt-4o-mini (create_openai_pair) khi RED_TEAM_PROVIDER=openai

Gemini Red Team dùng Google ADK trong agents/*.py — không đi qua file này.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from inspect import isawaitable
import math
import time
from typing import Any, Callable

from core.config import (
    get_red_model,
    get_red_provider,
    get_blue_model,
    get_blue_provider,
    blue_client_kwargs,
    red_openai_client_kwargs,
    PROVIDER_OPENROUTER,
)


def _openrouter_retry_delay(error, attempt: int) -> float | None:
    """Respect server reset times, without retrying a depleted daily quota."""
    body = error.body if isinstance(error.body, dict) else {}
    detail = body.get("error", body)
    metadata = detail.get("metadata", {}) if isinstance(detail, dict) else {}
    if not isinstance(metadata, dict):
        metadata = {}
    if metadata.get("limit_source") == "openrouter_free_tier_daily":
        return None
    headers = {name.lower(): value for name, value in error.response.headers.items()}
    if isinstance(metadata.get("headers"), dict):
        headers.update({name.lower(): str(value) for name, value in metadata["headers"].items()})
    delay = min(10 * 2 ** attempt, 40)
    try:
        if "retry-after" in headers:
            try:
                delay = float(headers["retry-after"])
            except ValueError:
                delay = parsedate_to_datetime(headers["retry-after"]).timestamp() - time.time()
        elif "x-ratelimit-reset" in headers:
            delay = float(headers["x-ratelimit-reset"]) / 1000 - time.time() + 1
    except (ValueError, TypeError, OverflowError):
        pass
    if not math.isfinite(delay) or delay > 60:
        return None
    return max(0, delay)


@dataclass
class OpenAIAgent:
    name: str
    instruction: str
    provider: str = "openai"


@dataclass
class _MockInvocationContext:
    user_id: str = "student"


@dataclass
class OpenAIRunner:
    """Optional ADK-style plugins + Chat Completions."""

    app_name: str
    model: str
    plugins: list = field(default_factory=list)
    provider: str = "openai"
    temperature: float = 0.4
    client_kwargs: dict = field(default_factory=dict)
    input_hooks: list[Callable[[str], str | None]] = field(default_factory=list)
    output_hooks: list[Callable[[str], str]] = field(default_factory=list)

    def _client(self):
        from openai import OpenAI

        if not self.client_kwargs.get("api_key"):
            raise RuntimeError(f"Missing API key for {self.provider}; configure local .env.")
        retries = 0 if self.provider == PROVIDER_OPENROUTER else 1
        return OpenAI(timeout=60, max_retries=retries, **(self.client_kwargs or {}))

    async def chat(self, agent: OpenAIAgent, user_message: str) -> str:
        for hook in self.input_hooks:
            blocked = hook(user_message)
            if blocked:
                return blocked

        block_msg = await self._run_input_plugins(user_message)
        if block_msg is not None:
            return block_msg

        client = self._client()
        from openai import RateLimitError

        attempts = 4 if self.provider == PROVIDER_OPENROUTER else 1
        for attempt in range(attempts):
            try:
                completion = client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": agent.instruction},
                        {"role": "user", "content": user_message},
                    ],
                    temperature=self.temperature,
                )
                break
            except RateLimitError as error:
                if attempt == attempts - 1:
                    raise
                delay = _openrouter_retry_delay(error, attempt)
                if delay is None:
                    raise
                print(f"OpenRouter HTTP 429: retry {attempt + 1}/{attempts - 1} after {delay:.1f}s.", flush=True)
                await asyncio.sleep(delay)
        text = (completion.choices[0].message.content or "").strip()
        if not text:
            raise RuntimeError("Provider returned an empty response")

        for hook in self.output_hooks:
            text = hook(text)

        text = await self._run_output_plugins(text)
        return text

    async def _run_input_plugins(self, user_message: str) -> str | None:
        if not self.plugins:
            return None
        from google.genai import types

        user_content = types.Content(
            role="user",
            parts=[types.Part.from_text(text=user_message)],
        )
        ctx = _MockInvocationContext()
        for plugin in self.plugins:
            cb = getattr(plugin, "on_user_message_callback", None)
            if cb is None:
                continue
            result = cb(invocation_context=ctx, user_message=user_content)
            if isawaitable(result):
                result = await result
            if result is None:
                continue
            return _content_to_text(result)
        return None

    async def _run_output_plugins(self, text: str) -> str:
        if not self.plugins or not text:
            return text
        from google.genai import types

        content = types.Content(
            role="model", parts=[types.Part.from_text(text=text)]
        )

        class _Resp:
            pass

        llm_response = _Resp()
        llm_response.content = content

        class _Ctx:
            pass

        for plugin in self.plugins:
            cb = getattr(plugin, "after_model_callback", None)
            if cb is None:
                continue
            out = cb(callback_context=_Ctx(), llm_response=llm_response)
            if isawaitable(out):
                out = await out
            if out is not None and getattr(out, "content", None) is not None:
                llm_response = out
        return _content_to_text(llm_response.content)


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = getattr(content, "parts", None) or []
    chunks = []
    for part in parts:
        t = getattr(part, "text", None)
        if t:
            chunks.append(t)
    return "".join(chunks)


def _make_pair(
    *,
    name: str,
    instruction: str,
    app_name: str,
    model: str,
    provider: str,
    client_kwargs: dict,
    plugins: list | None = None,
    input_hooks: list | None = None,
    output_hooks: list | None = None,
    temperature: float = 0.4,
) -> tuple[OpenAIAgent, OpenAIRunner]:
    agent = OpenAIAgent(name=name, instruction=instruction, provider=provider)
    runner = OpenAIRunner(
        app_name=app_name,
        model=model,
        provider=provider,
        client_kwargs=client_kwargs,
        plugins=list(plugins or []),
        input_hooks=list(input_hooks or []),
        output_hooks=list(output_hooks or []),
        temperature=temperature,
    )
    return agent, runner


def create_blue_pair(
    *,
    name: str,
    instruction: str,
    app_name: str,
    plugins: list | None = None,
    input_hooks: list | None = None,
    output_hooks: list | None = None,
    temperature: float = 0.4,
) -> tuple[OpenAIAgent, OpenAIRunner]:
    """Blue Team — always OpenRouter liquid/lfm-3-1.7b:free."""
    return _make_pair(
        name=name,
        instruction=instruction,
        app_name=app_name,
        model=get_blue_model(),
        provider=get_blue_provider(),
        client_kwargs=blue_client_kwargs(),
        plugins=plugins,
        input_hooks=input_hooks,
        output_hooks=output_hooks,
        temperature=temperature,
    )


def create_openai_pair(
    *,
    name: str,
    instruction: str,
    app_name: str,
    plugins: list | None = None,
    input_hooks: list | None = None,
    output_hooks: list | None = None,
    temperature: float = 0.4,
    model: str | None = None,
) -> tuple[OpenAIAgent, OpenAIRunner]:
    """Red Team OpenAI path (default = soft model; advance may pass harder)."""
    return _make_pair(
        name=name,
        instruction=instruction,
        app_name=app_name,
        model=model or get_red_model(),
        provider=get_red_provider(),
        client_kwargs=red_openai_client_kwargs(),
        plugins=plugins,
        input_hooks=input_hooks,
        output_hooks=output_hooks,
        temperature=temperature,
    )
