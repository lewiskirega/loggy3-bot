"""Typing orchestrator: character-by-character reproduction, binary copy, verification, and checkpoints."""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from opensource_runner.checkpoint import CheckpointManager
from opensource_runner.github import classify_file
from opensource_runner.models import (
    ProjectCheckpoint,
    ProjectProgress,
    ProjectState,
    TypingConfig,
)
from opensource_runner.security import (
    assert_not_in_source_cache,
    validate_safe_relative_path,
)
from opensource_runner.typing.platforms import (
    InputBackendError,
    InputController,
)
from opensource_runner.typing.vscode import VSCodeController
from opensource_runner.verification import verify_single_file


@dataclass
class TypingOutcome:
    status: str  # "completed" | "paused" | "stopped" | "focus_failed" | "verification_failed"
    message: str
    failed_file: str | None = None
    completed_files: int = 0
    total_files: int = 0


ProgressCallback = Callable[[ProjectProgress], None]


class TypingOrchestrator:
    """Reproduces source-cache files into workspace/<project-id>/ with per-file verification."""

    def __init__(
        self,
        *,
        checkpoint_manager: CheckpointManager,
        input_controller: InputController,
        vscode_controller: VSCodeController,
        typing_config: TypingConfig,
        source_cache_root: Path,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.checkpoints = checkpoint_manager
        self.input_ctrl = input_controller
        self.vscode = vscode_controller
        self.config = typing_config
        self.source_cache_root = source_cache_root.resolve()
        self.sleep = sleep_fn

    def reproduce(
        self,
        checkpoint: ProjectCheckpoint,
        source_dir: Path,
        workspace_dir: Path,
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> TypingOutcome:
        """Run or resume file-by-file reproduction."""
        health = self.input_ctrl.check_availability()
        if not health.available:
            raise InputBackendError(health.reason)

        # Build deterministic ordered file list if not already populated
        all_source_rel = [
            p.relative_to(source_dir).as_posix()
            for p in sorted(source_dir.rglob("*"))
            if p.is_file() and ".git" not in p.parts
        ]
        total_files = len(all_source_rel)

        # Validate previously completed files before skipping them
        verified_completed: list[str] = []
        for rel in checkpoint.completed_files:
            if rel in all_source_rel:
                src_p = validate_safe_relative_path(source_dir, rel)
                ws_p = validate_safe_relative_path(workspace_dir, rel)
                res = verify_single_file(rel, src_p, ws_p, classify_file(src_p))
                if res.verified:
                    verified_completed.append(rel)

        remaining = [rel for rel in all_source_rel if rel not in verified_completed]
        checkpoint.completed_files = verified_completed
        checkpoint.remaining_files = remaining
        self.checkpoints.clear_control_signal(checkpoint.project_id)
        self.checkpoints.transition(checkpoint, ProjectState.TYPING)

        workspace_dir.mkdir(parents=True, exist_ok=True)
        self.vscode.open_workspace(workspace_dir)

        char_delay_s = self.config.character_delay_ms / 1000.0
        file_delay_s = self.config.file_delay_ms / 1000.0

        for rel in list(remaining):
            # Check pause/stop control signal before each file
            sig = self.checkpoints.read_control_signal(checkpoint.project_id)
            if sig.action == "pause":
                self.checkpoints.transition(checkpoint, ProjectState.PAUSED)
                return TypingOutcome(
                    status="paused",
                    message="Typing paused by user request.",
                    completed_files=len(checkpoint.completed_files),
                    total_files=total_files,
                )
            if sig.action == "stop":
                self.checkpoints.transition(
                    checkpoint, ProjectState.PAUSED, error="Stopped by user."
                )
                return TypingOutcome(
                    status="stopped",
                    message="Typing stopped safely by user request (not completed).",
                    completed_files=len(checkpoint.completed_files),
                    total_files=total_files,
                )

            src_file = validate_safe_relative_path(source_dir, rel)
            ws_file = validate_safe_relative_path(workspace_dir, rel)
            assert_not_in_source_cache(ws_file, self.source_cache_root)

            ftype = classify_file(src_file)
            checkpoint.current_file = rel
            checkpoint.current_position = 0
            self.checkpoints.save_checkpoint(checkpoint)

            if ftype == "binary":
                ws_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_file, ws_file)
                ver = verify_single_file(rel, src_file, ws_file, "binary")
                if not ver.verified:
                    self.checkpoints.transition(
                        checkpoint,
                        ProjectState.PAUSED,
                        error=f"Binary verification failed for {rel}: {ver.reason}",
                    )
                    return TypingOutcome(
                        status="verification_failed",
                        message=ver.reason,
                        failed_file=rel,
                        completed_files=len(checkpoint.completed_files),
                        total_files=total_files,
                    )
            else:
                # Focus verification before typing text file
                focus = self.input_ctrl.verify_focus("VS Code", workspace_dir)
                if not focus.verified:
                    self.checkpoints.transition(
                        checkpoint,
                        ProjectState.PAUSED,
                        error=f"Focus could not be verified: {focus.reason}",
                    )
                    return TypingOutcome(
                        status="focus_failed",
                        message=focus.reason,
                        failed_file=rel,
                        completed_files=len(checkpoint.completed_files),
                        total_files=total_files,
                    )

                # If partial file exists from an interrupted run, verify first; never assume valid
                if ws_file.exists():
                    pre_ver = verify_single_file(rel, src_file, ws_file, "text")
                    if not pre_ver.verified:
                        # Clear invalid partial file before fresh reproduction
                        ws_file.write_bytes(b"")

                self.vscode.open_file(workspace_dir, ws_file)
                self.input_ctrl.prepare_target_file(ws_file)

                text = src_file.read_bytes().decode("utf-8")
                total_chars = len(text)
                try:
                    for idx, ch in enumerate(text, start=1):
                        if idx % 25 == 0:
                            sig = self.checkpoints.read_control_signal(checkpoint.project_id)
                            if sig.action in ("pause", "stop"):
                                checkpoint.current_position = idx - 1
                                self.checkpoints.transition(checkpoint, ProjectState.PAUSED)
                                return TypingOutcome(
                                    status="paused" if sig.action == "pause" else "stopped",
                                    message=f"Typing {sig.action}d during '{rel}'.",
                                    completed_files=len(checkpoint.completed_files),
                                    total_files=total_files,
                                )

                        self.input_ctrl.type_character(ch)
                        checkpoint.current_position = idx
                        if char_delay_s > 0:
                            self.sleep(char_delay_s)

                        if progress_callback and (idx == total_chars or idx % 20 == 0):
                            pct = (
                                (len(checkpoint.completed_files) + (idx / max(total_chars, 1)))
                                / max(total_files, 1)
                            ) * 100.0
                            prog = ProjectProgress(
                                project_id=checkpoint.project_id,
                                total_files=total_files,
                                completed_files=len(checkpoint.completed_files),
                                remaining_files=total_files - len(checkpoint.completed_files),
                                current_file=rel,
                                current_char_index=idx,
                                current_file_total_chars=total_chars,
                                percent_complete=round(pct, 2),
                            )
                            progress_callback(prog)
                except KeyboardInterrupt:
                    self.checkpoints.transition(
                        checkpoint, ProjectState.PAUSED, error="Interrupted by user (SIGINT)."
                    )
                    return TypingOutcome(
                        status="paused",
                        message="Typing paused safely via keyboard interrupt.",
                        completed_files=len(checkpoint.completed_files),
                        total_files=total_files,
                    )

                # Save via Ctrl+S and verify from disk
                self.input_ctrl.send_hotkey("ctrl", "s")
                ver = verify_single_file(rel, src_file, ws_file, "text")
                if not ver.verified:
                    self.checkpoints.transition(
                        checkpoint,
                        ProjectState.PAUSED,
                        error=f"Verification failed for {rel}: {ver.reason}",
                    )
                    return TypingOutcome(
                        status="verification_failed",
                        message=ver.reason,
                        failed_file=rel,
                        completed_files=len(checkpoint.completed_files),
                        total_files=total_files,
                    )

            # File succeeded — update checkpoint & progress
            checkpoint.completed_files.append(rel)
            checkpoint.remaining_files = [r for r in checkpoint.remaining_files if r != rel]
            checkpoint.current_file = None
            checkpoint.current_position = 0
            self.checkpoints.save_checkpoint(checkpoint)

            prog = ProjectProgress(
                project_id=checkpoint.project_id,
                total_files=total_files,
                completed_files=len(checkpoint.completed_files),
                remaining_files=len(checkpoint.remaining_files),
                current_file=rel,
                current_char_index=0,
                current_file_total_chars=0,
                percent_complete=round(
                    (len(checkpoint.completed_files) / max(total_files, 1)) * 100.0, 2
                ),
            )
            self.checkpoints.save_progress(prog)
            if progress_callback:
                progress_callback(prog)

            if file_delay_s > 0:
                self.sleep(file_delay_s)

        return TypingOutcome(
            status="completed",
            message=f"All {total_files} files reproduced and verified.",
            completed_files=len(checkpoint.completed_files),
            total_files=total_files,
        )
