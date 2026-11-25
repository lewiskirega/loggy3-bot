"""Minimal question-driven terminal prompt engine with testable I/O."""

from __future__ import annotations

from typing import Callable

from rich.console import Console

from opensource_runner.interactive.navigation import MenuChoice, NavAction, SelectionResult

InputFn = Callable[[str], str]


class PromptSession:
    """Asks one clear question at a time with defaults, back (`b`), and quit (`q`) support."""

    def __init__(
        self,
        console: Console,
        input_fn: InputFn = input,
    ) -> None:
        self.console = console
        self.input_fn = input_fn

    def ask_choice(
        self,
        question: str,
        choices: list[MenuChoice],
        *,
        default_index: int | None = None,
        allow_back: bool = True,
        allow_quit: bool = True,
        prompt_label: str = "Select an option",
    ) -> SelectionResult:
        """Render numbered choices and return the validated user selection."""
        if not choices:
            return SelectionResult(NavAction.BACK)

        self.console.print(f"\n{question}\n")
        for idx, item in enumerate(choices, start=1):
            default_marker = " (default)" if default_index == idx else ""
            self.console.print(f"  {idx}. {item.label}{default_marker}")
            if item.description:
                for line in item.description.splitlines():
                    self.console.print(f"     {line}")

        hints: list[str] = []
        if default_index is not None:
            hints.append(f"Enter={default_index}")
        if allow_back:
            hints.append("b=back")
        if allow_quit:
            hints.append("q=quit")
        hint_suffix = f" [{' / '.join(hints)}]" if hints else ""

        while True:
            try:
                raw = self.input_fn(f"\n{prompt_label}{hint_suffix}: ").strip()
            except (KeyboardInterrupt, EOFError):
                self.console.print("\nInterrupted safely.")
                return SelectionResult(NavAction.QUIT)

            if not raw and default_index is not None:
                return SelectionResult(NavAction.SELECT, choices[default_index - 1].key)

            lower = raw.lower()
            if allow_back and lower in ("b", "back"):
                return SelectionResult(NavAction.BACK)
            if allow_quit and lower in ("q", "quit", "exit"):
                return SelectionResult(NavAction.QUIT)

            if raw.isdigit():
                num = int(raw)
                if 1 <= num <= len(choices):
                    return SelectionResult(NavAction.SELECT, choices[num - 1].key)

            # Allow matching directly by choice key
            for item in choices:
                if lower == item.key.lower():
                    return SelectionResult(NavAction.SELECT, item.key)

            self.console.print(
                f"Invalid choice '{raw}'. Enter a number between 1 and {len(choices)}."
            )

    def ask_text(
        self,
        question: str,
        *,
        default: str = "",
        allow_back: bool = True,
    ) -> tuple[NavAction, str]:
        """Ask for a single line of text with optional default and back support."""
        default_hint = f" [{default}]" if default else ""
        back_hint = " (or 'b' to go back)" if allow_back else ""
        try:
            raw = self.input_fn(f"\n{question}{default_hint}{back_hint}: ").strip()
        except (KeyboardInterrupt, EOFError):
            return NavAction.QUIT, ""

        if allow_back and raw.lower() in ("b", "back"):
            return NavAction.BACK, ""
        if raw.lower() in ("q", "quit"):
            return NavAction.QUIT, ""
        return NavAction.SELECT, (raw if raw else default)

