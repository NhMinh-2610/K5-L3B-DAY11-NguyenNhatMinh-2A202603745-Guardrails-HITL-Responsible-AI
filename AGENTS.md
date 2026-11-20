# Repository Guidelines

## Project Structure & Module Organization

This Python 3.10+ VinBank security lab covers guardrails, human approval, and red-team attacks. Follow `CHECKPOINTS.md` for implementation tasks and `RULES.md` for submission constraints.

- `src/main.py`: CLI for checkpoints 2–4.
- `src/guardrails/` and `src/assignment/`: student guardrails, rate limiting, audit, monitoring, and pipeline exercises.
- `src/agents/`, `src/core/`, and `src/attacks/`: agent factories, provider configuration, and attack runners.
- `src/hitl/` and `src/testing/`: reference implementations.
- `tests/smoke/` and `tests/public/`: starter checks and assignment contracts.
- `data/` and `schemas/`: sample inputs, fixed demo secrets, and the results schema.
- `outputs/`: generated evidence; `scripts/grade.py` generates grading reports.

## Build, Test, and Development Commands

Run from the repository root. No separate build step is configured. PowerShell setup:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Configure local API keys before running checkpoints:

- `python src/main.py --part 2`: exercise input/output guardrails.
- `python src/main.py --part 3`: generate defense results, audit logs, and metrics after completing the pipeline.
- `python src/main.py --part 4`: run attacks against Red and Red Advance.
- `python -m pytest -q`: run the default smoke suite.
- `python -m pytest tests/public -q`: run assignment contracts.
- `python scripts/grade.py --submission-dir . --out outputs/grade_report.json`: validate artifacts, run public tests, and generate `lab_report.md`.

## Coding Style & Naming Conventions

Use four-space indentation, `snake_case` functions/modules, `PascalCase` classes, and `UPPER_SNAKE_CASE` constants. Follow existing type hints, docstrings, and async plugin callbacks. Preserve public signatures and explicit `"ALLOW"`/`"BLOCK"` statuses. No formatter or linter is configured.

## Testing Guidelines

Use pytest files named `test_*.py` and functions named `test_*`. Smoke tests run without API keys using fake models. Public tests can fail until starter TODOs are completed; results-contract tests skip until `outputs/results.json` exists. Add regression cases for changed security behavior. No numerical coverage threshold is configured.

## Commit & Pull Request Guidelines

History uses short descriptions such as `change model blue`; no formal commit format is established. Use focused, descriptive commits. PRs should explain behavior changes, identify affected checkpoints or issues, and report validation commands and results.

## Security & Generated Artifacts

Keep real credentials in untracked `.env`; commit only placeholder configuration. Preserve `data/protected/vinbank_secrets.json`. Generate submission evidence through lab commands and reports through the grader; never fabricate or manually edit results. Include required generated JSON artifacts when submitting.
