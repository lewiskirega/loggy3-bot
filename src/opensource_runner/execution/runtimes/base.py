"""Base abstractions for runtime adapters and tool discovery."""

from __future__ import annotations

import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from opensource_runner.models import InspectionReport


@dataclass
class CommandStep:
    description: str
    command: list[str]
    cwd: Path
    requires_approval: bool = True


@dataclass
class ExecutionPlan:
    runtime_name: str
    working_dir: Path
    setup_steps: list[CommandStep] = field(default_factory=list)
    run_command: list[str] = field(default_factory=list)
    env_overrides: dict[str, str] = field(default_factory=dict)
    expected_url: str | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class ExecutionResult:
    returncode: int
    stdout: str
    stderr: str
    detected_url: str | None = None


CommandRunner = Callable[[list[str], Path, dict[str, str] | None], ExecutionResult]


def default_command_runner(
    command: list[str], cwd: Path, env: dict[str, str] | None = None
) -> ExecutionResult:
    """Execute a subprocess safely without shell=True."""
    import os

    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    proc = subprocess.run(
        command,
        cwd=str(cwd),
        env=merged_env,
        capture_output=True,
        text=True,
        check=False,
    )
    return ExecutionResult(
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )


def detect_available_tools() -> dict[str, str | None]:
    """Discover installed runtimes and package managers via PATH."""
    tools = (
        "python3",
        "python",
        "uv",
        "git",
        "code",
        "node",
        "npm",
        "pnpm",
        "yarn",
        "php",
        "composer",
        "docker",
        "podman",
    )
    return {tool: shutil.which(tool) for tool in tools}


class RuntimeAdapter(ABC):
    """Produces an isolated ExecutionPlan from an InspectionReport."""

    name: str = "base"

    @abstractmethod
    def supports(self, report: InspectionReport) -> bool:
        """Return True if this adapter handles the inspected project."""

    @abstractmethod
    def build_plan(self, report: InspectionReport, workspace_dir: Path) -> ExecutionPlan:
        """Construct setup and run steps strictly inside workspace_dir."""
