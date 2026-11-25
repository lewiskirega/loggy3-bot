"""Per-project end-to-end disposable sandbox test runner."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from opensource_runner.checkpoint import CheckpointManager
from opensource_runner.execution import ExecutionError, ExecutionOrchestrator
from opensource_runner.github import GitHubRetriever, GitRetrievalError
from opensource_runner.licensing import inspect_license, write_license_reports
from opensource_runner.models import (
    LicenseStatus,
    ProjectCheckpoint,
    ProjectRegistryEntry,
    ProjectState,
    SandboxConfig,
    TypingConfig,
    utc_now,
)
from opensource_runner.projects import inspect_project
from opensource_runner.testing.dependency import install_sandbox_dependencies
from opensource_runner.testing.filesystem_guard import FilesystemGuard
from opensource_runner.testing.healthcheck import run_sandbox_execution_and_healthcheck
from opensource_runner.testing.models import ProjectSelfTestReport, StageResult, StageStatus
from opensource_runner.testing.runtime import run_static_validation
from opensource_runner.testing.sandbox import DisposableSandbox
from opensource_runner.typing import TypingOrchestrator, VSCodeController
from opensource_runner.typing.platforms import MockInputController
from opensource_runner.verification import verify_project

LogFn = Callable[[str, str], None]


def run_project_self_test(
    entry: ProjectRegistryEntry,
    sandbox_config: SandboxConfig,
    *,
    allow_network: bool = False,
    allow_execution: bool = True,
    local_override: Path | None = None,
    log_fn: LogFn | None = None,
) -> tuple[ProjectSelfTestReport, dict[str, object]]:
    """Run all pipeline stages for one project inside a disposable sandbox."""

    def _log(tag: str, msg: str) -> None:
        if log_fn:
            log_fn(tag, msg)

    report = ProjectSelfTestReport(
        project_id=entry.id,
        project_name=entry.name,
        repository=entry.repository,
    )
    artifacts: dict[str, object] = {}

    sandbox = DisposableSandbox(entry.id, sandbox_config)
    report.sandbox_mode = sandbox.mode
    report.sandbox_used = True
    fs_guard = FilesystemGuard(allowed_roots=[sandbox.root_dir])
    fs_guard.capture_baseline()
    _log(
        "SANDBOX",
        f"Created disposable sandbox for {entry.id} ({sandbox.mode}) at {sandbox.root_dir}",
    )

    try:
        # 1. Source Retrieval
        t0 = time.monotonic()
        retriever = GitHubRetriever()
        try:
            if local_override is not None:
                cache_dir, provenance, manifest = retriever.import_local_folder_to_cache(
                    project_id=entry.id,
                    project_name=entry.name,
                    local_source_dir=local_override,
                    source_cache_root=sandbox.source_cache_dir,
                )
            else:
                cache_dir, provenance, manifest = retriever.retrieve_to_cache(
                    project_id=entry.id,
                    project_name=entry.name,
                    repository=entry.repository,
                    source_cache_root=sandbox.source_cache_dir,
                    revision=entry.revision,
                )
            ret_time = round(time.monotonic() - t0, 3)
            report.timings_seconds["retrieval"] = ret_time
            report.commit_sha = provenance.commit
            report.branch = provenance.branch
            report.stages.append(
                StageResult(
                    name="source_retrieval",
                    status=StageStatus.PASS,
                    duration_seconds=ret_time,
                    message=f"Retrieved {manifest.total_files} files @ {provenance.commit[:12]}",
                )
            )
            _log("GITHUB", f"Retrieved {entry.id} ({provenance.branch} @ {provenance.commit[:12]})")
        except GitRetrievalError as exc:
            report.stages.append(
                StageResult(
                    name="source_retrieval",
                    status=StageStatus.FAIL,
                    duration_seconds=round(time.monotonic() - t0, 3),
                    message=str(exc),
                )
            )
            report.result = StageStatus.FAIL
            return report, artifacts

        # 2. Provenance & Workspace
        ws_dir = sandbox.workspace_dir / entry.id
        prov_dir = ws_dir / ".provenance"
        prov_dir.mkdir(parents=True, exist_ok=True)
        (prov_dir / "repository.json").write_text(
            provenance.model_dump_json(indent=2), encoding="utf-8"
        )
        (prov_dir / "source-manifest.json").write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8"
        )
        report.stages.append(
            StageResult(
                name="provenance_verification",
                status=StageStatus.PASS,
                message=f"Recorded repository.json and source-manifest.json ({manifest.total_files} files).",
            )
        )
        _log("PROVENANCE", f"Wrote provenance metadata for {entry.id}")

        # 3. License Detection
        lic = inspect_license(entry.id, entry.name, cache_dir)
        write_license_reports(prov_dir, lic)
        report.license_detected = lic.detected_license
        report.license_confidence = (
            "HIGH" if lic.license_file and lic.detected_license != "UNKNOWN" else "LOW"
        )
        lic_status = StageStatus.PASS if lic.status == LicenseStatus.APPROVED else StageStatus.WARN
        report.stages.append(
            StageResult(
                name="license_verification",
                status=lic_status,
                message=lic.reason,
                details={
                    "detected": lic.detected_license,
                    "file": lic.license_file,
                    "confidence": report.license_confidence,
                },
            )
        )

        # 4. Runtime & Project Inspection
        insp = inspect_project(entry.id, provenance.commit, cache_dir)
        report.runtime = insp.runtime
        report.network_required = bool(insp.dependencies)
        artifacts["runtime"] = insp.model_dump(mode="json")
        artifacts["dependencies"] = {
            "package_managers": insp.package_managers,
            "dependency_files": insp.dependency_files,
            "dependencies": insp.dependencies,
            "setup_commands": insp.setup_commands,
        }
        report.stages.append(
            StageResult(
                name="runtime_detection",
                status=StageStatus.PASS if insp.runtime != "UNKNOWN" else StageStatus.WARN,
                message=f"Runtime={insp.runtime}, entry_point={insp.entry_point}",
            )
        )

        # 5. File Reproduction + Intentional Pause/Resume Checkpoint Test
        t_rep = time.monotonic()
        cp_mgr = CheckpointManager(sandbox.state_dir)
        cp = ProjectCheckpoint(
            project_id=entry.id,
            project_name=entry.name,
            repository=entry.repository,
            state=ProjectState.PREPARED,
            branch=provenance.branch,
            commit=provenance.commit,
            source_cache_dir=str(cache_dir),
            workspace_dir=str(ws_dir),
            retrieval_approved=True,
            license_approved=True,
            inspection_complete=True,
            runtime=insp.runtime,
        )
        cp_mgr.save_checkpoint(cp)

        mock_input = MockInputController(focus_ok=True)
        orch = TypingOrchestrator(
            checkpoint_manager=cp_mgr,
            input_controller=mock_input,
            vscode_controller=VSCodeController(dry_run=True),
            typing_config=TypingConfig(character_delay_ms=0, file_delay_ms=0),
            source_cache_root=sandbox.source_cache_dir,
            sleep_fn=lambda _: None,
        )

        # Trigger a pause at ~30% progress if there are >= 3 files, then resume
        total_src = manifest.total_files
        pause_after = max(1, int(total_src * 0.3)) if total_src >= 3 else 0
        paused_once = {"done": False}

        def _pause_hook(prog) -> None:
            if pause_after and not paused_once["done"] and prog.completed_files >= pause_after:
                paused_once["done"] = True
                cp_mgr.set_control_signal(entry.id, "pause")

        first_outcome = orch.reproduce(cp, cache_dir, ws_dir, progress_callback=_pause_hook)
        checkpoint_ok = True
        if first_outcome.status == "paused":
            loaded_cp = cp_mgr.load_checkpoint(entry.id)
            if loaded_cp is None or loaded_cp.state != ProjectState.PAUSED:
                checkpoint_ok = False
            else:
                resumed = orch.reproduce(loaded_cp, cache_dir, ws_dir)
                if resumed.status != "completed":
                    checkpoint_ok = False
        elif first_outcome.status != "completed":
            checkpoint_ok = False

        rep_time = round(time.monotonic() - t_rep, 3)
        report.timings_seconds["reproduction"] = rep_time
        report.stages.append(
            StageResult(
                name="file_reproduction",
                status=StageStatus.PASS if checkpoint_ok else StageStatus.FAIL,
                duration_seconds=rep_time,
                message=f"Reproduced {total_src} files (pause/resume tested={paused_once['done']}).",
            )
        )
        report.stages.append(
            StageResult(
                name="checkpoint_resume",
                status=StageStatus.PASS if checkpoint_ok else StageStatus.FAIL,
                message="Checkpoint save/load/resume verified."
                if checkpoint_ok
                else "Checkpoint resume failed.",
            )
        )

        # 6. Full File Hash Verification
        t_ver = time.monotonic()
        ver_report = verify_project(entry.id, provenance.commit, cache_dir, ws_dir)
        cp_mgr.save_verification(ver_report)
        artifacts["verification"] = ver_report.model_dump(mode="json")
        ver_time = round(time.monotonic() - t_ver, 3)
        report.timings_seconds["verification"] = ver_time
        report.stages.append(
            StageResult(
                name="file_hash_verification",
                status=StageStatus.PASS if ver_report.verified else StageStatus.FAIL,
                duration_seconds=ver_time,
                message=f"Verified {ver_report.verified_files}/{ver_report.total_files} files.",
            )
        )

        # 7. Static Validation
        static_res = run_static_validation(ws_dir, insp, sandbox)
        report.stages.append(static_res)

        # 8. Build Execution Plan, Isolated Dependencies, Execution & Healthcheck
        exec_orch = ExecutionOrchestrator(checkpoint_manager=cp_mgr)
        try:
            plan = exec_orch.build_plan(insp, ws_dir)
            dep_res, dep_out, dep_err = install_sandbox_dependencies(
                plan, sandbox, allow_network=allow_network
            )
            report.dependencies_status = dep_res.status
            report.stages.append(dep_res)
            report.stdout_log += dep_out
            report.stderr_log += dep_err

            can_run = allow_execution and dep_res.status in (StageStatus.PASS,)
            exec_res, hc_res, run_out, run_err = run_sandbox_execution_and_healthcheck(
                plan, insp, sandbox, allow_execution=can_run
            )
            report.execution_status = exec_res.status
            report.healthcheck_status = hc_res.status
            report.stages.append(exec_res)
            report.stages.append(hc_res)
            report.stdout_log += run_out
            report.stderr_log += run_err
        except ExecutionError as exc:
            report.dependencies_status = StageStatus.FAIL
            report.execution_status = StageStatus.FAIL
            report.healthcheck_status = StageStatus.SKIPPED
            report.stages.append(
                StageResult(name="project_execution", status=StageStatus.FAIL, message=str(exc))
            )

        # 9. Filesystem Safety Check
        fs_ok, changed_paths = fs_guard.verify_no_host_modifications()
        report.stages.append(
            StageResult(
                name="filesystem_safety",
                status=StageStatus.PASS if fs_ok else StageStatus.FAIL,
                message="No host files outside sandbox modified."
                if fs_ok
                else f"Unexpected host modifications: {', '.join(changed_paths)}",
            )
        )
    finally:
        t_clean = time.monotonic()
        cleaned = sandbox.cleanup()
        clean_time = round(time.monotonic() - t_clean, 3)
        report.timings_seconds["cleanup"] = clean_time
        report.cleanup_status = StageStatus.PASS if cleaned else StageStatus.FAIL
        report.stages.append(
            StageResult(
                name="sandbox_cleanup",
                status=report.cleanup_status,
                duration_seconds=clean_time,
                message="Sandbox destroyed and verified removed."
                if cleaned
                else "Sandbox cleanup incomplete.",
            )
        )
        artifacts["sandbox"] = {
            "mode": sandbox.mode,
            "cpu_limit": sandbox_config.cpu_limit,
            "memory_limit_mb": sandbox_config.memory_limit_mb,
            "process_limit": sandbox_config.process_limit,
            "cleaned": cleaned,
        }
        report.finished_at = utc_now()

    has_fail = any(s.status == StageStatus.FAIL for s in report.stages)
    report.result = StageStatus.FAIL if has_fail else StageStatus.PASS
    return report, artifacts
