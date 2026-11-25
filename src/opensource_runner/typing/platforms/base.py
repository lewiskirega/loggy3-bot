"""Abstract InputController interface and MockInputController for deterministic testing."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


class InputBackendError(RuntimeError):
    """Raised when the OS keyboard automation backend is unavailable or blocked."""


class FocusVerificationError(RuntimeError):
    """Raised when VS Code / workspace window focus cannot be verified."""


@dataclass(frozen=True)
class BackendHealth:
    backend_name: str
    available: bool
    reason: str = ""


@dataclass(frozen=True)
class FocusCheckResult:
    verified: bool
    active_window_title: str = ""
    reason: str = ""


class InputController(ABC):
    """Cross-platform abstraction for individual keyboard/input event simulation."""

    backend_name: str = "base"

    @abstractmethod
    def check_availability(self) -> BackendHealth:
        """Verify that this input backend is installed and permitted by the OS."""

    @abstractmethod
    def verify_focus(self, expected_app: str, expected_workspace: Path) -> FocusCheckResult:
        """Verify that the expected VS Code workspace window currently holds focus."""

    @abstractmethod
    def type_character(self, char: str) -> None:
        """Emit a single keyboard/character event (never clipboard paste)."""

    @abstractmethod
    def send_hotkey(self, *keys: str) -> None:
        """Emit a key combination such as ('ctrl', 's')."""

    def prepare_target_file(self, target_file: Path) -> None:
        """Optional hook called when a file is opened for typing (used by mock backends)."""


class MockInputController(InputController):
    """In-memory / file-backed mock input controller for unit and integration tests."""

    backend_name = "mock"

    def __init__(
        self,
        *,
        focus_ok: bool = True,
        available: bool = True,
        corrupt_on_save: bool = False,
    ) -> None:
        self.focus_ok = focus_ok
        self.available = available
        self.corrupt_on_save = corrupt_on_save
        self.typed_chars: list[str] = []
        self.hotkeys: list[tuple[str, ...]] = []
        self._current_file: Path | None = None
        self._buffer: list[str] = []

    def check_availability(self) -> BackendHealth:
        if not self.available:
            return BackendHealth(self.backend_name, False, "Mock backend disabled")
        return BackendHealth(self.backend_name, True, "Mock backend ready")

    def verify_focus(self, expected_app: str, expected_workspace: Path) -> FocusCheckResult:
        if not self.focus_ok:
            return FocusCheckResult(
                verified=False,
                active_window_title="Terminal",
                reason="Mock focus check failed",
            )
        return FocusCheckResult(
            verified=True,
            active_window_title=f"{expected_workspace.name} - Visual Studio Code",
            reason="Focus verified (mock)",
        )

    def prepare_target_file(self, target_file: Path) -> None:
        self._current_file = target_file
        self._buffer = []

    def type_character(self, char: str) -> None:
        self.typed_chars.append(char)
        self._buffer.append(char)

    def send_hotkey(self, *keys: str) -> None:
        normalized = tuple(k.lower() for k in keys)
        self.hotkeys.append(normalized)
        if normalized == ("ctrl", "s") and self._current_file is not None:
            content = "".join(self._buffer)
            if self.corrupt_on_save:
                content = content + "# CORRUPTED"
            self._current_file.parent.mkdir(parents=True, exist_ok=True)
            self._current_file.write_bytes(content.encode("utf-8"))
