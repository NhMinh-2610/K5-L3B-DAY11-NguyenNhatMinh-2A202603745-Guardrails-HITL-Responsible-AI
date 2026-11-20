"""Resume reuses actual saved responses, never unfinished/error cases."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from attacks import attacks
from core.gemini_quota import GeminiQuotaError


@pytest.fixture
def cases(monkeypatch):
    monkeypatch.setenv("RED_TEAM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.5-flash")
    return [{"id": number, "category": "test", "input": f"banking {number}"} for number in range(1, 6)]


def test_resume_retries_only_pending_and_failed_cases(monkeypatch, tmp_path, cases):
    calls = []
    stopped = [False]

    async def chat(agent, runner, prompt):
        calls.append(prompt)
        if prompt == "banking 3" and not stopped[0]:
            stopped[0] = True
            raise GeminiQuotaError("daily_quota")
        return "A banking answer.", None

    monkeypatch.setattr(attacks, "chat_with_agent", chat)
    path = tmp_path / "unsafe_attack_result.json"
    agent = SimpleNamespace(instruction="internal test context")

    def run(resume):
        return asyncio.run(attacks.run_attacks(agent, None, cases, "red_default", output_path=path, resume=resume))

    assert len(run(False)) == 3
    partial = json.loads(path.read_text(encoding="utf-8"))
    assert partial["completed_count"] == 2 and not partial["complete"]
    assert len(run(True)) == 5
    assert calls == ["banking 1", "banking 2", "banking 3", "banking 3", "banking 4", "banking 5"]
    assert json.loads(path.read_text(encoding="utf-8"))["complete"]
    calls.clear()
    assert len(run(True)) == 5 and not calls
    monkeypatch.setenv("GEMINI_MODEL", "another-model")
    assert len(run(True)) == 5 and len(calls) == 5


def test_cancelled_run_preserves_each_completed_case(monkeypatch, tmp_path, cases):
    calls = []

    async def chat(agent, runner, prompt):
        calls.append(prompt)
        if prompt == "banking 2":
            raise asyncio.CancelledError()
        return "A banking answer.", None

    monkeypatch.setattr(attacks, "chat_with_agent", chat)
    path = tmp_path / "checkpoint.json"
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(attacks.run_attacks(SimpleNamespace(instruction="test"), None, cases, output_path=path))
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    assert checkpoint["completed_count"] == 1 and not checkpoint["complete"]
    assert len(checkpoint["results"]) == 1


def test_nemo_error_is_not_a_reusable_success(monkeypatch, tmp_path, cases):
    calls = []

    async def chat(agent, runner, prompt):
        calls.append(prompt)
        return "Request blocked: NeMo Guardrails input check failed (GeminiQuotaError). Fail-closed — please try again later.", None

    monkeypatch.setattr(attacks, "chat_with_agent", chat)
    path = tmp_path / "checkpoint.json"
    agent = SimpleNamespace(instruction="test")
    for _ in range(2):
        rows = asyncio.run(attacks.run_attacks(agent, None, cases, "red_advance", output_path=path, resume=True))
        assert len(rows) == 1 and rows[0]["layer"] == "nemo_error"
    assert len(calls) == 2
    assert json.loads(path.read_text(encoding="utf-8"))["completed_count"] == 0


def test_partial_combined_evidence_is_marked_incomplete(monkeypatch, tmp_path, cases):
    path = attacks.save_attack_results(
        unsafe_results=[{"id": 1, "input": "banking", "leaked": False}],
        guards_results=[], filepath=tmp_path / "attack_results.json", expected_per_target=5,
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert not data["complete"] and data["technical_failure"]


def test_cp4_skips_the_separate_warmup(monkeypatch, tmp_path, cases):
    import main
    from agents import agent, guards_agent

    calls = []
    monkeypatch.setattr(agent, "create_red_agent_default", lambda: (None, None))
    monkeypatch.setattr(guards_agent, "create_red_agent_advance", lambda: (None, None))

    async def warmup(*args):
        raise AssertionError("Unnecessary warmup API call")

    async def run(*args, **kwargs):
        calls.append((kwargs["target_name"], kwargs["resume"]))
        return [{"id": row["id"], "input": row["input"], "leaked": False} for row in cases]

    save = attacks.save_attack_results
    monkeypatch.setattr(agent, "test_agent", warmup)
    monkeypatch.setattr(attacks, "run_attacks", run)
    monkeypatch.setattr(attacks, "save_attack_results", lambda **kwargs: save(**kwargs, filepath=tmp_path / "attack_results.json"))
    asyncio.run(main.part4_attacks(resume=True))
    assert calls == [("red_default", True), ("red_advance", True)]
