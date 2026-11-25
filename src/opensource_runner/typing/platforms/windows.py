"""Windows keyboard input backend using Win32 SendInput (no admin privileges required)."""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from opensource_runner.typing.platforms.base import (
    BackendHealth,
    FocusCheckResult,
    InputBackendError,
    InputController,
)

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

VK_MAP: dict[str, int] = {
    "ctrl": 0x11,
    "shift": 0x10,
    "alt": 0x12,
    "enter": 0x0D,
    "return": 0x0D,
    "tab": 0x09,
    "esc": 0x1B,
    "s": 0x53,
}


class WindowsInputController(InputController):
    """Win32 SendInput keyboard controller for Windows 10/11."""

    backend_name = "windows-sendinput"

    def check_availability(self) -> BackendHealth:
        if sys.platform != "win32":
            return BackendHealth(
                self.backend_name,
                False,
                "WindowsInputController is only available on Windows.",
            )
        if not hasattr(ctypes, "windll"):
            return BackendHealth(self.backend_name, False, "ctypes.windll unavailable.")
        return BackendHealth(self.backend_name, True, "Win32 SendInput available.")

    def verify_focus(self, expected_app: str, expected_workspace: Path) -> FocusCheckResult:
        if sys.platform != "win32":
            return FocusCheckResult(False, "", "Not running on Windows.")
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return FocusCheckResult(False, "", "No active foreground window detected.")
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value
        ws_name = expected_workspace.name.lower()
        title_lower = title.lower()
        is_vscode = "visual studio code" in title_lower or expected_app.lower() in title_lower
        has_ws = ws_name in title_lower
        if is_vscode and has_ws:
            return FocusCheckResult(True, title, "VS Code workspace window focused.")
        return FocusCheckResult(
            False,
            title,
            f"Active window '{title}' does not match VS Code workspace '{expected_workspace.name}'.",
        )

    def _send_vk(self, vk: int, key_up: bool = False) -> None:
        if sys.platform != "win32":
            raise InputBackendError("Win32 SendInput requires Windows.")
        flags = KEYEVENTF_KEYUP if key_up else 0
        ctypes.windll.user32.keybd_event(vk, 0, flags, 0)

    def type_character(self, char: str) -> None:
        if sys.platform != "win32":
            raise InputBackendError("Win32 SendInput requires Windows.")
        if char == "\r":
            return
        if char == "\n":
            self._send_vk(VK_MAP["enter"], key_up=False)
            self._send_vk(VK_MAP["enter"], key_up=True)
            return
        if char == "\t":
            self._send_vk(VK_MAP["tab"], key_up=False)
            self._send_vk(VK_MAP["tab"], key_up=True)
            return

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", ctypes.c_ushort),
                ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        class INPUT_UNION(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", ctypes.c_ulong), ("union", INPUT_UNION)]

        extra = ctypes.c_ulong(0)
        for code_unit in char.encode("utf-16-le"):
            pass
        # Emit UTF-16 code units via KEYEVENTF_UNICODE
        raw_utf16 = char.encode("utf-16-le")
        for idx in range(0, len(raw_utf16), 2):
            scan = int.from_bytes(raw_utf16[idx : idx + 2], "little")
            down = INPUT(
                type=INPUT_KEYBOARD,
                union=INPUT_UNION(
                    ki=KEYBDINPUT(0, scan, KEYEVENTF_UNICODE, 0, ctypes.pointer(extra))
                ),
            )
            up = INPUT(
                type=INPUT_KEYBOARD,
                union=INPUT_UNION(
                    ki=KEYBDINPUT(
                        0, scan, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, ctypes.pointer(extra)
                    )
                ),
            )
            sent = ctypes.windll.user32.SendInput(
                2, ctypes.byref((INPUT * 2)(down, up)), ctypes.sizeof(INPUT)
            )
            if sent != 2:
                raise InputBackendError(f"Win32 SendInput failed for character {char!r}.")

    def send_hotkey(self, *keys: str) -> None:
        if sys.platform != "win32":
            raise InputBackendError("Win32 SendInput requires Windows.")
        vks = [VK_MAP[k.lower()] for k in keys if k.lower() in VK_MAP]
        for vk in vks:
            self._send_vk(vk, key_up=False)
        for vk in reversed(vks):
            self._send_vk(vk, key_up=True)
