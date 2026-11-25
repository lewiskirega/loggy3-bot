"""Unit tests for doctor, version, clean CLI commands and command validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from opensource_runner import __version__
from opensource_runner.cli.app import app
from opensource_runner.security import SecurityError, validate_command_argv

runner = CliRunner()


def test_version_command() -> None:
    r = runner.invoke(app, ["version"])
    assert r.exit_code == 0
    assert __version__ in r.stdout


def test_doctor_command_runs_cleanly(tmp_path: Path) -> None:
    (tmp_path / "projects").mkdir()
    r = runner.invoke(app, ["doctor", "--root", str(tmp_path)])
    assert r.exit_code == 0
    assert "OpenSource Runner Doctor" in r.stdout
    assert "Overall:" in r.stdout


def test_clean_command_requires_confirmation(tmp_path: Path) -> None:
    ws = tmp_path / "workspace" / "flappy"
    ws.mkdir(parents=True)
    (ws / "Flappy.py").write_text("print(1)\n", encoding="utf-8")

    # Declined clean must leave workspace intact
    r = runner.invoke(app, ["clean", "flappy", "--root", str(tmp_path)], input="n\n")
    assert r.exit_code == 0
    assert (ws / "Flappy.py").is_file()

    # Confirmed clean removes workspace
    r = runner.invoke(app, ["clean", "flappy", "--yes", "--root", str(tmp_path)])
    assert r.exit_code == 0
    assert not ws.exists()


def test_validate_command_argv_blocks_privileged_and_shell_operators() -> None:
    assert validate_command_argv(["python", "Flappy.py"]) == ["python", "Flappy.py"]

    with pytest.raises(SecurityError):
        validate_command_argv([])

    with pytest.raises(SecurityError):
        validate_command_argv(["sudo", "rm", "-rf", "/"])

    with pytest.raises(SecurityError):
        validate_command_argv(["python", "app.py; rm -rf /"])
