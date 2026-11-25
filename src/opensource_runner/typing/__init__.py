"""Keyboard typing and VS Code automation package."""

from opensource_runner.typing.orchestrator import TypingOrchestrator, TypingOutcome
from opensource_runner.typing.vscode import (
    VSCodeController,
    VSCodeNotFoundError,
    discover_vscode_cli,
)

__all__ = [
    "TypingOrchestrator",
    "TypingOutcome",
    "VSCodeController",
    "VSCodeNotFoundError",
    "discover_vscode_cli",
]
