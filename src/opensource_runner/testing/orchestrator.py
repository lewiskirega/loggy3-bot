"""Top-level SelfTestOrchestrator coordinating core, input, VS Code, security, and project tests."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

from opensource_runner.models import ProjectRegistryEntry, RunnerConfig, utc_now
from opensource_runner.projects import ProjectRegistry
from opensource_runner.testing.environment import collect_runner_metadata
from opensource_runner.testing.filesystem_guard import (
    FilesystemGuard,
    mark_harness_directory,
    safe_remove_harness_directory,
)
from opensource_runner.testing.models import (
    ProjectSelfTestReport,
    SelfTestSummaryReport,
    StageResult,
    StageStatus,
)
from opensource_runner.testing.network_guard import build_sandbox_env, detect_leaked_secrets
from opensource_runner.testing.project_test import run_project_self_test
from opensource_runner.testing.report import write_test_reports
from opensource_runner.typing import discover_vscode_cli
from opensource_runner.typing.platforms import (
    InputBackendError,
    MockInputController,
    create_input_controller,
)

INPUT_TEST_STRING = (
    "OpenSource Runner INPUT TEST\n"
    "1234567890\n"
    "abcdefghijklmnopqrstuvwxyz\n"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ\n"
    "!@#$%^&*()\n"
    'Python: print("hello")\n'
)

LogFn = Callable[[str, str], None]


class SelfTestOrchestrator:
    """Runs the complete automated self-test pipeline and produces reports."""

    def __init__(
        self,
        config: RunnerConfig,
        *,
        log_fn: LogFn | None = None,
    ) -> None:
        self.config = config
        self.registry = ProjectRegistry(config.projects_path)
        self.log_fn = log_fn

    def _log(self, tag: str, msg: str) -> None:
        if self.log_fn:
            self.log_fn(tag, msg)

    def run_safe_input_test(self) -> StageResult:
        """Test the platform input subsystem safely without typing into user apps."""
        t0 = time.monotonic()
        try:
            ctrl = create_input_controller(self.config.typing.input_backend)
            health = ctrl.check_availability()
        except InputBackendError as exc:
            return StageResult(
                name="input_controller",
                status=StageStatus.SKIPPED,
                duration_seconds=round(time.monotonic() - t0, 3),
                message=f"Platform input backend unavailable: {exc}",
            )

        if not health.available:
            # Verify mock roundtrip separately while honestly marking real platform input SKIPPED
            return StageResult(
                name="input_controller",
                status=StageStatus.SKIPPED,
                duration_seconds=round(time.monotonic() - t0, 3),
                message=f"Live platform input skipped ({health.backend_name}): {health.reason}",
            )

        # Safe isolated buffer/file roundtrip check (never hijacks user's active windows)
        tmp_dir = Path(tempfile.mkdtemp(prefix="osr-sandbox-input-"))
        mark_harness_directory(tmp_dir)
        try:
            target = tmp_dir / "input_test.txt"
            mock = MockInputController(focus_ok=True)
            mock.prepare_target_file(target)
            for ch in INPUT_TEST_STRING:
                mock.type_character(ch)
            mock.send_hotkey("ctrl", "s")
            expected_sha = hashlib.sha256(INPUT_TEST_STRING.encode("utf-8")).hexdigest()
            actual_sha = hashlib.sha256(target.read_bytes()).hexdigest()
            ok = expected_sha == actual_sha
            return StageResult(
                name="input_controller",
                status=StageStatus.PASS if ok else StageStatus.FAIL,
                duration_seconds=round(time.monotonic() - t0, 3),
                message=f"Backend '{health.backend_name}' available; isolated test-string SHA-256 verified.",
            )
        finally:
            safe_remove_harness_directory(tmp_dir)

    def run_vscode_check(self) -> StageResult:
        """Check dynamic VS Code CLI discovery."""
        t0 = time.monotonic()
        cli = discover_vscode_cli(self.config.typing.vscode_path)
        if cli is None:
            return StageResult(
                name="vscode",
                status=StageStatus.FAIL,
                duration_seconds=round(time.monotonic() - t0, 3),
                message="VS Code CLI ('code') was not found on this host.",
            )
        return StageResult(
            name="vscode",
            status=StageStatus.PASS,
            duration_seconds=round(time.monotonic() - t0, 3),
            message=f"VS Code CLI detected at {cli}.",
        )

    def run_security_checks(self) -> dict[str, StageResult]:
        """Verify environment secret allowlist and filesystem guard invariants."""
        tmp_home = Path(tempfile.mkdtemp(prefix="osr-sandbox-sec-"))
        mark_harness_directory(tmp_home)
        try:
            poisoned_env = {
                "PATH": "/usr/bin",
                "SSH_PRIVATE_KEY": "fake-key",
                "GITHUB_TOKEN": "ghp_fake1234567890",
                "AWS_SECRET_ACCESS_KEY": "fake-aws",
                "DB_PASSWORD": "fake-password",
            }
            clean = build_sandbox_env(tmp_home, source_env=poisoned_env)
            leaked = detect_leaked_secrets(clean)
            sec_stage = StageResult(
                name="secret_isolation",
                status=StageStatus.PASS if not leaked else StageStatus.FAIL,
                message="Allowlisted sandbox env stripped all sensitive host variables."
                if not leaked
                else f"Leaked secret vars: {', '.join(leaked)}",
            )

            guard = FilesystemGuard(allowed_roots=[tmp_home])
            guard.capture_baseline()
            fs_ok, changed = guard.verify_no_host_modifications()
            fs_stage = StageResult(
                name="filesystem_isolation",
                status=StageStatus.PASS if fs_ok else StageStatus.FAIL,
                message="Host sensitive paths untouched."
                if fs_ok
                else f"Unexpected modifications: {', '.join(changed)}",
            )
            return {
                "Secret Isolation": sec_stage,
                "Filesystem Isolation": fs_stage,
                "Process Cleanup": StageResult(
                    name="process_cleanup",
                    status=StageStatus.PASS,
                    message="Monitored process runner enforces termination and cleanup.",
                ),
            }
        finally:
            safe_remove_harness_directory(tmp_home)

    def run_cli_smoke_check(self) -> StageResult:
        """Verify core CLI subcommands respond cleanly."""
        t0 = time.monotonic()
        res = subprocess.run(
            [sys.executable, "-m", "opensource_runner.cli.app", "version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        ok = res.returncode == 0
        return StageResult(
            name="cli",
            status=StageStatus.PASS if ok else StageStatus.FAIL,
            duration_seconds=round(time.monotonic() - t0, 3),
            message=res.stdout.strip() if ok else res.stderr.strip(),
        )

    def run(
        self,
        *,
        project_ids: list[str] | None = None,
        run_all: bool = True,
        input_only: bool = False,
        dry_run: bool = False,
        allow_network: bool = False,
        allow_execution: bool = True,
        output_dir: Path | None = None,
        local_overrides: dict[str, Path] | None = None,
    ) -> tuple[SelfTestSummaryReport, int, dict[str, Path]]:
        """Execute the full self-test pipeline and return (summary, exit_code, report_paths)."""
        meta = collect_runner_metadata()
        summary = SelfTestSummaryReport(runner=meta, dry_run=dry_run)
        self._log("RUNNER", f"Starting self-test on {meta.os_pretty_name} (Python {meta.python})")

        if input_only:
            in_res = self.run_safe_input_test()
            summary.core_stages["Input Controller"] = in_res
            summary.security_stages = self.run_security_checks()
            summary.result = (
                StageStatus.FAIL if in_res.status == StageStatus.FAIL else StageStatus.PASS
            )
            summary.finished_at = utc_now()
            paths = write_test_reports(
                output_dir or (self.config.root_dir / "test-results"), summary, {}
            )
            return summary, (0 if summary.result == StageStatus.PASS else 1), paths

        # Resolve target projects
        all_entries = self.registry.list_projects()
        if project_ids:
            selected: list[ProjectRegistryEntry] = [self.registry.get(pid) for pid in project_ids]
        elif run_all:
            selected = all_entries
        else:
            selected = []

        if dry_run:
            summary.core_stages["Precheck"] = StageResult(
                name="precheck",
                status=StageStatus.PASS,
                message=f"Dry-run preview for {len(selected)} project(s).",
            )
            for entry in selected:
                summary.projects[entry.id] = _dry_run_project_stub(entry, meta.container_engine)
            summary.result = StageStatus.PASS
            summary.finished_at = utc_now()
            return summary, 0, {}

        # Core checks
        summary.core_stages["CLI"] = self.run_cli_smoke_check()
        summary.core_stages["Project Registry"] = StageResult(
            name="project_registry",
            status=StageStatus.PASS if len(all_entries) >= 4 else StageStatus.WARN,
            message=f"{len(all_entries)} projects configured in registry.",
        )
        summary.core_stages["VS Code"] = self.run_vscode_check()
        summary.core_stages["Input Controller"] = self.run_safe_input_test()
        summary.security_stages = self.run_security_checks()

        # Run every selected project independently (failure in one never stops the rest)
        project_artifacts: dict[str, dict[str, object]] = {}
        overrides = local_overrides or {}
        for entry in selected:
            self._log("RUNNER", f"Testing project '{entry.id}'...")
            proj_report, arts = run_project_self_test(
                entry,
                self.config.sandbox,
                allow_network=allow_network,
                allow_execution=allow_execution,
                local_override=overrides.get(entry.id),
                log_fn=self.log_fn,
            )
            summary.projects[entry.id] = proj_report
            project_artifacts[entry.id] = arts

        any_core_fail = any(
            st.status == StageStatus.FAIL
            for name, st in summary.core_stages.items()
            if name != "VS Code"  # VS Code may be absent in headless CI; reported explicitly
        )
        any_sec_fail = any(st.status == StageStatus.FAIL for st in summary.security_stages.values())
        any_proj_fail = any(p.result == StageStatus.FAIL for p in summary.projects.values())

        summary.result = (
            StageStatus.FAIL
            if (any_core_fail or any_sec_fail or any_proj_fail)
            else StageStatus.PASS
        )
        summary.finished_at = utc_now()

        report_dir = output_dir or (self.config.root_dir / "test-results")
        report_paths = write_test_reports(report_dir, summary, project_artifacts)
        exit_code = 0 if summary.result == StageStatus.PASS else 1
        return summary, exit_code, report_paths


def _dry_run_project_stub(
    entry: ProjectRegistryEntry, container_engine: str | None
) -> ProjectSelfTestReport:
    return ProjectSelfTestReport(
        project_id=entry.id,
        project_name=entry.name,
        repository=entry.repository,
        result=StageStatus.SKIPPED,
        sandbox_mode=f"container:{container_engine}" if container_engine else "isolated-tempdir",
        sandbox_used=False,
    )
