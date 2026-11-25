"""Node.js runtime adapter respecting npm, pnpm, and yarn lockfiles."""

from __future__ import annotations

import shlex
from pathlib import Path

from opensource_runner.execution.runtimes.base import (
    CommandStep,
    ExecutionPlan,
    RuntimeAdapter,
)
from opensource_runner.models import InspectionReport


class NodeRuntime(RuntimeAdapter):
    """Node.js execution adapter."""

    name = "Node.js"

    def supports(self, report: InspectionReport) -> bool:
        return report.runtime == "Node.js"

    def build_plan(self, report: InspectionReport, workspace_dir: Path) -> ExecutionPlan:
        work_dir = workspace_dir.resolve()
        setup_steps = [
            CommandStep(
                description=f"Node setup: {cmd_str}",
                command=shlex.split(cmd_str),
                cwd=work_dir,
                requires_approval=True,
            )
            for cmd_str in report.setup_commands
        ]
        run_cmd = shlex.split(report.run_command) if report.run_command else []
        return ExecutionPlan(
            runtime_name=self.name,
            working_dir=work_dir,
            setup_steps=setup_steps,
            run_command=run_cmd,
            expected_url=report.expected_url,
        )
