"""Static validation checks executed before running third-party project code."""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

from opensource_runner.models import InspectionReport
from opensource_runner.testing.models import StageResult, StageStatus
from opensource_runner.testing.sandbox import DisposableSandbox


def run_static_validation(
    workspace_dir: Path,
    inspection: InspectionReport,
    sandbox: DisposableSandbox,
) -> StageResult:
    """Run language-appropriate static syntax/manifest validation inside the sandbox."""
    t0 = time.monotonic()
    errors: list[str] = []
    checks_run: list[str] = []

    if "Python" in inspection.languages:
        checks_run.append("python -m compileall")
        metrics = sandbox.run_in_sandbox(
            [sys.executable, "-m", "compileall", "-q", "."],
            cwd=workspace_dir,
            timeout_seconds=60,
        )
        if metrics.exit_code != 0:
            errors.append(
                f"Python compileall failed: {metrics.stderr.strip() or metrics.stdout.strip()}"
            )

    pkg_json = workspace_dir / "package.json"
    if pkg_json.is_file():
        checks_run.append("package.json parse")
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or "name" not in data:
                errors.append("package.json missing required 'name' field.")
        except json.JSONDecodeError as exc:
            errors.append(f"Invalid package.json: {exc}")

    if "PHP" in inspection.languages and shutil.which("php"):
        checks_run.append("php -l")
        for php_file in sorted(workspace_dir.rglob("*.php")):
            metrics = sandbox.run_in_sandbox(
                ["php", "-l", str(php_file)],
                cwd=workspace_dir,
                timeout_seconds=30,
            )
            if metrics.exit_code != 0:
                errors.append(f"php -l failed on {php_file.name}: {metrics.stderr.strip()}")

    if inspection.entry_point:
        ep = workspace_dir / inspection.entry_point
        checks_run.append(f"entry_point:{inspection.entry_point}")
        if not ep.is_file():
            errors.append(f"Declared entry point not found: {inspection.entry_point}")

    elapsed = round(time.monotonic() - t0, 3)
    if errors:
        return StageResult(
            name="static_validation",
            status=StageStatus.FAIL,
            duration_seconds=elapsed,
            message="; ".join(errors),
            details={"checks": checks_run, "errors": errors},
        )
    return StageResult(
        name="static_validation",
        status=StageStatus.PASS,
        duration_seconds=elapsed,
        message=f"Static validation passed ({', '.join(checks_run) or 'no checks required'}).",
        details={"checks": checks_run},
    )
