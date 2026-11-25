"""Cross-platform Visual Studio Code discovery and workspace controller."""

from __future__ import annotations

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

    # Platform-specific fallback locations
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
    """Opens isolated project workspaces and files in Visual Studio Code."""

    def __init__(self, configured_path: str = "", *, dry_run: bool = False) -> None:
        self.configured_path = configured_path
        self.dry_run = dry_run
        self._cli_path: Path | None = discover_vscode_cli(configured_path)

    @property
    def cli_path(self) -> Path | None:
        return self._cli_path

    def open_workspace(self, workspace_dir: Path) -> None:
        if self.dry_run:
            return
        if self._cli_path is None:
            raise VSCodeNotFoundError(
                "Visual Studio Code CLI ('code') was not found. "
                "Install VS Code or set typing.vscode_path in config.toml."
            )
        subprocess.Popen(
            [str(self._cli_path), "--new-window", str(workspace_dir)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def open_file(self, workspace_dir: Path, target_file: Path) -> None:
        if self.dry_run:
            return
        if self._cli_path is None:
            raise VSCodeNotFoundError("Visual Studio Code CLI ('code') was not found.")
        target_file.parent.mkdir(parents=True, exist_ok=True)
        if not target_file.exists():
            target_file.touch()
        subprocess.Popen(
            [str(self._cli_path), "--reuse-window", str(workspace_dir), str(target_file)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
