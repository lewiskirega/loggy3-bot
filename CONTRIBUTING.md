# Contributing to OpenSource Runner

Thank you for contributing to **OpenSource Runner**!

## Branching & Pull Request Workflow

1. Branch off `main` using a descriptive prefix:
   - `feature/<name>`
   - `fix/<name>`
   - `chore/<name>`
   - `docs/<name>`
2. Never commit generated project data (`source-cache/`, `workspace/`, `state/`, `logs/`, `.provenance/`, `.venv/`, `dist/`, `.env`).
3. Ensure all quality checks pass locally before opening a PR:
   ```bash
   ruff format --check .
   ruff check .
   mypy src
   python -m pytest -v --cov=opensource_runner
   python -m build
   ```
4. Never introduce AI/LLM code generation for imported third-party projects or bypass license, verification, or execution approval gates.
5. Never execute third-party repositories inside standard CI tests — use local fixtures and mocked controllers.

## Development Setup

```bash
python -m venv .venv
# Windows CMD: .venv\Scripts\activate
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
# Linux: source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Optional pre-commit hooks are configured in `.pre-commit-config.yaml`.
