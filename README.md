# OpenSource Runner

A cross-platform terminal automation bot for **Windows 10/11** and **Linux** (Fedora, Ubuntu, Debian, Arch, etc.) that retrieves open-source projects from GitHub (or a local source folder), pins exact commits, inspects licenses and technology stacks, reproduces source files into isolated Visual Studio Code workspaces via simulated individual keyboard keystrokes, verifies every file with diffs and SHA-256 hashes, maintains persistent checkpoints, and runs the project **only when you explicitly enter `opensource-runner run`**.

> **CI Status Badges**: Add live CI, Python version, License, and Release badges here once the GitHub repository URL is created.

---

## Features

- **Transparent Provenance**: Records repository URL, branch, exact commit SHA, retrieval timestamp, license report, and SHA-256 manifests under `.provenance/`. Never claims authorship of imported code.
- **No AI Code Generation**: Source files come strictly from the selected GitHub repository or a user-provided local folder.
- **Immutable Source Cache & Isolated Workspaces**: Keeps untouched source under `source-cache/<id>/<commit>/` and reproduces files into `workspace/<id>/`.
- **Keyboard-Event Reproduction**: Types text files character-by-character via platform-native input backends (never clipboard pasting) and copies binary files with SHA-256 verification.
- **Strict Verification & Checkpoints**: Verifies every file on save and performs full-project comparison before reaching `READY_TO_RUN`. Supports `pause`, `resume`, `stop`, and crash recovery.
- **Explicit Execution & Dependency Approval**: Never launches code after `prepare`, `type`, or `verify`. Prompts before installing dependencies into isolated environments (`.venv`, `uv`, Node lockfile, Composer, or optional Docker/Podman).
- **Host Diagnostics**: Built-in `opensource-runner doctor` checks OS, runtimes, VS Code CLI, display server, input backend, and directory permissions.

---

## Architecture

```text
PROJECT REGISTRY (projects/*.toml)
  -> SELECT (attribution notice)
  -> PREPARE (retrieval approval -> GitHub/local -> commit pin -> immutable source-cache
              -> license check -> multi-stack inspection -> .provenance/run-config.json)
  -> TYPE (VS Code workspace -> focus guard -> keyboard input events / binary copy
           -> per-file verification -> atomic checkpoint)
  -> VERIFY (full diff + SHA-256 -> READY_TO_RUN)
  -> WAIT FOR USER
  -> RUN (command validation -> dependency approval -> isolated runtime execution)
```

---

## Supported Platforms & Requirements

- **Windows 10 / Windows 11** (native Python + Git + VS Code; no WSL, Cygwin, or MSYS2 required)
- **Linux** (Fedora, Ubuntu, Debian, Arch, and similar distributions)
- **Python 3.12+** (tested on Python 3.12 and 3.13)
- **Git CLI**
- **Visual Studio Code** with `code` CLI available

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
git clone <YOUR-GITHUB-REPOSITORY>
cd opensource-runner
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e .
```

**Windows PowerShell:**

```powershell
git clone <YOUR-GITHUB-REPOSITORY>
cd opensource-runner
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

> **PowerShell Execution Policy Note**: If PowerShell blocks `Activate.ps1`, run it only for the current session with `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` (do not lower your system-wide policy unnecessarily), or use Windows Command Prompt.

### 3. Verify Installation

```cmd
opensource-runner doctor
opensource-runner list
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
git clone <YOUR-GITHUB-REPOSITORY>
cd opensource-runner
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
- **Linux X11**: Uses `xdotool` (install via `sudo dnf install xdotool` or `sudo apt install xdotool`).
- **Linux Wayland**: Supports `ydotool` (with `ydotoold` and `/dev/uinput` permission) or `dotool`. On wlroots compositors (Sway, Hyprland), `wtype` is also supported; GNOME Mutter does not implement `zwp_virtual_keyboard_v1`, so `ydotool` or `dotool` is required on GNOME Wayland.
- **Fail-Closed Behavior**: If the active environment blocks synthetic keyboard input, `opensource-runner type` stops safely and never falls back to clipboard pasting.
- **VS Code Discovery**: `code` is located dynamically via `config.toml`, `PATH`, and platform-standard locations (User/System installs on Windows, Snap/Flatpak/usr on Linux).

---

## CLI Commands

| Command | Description |
| --- | --- |
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
| `opensource-runner logs` | Show recent project logs (with secret redaction) |
| `opensource-runner config` | Display active configuration and discovered system tools |
| `opensource-runner doctor` | Diagnose OS, runtimes, VS Code, display server, input backend, and permissions |
| `opensource-runner clean` | Safely remove generated workspace/state for a project after confirmation |
| `opensource-runner version` | Print installed package version |
| `opensource-runner help` | Show CLI help |

### Standard Workflow (Identical on Windows CMD, PowerShell, and Linux)

```bash
opensource-runner doctor
opensource-runner list
opensource-runner select flappy
opensource-runner prepare
opensource-runner type
opensource-runner verify
opensource-runner run
```

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

Copy `config.example.toml` to `config.toml` to customize directories, typing delays (`typing_speed`, `character_delay_ms`, `file_delay_ms`), `vscode_path`, `input_backend`, or execution flags.

---

## Security, License & Provenance

- See [SECURITY.md](SECURITY.md) for vulnerability reporting and security boundaries.
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
- `release.yml`: Triggered on `v*.*.*` tags; validates tag matches `pyproject.toml`, runs tests + security + build, and publishes a GitHub Release with `.whl` and `.tar.gz` attached.

---

## Release Process

1. Update version in `pyproject.toml` and `src/opensource_runner/__init__.py`.
2. Update `CHANGELOG.md`.
3. Run tests, lint, type checks, security checks, and `python -m build`.
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
| **License review required** | Inspect `workspace/<id>/.provenance/LICENSE-REPORT.md`. If you approve continuing, run `opensource-runner prepare --approve-license`. |
| **File verification failure** | Inspect the reported file mismatch; do not execute until resolved. Re-run `opensource-runner resume` or `opensource-runner verify`. |
| **Checkpoint corruption** | Back up `state/projects/<id>/checkpoint.json` and run `opensource-runner clean <id>` or re-run `select` + `prepare`. |
| **VS Code focus lost** | Click the target VS Code workspace window to focus it, then run `opensource-runner resume`. |
| **Project run command unknown** | Inspect `workspace/<id>/.provenance/run-config.json` and the project's `README.md`; the bot never guesses undocumented run commands. |
