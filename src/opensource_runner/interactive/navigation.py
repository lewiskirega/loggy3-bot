"""Navigation actions and menu choice data structures."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class NavAction(str, Enum):
    SELECT = "select"
    BACK = "back"
    QUIT = "quit"


@dataclass(frozen=True)
class MenuChoice:
    key: str
    label: str
    description: str = ""


@dataclass(frozen=True)
class SelectionResult:
    action: NavAction
    choice_key: str | None = None

