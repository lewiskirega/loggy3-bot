"""Cross-platform Visual Studio Code discovery and workspace controller."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


class VSCodeNotFoundError(RuntimeError):
    """Raised when Visual Studio Code CLI cannot be located."""


def discover_vscode_cli(configured_path: str = "") -> Path | None:
    """Dynamically locate the VS Code CLI without hard-coding a single OS path."""
    if configured_path:
        p = Path(configured_path).expanduser()
        if p.is_file():
            return p

    for candidate in ("code", "code.cmd", "code-insiders"):
        found = shutil.which(candidate)
        if found:
            return Path(found)

    candidates: list[Path] = []
    if sys.platform == "win32":
        local_app = os.environ.get("LOCALAPPDATA", "")
        prog_files = os.environ.get("ProgramFiles", "")
        if local_app:
            candidates.append(
                Path(local_app) / "Programs" / "Microsoft VS Code" / "bin" / "code.cmd"
            )
        if prog_files:
            candidates.append(Path(prog_files) / "Microsoft VS Code" / "bin" / "code.cmd")
    else:
        candidates.extend(
            [
                Path("/var/lib/snapd/snap/bin/code"),
                Path("/snap/bin/code"),
                Path("/usr/share/code/bin/code"),
                Path("/opt/visual-studio-code/bin/code"),
            ]
        )

    for path in candidates:
        if path.is_file():
            return path
    return None


class VSCodeController:
    """Opens isolated project workspaces and target source files in Visual Studio Code."""

    def __init__(self, configured_path: str = "", *, dry_run: bool = False) -> None:
        self.configured_path = configured_path
        self.dry_run = dry_run
        self._cli_path: Path | None = discover_vscode_cli(configured_path)
        self._workspace_opened = False
        self.last_launch_args: list[str] = []

    @property
    def cli_path(self) -> Path | None:
        return self._cli_path

    @staticmethod
    def _validate_workspace_dir(workspace_dir: Path) -> Path:
        resolved = workspace_dir.resolve()
        if resolved.name == ".provenance":
            raise ValueError(
                "Refusing to open '.provenance' metadata directory as VS Code workspace."
            )
        resolved.mkdir(parents=True, exist_ok=True)
        return resolved

    @staticmethod
    def _ensure_editor_settings(workspace_dir: Path) -> None:
        vscode_dir = workspace_dir / ".vscode"
        vscode_dir.mkdir(parents=True, exist_ok=True)
        settings_path = vscode_dir / "settings.json"
        if not settings_path.exists():
            settings_path.write_text(
                json.dumps(
                    {
                        "editor.autoClosingBrackets": "never",
                        "editor.autoClosingQuotes": "never",
                        "editor.autoClosingOvertype": "never",
                        "editor.autoIndent": "none",
                        "editor.formatOnSave": False,
                        "editor.formatOnType": False,
                        "files.autoSave": "off",
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

    def open_workspace(self, workspace_dir: Path, initial_file: Path | None = None) -> list[str]:
        """Launch VS Code on the project workspace (optionally opening the first pending text file)."""
        resolved_ws = self._validate_workspace_dir(workspace_dir)
        self._ensure_editor_settings(resolved_ws)

        cmd = [str(self._cli_path or "code"), "--new-window", str(resolved_ws)]
        if initial_file is not None:
            if ".provenance" in initial_file.parts:
                raise ValueError(
                    "Refusing to open '.provenance' metadata file as reproduction target."
                )
            initial_file.parent.mkdir(parents=True, exist_ok=True)
            if not initial_file.exists():
                initial_file.touch()
            cmd.append(str(initial_file))

        self.last_launch_args = cmd
        self._workspace_opened = True
        if self.dry_run:
            return cmd
        if self._cli_path is None:
            raise VSCodeNotFoundError(
                "Visual Studio Code CLI ('code') was not found. "
                "Install VS Code or set typing.vscode_path in config.toml."
            )
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return cmd

    def open_file(self, workspace_dir: Path, target_file: Path) -> list[str]:
        """Open a target source file in the project's VS Code workspace window."""
        resolved_ws = self._validate_workspace_dir(workspace_dir)
        if ".provenance" in target_file.parts:
            raise ValueError("Refusing to open '.provenance' metadata file as reproduction target.")
        target_file.parent.mkdir(parents=True, exist_ok=True)
        if not target_file.exists():
            target_file.touch()

        if not self._workspace_opened:
            return self.open_workspace(resolved_ws, initial_file=target_file)

        cmd = [
            str(self._cli_path or "code"),
            "--reuse-window",
            str(resolved_ws),
            str(target_file),
        ]
        self.last_launch_args = cmd
        if self.dry_run:
            return cmd
        if self._cli_path is None:
            raise VSCodeNotFoundError("Visual Studio Code CLI ('code') was not found.")
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return cmd
