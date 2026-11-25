"""Monitored subprocess execution with strict timeouts and orphan cleanup."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from opensource_runner.models import utc_now
from opensource_runner.security import validate_command_argv
from opensource_runner.testing.models import ProcessMetrics


def run_monitored_command(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout_seconds: int = 120,
) -> ProcessMetrics:
    """Execute a structured argv command with timeout enforcement and clean termination."""
    validate_command_argv(command)
    start_ts = utc_now()
    t0 = time.monotonic()

    proc = subprocess.Popen(
        command,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
    )
    timed_out = False
    reason = "completed"
    try:
        stdout, stderr = proc.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        reason = f"timeout after {timeout_seconds}s"
        proc.terminate()
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate(timeout=5)
            reason = f"force-killed after {timeout_seconds}s timeout"

    elapsed = round(time.monotonic() - t0, 3)
    return ProcessMetrics(
        pid=proc.pid,
        command=command,
        start_time=start_ts,
        end_time=utc_now(),
        duration_seconds=elapsed,
        exit_code=proc.returncode,
        stdout=stdout or "",
        stderr=stderr or "",
        timed_out=timed_out,
        termination_reason=reason,
    )
