# Testing Implementation Plan — Automated Sandbox Test Harness

## 1. Current Implementation Inventory

Inspection of the existing repository (`main` @ `9eb3aaa`):

- **CLI (`src/opensource_runner/cli/app.py`)**: 16 working commands (`list`, `select`, `prepare`, `status`, `type`, `pause`/`break`, `resume`, `stop`, `verify`, `run`, `logs`, `config`, `doctor`, `clean`, `version`, `help`) with `--dry-run`, `--local-source`, retrieval/overwrite/license/dependency approval gates.
- **Project Registry (`projects/*.toml`)**: All four target projects registered (`flappy`, `flask-inventory-management`, `flaskblog`, `flatnotes`).
- **GitHub Retrieval (`src/opensource_runner/github/`)**: `git ls-remote --symref` branch/commit pinning, immutable `source-cache/<id>/<sha>/`, local folder snapshot import, SHA-256 manifest, full UTF-8 text/binary classification.
- **Licensing (`src/opensource_runner/licensing/`)**: `LICENSE`/`README`/copyright/third-party notice scanner, `.provenance/license-report.json` + `LICENSE-REPORT.md`, mandatory approval gate for missing/ambiguous/copyleft licenses.
- **Inspection (`src/opensource_runner/projects/inspector.py`)**: Detects Python (stdlib, `requirements.txt`, nested `pyproject.toml`/`uv.lock`, AST import fallback), Node.js (`npm`/`pnpm`/`yarn`), PHP (`composer`), polyglot stacks, Docker/Podman, `.env.example`, and entry points.
- **Typing & VS Code (`src/opensource_runner/typing/`)**: `InputController` ABC (`WindowsInputController`, `LinuxX11InputController`, `LinuxWaylandInputController`, `MockInputController`), dynamic VS Code discovery, focus guard, CRLF-preserving character typing, binary copy, pause/resume/stop.
- **Verification & Checkpoints (`src/opensource_runner/verification/`, `src/opensource_runner/checkpoint/`)**: Per-file & full-project diff + SHA-256 verification; atomic JSON checkpoints with strict state transitions.
- **Execution & Security (`src/opensource_runner/execution/`, `src/opensource_runner/security/`)**: `PythonRuntime`, `NodeRuntime`, `PhpRuntime`, `ContainerRuntime`, `validate_command_argv` (`shell=False`), path traversal & immutable cache guards, log secret redaction.
- **Tests & CI (`tests/`, `.github/workflows/`)**: 35 unit + integration tests (70.63% coverage), `ci.yml`, `security.yml`, `build.yml`, `release.yml`.

## 2. Missing Components

1. Dedicated `src/opensource_runner/testing/` test harness package (orchestrator, disposable sandbox manager, filesystem/network/secret guards, monitored process runner, health checks, HTML/JSON/TXT reporter).
2. `opensource-runner self-test` CLI command (`--all`, `--project`, `--input`, `--dry-run`, `--cleanup`, `--verbose`, `--debug`).
3. `[sandbox]` resource-limit configuration in `RunnerConfig` and `config.example.toml`.
4. Synthetic edge-case test fixtures under `tests/fixtures/` and chaos/failure tests.
5. `.github/workflows/self-test.yml` with zero-secret isolation for third-party test jobs.

## 3. Security Risks & Mitigations

| Risk | Mitigation |
| --- | --- |
| Untrusted third-party code executing on host | Prefer non-root Docker/Podman containers with `--cpus`, `--memory`, `--pids-limit`, `--network none` during execution, mounting only the disposable project directory. Fallback uses an isolated `tempfile` directory + `.venv` outside `$HOME`. |
| Host secret/credential leakage | Explicit environment allowlist (`PATH`, `LANG`, `LC_ALL`, `HOME`, `TEMP`, `TMP`); block `SSH_PRIVATE_KEY`, `GITHUB_TOKEN`, cloud/DB/API credentials; never mount `/home`, `/root`, SSH, Git, or browser dirs. |
| Orphan/hanging processes | `ProcessMonitor` enforces strict timeouts (120s execution, 300s dependency install, 60s health check), terminates gracefully then force-kills, and verifies zero lingering children. |
| GUI app hijacking user's desktop (`Flappy`) | Never open GUI windows on the host display; use headless/virtual display (`Xvfb`) if available or mark `GUI_EXECUTION = SKIPPED` while still validating syntax, imports, assets, and startup structure. |
| Unexpected host filesystem writes | `FilesystemGuard` snapshots allowed directories and checks host sensitive paths before/after tests; `--cleanup` strictly refuses to delete paths not tagged as harness-created. |

## 4. Sandbox Architecture

```text
Host
├── OpenSource Runner CLI (`opensource-runner self-test`)
├── SelfTestOrchestrator
│   ├── Precheck + Bot Unit Tests + CLI Tests + Input Test + VS Code Test
│   └── Per-Project Disposable Sandbox (`tempfile.mkdtemp(prefix="osr-sandbox-")`)
│       ├── Container mode (Docker/Podman): non-root, CPU/RAM/PID limits, single mount
│       │   ├── Phase A (Dependency install): restricted network enabled
│       │   └── Phase B (Execution + Health check): --network none by default
│       └── Fallback mode (Isolated tempdir + .venv + allowlisted env)
├── Guards: FilesystemGuard + NetworkGuard (Env Allowlist) + ProcessMonitor
└── Reports: test-results/{summary.json, summary.html, summary.txt, projects/<id>/*}
```

## 5. Project-Specific Test Strategy

- **`flappy`**: Missing `LICENSE` triggers `WARN`/review gate; pure Python stdlib + `tkinter`; run `compileall`, AST/import check, asset check; GUI execution runs under `xvfb-run` if available, else `SKIPPED` (never hijacks host desktop).
- **`flask-inventory-management`**: MIT license; CRLF text files + binary `flaskDB.db` & `image1.jpg`; AST-inferred `flask` dependency installed in sandbox `.venv`/container; static `compileall` + HTTP `GET /` health check.
- **`flaskblog`**: MIT license; nested `app/pyproject.toml` + `app/uv.lock`; UTF-8 multibyte translations + binary assets; isolated install + HTTP health check on port `1283`.
- **`flatnotes`**: Default branch `develop`; MIT license + bundled `OFL.txt`; polyglot Vue/Vite + FastAPI/Uvicorn + `Dockerfile`; static validation + isolated build/start + HTTP health check on port `8080`.

## 6. Acceptance Criteria

- All stages produce explicit `PASS` / `FAIL` / `SKIPPED` / `UNAVAILABLE` / `WARN` results (never falsely reporting skipped/unavailable checks as `PASS`).
- Single project failure does not abort remaining projects; exit codes: `0` (all required pass), `1` (failure), `2` (infrastructure error).
- `test-results/` contains complete machine-readable (`summary.json`, per-project JSONs) and human-readable (`summary.html`, `summary.txt`) reports.
- Disposable sandboxes are destroyed and verified clean after every run.
- All unit, integration, chaos, lint (`ruff`), type (`mypy`), and build checks pass.

