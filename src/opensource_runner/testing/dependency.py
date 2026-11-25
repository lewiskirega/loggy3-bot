"""Isolated dependency installation inside the disposable sandbox."""

from __future__ import annotations

import time

from opensource_runner.execution.runtimes import ExecutionPlan
from opensource_runner.testing.models import StageResult, StageStatus
from opensource_runner.testing.sandbox import DisposableSandbox


def install_sandbox_dependencies(
    plan: ExecutionPlan,
    sandbox: DisposableSandbox,
    *,
    allow_network: bool = False,
) -> tuple[StageResult, str, str]:
    """Install dependencies strictly inside the disposable sandbox with timeouts."""
    t0 = time.monotonic()
    if not plan.setup_steps:
        return (
            StageResult(
                name="dependency_installation",
                status=StageStatus.PASS,
                duration_seconds=round(time.monotonic() - t0, 3),
                message="No external dependencies required.",
            ),
            "",
            "",
        )

    if not allow_network:
        return (
            StageResult(
                name="dependency_installation",
                status=StageStatus.SKIPPED,
                duration_seconds=round(time.monotonic() - t0, 3),
                message="Skipped network dependency installation (offline/network-disabled mode).",
                details={"proposed_steps": [" ".join(s.command) for s in plan.setup_steps]},
            ),
            "",
            "",
        )

    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    for step in plan.setup_steps:
        metrics = sandbox.run_in_sandbox(
            step.command,
            cwd=step.cwd,
            timeout_seconds=sandbox.config.dependency_timeout_seconds,
            extra_env=plan.env_overrides or None,
        )
        stdout_parts.append(metrics.stdout)
        stderr_parts.append(metrics.stderr)
        if metrics.timed_out or metrics.exit_code != 0:
            return (
                StageResult(
                    name="dependency_installation",
                    status=StageStatus.FAIL,
                    duration_seconds=round(time.monotonic() - t0, 3),
                    message=(
                        f"Dependency step failed ({' '.join(step.command)}): "
                        f"{metrics.termination_reason} / exit={metrics.exit_code}"
                    ),
                ),
                "\n".join(stdout_parts),
                "\n".join(stderr_parts),
            )

    return (
        StageResult(
            name="dependency_installation",
            status=StageStatus.PASS,
            duration_seconds=round(time.monotonic() - t0, 3),
            message=f"Installed {len(plan.setup_steps)} isolated dependency step(s).",
        ),
        "\n".join(stdout_parts),
        "\n".join(stderr_parts),
    )
