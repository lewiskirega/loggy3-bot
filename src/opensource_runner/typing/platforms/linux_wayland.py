"""Linux Wayland keyboard input backend with strict fail-closed diagnostics."""

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


class LinuxWaylandInputController(InputController):
    """Wayland keyboard controller supporting ydotool, dotool, and wtype (non-GNOME)."""

    backend_name = "linux-wayland"

    def __init__(self) -> None:
        self.ydotool_bin = shutil.which("ydotool")
        self.dotool_bin = shutil.which("dotool")
        self.wtype_bin = shutil.which("wtype")
        self.desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()

    def _selected_tool(self) -> str | None:
        if self.ydotool_bin:
            return "ydotool"
        if self.dotool_bin:
            return "dotool"
        if self.wtype_bin and "gnome" not in self.desktop:
            return "wtype"
        return None

    def check_availability(self) -> BackendHealth:
        if (
            not os.environ.get("WAYLAND_DISPLAY")
            and os.environ.get("XDG_SESSION_TYPE", "").lower() != "wayland"
        ):
            return BackendHealth(self.backend_name, False, "Wayland session is not active.")

        tool = self._selected_tool()
        if tool is None:
            if "gnome" in self.desktop:
                return BackendHealth(
                    self.backend_name,
                    False,
                    "No permitted Wayland keyboard backend found on GNOME Wayland. "
                    "GNOME does not support wtype; install and enable `ydotool` (with ydotoold) "
                    "or `dotool` with /dev/uinput access. Refusing to fall back to clipboard pasting.",
                )
            return BackendHealth(
                self.backend_name,
                False,
                "No Wayland keyboard backend found. Install `ydotool`, `dotool`, or `wtype`. "
                "Refusing to fall back to clipboard pasting.",
            )
        return BackendHealth(
            f"{self.backend_name}-{tool}", True, f"Wayland backend '{tool}' available."
        )

    def verify_focus(self, expected_app: str, expected_workspace: Path) -> FocusCheckResult:
        # Wayland compositors restrict arbitrary window-title queries unless a compositor tool exists.
        swaymsg = shutil.which("swaymsg")
        if swaymsg and "sway" in self.desktop:
            res = subprocess.run(
                [swaymsg, "-t", "get_tree"], capture_output=True, text=True, check=False
            )
            if res.returncode == 0 and expected_workspace.name.lower() in res.stdout.lower():
                return FocusCheckResult(True, expected_workspace.name, "Verified via swaymsg.")

        hyprctl = shutil.which("hyprctl")
        if hyprctl and "hyprland" in self.desktop:
            res = subprocess.run(
                [hyprctl, "activewindow"], capture_output=True, text=True, check=False
            )
            title = res.stdout.strip()
            if res.returncode == 0 and expected_workspace.name.lower() in title.lower():
                return FocusCheckResult(True, title, "Verified via hyprctl.")

        return FocusCheckResult(
            False,
            "",
            "Wayland compositor blocks automatic active-window focus introspection. "
            "Focus could not be verified automatically.",
        )

    def type_character(self, char: str) -> None:
        tool = self._selected_tool()
        if tool is None:
            raise InputBackendError(self.check_availability().reason)
        if char == "\r":
            return

        if tool == "ydotool":
            assert self.ydotool_bin is not None
            if char == "\n":
                cmd = [self.ydotool_bin, "key", "28:1", "28:0"]
            elif char == "\t":
                cmd = [self.ydotool_bin, "key", "15:1", "15:0"]
            else:
                cmd = [self.ydotool_bin, "type", "--key-delay", "0", "--", char]
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        elif tool == "dotool":
            assert self.dotool_bin is not None
            payload = (
                "key enter\n"
                if char == "\n"
                else ("key tab\n" if char == "\t" else f"type {char}\n")
            )
            res = subprocess.run(
                [self.dotool_bin], input=payload, capture_output=True, text=True, check=False
            )
        else:
            assert self.wtype_bin is not None
            if char == "\n":
                cmd = [self.wtype_bin, "-k", "Return"]
            elif char == "\t":
                cmd = [self.wtype_bin, "-k", "Tab"]
            else:
                cmd = [self.wtype_bin, "--", char]
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)

        if res.returncode != 0:
            raise InputBackendError(f"Wayland backend '{tool}' failed: {res.stderr.strip()}")

    def send_hotkey(self, *keys: str) -> None:
        tool = self._selected_tool()
        if tool is None:
            raise InputBackendError(self.check_availability().reason)
        normalized = tuple(k.lower() for k in keys)
        if tool == "ydotool" and normalized == ("ctrl", "s"):
            assert self.ydotool_bin is not None
            # LeftCtrl=29, S=31
            res = subprocess.run(
                [self.ydotool_bin, "key", "29:1", "31:1", "31:0", "29:0"],
                capture_output=True,
                text=True,
                check=False,
            )
        elif tool == "dotool":
            assert self.dotool_bin is not None
            combo = "+".join(normalized)
            res = subprocess.run(
                [self.dotool_bin],
                input=f"key {combo}\n",
                capture_output=True,
                text=True,
                check=False,
            )
        elif tool == "wtype" and normalized == ("ctrl", "s"):
            assert self.wtype_bin is not None
            res = subprocess.run(
                [self.wtype_bin, "-M", "ctrl", "-k", "s", "-m", "ctrl"],
                capture_output=True,
                text=True,
                check=False,
            )
        else:
            raise InputBackendError(f"Unsupported hotkey {keys!r} for Wayland backend '{tool}'.")
        if res.returncode != 0:
            raise InputBackendError(f"Wayland hotkey failed: {res.stderr.strip()}")
