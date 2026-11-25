# VS Code Reproduction Bug Investigation

## 1. Real On-Disk Diagnostic Snapshot

Inspected directly from `/home/crawler/Documents/Projects/loggy3-bot` before applying fixes:

```text
PROJECT ID:            flask-inventory-management
REPOSITORY URL:        https://github.com/alaminerca/Flask-Inventory-Management
PINNED COMMIT:         4e1072c7f1b4707601b97678b32480c95ba3f236 (branch: main)

SOURCE CACHE:          /home/crawler/Documents/Projects/loggy3-bot/source-cache/flask-inventory-management/4e1072c7f1b4707601b97678b32480c95ba3f236
WORKSPACE:             /home/crawler/Documents/Projects/loggy3-bot/workspace/flask-inventory-management

SOURCE FILE COUNT:     13
TEXT FILE COUNT:       11
BINARY FILE COUNT:     2 (flaskDB.db, static/image/image1.jpg)

WORKSPACE FILE COUNT:  1 non-metadata file (LICENSE = 0 bytes) + .provenance/* + .vscode/settings.json
REPRODUCED FILE COUNT: 0
PENDING FILE COUNT:    13

VS CODE EXECUTABLE:    /var/lib/snapd/snap/bin/code
VS CODE LAUNCH TARGET: /home/crawler/Documents/Projects/loggy3-bot/workspace/flask-inventory-management
INITIAL OPEN FILE:     LICENSE (0 bytes touched, then failed before typing)
CURRENT WORKFLOW STATE: TYPING (stuck; current_file="LICENSE", current_position=0, completed_files=[])
DISPLAY / DESKTOP:     wayland / GNOME (Fedora Linux 45 Workstation Edition)
INPUT TOOL ON PATH:    /usr/bin/ydotool, /usr/bin/ydotoold
YDOTOOL SOCKET:        /tmp/.ydotool_socket (srw------- root:root — Permission denied for non-root user)
```

## 2. Complete Execution Path Trace

1. **Interactive Wizard / CLI** (`src/opensource_runner/interactive/workflows.py` -> `workflow_prepare` / `_do_reproduce`, or `src/opensource_runner/cli/app.py` -> `cmd_type`).
2. **Repository Retrieval & Source Cache** (`src/opensource_runner/github/__init__.py` -> `GitHubRetriever.retrieve_to_cache`): Succeeded cleanly. All 13 files were cloned into immutable `source-cache/flask-inventory-management/4e1072c7f1b4707601b97678b32480c95ba3f236/`.
3. **Workspace & Provenance Creation** (`workflows.py:_do_download_and_inspect` / `cli/app.py:cmd_prepare`): Created `workspace/flask-inventory-management/.provenance/{repository.json, source-manifest.json, license-report.json, LICENSE-REPORT.md, inspection-report.json, run-config.json}`.
4. **Source File Enumeration** (`src/opensource_runner/typing/orchestrator.py:TypingOrchestrator.reproduce`): Correctly enumerated all 13 files from `source-cache/.../` (`LICENSE`, `flaskDB.db`, `flaskmain.py`, `static/image/image1.jpg`, and 9 `templates/*.html` files).
5. **Input Backend Precheck** (`src/opensource_runner/typing/platforms/linux_wayland.py:LinuxWaylandInputController.check_availability`): **BUG #1** — Only checked `shutil.which("ydotool")`, NOT whether `/tmp/.ydotool_socket` (or `$YDOTOOL_SOCKET`) was accessible to the current user! It falsely returned `available=True`.
6. **VS Code Launch** (`src/opensource_runner/typing/vscode.py:VSCodeController.open_workspace` + `open_file`): **BUG #2** — Launched `code --new-window <workspace>` asynchronously and immediately called `code --reuse-window <workspace> <file>` without opening the first pending text file directly with the workspace window. When only `.provenance/` existed in the workspace, VS Code opened the workspace showing `.provenance/` (and `source-manifest.json` if clicked/opened).
7. **Keyboard Event Dispatch** (`linux_wayland.py:type_character`): Touched 0-byte `workspace/flask-inventory-management/LICENSE` and invoked `ydotool type --key-delay 0 -- M`, which immediately failed with:
   ```text
   failed to connect socket `/tmp/.ydotool_socket': Permission denied
   Please check if the current user has sufficient permissions to access the socket file.
   ```
8. **Error Handling & Checkpoint State** (`orchestrator.py:reproduce`): **BUG #3** — `InputBackendError` propagated out of `reproduce()` without transitioning `checkpoint.json` out of `TYPING` or recording `last_error`, leaving the checkpoint stuck in `state: "TYPING"` with `current_position: 0` and leaving a 0-byte `LICENSE` file (same happened on `flatnotes/.dockerignore`).
9. **Structured Reproduction Logging**: **BUG #4** — `workflows.py` did not attach `get_project_logger` to `TypingOrchestrator`, leaving `logs/flask-inventory-management.log` absent.

## 3. Confirmed Root Causes

1. **Primary Root Cause (`ydotool` socket permission blindspot)**: On Fedora Workstation, `ydotoold` runs as `root` with socket `/tmp/.ydotool_socket` mode `0600` (`srw-------`). `LinuxWaylandInputController.check_availability()` checked only binary presence (`shutil.which("ydotool")`), not socket existence/read-write permission (`os.access`), so it launched VS Code and attempted typing into an unusable backend.
2. **Stuck Checkpoint on Input Failure**: `TypingOrchestrator.reproduce()` did not catch `InputBackendError` to transition the checkpoint safely to `PAUSED` with `last_error`.
3. **VS Code Window/File Launch Race**: `open_workspace()` (`--new-window`) and `open_file()` (`--reuse-window`) raced on cold launch instead of launching VS Code directly with the first pending text source file.
4. **Missing `[REPRODUCTION]` Logging & Input Diagnostics**: No structured `[REPRODUCTION]` lifecycle logs and no `opensource-runner doctor --input` command to surface exact socket/focus/typing diagnostics before launching VS Code.

## 4. Proposed Corrections

1. Verify `ydotool` socket existence and read/write permissions inside `LinuxWaylandInputController.check_availability()`, returning `available=False` with exact Fedora remediation instructions when denied (never launching VS Code or claiming success).
2. Add `VSCodeController.open_workspace_and_file()` to launch VS Code directly on `<workspace_dir>` + the first pending text file (never `.provenance/source-manifest.json`), with `--reuse-window` for subsequent files.
3. Catch `InputBackendError` in `TypingOrchestrator.reproduce()` to transition the checkpoint cleanly to `PAUSED` with `last_error` and return `TypingOutcome(status="input_failed")`; add structured `[REPRODUCTION]` logging at every stage.
4. Implement `opensource-runner doctor --input` with explicit `PASS` / `FAIL` / `UNSUPPORTED` / `NOT TESTED` reporting and a controlled temporary-workspace typing test.
5. Add comprehensive regression tests covering every failure mode, workspace isolation, launch arguments, and checkpoint recovery.

