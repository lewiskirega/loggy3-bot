"""Main interactive terminal wizard loop for OpenSource Runner."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from opensource_runner.checkpoint import CheckpointManager
from opensource_runner.config import load_config
from opensource_runner.interactive.formatting import (
    TerminalCapabilities,
    create_console,
    detect_terminal_capabilities,
    render_banner,
)
from opensource_runner.interactive.menu import MAIN_MENU_CHOICES
from opensource_runner.interactive.navigation import NavAction
from opensource_runner.interactive.prompts import InputFn, PromptSession
from opensource_runner.interactive.workflows import InteractiveWorkflows
from opensource_runner.projects import ProjectRegistry


class InteractiveWizard:
    """Minimal, question-driven interactive terminal wizard."""

    def __init__(
        self,
        *,
        root_dir: Path | None = None,
        input_fn: InputFn = input,
        console: Console | None = None,
        caps: TerminalCapabilities | None = None,
    ) -> None:
        self.config = load_config(root_dir=root_dir)
        self.caps = caps or detect_terminal_capabilities(self.config.ui.appearance)
        self.console = console or create_console(self.caps)
        self.prompts = PromptSession(self.console, input_fn=input_fn)
        self.registry = ProjectRegistry(self.config.projects_path)
        self.checkpoints = CheckpointManager(self.config.state_path)
        self.workflows = InteractiveWorkflows(
            config=self.config,
            registry=self.registry,
            checkpoints=self.checkpoints,
            console=self.console,
            caps=self.caps,
            prompts=self.prompts,
        )

    def run(self) -> int:
        """Run the main menu loop until the user chooses Exit or interrupts safely."""
        render_banner(self.console, self.caps)
        while True:
            sel = self.prompts.ask_choice(
                "Welcome! What would you like to do?",
                MAIN_MENU_CHOICES,
                allow_back=False,
                allow_quit=True,
                prompt_label="Select an option",
            )
            if sel.action == NavAction.QUIT or sel.choice_key == "exit":
                self.console.print("\nGoodbye.")
                return 0

            key = sel.choice_key
            if key == "prepare":
                if self.workflows.workflow_prepare() == "exit":
                    self.console.print("\nGoodbye.")
                    return 0
            elif key == "continue":
                self.workflows.workflow_continue()
            elif key == "verify":
                self.workflows.workflow_verify()
            elif key == "run":
                self.workflows.workflow_run()
            elif key == "safety_tests":
                self.workflows.workflow_safety_tests()
            elif key == "status":
                self.workflows.workflow_status()
            elif key == "settings":
                self.workflows.workflow_settings()


def run_interactive_wizard(
    *,
    root_dir: Path | None = None,
    input_fn: InputFn = input,
    console: Console | None = None,
    caps: TerminalCapabilities | None = None,
) -> int:
    """Launch the default interactive terminal wizard."""
    wizard = InteractiveWizard(
        root_dir=root_dir,
        input_fn=input_fn,
        console=console,
        caps=caps,
    )
    return wizard.run()
