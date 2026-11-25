"""Unit tests for TypingOrchestrator with mocked InputController."""

from __future__ import annotations

from pathlib import Path

from opensource_runner.checkpoint import CheckpointManager
from opensource_runner.models import ProjectCheckpoint, ProjectState, TypingConfig
from opensource_runner.typing import TypingOrchestrator, VSCodeController
from opensource_runner.typing.platforms import MockInputController


def _make_orchestrator(
    tmp_path: Path, mock_input: MockInputController
) -> tuple[CheckpointManager, TypingOrchestrator]:
    mgr = CheckpointManager(tmp_path / "state")
    vscode = VSCodeController(dry_run=True)
    cfg = TypingConfig(character_delay_ms=0, file_delay_ms=0)
    orch = TypingOrchestrator(
        checkpoint_manager=mgr,
        input_controller=mock_input,
        vscode_controller=vscode,
        typing_config=cfg,
        source_cache_root=tmp_path / "source-cache",
        sleep_fn=lambda _: None,
    )
    return mgr, orch


def test_typing_reproduces_text_and_binary_and_checkpoints(tmp_path: Path) -> None:
    src = tmp_path / "source-cache" / "flappy" / "sha1"
    ws = tmp_path / "workspace" / "flappy"
    src.mkdir(parents=True)
    (src / "Flappy.py").write_text("print('flap')\n", encoding="utf-8")
    (src / "icon.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x01")

    mock_input = MockInputController(focus_ok=True)
    mgr, orch = _make_orchestrator(tmp_path, mock_input)
    cp = ProjectCheckpoint(
        project_id="flappy",
        project_name="Flappy",
        repository="https://example.com/flappy",
        state=ProjectState.PREPARED,
        license_approved=True,
        inspection_complete=True,
    )
    mgr.save_checkpoint(cp)

    outcome = orch.reproduce(cp, src, ws)
    assert outcome.status == "completed"
    assert outcome.completed_files == 2
    assert (ws / "Flappy.py").read_text(encoding="utf-8") == "print('flap')\n"
    assert (ws / "icon.png").read_bytes() == b"\x89PNG\r\n\x1a\n\x00\x01"
    assert ("ctrl", "s") in mock_input.hotkeys


def test_typing_pauses_on_focus_failure(tmp_path: Path) -> None:
    src = tmp_path / "source-cache" / "flappy" / "sha1"
    ws = tmp_path / "workspace" / "flappy"
    src.mkdir(parents=True)
    (src / "Flappy.py").write_text("x = 1\n", encoding="utf-8")

    mock_input = MockInputController(focus_ok=False)
    mgr, orch = _make_orchestrator(tmp_path, mock_input)
    cp = ProjectCheckpoint(
        project_id="flappy",
        project_name="Flappy",
        repository="https://example.com/flappy",
        state=ProjectState.PREPARED,
    )
    mgr.save_checkpoint(cp)

    outcome = orch.reproduce(cp, src, ws)
    assert outcome.status == "focus_failed"
    loaded = mgr.load_checkpoint("flappy")
    assert loaded is not None and loaded.state == ProjectState.PAUSED

    # Explicit manual focus confirmation (e.g. GNOME Wayland) allows proceeding safely
    outcome_ok = orch.reproduce(cp, src, ws, manual_focus_confirm=lambda _ws, _reason: True)
    assert outcome_ok.status == "completed"
    assert (ws / "Flappy.py").read_text(encoding="utf-8") == "x = 1\n"


def test_typing_halts_on_verification_failure_without_auto_repair(tmp_path: Path) -> None:
    src = tmp_path / "source-cache" / "flappy" / "sha1"
    ws = tmp_path / "workspace" / "flappy"
    src.mkdir(parents=True)
    (src / "Flappy.py").write_text("x = 1\n", encoding="utf-8")

    mock_input = MockInputController(focus_ok=True, corrupt_on_save=True)
    mgr, orch = _make_orchestrator(tmp_path, mock_input)
    cp = ProjectCheckpoint(
        project_id="flappy",
        project_name="Flappy",
        repository="https://example.com/flappy",
        state=ProjectState.PREPARED,
    )
    mgr.save_checkpoint(cp)

    outcome = orch.reproduce(cp, src, ws)
    assert outcome.status == "verification_failed"
    assert outcome.failed_file == "Flappy.py"
    # Corrupted file must NOT be auto-repaired
    assert "# CORRUPTED" in (ws / "Flappy.py").read_text(encoding="utf-8")


def test_resume_skips_already_verified_files_and_retypes_interrupted(tmp_path: Path) -> None:
    src = tmp_path / "source-cache" / "flappy" / "sha1"
    ws = tmp_path / "workspace" / "flappy"
    src.mkdir(parents=True)
    ws.mkdir(parents=True)
    (src / "a.py").write_bytes(b"a = 1\n")
    (src / "b.py").write_bytes(b"b = 2\n")
    # Simulate a.py already verified and b.py partially typed
    (ws / "a.py").write_bytes(b"a = 1\n")
    (ws / "b.py").write_bytes(b"b = ")

    mock_input = MockInputController(focus_ok=True)
    mgr, orch = _make_orchestrator(tmp_path, mock_input)
    cp = ProjectCheckpoint(
        project_id="flappy",
        project_name="Flappy",
        repository="https://example.com/flappy",
        state=ProjectState.PAUSED,
        completed_files=["a.py"],
        remaining_files=["b.py"],
    )
    mgr.save_checkpoint(cp)

    outcome = orch.reproduce(cp, src, ws)
    assert outcome.status == "completed"
    # Only b.py characters should have been typed
    assert "".join(mock_input.typed_chars) == "b = 2\n"
    assert (ws / "b.py").read_text(encoding="utf-8") == "b = 2\n"
