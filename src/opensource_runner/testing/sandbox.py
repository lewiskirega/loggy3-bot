"""Disposable sandbox manager supporting Docker/Podman and isolated tempdir/venv fallback."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from opensource_runner.models import SandboxConfig
from opensource_runner.testing.environment import detect_container_engine
from opensource_runner.testing.filesystem_guard import (
    HARNESS_MARKER_FILE,
    mark_harness_directory,
    safe_remove_harness_directory,
)
from opensource_runner.testing.models import ProcessMetrics
from opensource_runner.testing.network_guard import build_sandbox_env, detect_leaked_secrets
from opensource_runner.testing.timeout import run_monitored_command

SANDBOX_PREFIX = "osr-sandbox-"


class DisposableSandbox:
    """Isolated disposable test environment with guaranteed cleanup."""

    def __init__(
        self,
        project_id: str,
        config: SandboxConfig,
        *,
        prefer_container: bool = True,
    ) -> None:
        self.project_id = project_id
        self.config = config
        self.root_dir = Path(tempfile.mkdtemp(prefix=f"{SANDBOX_PREFIX}{project_id}-")).resolve()
        mark_harness_directory(self.root_dir)
        self.sandbox_home = self.root_dir / "home"
        self.sandbox_home.mkdir(parents=True, exist_ok=True)
        self.source_cache_dir = self.root_dir / "source-cache"
        self.workspace_dir = self.root_dir / "workspace"
        self.state_dir = self.root_dir / "state"
        self.logs_dir = self.root_dir / "logs"
        for d in (self.source_cache_dir, self.workspace_dir, self.state_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)

        self.container_engine: str | None = detect_container_engine() if prefer_container else None
        self.container_ready = self._probe_container_engine()
        self.mode = (
            f"container:{self.container_engine}" if self.container_ready else "isolated-tempdir"
        )

    def _probe_container_engine(self) -> bool:
        if not self.container_engine:
            return False
        try:
            res = subprocess.run(
                [self.container_engine, "info"],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            return res.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def build_clean_env(self, extra_env: dict[str, str] | None = None) -> dict[str, str]:
        env = build_sandbox_env(self.sandbox_home, extra_env=extra_env)
        leaked = detect_leaked_secrets(env)
        if leaked:
            for key in leaked:
                env.pop(key, None)
        return env

    def build_container_run_command(
        self,
        *,
        image: str,
        project_dir: Path,
        command: list[str],
        network_enabled: bool = False,
        extra_env: dict[str, str] | None = None,
    ) -> list[str]:
        """Build a hardened, non-root, resource-limited container invocation."""
        assert self.container_engine is not None
        args: list[str] = [
            self.container_engine,
            "run",
            "--rm",
            f"--cpus={self.config.cpu_limit}",
            f"--memory={self.config.memory_limit_mb}m",
            f"--pids-limit={self.config.process_limit}",
            "--security-opt=no-new-privileges",
            "--workdir=/sandbox",
            "-v",
            f"{project_dir.resolve()}:/sandbox:rw",
        ]
        if not network_enabled:
            args.extend(["--network", "none"])
        if hasattr(os, "getuid") and hasattr(os, "getgid"):
            args.extend(["--user", f"{os.getuid()}:{os.getgid()}"])
        if extra_env:
            for key, val in extra_env.items():
                args.extend(["-e", f"{key}={val}"])
        args.append(image)
        args.extend(command)
        return args

    def run_in_sandbox(
        self,
        command: list[str],
        *,
        cwd: Path,
        timeout_seconds: int | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> ProcessMetrics:
        """Execute a command inside the isolated tempdir sandbox with allowlisted env."""
        clean_env = self.build_clean_env(extra_env=extra_env)
        return run_monitored_command(
            command,
            cwd=cwd,
            env=clean_env,
            timeout_seconds=timeout_seconds or self.config.execution_timeout_seconds,
        )

    def cleanup(self) -> bool:
        """Destroy the disposable sandbox directory and verify removal."""
        return safe_remove_harness_directory(self.root_dir)


def cleanup_abandoned_sandboxes(base_temp_dir: Path | None = None) -> list[str]:
    """Remove only harness-marked abandoned sandbox directories under the OS temp dir."""
    root = (base_temp_dir or Path(tempfile.gettempdir())).resolve()
    removed: list[str] = []
    if not root.is_dir():
        return removed
    for child in sorted(root.iterdir()):
        if not child.is_dir() or not child.name.startswith(SANDBOX_PREFIX):
            continue
        if (child / HARNESS_MARKER_FILE).is_file():
            safe_remove_harness_directory(child)
            removed.append(str(child))
    return removed
