"""Linux X11 keyboard input backend using xdotool (never clipboard pasting)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from opensource_runner.typing.platforms.base import (
    BackendHealth,
    FocusCheckResult,
    InputBackendError,
    InputController,
)


class LinuxX11InputController(InputController):
    """X11 keyboard controller backed by xdotool."""

    backend_name = "linux-x11-xdotool"

    def __init__(self, xdotool_bin: str | None = None) -> None:
        self.xdotool_bin = xdotool_bin or shutil.which("xdotool")

    def check_availability(self) -> BackendHealth:
        if not os.environ.get("DISPLAY"):
            return BackendHealth(
                self.backend_name,
                False,
                "X11 DISPLAY environment variable is not set.",
            )
        if not self.xdotool_bin:
            return BackendHealth(
                self.backend_name,
                False,
                "xdotool is not installed. Install xdotool (e.g. `sudo dnf install xdotool` or `sudo apt install xdotool`).",
            )
        return BackendHealth(self.backend_name, True, f"xdotool available at {self.xdotool_bin}.")

    def verify_focus(self, expected_app: str, expected_workspace: Path) -> FocusCheckResult:
        if not self.xdotool_bin:
            return FocusCheckResult(False, "", "xdotool is not installed.")
        res = subprocess.run(
            [self.xdotool_bin, "getactivewindow", "getwindowname"],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            return FocusCheckResult(
                False, "", f"Could not query active X11 window: {res.stderr.strip()}"
            )
        title = res.stdout.strip()
        title_lower = title.lower()
        is_vscode = "visual studio code" in title_lower or expected_app.lower() in title_lower
        has_ws = expected_workspace.name.lower() in title_lower
        if is_vscode and has_ws:
            return FocusCheckResult(True, title, "VS Code workspace window focused.")
        return FocusCheckResult(
            False,
            title,
            f"Active window '{title}' does not match VS Code workspace '{expected_workspace.name}'.",
        )

    def type_character(self, char: str) -> None:
        if not self.xdotool_bin:
            raise InputBackendError("xdotool is not installed.")
        if char == "\r":
            return
        if char == "\n":
            cmd = [self.xdotool_bin, "key", "--clearmodifiers", "Return"]
        elif char == "\t":
            cmd = [self.xdotool_bin, "key", "--clearmodifiers", "Tab"]
        else:
            cmd = [self.xdotool_bin, "type", "--clearmodifiers", "--delay", "0", "--", char]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode != 0:
            raise InputBackendError(f"xdotool failed: {res.stderr.strip()}")

    def send_hotkey(self, *keys: str) -> None:
        if not self.xdotool_bin:
            raise InputBackendError("xdotool is not installed.")
        combo = "+".join(keys)
        res = subprocess.run(
            [self.xdotool_bin, "key", "--clearmodifiers", combo],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            raise InputBackendError(f"xdotool hotkey '{combo}' failed: {res.stderr.strip()}")
