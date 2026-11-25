"""Optional Docker / Podman container runtime adapter."""

from __future__ import annotations

import shutil
from pathlib import Path

from opensource_runner.execution.runtimes.base import (
    CommandStep,
    ExecutionPlan,
    RuntimeAdapter,
)
from opensource_runner.models import InspectionReport


class ContainerRuntime(RuntimeAdapter):
    """Builds and runs Dockerfile-based projects using Docker or Podman."""

    name = "Container"

    def __init__(self, engine: str | None = None) -> None:
        self.engine = engine or shutil.which("docker") or shutil.which("podman")

    def supports(self, report: InspectionReport) -> bool:
        return bool(report.docker_files) and self.engine is not None

    def build_plan(self, report: InspectionReport, workspace_dir: Path) -> ExecutionPlan:
        engine_name = Path(self.engine).name if self.engine else "docker"
        image_tag = f"opensource-runner-{report.project_id}:local"
        work_dir = workspace_dir.resolve()
        setup_steps = [
            CommandStep(
                description=f"Build container image '{image_tag}' with {engine_name}",
                command=[engine_name, "build", "-t", image_tag, "."],
                cwd=work_dir,
                requires_approval=True,
            )
        ]
        port = "8080"
        if report.expected_url and ":" in report.expected_url.rsplit("/", 1)[-1]:
            port = report.expected_url.rsplit(":", 1)[-1]
        run_cmd = [engine_name, "run", "--rm", "-p", f"{port}:{port}", image_tag]
        return ExecutionPlan(
            runtime_name=f"Container ({engine_name})",
            working_dir=work_dir,
            setup_steps=setup_steps,
            run_command=run_cmd,
            expected_url=report.expected_url or f"http://127.0.0.1:{port}",
        )
