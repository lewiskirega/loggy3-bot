"""Explicit confirmation dialogs with safe defaults for important operations."""

from __future__ import annotations

from opensource_runner.interactive.prompts import PromptSession


def ask_confirmation(
    prompts: PromptSession,
    *,
    title: str,
    summary_lines: list[str],
    default_yes: bool = False,
    question: str = "Continue?",
) -> bool:
    """Display a clear operation summary and require explicit user confirmation."""
    prompts.console.print(f"\n{title}\n")
    for line in summary_lines:
        prompts.console.print(line)

    yn = "[Y/n]" if default_yes else "[y/N]"
    while True:
        try:
            raw = prompts.input_fn(f"\n{question} {yn}: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            prompts.console.print("\nOperation cancelled safely.")
            return False

        if not raw:
            return default_yes
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no", "b", "q"):
            return False
        prompts.console.print("Please enter 'y' or 'n'.")

