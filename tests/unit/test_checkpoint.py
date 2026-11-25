"""Unit tests for checkpoints, state transitions, and corruption handling."""

from __future__ import annotations

from pathlib import Path

import pytest

from opensource_runner.checkpoint import (
    CheckpointManager,
    CorruptedCheckpointError,
    InvalidStateTransitionError,
)
from opensource_runner.models import ProjectCheckpoint, ProjectState


def test_checkpoint_save_load_and_active_project(tmp_path: Path) -> None:
    mgr = CheckpointManager(tmp_path / "state")
    cp = ProjectCheckpoint(
        project_id="flappy",
        project_name="Flappy",
        repository="https://github.com/Makivskyi2006/Flappy",
        state=ProjectState.SELECTED,
    )
    mgr.set_active_project("flappy")
    mgr.save_checkpoint(cp)

    assert mgr.get_active_project() == "flappy"
    loaded = mgr.load_checkpoint("flappy")
    assert loaded is not None
    assert loaded.project_id == "flappy"
    assert loaded.state == ProjectState.SELECTED


def test_cannot_transition_to_running_without_verification(tmp_path: Path) -> None:
    mgr = CheckpointManager(tmp_path / "state")
    cp = ProjectCheckpoint(
        project_id="flappy",
        project_name="Flappy",
        repository="https://github.com/Makivskyi2006/Flappy",
        state=ProjectState.PREPARED,
        verification_passed=False,
    )
    mgr.save_checkpoint(cp)

    with pytest.raises(InvalidStateTransitionError):
        mgr.transition(cp, ProjectState.RUNNING)


def test_corrupted_checkpoint_raises_explicit_error(tmp_path: Path) -> None:
    mgr = CheckpointManager(tmp_path / "state")
    cp_file = mgr.checkpoint_file("flappy")
    cp_file.parent.mkdir(parents=True, exist_ok=True)
    cp_file.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(CorruptedCheckpointError):
        mgr.load_checkpoint("flappy")
