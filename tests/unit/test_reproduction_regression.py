"""Regression tests for VS Code launch, provenance separation, Wayland socket checks, and reproduction."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from typer.testing import CliRunner

from opensource_runner.checkpoint import CheckpointManager
from opensource_runner.cli.app import app
from opensource_runner.models import ProjectCheckpoint, ProjectState, TypingConfig
from opensource_runner.testing.input_test import run_controlled_typing_test
from opensource_runner.typing.orchestrator import TypingOrchestrator, enumerate_source_files
from opensource_runner.typing.platforms import (
    BackendHealth,
    FocusCheckResult,
    InputBackendError,
    InputController,
    LinuxWaylandInputController,
    MockInputController,
)
from opensource_runner.typing.vscode import VSCodeController

runner = CliRunner()


class _FailingKeyboardController(InputController):
    backend_name = "failing-mock"

    def check_availability(self) -> BackendHealth:
        return BackendHealth(self.backend_name, True, "ready")

    def verify_focus(self, expected_app: str, expected_workspace: Path) -> FocusCheckResult:
        return FocusCheckResult(True, "VS Code", "focused")

    def type_character(self, char: str) -> None:
        raise InputBackendError(
            "failed to connect socket '/tmp/.ydotool_socket': Permission denied"
        )

    def send_hotkey(self, *keys: str) -> None:
        raise InputBackendError("hotkey failed")


def test_enumerate_excludes_git_and_provenance(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x", encoding="utf-8")
    (tmp_path / ".provenance").mkdir()
    (tmp_path / ".provenance" / "source-manifest.json").write_text("{}", encoding="utf-8")
    (tmp_path / "flaskmain.py").write_text("print(1)\n", encoding="utf-8")
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "index.html").write_text("<h1>Hi</h1>\n", encoding="utf-8")

    files = enumerate_source_files(tmp_path)
    assert files == ["flaskmain.py", "templates/index.html"]


def test_vscode_controller_opens_workspace_and_rejects_provenance(tmp_path: Path) -> None:
    ws = tmp_path / "workspace" / "flask-inventory-management"
    ws.mkdir(parents=True)
    target = ws / "flaskmain.py"
    prov_dir = ws / ".provenance"
    prov_dir.mkdir()
    manifest = prov_dir / "source-manifest.json"
    manifest.write_text("{}", encoding="utf-8")

    vc = VSCodeController(dry_run=True)
    args = vc.open_workspace(ws, initial_file=target)
    assert "--new-window" in args
    assert str(ws.resolve()) in args
    assert str(target) in args
    assert "source-manifest.json" not in " ".join(args)

    with pytest.raises(ValueError, match=".provenance"):
        vc.open_workspace(prov_dir)
    with pytest.raises(ValueError, match=".provenance"):
        vc.open_file(ws, manifest)


def test_empty_source_queue_returns_cleanly(tmp_path: Path) -> None:
    src = tmp_path / "source-cache" / "empty" / "sha1"
    ws = tmp_path / "workspace" / "empty"
    src.mkdir(parents=True)
    mgr = CheckpointManager(tmp_path / "state")
    cp = ProjectCheckpoint(
        project_id="empty",
        project_name="Empty",
        repository="https://example.com/empty",
        state=ProjectState.PREPARED,
    )
    mgr.save_checkpoint(cp)
    orch = TypingOrchestrator(
        checkpoint_manager=mgr,
        input_controller=MockInputController(),
        vscode_controller=VSCodeController(dry_run=True),
        typing_config=TypingConfig(character_delay_ms=0, file_delay_ms=0),
        source_cache_root=tmp_path / "source-cache",
        sleep_fn=lambda _: None,
    )
    outcome = orch.reproduce(cp, src, ws)
    assert outcome.status == "completed"
    assert outcome.total_files == 0


def test_input_failure_transitions_checkpoint_to_paused_and_logs(tmp_path: Path, caplog) -> None:
    src = tmp_path / "source-cache" / "inv" / "sha1"
    ws = tmp_path / "workspace" / "inv"
    src.mkdir(parents=True)
    (src / "flaskmain.py").write_text("print(1)\n", encoding="utf-8")

    mgr = CheckpointManager(tmp_path / "state")
    cp = ProjectCheckpoint(
        project_id="inv",
        project_name="Inv",
        repository="https://example.com/inv",
        state=ProjectState.PREPARED,
    )
    mgr.save_checkpoint(cp)
    logger = logging.getLogger("test.reproduction")
    orch = TypingOrchestrator(
        checkpoint_manager=mgr,
        input_controller=_FailingKeyboardController(),
        vscode_controller=VSCodeController(dry_run=True),
        typing_config=TypingConfig(character_delay_ms=0, file_delay_ms=0),
        source_cache_root=tmp_path / "source-cache",
        logger=logger,
        sleep_fn=lambda _: None,
    )
    with caplog.at_level(logging.INFO, logger="test.reproduction"):
        outcome = orch.reproduce(cp, src, ws)

    assert outcome.status == "input_failed"
    assert "Permission denied" in outcome.message
    loaded = mgr.load_checkpoint("inv")
    assert loaded is not None
    assert loaded.state == ProjectState.PAUSED
    assert loaded.last_error and "Permission denied" in loaded.last_error
    assert "[REPRODUCTION] Starting project reproduction" in caplog.text


def test_wayland_check_availability_detects_missing_or_unreadable_ydotool_socket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    monkeypatch.setenv("YDOTOOL_SOCKET", str(tmp_path / "missing.sock"))
    monkeypatch.setattr(
        "shutil.which", lambda name: "/usr/bin/ydotool" if name == "ydotool" else None
    )

    ctrl = LinuxWaylandInputController()
    health = ctrl.check_availability()
    assert health.available is False
    assert "socket was not found" in health.reason


def test_controlled_typing_test_passes_with_mock_and_fails_safely_when_unavailable() -> None:
    vc = VSCodeController(dry_run=True)
    rep_ok = run_controlled_typing_test(MockInputController(focus_ok=True), vc)
    assert rep_ok.overall == "PASS"
    assert rep_ok.exact_content_verification == "PASS"

    rep_unavail = run_controlled_typing_test(MockInputController(available=False), vc)
    assert rep_unavail.overall == "UNSUPPORTED"
    assert rep_unavail.keyboard_input == "UNSUPPORTED"


def test_doctor_input_flag_outputs_diagnostics() -> None:
    r = runner.invoke(app, ["doctor", "--input"])
    assert r.exit_code == 0
    assert "OPEN SOURCE RUNNER INPUT DIAGNOSTICS" in r.stdout
    assert "Backend available:" in r.stdout
    assert "Overall result:" in r.stdout
