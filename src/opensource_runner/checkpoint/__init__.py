"""Persistent checkpointing, state transitions, and cross-process control signals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from opensource_runner.models import (
    ALLOWED_TRANSITIONS,
    ControlSignal,
    ProjectCheckpoint,
    ProjectProgress,
    ProjectState,
    ProjectVerificationReport,
    utc_now,
)


class CheckpointError(Exception):
    """Raised when checkpoint loading, saving, or state transitioning fails."""


class InvalidStateTransitionError(CheckpointError):
    """Raised on illegal project state machine transitions."""


class CorruptedCheckpointError(CheckpointError):
    """Raised when a checkpoint JSON file cannot be parsed or validated."""


def _atomic_write_json(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(payload, encoding="utf-8")
    tmp_path.replace(path)


class CheckpointManager:
    """Manages per-project state under state/projects/<project-id>/."""

    def __init__(self, state_root: Path) -> None:
        self.state_root = state_root.resolve()
        self.projects_root = self.state_root / "projects"
        self.active_file = self.state_root / "active_project.json"

    def project_dir(self, project_id: str) -> Path:
        return self.projects_root / project_id

    def checkpoint_file(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "checkpoint.json"

    def progress_file(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "progress.json"

    def verification_file(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "verification.json"

    def control_file(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "control.json"

    # ---- Active project tracking ----

    def set_active_project(self, project_id: str) -> None:
        payload = json.dumps(
            {"active_project_id": project_id, "updated_at": utc_now().isoformat()},
            indent=2,
        )
        _atomic_write_json(self.active_file, payload)

    def get_active_project(self) -> str | None:
        if not self.active_file.exists():
            return None
        try:
            data = json.loads(self.active_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CorruptedCheckpointError(f"Corrupted active project file: {exc}") from exc
        value = data.get("active_project_id")
        return str(value) if value else None

    # ---- Checkpoint CRUD ----

    def save_checkpoint(self, checkpoint: ProjectCheckpoint) -> Path:
        checkpoint.updated_at = utc_now()
        path = self.checkpoint_file(checkpoint.project_id)
        _atomic_write_json(path, checkpoint.model_dump_json(indent=2))
        return path

    def load_checkpoint(self, project_id: str) -> ProjectCheckpoint | None:
        path = self.checkpoint_file(project_id)
        if not path.exists():
            return None
        try:
            raw = path.read_text(encoding="utf-8")
            return ProjectCheckpoint.model_validate_json(raw)
        except (OSError, ValidationError, ValueError) as exc:
            raise CorruptedCheckpointError(
                f"Corrupted checkpoint for '{project_id}' at '{path}': {exc}"
            ) from exc

    def transition(
        self,
        checkpoint: ProjectCheckpoint,
        target_state: ProjectState,
        *,
        error: str | None = None,
    ) -> ProjectCheckpoint:
        current = checkpoint.state
        if target_state == ProjectState.RUNNING:
            if not checkpoint.verification_passed or current != ProjectState.READY_TO_RUN:
                raise InvalidStateTransitionError(
                    "Project cannot transition to RUNNING until verification passes "
                    "and state is READY_TO_RUN."
                )
        allowed = ALLOWED_TRANSITIONS.get(current, set())
        if target_state != current and target_state not in allowed:
            raise InvalidStateTransitionError(
                f"Invalid state transition: {current.value} -> {target_state.value}"
            )
        checkpoint.state = target_state
        if error is not None:
            checkpoint.last_error = error
        elif target_state not in (ProjectState.FAILED, ProjectState.PAUSED):
            checkpoint.last_error = None
        self.save_checkpoint(checkpoint)
        return checkpoint

    # ---- Progress CRUD ----

    def save_progress(self, progress: ProjectProgress) -> Path:
        progress.updated_at = utc_now()
        path = self.progress_file(progress.project_id)
        _atomic_write_json(path, progress.model_dump_json(indent=2))
        return path

    def load_progress(self, project_id: str) -> ProjectProgress | None:
        path = self.progress_file(project_id)
        if not path.exists():
            return None
        try:
            return ProjectProgress.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError) as exc:
            raise CorruptedCheckpointError(
                f"Corrupted progress file for '{project_id}': {exc}"
            ) from exc

    # ---- Verification CRUD ----

    def save_verification(self, report: ProjectVerificationReport) -> Path:
        path = self.verification_file(report.project_id)
        _atomic_write_json(path, report.model_dump_json(indent=2))
        return path

    def load_verification(self, project_id: str) -> ProjectVerificationReport | None:
        path = self.verification_file(project_id)
        if not path.exists():
            return None
        try:
            return ProjectVerificationReport.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError) as exc:
            raise CorruptedCheckpointError(
                f"Corrupted verification report for '{project_id}': {exc}"
            ) from exc

    # ---- Control Signals (pause / stop) ----

    def set_control_signal(self, project_id: str, action: Literal["none", "pause", "stop"]) -> Path:
        sig = ControlSignal(action=action)
        path = self.control_file(project_id)
        _atomic_write_json(path, sig.model_dump_json(indent=2))
        return path

    def read_control_signal(self, project_id: str) -> ControlSignal:
        path = self.control_file(project_id)
        if not path.exists():
            return ControlSignal(action="none")
        try:
            return ControlSignal.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError):
            return ControlSignal(action="none")

    def clear_control_signal(self, project_id: str) -> None:
        self.set_control_signal(project_id, "none")
