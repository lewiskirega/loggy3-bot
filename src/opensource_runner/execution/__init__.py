"""Execution orchestrator enforcing verification and dependency approval gates."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from opensource_runner.checkpoint import CheckpointManager
from opensource_runner.execution.runtimes import (
    CommandRunner,
    ContainerRuntime,
    ExecutionPlan,
    ExecutionResult,
    NodeRuntime,
    PhpRuntime,
    PythonRuntime,
    RuntimeAdapter,
    default_command_runner,
)
from opensource_runner.models import InspectionReport, ProjectCheckpoint, ProjectState
from opensource_runner.security import SecurityError, validate_command_argv

URL_RE = re.compile(r"https?://(?:127\.0\.0\.1|localhost|0\.0\.0\.0):\d+")


class ExecutionError(RuntimeError):
    """Raised when execution preconditions fail or a command returns non-zero."""


ApprovalCallback = Callable[[str], bool]


class ExecutionOrchestrator:
    """Plans and runs verified projects only on explicit user request."""

    def __init__(
        self,
        *,
        checkpoint_manager: CheckpointManager,
        command_runner: CommandRunner = default_command_runner,
        adapters: list[RuntimeAdapter] | None = None,
    ) -> None:
        self.checkpoints = checkpoint_manager
        self.runner = command_runner
        self.adapters: list[RuntimeAdapter] = adapters or [
            PythonRuntime(),
            NodeRuntime(),
            PhpRuntime(),
            ContainerRuntime(),
        ]

    def build_plan(
        self,
        report: InspectionReport,
        workspace_dir: Path,
        *,
        prefer_container: bool = False,
    ) -> ExecutionPlan:
        if prefer_container:
            container = ContainerRuntime()
            if container.supports(report):
                return container.build_plan(report, workspace_dir)

        for adapter in self.adapters:
            if adapter.supports(report):
                return adapter.build_plan(report, workspace_dir)

        raise ExecutionError(f"No supported runtime adapter found for runtime='{report.runtime}'.")

    def execute(
        self,
        checkpoint: ProjectCheckpoint,
        report: InspectionReport,
        workspace_dir: Path,
        *,
        approve_fn: ApprovalCallback,
        require_approval: bool = True,
        prefer_container: bool = False,
    ) -> ExecutionResult:
        if not checkpoint.verification_passed or checkpoint.state != ProjectState.READY_TO_RUN:
            raise ExecutionError(
                "Project cannot be executed until full verification succeeds "
                f"(current state: {checkpoint.state.value})."
            )

        plan = self.build_plan(report, workspace_dir, prefer_container=prefer_container)
        if not plan.run_command:
            raise ExecutionError(
                "No documented run command could be determined from the repository."
            )

        # Dependency / setup steps require explicit approval
        for step in plan.setup_steps:
            try:
                validate_command_argv(step.command)
            except SecurityError as exc:
                raise ExecutionError(str(exc)) from exc
            if require_approval and step.requires_approval:
                cmd_display = " ".join(step.command)
                if not approve_fn(cmd_display):
                    raise ExecutionError(f"User declined dependency/setup command: {cmd_display}")
            res = self.runner(step.command, step.cwd, plan.env_overrides or None)
            if res.returncode != 0:
                self.checkpoints.transition(
                    checkpoint,
                    ProjectState.FAILED,
                    error=f"Setup step failed ({' '.join(step.command)}): {res.stderr.strip()}",
                )
                raise ExecutionError(
                    f"Setup step failed with exit code {res.returncode}: {res.stderr.strip()}"
                )

        if plan.setup_steps:
            checkpoint.dependencies_installed = True
            self.checkpoints.save_checkpoint(checkpoint)

        try:
            validate_command_argv(plan.run_command)
        except SecurityError as exc:
            raise ExecutionError(str(exc)) from exc

        # Transition READY_TO_RUN -> RUNNING
        self.checkpoints.transition(checkpoint, ProjectState.RUNNING)
        checkpoint.execution_status = "RUNNING"
        self.checkpoints.save_checkpoint(checkpoint)

        result = self.runner(plan.run_command, plan.working_dir, plan.env_overrides or None)
        combined = f"{result.stdout}\n{result.stderr}"
        url_match = URL_RE.search(combined)
        result.detected_url = url_match.group(0) if url_match else plan.expected_url

        if result.returncode == 0:
            checkpoint.execution_status = "COMPLETED"
            self.checkpoints.transition(checkpoint, ProjectState.COMPLETED)
        else:
            checkpoint.execution_status = f"FAILED (exit {result.returncode})"
            self.checkpoints.transition(
                checkpoint,
                ProjectState.FAILED,
                error=result.stderr.strip() or f"Process exited with code {result.returncode}",
            )
        return result
