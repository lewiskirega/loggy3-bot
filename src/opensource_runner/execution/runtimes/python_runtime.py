"""Python runtime adapter with per-project isolated virtual environments (.venv or uv)."""

from __future__ import annotations

import shlex
import shutil
import sys
from pathlib import Path

from opensource_runner.execution.runtimes.base import (
    CommandStep,
    ExecutionPlan,
    RuntimeAdapter,
)
from opensource_runner.models import InspectionReport


def _venv_python(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


class PythonRuntime(RuntimeAdapter):
    """Isolated Python execution using uv (when uv.lock is present) or venv + pip."""

    name = "Python"

    def supports(self, report: InspectionReport) -> bool:
        return report.runtime in ("Python", "Python+Node.js")

    def build_plan(self, report: InspectionReport, workspace_dir: Path) -> ExecutionPlan:
        work_dir = (
            (workspace_dir / report.working_subdir).resolve()
            if report.working_subdir
            else workspace_dir.resolve()
        )
        setup_steps: list[CommandStep] = []
        notes: list[str] = []
        env_overrides: dict[str, str] = {}

        # Handle polyglot frontend build first if Node.js is also part of the project
        if report.runtime == "Python+Node.js":
            for cmd_str in report.setup_commands:
                tokens = shlex.split(cmd_str)
                if tokens and tokens[0] in ("npm", "pnpm", "yarn"):
                    setup_steps.append(
                        CommandStep(
                            description=f"Frontend step: {cmd_str}",
                            command=tokens,
                            cwd=workspace_dir.resolve(),
                            requires_approval=True,
                        )
                    )

        use_uv = "uv" in report.package_managers and shutil.which("uv") is not None
        venv_dir = work_dir / ".venv"
        venv_py = _venv_python(venv_dir)

        if use_uv:
            setup_steps.append(
                CommandStep(
                    description="Sync isolated Python environment with uv",
                    command=["uv", "sync", "--no-dev"],
                    cwd=work_dir,
                    requires_approval=True,
                )
            )
            run_cmd = shlex.split(report.run_command) if report.run_command else []
        else:
            if report.dependencies:
                if not venv_dir.exists():
                    setup_steps.append(
                        CommandStep(
                            description="Create isolated Python virtual environment (.venv)",
                            command=[sys.executable, "-m", "venv", str(venv_dir)],
                            cwd=work_dir,
                            requires_approval=True,
                        )
                    )
                for cmd_str in report.setup_commands:
                    tokens = shlex.split(cmd_str)
                    if tokens and tokens[0] in ("python", "python3"):
                        tokens[0] = str(venv_py)
                        setup_steps.append(
                            CommandStep(
                                description=f"Install Python dependencies: {cmd_str}",
                                command=tokens,
                                cwd=work_dir,
                                requires_approval=True,
                            )
                        )
            run_tokens = shlex.split(report.run_command) if report.run_command else []
            if run_tokens and run_tokens[0] in ("python", "python3"):
                run_tokens[0] = str(venv_py) if report.dependencies else sys.executable
            run_cmd = run_tokens

        # For flatnotes-style apps requiring data path / auth defaults if unset
        if "FLATNOTES_PATH" in report.env_vars:
            data_dir = workspace_dir / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            env_overrides["FLATNOTES_PATH"] = str(data_dir)
            env_overrides.setdefault("FLATNOTES_AUTH_TYPE", "none")
            notes.append(
                f"Configured local FLATNOTES_PATH={data_dir} and FLATNOTES_AUTH_TYPE=none for local dev."
            )

        return ExecutionPlan(
            runtime_name=report.runtime,
            working_dir=work_dir,
            setup_steps=setup_steps,
            run_command=run_cmd,
            env_overrides=env_overrides,
            expected_url=report.expected_url,
            notes=notes,
        )
