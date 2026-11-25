# OpenSource Runner

[![CI](https://github.com/lewiskirega/loggy3-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/lewiskirega/loggy3-bot/actions/workflows/ci.yml)
[![Security](https://github.com/lewiskirega/loggy3-bot/actions/workflows/security.yml/badge.svg)](https://github.com/lewiskirega/loggy3-bot/actions/workflows/security.yml)
[![Self-Test](https://github.com/lewiskirega/loggy3-bot/actions/workflows/self-test.yml/badge.svg)](https://github.com/lewiskirega/loggy3-bot/actions/workflows/self-test.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

A cross-platform terminal automation bot for **Windows 10/11** and **Linux** (Fedora, Ubuntu, Debian, Arch, etc.) with a **minimal, question-driven interactive wizard**, **direct CLI commands**, and an **automated disposable sandbox test harness**.

It retrieves open-source projects from GitHub (or a local source folder), pins exact commits, inspects licenses and technology stacks, reproduces source files into isolated Visual Studio Code workspaces via simulated individual keyboard keystrokes, verifies every file with diffs and SHA-256 hashes, maintains persistent checkpoints, and runs the project **only when you explicitly confirm or enter `opensource-runner run`**.

---

## Features

- **Minimal Interactive Terminal Wizard (Default)**: Launch `opensource-runner` and answer one clear question at a time (`Enter` for default, `b` to go back, `q` to quit, `Ctrl+C` to pause/exit safely) with automatic plain-text ASCII fallback on limited terminals.
- **Direct CLI Commands**: Full scriptable CLI sharing the exact same backend services as the interactive wizard.
- **Automated Disposable Sandbox Test Harness (`self-test`)**: Validates the runner, CLI, input subsystem, VS Code discovery, and all four starter projects inside disposable Docker/Podman containers (or isolated tempdir/venv fallback) with resource limits, secret allowlisting, filesystem guards, HTTP/headless health checks, guaranteed cleanup, and JSON/HTML/TXT reports under `test-results/`.
- **Transparent Provenance & No AI Code Generation**: Records repository URL, branch, exact commit SHA, retrieval timestamp, license report, run config, and SHA-256 manifests under `.provenance/`. Never claims authorship of third-party source.
- **Immutable Source Cache & Isolated Workspaces**: Keeps untouched source under `source-cache/<id>/<commit>/` and reproduces files into `workspace/<id>/`.
- **Keyboard-Event Reproduction**: Types text files character-by-character via platform-native input backends (never clipboard pasting) and copies binary files with SHA-256 verification.
- **Strict Verification, Checkpoints & Approval Gates**: Verifies every file on save and performs full-project comparison before reaching `READY_TO_RUN`. Requires explicit confirmation before retrieval, license warnings, overwrites, dependency installs, execution, or security setting changes.
- **Host Diagnostics (`doctor`)**: Checks OS, Python, Git, VS Code CLI, runtimes, display server, keyboard input backend, and directory permissions.

---

## Architecture

```text
INTERACTIVE WIZARD (`opensource-runner`)  /  DIRECT CLI (`opensource-runner <cmd>`)
                                    │
                                    ▼
  PROJECT REGISTRY (projects/*.toml)
    -> SELECT (attribution notice)
    -> PREPARE (retrieval approval -> GitHub/local -> commit pin -> immutable source-cache
                -> license check -> multi-stack inspection -> .provenance/run-config.json)
    -> TYPE (VS Code workspace -> focus guard -> keyboard input events / binary copy
             -> per-file verification -> atomic checkpoint)
    -> VERIFY (full diff + SHA-256 -> READY_TO_RUN)
    -> WAIT FOR USER
    -> RUN (command validation -> dependency approval -> isolated runtime execution)

  AUTOMATED SAFETY HARNESS (`opensource-runner self-test`)
    -> Precheck + CLI + Input + VS Code + Security Guards
    -> Disposable Sandbox (Docker/Podman non-root or isolated tempdir + allowlisted env)
    -> Per-project retrieval, checkpoint/resume test, static validation, deps, healthcheck, cleanup
    -> Reports: test-results/{summary.json, summary.html, summary.txt, projects/<id>/*}
```

---

## Supported Platforms & Requirements

- **Windows 10 / Windows 11** (native Python + Git + VS Code; no WSL, Cygwin, or MSYS2 required)
- **Linux** (Fedora, Ubuntu, Debian, Arch, and similar distributions)
- **Python 3.12+** (tested on Python 3.12 and 3.13)
- **Git CLI**
- **Visual Studio Code** with `code` CLI available
- **Optional**: Docker or Podman for containerized sandboxes and container runtimes

---

## Windows Installation

### 1. Install Prerequisites

Install **Python 3.12+**, **Git**, and **Visual Studio Code** (ensure `code` is on PATH). Verify:

```cmd
python --version
git --version
code --version
```

### 2. Clone & Install

**Windows Command Prompt (CMD):**

```cmd
git clone https://github.com/lewiskirega/loggy3-bot.git
cd loggy3-bot
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e .
```

**Windows PowerShell:**

```powershell
git clone https://github.com/lewiskirega/loggy3-bot.git
cd loggy3-bot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

> **PowerShell Execution Policy Note**: If PowerShell blocks `Activate.ps1`, allow it for the current session only with `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` (do not lower your system-wide execution policy), or use Windows Command Prompt.

### 3. Verify & Launch

```cmd
opensource-runner doctor
opensource-runner
```

---

## Linux Installation

### Fedora Prerequisites

```bash
sudo dnf install git python3 python3-pip
```

### Ubuntu / Debian Prerequisites

```bash
sudo apt update
sudo apt install git python3 python3-venv python3-pip
```

### Clone & Install

```bash
git clone https://github.com/lewiskirega/loggy3-bot.git
cd loggy3-bot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

### Isolated CLI Installation with `pipx`

```bash
pipx install .
opensource-runner doctor
```

---

## Wayland / X11 Support & VS Code Setup

Run `opensource-runner doctor` to inspect your display server and keyboard backend:

- **Windows 10/11**: Uses native Win32 `SendInput` (`KEYEVENTF_UNICODE`) — no administrator privileges required.
- **Linux X11**: Uses `xdotool` (`sudo dnf install xdotool` / `sudo apt install xdotool`).
- **Linux Wayland**: Supports `ydotool` (with `ydotoold` and `/dev/uinput` permission) or `dotool`. On wlroots compositors (Sway, Hyprland), `wtype` is also supported; GNOME Mutter does not implement `zwp_virtual_keyboard_v1`, so `ydotool` or `dotool` is required on GNOME Wayland:
  ```bash
  sudo dnf install ydotool
  sudo systemctl enable --now ydotoold
  ```
- **Fail-Closed Behavior**: If the active environment blocks synthetic keyboard input, `opensource-runner type` stops safely and never falls back to clipboard pasting.
- **VS Code Discovery**: `code` is located dynamically via `config.toml`, `PATH`, and platform-standard locations (User/System installs on Windows, Snap/Flatpak/usr on Linux).

---

## Interactive Terminal Wizard (Default)

Launch the bot with no arguments:

```bash
opensource-runner
```

```text
╭──────────────────────╮
│ OPENSOURCE RUNNER    │
│ Interactive Terminal │
╰──────────────────────╯

Welcome! What would you like to do?

  1. Prepare a project
  2. Continue previous work
  3. Verify a project
  4. Run a project
  5. Automated safety tests
  6. Project status
  7. Settings
  8. Exit
```

- Press **Enter** to accept a displayed default.
- Press **`b`** to go back, **`q`** to quit safely, or **`Ctrl+C`** to pause/interrupt cleanly.
- Non-sensitive preferences (last selected project, typing speed, paths, appearance, confirmation preferences) are saved to `config.toml`. Secrets and credentials are never stored.

---

## Direct CLI Commands

All direct commands share the exact same underlying services as the interactive wizard:

| Command | Description |
| --- | --- |
| `opensource-runner` | Launch the interactive terminal wizard (default) |
| `opensource-runner list` | List all configured projects in `projects/` |
| `opensource-runner select <project>` | Select a project and display third-party attribution notice |
| `opensource-runner prepare` | Retrieve repository (or `--local-source`), pin commit, check license, inspect stack |
| `opensource-runner status` | Display active project state, commit, progress, and verification status |
| `opensource-runner type` | Reproduce source files into VS Code via keyboard events (supports `--dry-run`) |
| `opensource-runner pause` | Safely pause an active typing session |
| `opensource-runner resume` | Resume reproduction from the latest valid checkpoint |
| `opensource-runner stop` | Safely stop typing without marking the project completed |
| `opensource-runner verify` | Run full-project diff & SHA-256 verification (`READY_TO_RUN`) |
| `opensource-runner run` | Explicitly run a verified project after dependency approval |
| `opensource-runner self-test` | Run the automated disposable sandbox test harness (`--all`, `--project`, `--input`, `--dry-run`, `--cleanup`, `--allow-network`, `--verbose`) |
| `opensource-runner doctor` | Diagnose OS, runtimes, VS Code, display server, input backend, and permissions |
| `opensource-runner clean` | Safely remove generated workspace/state for a project after confirmation |
| `opensource-runner logs` | Show recent project logs (with secret redaction) |
| `opensource-runner config` | Display active configuration and discovered system tools |
| `opensource-runner version` | Print installed package version |
| `opensource-runner help` | Show CLI help |

### Automated Sandbox Self-Test Examples

```bash
# Preview sandbox test plan without executing project code
opensource-runner self-test --dry-run

# Run safe isolated input and security self-check
opensource-runner self-test --input

# Test one project in a disposable sandbox with tagged verbose logs
opensource-runner self-test --project flappy --verbose

# Test all four projects in disposable sandboxes (with dependency network enabled)
opensource-runner self-test --all --allow-network --verbose

# Clean any abandoned harness-marked sandbox directories
opensource-runner self-test --cleanup
```

Reports are written to `test-results/summary.json`, `test-results/summary.html`, `test-results/summary.txt`, and `test-results/projects/<project-id>/`.

---

## Four Built-in Starter Projects

| Project ID | Name | Repository | Config File |
| --- | --- | --- | --- |
| `flappy` | Flappy | `https://github.com/Makivskyi2006/Flappy` | `projects/flappy.toml` |
| `flask-inventory-management` | Flask Inventory Management | `https://github.com/alaminerca/Flask-Inventory-Management` | `projects/flask-inventory-management.toml` |
| `flaskblog` | FlaskBlog | `https://github.com/DogukanUrker/flaskBlog` | `projects/flaskblog.toml` |
| `flatnotes` | flatnotes | `https://github.com/dullage/flatnotes` | `projects/flatnotes.toml` |

---

## Configuration

Copy `config.example.toml` to `config.toml` (or use **Settings** in the interactive wizard) to customize paths, typing delays (`typing_speed`, `character_delay_ms`, `file_delay_ms`), `vscode_path`, `input_backend`, `[sandbox]` resource limits (`cpu_limit`, `memory_limit_mb`, `process_limit`, timeouts, `network_enabled`), and `[ui]` preferences (`appearance`, `confirm_all_operations`).

---

## Security, License & Provenance

- See [SECURITY.md](SECURITY.md) for vulnerability reporting and security boundaries.
- See [TESTING_IMPLEMENTATION_PLAN.md](TESTING_IMPLEMENTATION_PLAN.md) for the sandbox isolation architecture and security risk matrix.
- See [LICENSE](LICENSE) for OpenSource Runner's MIT license.
- Imported third-party repositories retain their own licenses and copyright notices; provenance metadata is stored in `workspace/<id>/.provenance/`.

---

## Development, Testing & CI/CD

```bash
python -m pip install -e ".[dev]"
ruff format --check .
ruff check .
mypy src
python -m pytest -v --cov=opensource_runner --cov-report=xml --cov-report=term
pip-audit
python -m build
```

GitHub Actions workflows in `.github/workflows/`:
- `ci.yml`: Windows + Ubuntu matrix (Python 3.12 & 3.13) running Ruff, mypy, pytest with coverage, CLI smoke checks, and package build.
- `security.yml`: `pip-audit` dependency vulnerability scan and `gitleaks` secret scan.
- `build.yml`: Builds `.whl` and `.tar.gz` and uploads artifacts.
- `self-test.yml`: Runs `self-test --dry-run`, `self-test --input`, harness unit/chaos tests, and `--cleanup` across Ubuntu and Windows with `persist-credentials: false`.
- `release.yml`: Triggered on `v*.*.*` tags; validates tag matches `pyproject.toml`, runs full quality/security/build checks, and publishes a GitHub Release with `.whl` and `.tar.gz` attached.

---

## Release Process

1. Update version in `pyproject.toml` and `src/opensource_runner/__init__.py`.
2. Update `CHANGELOG.md`.
3. Run tests, lint, type checks, `pip-audit`, and `python -m build`.
4. Commit changes, push feature branch, and merge PR into `main`.
5. Tag and push:
   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```
6. GitHub Actions validates and publishes the GitHub Release with `.whl` and `.tar.gz` artifacts.

---

## Troubleshooting

| Problem | Actionable Solution |
| --- | --- |
| **Python not found** | Install Python 3.12+ and enable "Add Python to PATH" on Windows, or install `python3` on Linux. |
| **Git not found** | Install Git for Windows or `git` via your Linux package manager and restart your terminal. |
| **VS Code / `code` command unavailable** | In VS Code, run Command Palette → *Shell Command: Install 'code' command in PATH*, or set `typing.vscode_path` in `config.toml`. |
| **Wayland input unavailable** | Install and enable `ydotool` (`ydotoold`) or `dotool` with `/dev/uinput` access. Run `opensource-runner doctor` to verify. |
| **X11 input unavailable** | Install `xdotool` (`sudo dnf install xdotool` / `sudo apt install xdotool`). |
| **Permission denied** | Ensure `workspace/`, `source-cache/`, `state/`, and `logs/` are owned by your user (do not run as root/Administrator). |
| **Dependency installation failure** | Inspect the exact failing command shown by `run`, check network/Python version compatibility (e.g., use `uv` or `--container` for Python 3.13 pinned apps). |
| **GitHub retrieval failure** | Verify network/DNS access and repository URL; retry `prepare` (the immutable cache is never corrupted on partial failures). |
| **License review required** | Inspect `workspace/<id>/.provenance/LICENSE-REPORT.md`. Approve in the interactive prompt or run `opensource-runner prepare --approve-license`. |
| **File verification failure** | Inspect the reported file mismatch; do not execute until resolved. Re-run `opensource-runner resume` or `opensource-runner verify`. |
| **Checkpoint corruption** | Back up `state/projects/<id>/checkpoint.json` and run `opensource-runner clean <id>` or re-run preparation. |
| **VS Code focus lost** | Click the target VS Code workspace window to focus it, then resume via the wizard or `opensource-runner resume`. |
| **Project run command unknown** | Inspect `workspace/<id>/.provenance/run-config.json` and the project's `README.md`; the bot never guesses undocumented run commands. |
| **Abandoned sandbox directories** | Run `opensource-runner self-test --cleanup` to safely remove harness-marked temporary sandboxes. |
