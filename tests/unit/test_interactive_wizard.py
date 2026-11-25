"""Unit tests for the minimal interactive terminal wizard (mocked I/O, no live keyboard)."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Iterator

from rich.console import Console
from typer.testing import CliRunner

from opensource_runner.checkpoint import CheckpointManager
from opensource_runner.cli.app import app
from opensource_runner.config import load_config
from opensource_runner.interactive.app import InteractiveWizard
from opensource_runner.interactive.confirmation import ask_confirmation
from opensource_runner.interactive.formatting import (
    TerminalCapabilities,
    detect_terminal_capabilities,
    render_banner,
    render_status_table,
)
from opensource_runner.interactive.navigation import MenuChoice, NavAction
from opensource_runner.interactive.prompts import PromptSession
from opensource_runner.models import ProjectCheckpoint, ProjectState

runner = CliRunner()


def _make_scripted_input(answers: list[str]):
    it: Iterator[str] = iter(answers)

    def _fn(prompt: str) -> str:
        try:
            return next(it)
        except StopIteration:
            raise EOFError from None

    return _fn


def _make_capture_console(plain: bool = True) -> tuple[Console, StringIO, TerminalCapabilities]:
    buf = StringIO()
    caps = TerminalCapabilities(
        is_tty=not plain,
        supports_unicode=not plain,
        supports_color=False,
        plain_mode=plain,
    )
    console = Console(file=buf, no_color=True, force_terminal=False, width=100)
    return console, buf, caps


def _setup_workspace(tmp_path: Path) -> Path:
    (tmp_path / "projects").mkdir(parents=True)
    for pid, name, url in (
        ("flappy", "Flappy", "https://github.com/Makivskyi2006/Flappy"),
        (
            "flask-inventory-management",
            "Flask Inventory Management",
            "https://github.com/alaminerca/Flask-Inventory-Management",
        ),
        ("flaskblog", "FlaskBlog", "https://github.com/DogukanUrker/flaskBlog"),
        ("flatnotes", "flatnotes", "https://github.com/dullage/flatnotes"),
    ):
        (tmp_path / "projects" / f"{pid}.toml").write_text(
            f'id = "{pid}"\nname = "{name}"\nrepository = "{url}"\nrevision = "auto"\nenabled = true\n',
            encoding="utf-8",
        )
    return tmp_path


def test_main_menu_renders_and_exits_cleanly(tmp_path: Path) -> None:
    root = _setup_workspace(tmp_path)
    console, buf, caps = _make_capture_console(plain=True)
    wizard = InteractiveWizard(
        root_dir=root,
        input_fn=_make_scripted_input(["8"]),
        console=console,
        caps=caps,
    )
    code = wizard.run()
    out = buf.getvalue()
    assert code == 0
    assert "OPENSOURCE RUNNER" in out
    assert "1. Prepare a project" in out
    assert "8. Exit" in out
    assert "Goodbye." in out


def test_invalid_answer_defaults_back_and_quit() -> None:
    console, buf, _ = _make_capture_console(plain=True)
    prompts = PromptSession(console, input_fn=_make_scripted_input(["99", "", "b", "q"]))
    choices = [MenuChoice("a", "Alpha"), MenuChoice("b_opt", "Beta")]

    # First invalid ("99"), then Enter selects default (2 -> Beta)
    res1 = prompts.ask_choice("Pick one", choices, default_index=2)
    assert res1.action == NavAction.SELECT and res1.choice_key == "b_opt"
    assert "Invalid choice '99'" in buf.getvalue()

    res2 = prompts.ask_choice("Pick again", choices)
    assert res2.action == NavAction.BACK

    res3 = prompts.ask_choice("Pick third", choices)
    assert res3.action == NavAction.QUIT


def test_keyboard_interrupt_exits_safely(tmp_path: Path) -> None:
    root = _setup_workspace(tmp_path)
    console, buf, caps = _make_capture_console(plain=True)

    def _raise_ctrl_c(_prompt: str) -> str:
        raise KeyboardInterrupt

    wizard = InteractiveWizard(root_dir=root, input_fn=_raise_ctrl_c, console=console, caps=caps)
    assert wizard.run() == 0
    assert "Interrupted safely." in buf.getvalue()


def test_confirmation_rejection_never_starts_operation(tmp_path: Path, monkeypatch) -> None:
    root = _setup_workspace(tmp_path)
    console, buf, caps = _make_capture_console(plain=True)
    called = {"download": False}

    # Choose 1 (Prepare) -> 1 (Flappy) -> 4 (Complete preparation) -> n (reject confirmation) -> 8 (Exit)
    wizard = InteractiveWizard(
        root_dir=root,
        input_fn=_make_scripted_input(["1", "1", "4", "n", "8"]),
        console=console,
        caps=caps,
    )

    def _spy(*args, **kwargs):
        called["download"] = True
        return True

    monkeypatch.setattr(wizard.workflows, "_do_download_and_inspect", _spy)
    assert wizard.run() == 0
    assert called["download"] is False
    assert "READY TO START" in buf.getvalue()


def test_confirmation_defaults_and_acceptance() -> None:
    console, _, _ = _make_capture_console(plain=True)
    # Safe default False on Enter, then explicit 'y'
    p1 = PromptSession(console, input_fn=_make_scripted_input(["", "y"]))
    assert ask_confirmation(p1, title="RUN", summary_lines=["cmd"], default_yes=False) is False
    assert ask_confirmation(p1, title="RUN", summary_lines=["cmd"], default_yes=False) is True


def test_status_and_continue_previous_work_menus(tmp_path: Path) -> None:
    root = _setup_workspace(tmp_path)
    cp_mgr = CheckpointManager(root / "state")
    cp = ProjectCheckpoint(
        project_id="flappy",
        project_name="Flappy",
        repository="https://github.com/Makivskyi2006/Flappy",
        state=ProjectState.PAUSED,
        current_file="Flappy.py",
    )
    cp_mgr.save_checkpoint(cp)

    console, buf, caps = _make_capture_console(plain=True)
    # 6 (Status) -> b (back) -> 2 (Continue) -> 1 (Flappy) -> n (decline resume) -> 8 (Exit)
    wizard = InteractiveWizard(
        root_dir=root,
        input_fn=_make_scripted_input(["6", "b", "2", "1", "n", "8"]),
        console=console,
        caps=caps,
    )
    assert wizard.run() == 0
    out = buf.getvalue()
    assert "PROJECTS WITH SAVED PROGRESS" in out
    assert "Flappy" in out
    assert "PAUSED" in out


def test_settings_persists_non_sensitive_preferences(tmp_path: Path) -> None:
    root = _setup_workspace(tmp_path)
    console, _, caps = _make_capture_console(plain=True)
    # 7 (Settings) -> 1 (Typing speed) -> 45 -> y (save) -> 8 (Exit)
    wizard = InteractiveWizard(
        root_dir=root,
        input_fn=_make_scripted_input(["7", "1", "45", "y", "8"]),
        console=console,
        caps=caps,
    )
    assert wizard.run() == 0
    reloaded = load_config(root_dir=root)
    assert reloaded.typing.typing_speed == 45
    cfg_text = (root / "config.toml").read_text(encoding="utf-8")
    assert "password" not in cfg_text.lower()
    assert "token" not in cfg_text.lower()


def test_safety_test_menu_and_plain_terminal_fallback(tmp_path: Path) -> None:
    root = _setup_workspace(tmp_path)
    console, buf, caps = _make_capture_console(plain=True)
    # 5 (Safety tests) -> 5 (View previous test report -> none) -> 8 (Exit)
    wizard = InteractiveWizard(
        root_dir=root,
        input_fn=_make_scripted_input(["5", "5", "8"]),
        console=console,
        caps=caps,
    )
    assert wizard.run() == 0
    assert "What would you like to test?" in buf.getvalue()

    # Plain terminal capability formatting check (Windows CMD / dumb terminal fallback)
    plain_caps = detect_terminal_capabilities("plain")
    assert plain_caps.plain_mode is True
    assert plain_caps.supports_unicode is False
    render_banner(console, plain_caps)
    render_status_table(console, plain_caps, [("Flappy", "VERIFIED", "100%")])
    assert "+------------------------------------------+" in buf.getvalue()


def test_bare_cli_launches_interactive_wizard(tmp_path: Path) -> None:
    root = _setup_workspace(tmp_path)
    r = runner.invoke(app, ["--root", str(root)], input="8\n")
    assert r.exit_code == 0
    assert "OPENSOURCE RUNNER" in r.stdout
    assert "1. Prepare a project" in r.stdout
