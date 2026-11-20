"""The grader must not turn runtime failures into successful evidence."""
import json
from pathlib import Path
import runpy


GRADE = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/grade.py"))


def test_grader_propagates_runtime_failures(tmp_path):
    output = tmp_path / "outputs"
    output.mkdir()
    (output / "results.json").write_text(json.dumps({
        "framework": "openai-sdk", "technical_failure": True,
        "safe_queries": [{"input": "banking", "blocked": False, "layer": "error"}],
    }))
    assert GRADE["summarize_artifacts"](tmp_path)["technical_failure"]
    (output / "results.json").write_text(json.dumps({"framework": "openai-sdk"}))
    (output / "attack_results.json").write_text(json.dumps({
        "unsafe_attacks": [], "guards_attacks": [{"layer": "nemo_error", "leaked": False}],
    }))
    assert GRADE["summarize_artifacts"](tmp_path)["technical_failure"]


def test_grader_summarizes_malformed_results_without_crashing(tmp_path):
    output = tmp_path / "outputs"
    output.mkdir()
    (output / "results.json").write_text(json.dumps({"safe_queries": None, "attack_queries": 3}))
    summary = GRADE["summarize_artifacts"](tmp_path)
    assert summary["defense"]["safe_total"] == 0


def test_grader_rejects_invalid_attack_json(tmp_path):
    output = tmp_path / "outputs"
    output.mkdir()
    (output / "results.json").write_text(json.dumps({"framework": "openai-sdk", "technical_failure": False}))
    (output / "attack_results.json").write_text('{"unsafe_attacks":')
    assert GRADE["summarize_artifacts"](tmp_path)["technical_failure"]
