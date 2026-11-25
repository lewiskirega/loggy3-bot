"""Platform display server detection and InputController factory."""

from __future__ import annotations

import os
import sys

from opensource_runner.typing.platforms.base import (
    BackendHealth,
    FocusCheckResult,
    FocusVerificationError,
    InputBackendError,
    InputController,
    MockInputController,
)
from opensource_runner.typing.platforms.linux_wayland import LinuxWaylandInputController
from opensource_runner.typing.platforms.linux_x11 import LinuxX11InputController
from opensource_runner.typing.platforms.windows import WindowsInputController


def detect_display_platform() -> str:
    """Detect active platform/display server: 'windows', 'wayland', 'x11', or 'unknown'."""
    if sys.platform == "win32":
        return "windows"
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if session == "x11" or os.environ.get("DISPLAY"):
        return "x11"
    return "unknown"


def create_input_controller(preference: str = "auto") -> InputController:
    """Instantiate the appropriate platform-specific InputController."""
    pref = preference.lower().strip()
    if pref == "mock":
        return MockInputController()
    if pref == "auto":
        pref = detect_display_platform()

    if pref == "windows":
        return WindowsInputController()
    if pref == "wayland":
        return LinuxWaylandInputController()
    if pref == "x11":
        return LinuxX11InputController()
    raise InputBackendError(
        f"Unsupported or undetectable display platform '{pref}'. "
        "Set typing.input_backend in config.toml or run inside an active desktop session."
    )


__all__ = [
    "BackendHealth",
    "FocusCheckResult",
    "FocusVerificationError",
    "InputBackendError",
    "InputController",
    "LinuxWaylandInputController",
    "LinuxX11InputController",
    "MockInputController",
    "WindowsInputController",
    "create_input_controller",
    "detect_display_platform",
]
