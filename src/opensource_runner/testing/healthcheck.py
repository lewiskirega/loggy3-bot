"""Automated HTTP and headless GUI health checks for sandboxed project runs."""

from __future__ import annotations

import shutil
import subprocess
import time
import urllib.error
import urllib.request

from opensource_runner.execution.runtimes import ExecutionPlan
from opensource_runner.models import InspectionReport
from opensource_runner.security import validate_command_argv
from opensource_runner.testing.models import StageResult, StageStatus
from opensource_runner.testing.sandbox import DisposableSandbox


def poll_http_health(url: str, timeout_seconds: int = 15) -> tuple[bool, int | None, str]:
    """Poll an HTTP endpoint until it responds or times out."""
    deadline = time.monotonic() + timeout_seconds
    last_err = "no response"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                code = int(resp.status)
                if 200 <= code < 500:
                    return True, code, f"HTTP {code} from {url}"
        except urllib.error.HTTPError as exc:
            # Even 401/403/404 confirms the web server is up and serving HTTP
            return True, int(exc.code), f"HTTP {exc.code} from {url}"
        except Exception as exc:
            last_err = str(exc)
            time.sleep(0.4)
    return False, None, f"Health check timed out for {url}: {last_err}"


def run_sandbox_execution_and_healthcheck(
    plan: ExecutionPlan,
    inspection: InspectionReport,
    sandbox: DisposableSandbox,
    *,
    allow_execution: bool = True,
) -> tuple[StageResult, StageResult, str, str]:
    """Execute a project safely in the sandbox and run an appropriate health check."""
    t0 = time.monotonic()
    if not allow_execution:
        return (
            StageResult(
                name="project_execution",
                status=StageStatus.SKIPPED,
                message="Execution skipped by test configuration.",
            ),
            StageResult(
                name="healthcheck",
                status=StageStatus.SKIPPED,
                message="Health check skipped because execution was skipped.",
            ),
            "",
            "",
        )

    if not plan.run_command:
        return (
            StageResult(
                name="project_execution",
                status=StageStatus.FAIL,
                message="No documented run command detected.",
            ),
            StageResult(
                name="healthcheck",
                status=StageStatus.SKIPPED,
                message="Health check skipped due to missing run command.",
            ),
            "",
            "",
        )

    # GUI apps (e.g., tkinter Flappy): never hijack the user's real desktop
    if "tkinter" in inspection.frameworks:
        xvfb = shutil.which("xvfb-run")
        if not xvfb:
            return (
                StageResult(
                    name="project_execution",
                    status=StageStatus.SKIPPED,
                    duration_seconds=round(time.monotonic() - t0, 3),
                    message=(
                        "GUI_EXECUTION = SKIPPED (tkinter GUI app and Xvfb unavailable; "
                        "refusing to hijack host desktop)."
                    ),
                ),
                StageResult(
                    name="healthcheck",
                    status=StageStatus.SKIPPED,
                    message="GUI health check skipped without virtual display.",
                ),
                "",
                "",
            )
        cmd = [xvfb, "-a", *plan.run_command]
    else:
        cmd = list(plan.run_command)

    validate_command_argv(cmd)
    env = sandbox.build_clean_env(extra_env=plan.env_overrides or None)
    proc = subprocess.Popen(
        cmd,
        cwd=str(plan.working_dir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
    )

    try:
        if plan.expected_url:
            ok, status_code, msg = poll_http_health(
                plan.expected_url,
                timeout_seconds=min(sandbox.config.healthcheck_timeout_seconds, 20),
            )
            # Terminate cleanly after health check
            proc.terminate()
            try:
                stdout, stderr = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate(timeout=5)

            elapsed = round(time.monotonic() - t0, 3)
            if ok:
                return (
                    StageResult(
                        name="project_execution",
                        status=StageStatus.PASS,
                        duration_seconds=elapsed,
                        message="Service started and terminated cleanly.",
                    ),
                    StageResult(
                        name="healthcheck",
                        status=StageStatus.PASS,
                        duration_seconds=elapsed,
                        message=msg,
                        details={"url": plan.expected_url, "http_status": status_code},
                    ),
                    stdout or "",
                    stderr or "",
                )
            return (
                StageResult(
                    name="project_execution",
                    status=StageStatus.FAIL,
                    duration_seconds=elapsed,
                    message=f"Service failed health check (exit={proc.returncode}).",
                ),
                StageResult(
                    name="healthcheck",
                    status=StageStatus.FAIL,
                    duration_seconds=elapsed,
                    message=msg,
                ),
                stdout or "",
                stderr or "",
            )

        # Non-HTTP process (e.g., Xvfb GUI smoke run): wait briefly to confirm no immediate crash
        time.sleep(1.5)
        polled = proc.poll()
        if polled is None:
            proc.terminate()
            try:
                stdout, stderr = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate(timeout=5)
            elapsed = round(time.monotonic() - t0, 3)
            return (
                StageResult(
                    name="project_execution",
                    status=StageStatus.PASS,
                    duration_seconds=elapsed,
                    message="Application started cleanly under virtual display and exited on SIGTERM.",
                ),
                StageResult(
                    name="healthcheck",
                    status=StageStatus.PASS,
                    duration_seconds=elapsed,
                    message="No immediate crash detected during startup window.",
                ),
                stdout or "",
                stderr or "",
            )

        stdout, stderr = proc.communicate(timeout=5)
        elapsed = round(time.monotonic() - t0, 3)
        status = StageStatus.PASS if polled == 0 else StageStatus.FAIL
        return (
            StageResult(
                name="project_execution",
                status=status,
                duration_seconds=elapsed,
                message=f"Process exited with code {polled}.",
            ),
            StageResult(
                name="healthcheck",
                status=status,
                duration_seconds=elapsed,
                message=f"Exit code {polled}.",
            ),
            stdout or "",
            stderr or "",
        )
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
