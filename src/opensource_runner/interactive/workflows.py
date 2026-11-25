"""Question-driven interactive workflows delegating directly to core application services."""

from __future__ import annotations

import shlex
from pathlib import Path

from rich.console import Console

from opensource_runner.checkpoint import CheckpointManager, CorruptedCheckpointError
from opensource_runner.config import save_config
from opensource_runner.execution import ExecutionError, ExecutionOrchestrator
from opensource_runner.github import GitHubRetriever, GitRetrievalError
from opensource_runner.interactive.confirmation import ask_confirmation
from opensource_runner.interactive.formatting import (
    TerminalCapabilities,
    render_status_table,
)
from opensource_runner.interactive.menu import (
    POST_PREPARE_CHOICES,
    PREPARE_ACTION_CHOICES,
    SAFETY_TEST_CHOICES,
    SETTINGS_CHOICES,
    VERIFY_ACTION_CHOICES,
)
from opensource_runner.interactive.navigation import MenuChoice, NavAction
from opensource_runner.interactive.progress import render_progress_snapshot
from opensource_runner.interactive.prompts import PromptSession
from opensource_runner.licensing import inspect_license, write_license_reports
from opensource_runner.logging_utils import get_project_logger
from opensource_runner.models import (
    InspectionReport,
    LicenseStatus,
    ProjectCheckpoint,
    ProjectRegistryEntry,
    ProjectRunConfig,
    ProjectState,
    RunnerConfig,
    utc_now,
)
from opensource_runner.projects import ProjectRegistry, inspect_project
from opensource_runner.testing import SelfTestOrchestrator, render_summary_text
from opensource_runner.typing import TypingOrchestrator, VSCodeController
from opensource_runner.typing.platforms import InputBackendError, create_input_controller
from opensource_runner.verification import verify_project


class InteractiveWorkflows:
    """Coordinates interactive user choices with existing OpenSource Runner services."""

    def __init__(
        self,
        *,
        config: RunnerConfig,
        registry: ProjectRegistry,
        checkpoints: CheckpointManager,
        console: Console,
        caps: TerminalCapabilities,
        prompts: PromptSession,
    ) -> None:
        self.config = config
        self.registry = registry
        self.checkpoints = checkpoints
        self.console = console
        self.caps = caps
        self.prompts = prompts

    # ---- Helper selectors ----

    def _ask_project(self, question: str) -> ProjectRegistryEntry | None:
        projects = self.registry.list_projects()
        if not projects:
            self.console.print("No projects configured in projects/.")
            return None
        choices = [MenuChoice(p.id, p.name) for p in projects]
        default_idx = None
        if self.config.ui.last_project_id:
            for idx, p in enumerate(projects, start=1):
                if p.id == self.config.ui.last_project_id:
                    default_idx = idx
                    break
        sel = self.prompts.ask_choice(
            question,
            choices,
            default_index=default_idx,
            prompt_label="Select project",
        )
        if sel.action != NavAction.SELECT or not sel.choice_key:
            return None
        entry = self.registry.get(sel.choice_key)
        self.config.ui.last_project_id = entry.id
        save_config(self.config)
        return entry

    def _get_or_init_checkpoint(self, entry: ProjectRegistryEntry) -> ProjectCheckpoint:
        self.checkpoints.set_active_project(entry.id)
        cp = self.checkpoints.load_checkpoint(entry.id)
        if cp is None:
            cp = ProjectCheckpoint(
                project_id=entry.id,
                project_name=entry.name,
                repository=entry.repository,
                state=ProjectState.SELECTED,
            )
            self.checkpoints.save_checkpoint(cp)
        return cp

    # ---- Option 1: Prepare a project ----

    def workflow_prepare(self) -> str:
        """Returns 'main_menu' or 'exit'."""
        entry = self._ask_project("Which project would you like to prepare?")
        if entry is None:
            return "main_menu"

        action_sel = self.prompts.ask_choice(
            "What would you like to do?",
            PREPARE_ACTION_CHOICES,
            default_index=4,
            prompt_label="Select action",
        )
        if action_sel.action != NavAction.SELECT or action_sel.choice_key in (None, "back"):
            return "main_menu"

        action = action_sel.choice_key
        cp = self._get_or_init_checkpoint(entry)

        if action == "download_inspect":
            if not ask_confirmation(
                self.prompts,
                title="READY TO DOWNLOAD & INSPECT",
                summary_lines=[
                    f"Project: {entry.name}",
                    f"Repository: {entry.repository}",
                    "This will retrieve the repository, pin the commit, and inspect license/runtime.",
                ],
                default_yes=True,
            ):
                return "main_menu"
            self._do_download_and_inspect(entry, cp)
            return "main_menu"

        if action == "workspace":
            ws_dir = (self.config.workspace_path / entry.id).resolve()
            if not ask_confirmation(
                self.prompts,
                title="PREPARE VS CODE WORKSPACE",
                summary_lines=[
                    f"Project: {entry.name}",
                    f"Workspace: {ws_dir}",
                ],
                default_yes=True,
            ):
                return "main_menu"
            ws_dir.mkdir(parents=True, exist_ok=True)
            cp.workspace_dir = str(ws_dir)
            self.checkpoints.save_checkpoint(cp)
            self.console.print(f"Workspace ready at {ws_dir}")
            return "main_menu"

        if action == "reproduce":
            if not cp.source_cache_dir or not cp.workspace_dir:
                self.console.print("Project must be downloaded and inspected first.")
                return "main_menu"
            if not ask_confirmation(
                self.prompts,
                title="REPRODUCE SOURCE FILES",
                summary_lines=[
                    f"Project: {entry.name}",
                    f"Workspace: {cp.workspace_dir}",
                    "This will reproduce files via keyboard events and verify each file.",
                ],
                default_yes=False,
            ):
                return "main_menu"
            self._do_reproduce(cp)
            return "main_menu"

        # Complete preparation
        if not ask_confirmation(
            self.prompts,
            title="READY TO START",
            summary_lines=[
                f"Project: {entry.name}",
                f"Repository: {entry.repository}",
                "Operation: Complete preparation",
                "",
                "This will:",
                "- Retrieve the source.",
                "- Inspect its license and dependencies.",
                "- Create a workspace.",
                "- Reproduce source files.",
                "- Verify reproduced files.",
            ],
            default_yes=True,
        ):
            return "main_menu"

        if not self._do_download_and_inspect(entry, cp):
            return "main_menu"
        if not self._do_reproduce(cp):
            return "main_menu"
        ver_ok, total, verified = self._do_verify(cp)
        if not ver_ok:
            return "main_menu"

        self.console.print("\nPREPARATION COMPLETE\n")
        self.console.print(f"Project: {entry.name}\n")
        self.console.print("Source retrieved: YES")
        self.console.print("License checked: YES")
        self.console.print("Workspace created: YES")
        self.console.print(f"Files reproduced: {verified}/{total}")
        self.console.print(f"Files verified: {verified}/{total}\n")
        self.console.print(f"Status: {cp.state.value}")

        nxt = self.prompts.ask_choice(
            "What would you like to do next?",
            POST_PREPARE_CHOICES,
            default_index=3,
            allow_back=False,
        )
        if nxt.choice_key == "run":
            self._run_project_checked(entry, cp)
            return "main_menu"
        if nxt.choice_key == "view_report":
            self._print_verification_report(entry.id)
            return "main_menu"
        if nxt.choice_key == "exit" or nxt.action == NavAction.QUIT:
            return "exit"
        return "main_menu"

    def _do_download_and_inspect(self, entry: ProjectRegistryEntry, cp: ProjectCheckpoint) -> bool:
        ws_dir = (self.config.workspace_path / entry.id).resolve()
        if ws_dir.exists():
            existing = [p for p in ws_dir.iterdir() if p.name != ".provenance"]
            if existing:
                if not ask_confirmation(
                    self.prompts,
                    title="EXISTING WORKSPACE DETECTED",
                    summary_lines=[
                        f"Workspace '{ws_dir}' already contains {len(existing)} item(s).",
                    ],
                    default_yes=False,
                    question="Continue without overwriting existing files?",
                ):
                    return False

        self.checkpoints.transition(cp, ProjectState.PREPARING)
        retriever = GitHubRetriever()
        try:
            cache_dir, provenance, manifest = retriever.retrieve_to_cache(
                project_id=entry.id,
                project_name=entry.name,
                repository=entry.repository,
                source_cache_root=self.config.source_cache_path,
                revision=entry.revision,
            )
        except GitRetrievalError as exc:
            self.checkpoints.transition(cp, ProjectState.FAILED, error=str(exc))
            self.console.print(f"Retrieval failed: {exc}")
            return False

        ws_dir.mkdir(parents=True, exist_ok=True)
        prov_dir = ws_dir / ".provenance"
        prov_dir.mkdir(parents=True, exist_ok=True)
        (prov_dir / "repository.json").write_text(
            provenance.model_dump_json(indent=2), encoding="utf-8"
        )
        (prov_dir / "source-manifest.json").write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8"
        )

        lic = inspect_license(entry.id, entry.name, cache_dir)
        if lic.status == LicenseStatus.REVIEW_REQUIRED:
            approved = ask_confirmation(
                self.prompts,
                title="LICENSE REVIEW REQUIRED",
                summary_lines=[
                    f"Project: {entry.name}",
                    f"Reason: {lic.reason}",
                ],
                default_yes=False,
                question="Approve continuing despite license warning?",
            )
            if not approved:
                write_license_reports(prov_dir, lic)
                cp.license_approved = False
                self.checkpoints.transition(cp, ProjectState.PREPARED)
                self.console.print("License not approved. Stopping safely.")
                return False
            lic.status = LicenseStatus.APPROVED
            lic.user_approved = True
            lic.approved_at = utc_now()
        write_license_reports(prov_dir, lic)

        insp = inspect_project(entry.id, provenance.commit, cache_dir)
        (prov_dir / "inspection-report.json").write_text(
            insp.model_dump_json(indent=2), encoding="utf-8"
        )
        run_cfg = ProjectRunConfig(
            project_id=entry.id,
            project_name=entry.name,
            repository=provenance.repository,
            revision=provenance.commit,
            license_result=f"{lic.detected_license} ({lic.status.value})",
            license_approved=lic.user_approved,
            project_root=str(ws_dir),
            entry_point=insp.entry_point,
            runtime=insp.runtime,
            dependencies=insp.dependencies,
            setup_commands=insp.setup_commands,
            run_command=insp.run_command,
            test_command=insp.test_command,
            required_env_vars=insp.env_vars,
        )
        (prov_dir / "run-config.json").write_text(
            run_cfg.model_dump_json(indent=2), encoding="utf-8"
        )

        cp.branch = provenance.branch
        cp.commit = provenance.commit
        cp.source_cache_dir = str(cache_dir)
        cp.workspace_dir = str(ws_dir)
        cp.retrieval_approved = True
        cp.license_approved = lic.user_approved
        cp.inspection_complete = True
        cp.runtime = insp.runtime
        cp.remaining_files = [f.relative_path for f in manifest.files]
        self.checkpoints.transition(cp, ProjectState.PREPARED)
        self.console.print(
            f"Prepared {entry.name} ({provenance.branch} @ {provenance.commit[:12]}, runtime={insp.runtime})."
        )
        return True

    def _do_reproduce(self, cp: ProjectCheckpoint) -> bool:
        assert cp.source_cache_dir and cp.workspace_dir
        if not cp.license_approved:
            self.console.print("License has not been approved. Cannot reproduce source files.")
            return False
        try:
            input_ctrl = create_input_controller(self.config.typing.input_backend)
        except InputBackendError as exc:
            self.console.print(f"Input backend unavailable: {exc}")
            return False

        vscode = VSCodeController(
            configured_path=self.config.typing.vscode_path,
            dry_run=(self.config.typing.input_backend == "mock"),
        )
        logger = get_project_logger(self.config.logs_path, cp.project_id)
        orch = TypingOrchestrator(
            checkpoint_manager=self.checkpoints,
            input_controller=input_ctrl,
            vscode_controller=vscode,
            typing_config=self.config.typing,
            source_cache_root=self.config.source_cache_path,
            logger=logger,
            sleep_fn=(lambda _: None)
            if self.config.typing.input_backend == "mock"
            else __import__("time").sleep,
        )
        self.console.print(f"\nPreparing {cp.project_name} (Press Ctrl+C to pause safely)")

        def _confirm_manual_focus(ws_path: Path, reason: str) -> bool:
            confirmed = ask_confirmation(
                self.prompts,
                title="MANUAL FOCUS CONFIRMATION REQUIRED",
                summary_lines=[
                    f"Workspace: {ws_path}",
                    f"Reason: {reason}",
                    "Open and click inside the VS Code window for this workspace.",
                    "After confirming, you will have 3 seconds to focus the VS Code editor.",
                ],
                default_yes=False,
                question="Confirm VS Code workspace is open and ready?",
            )
            if confirmed:
                import time

                for sec in (3, 2, 1):
                    self.console.print(f"Focus VS Code now... starting in {sec}s")
                    time.sleep(1)
            return confirmed

        try:
            outcome = orch.reproduce(
                cp,
                Path(cp.source_cache_dir),
                Path(cp.workspace_dir),
                progress_callback=lambda p: render_progress_snapshot(
                    self.console, self.caps, cp.project_name, "Reproducing source files", p
                ),
                manual_focus_confirm=_confirm_manual_focus,
            )
        except InputBackendError as exc:
            self.console.print(f"\nInput backend blocked: {exc}")
            return False

        self.console.print("")
        if outcome.status != "completed":
            self.console.print(f"Reproduction stopped ({outcome.status}): {outcome.message}")
            return False
        return True

    def _do_verify(self, cp: ProjectCheckpoint) -> tuple[bool, int, int]:
        assert cp.source_cache_dir and cp.workspace_dir and cp.commit
        self.checkpoints.transition(cp, ProjectState.VERIFYING)
        report = verify_project(
            cp.project_id, cp.commit, Path(cp.source_cache_dir), Path(cp.workspace_dir)
        )
        self.checkpoints.save_verification(report)
        prov_dir = Path(cp.workspace_dir) / ".provenance"
        prov_dir.mkdir(parents=True, exist_ok=True)
        (prov_dir / "verification-report.json").write_text(
            report.model_dump_json(indent=2), encoding="utf-8"
        )
        if not report.verified:
            cp.verification_passed = False
            self.checkpoints.transition(cp, ProjectState.PAUSED, error="Verification failed.")
            self.console.print(
                f"Verification failed: {report.verified_files}/{report.total_files} verified."
            )
            return False, report.total_files, report.verified_files

        cp.verification_passed = True
        self.checkpoints.transition(cp, ProjectState.VERIFIED)
        self.checkpoints.transition(cp, ProjectState.READY_TO_RUN)
        return True, report.total_files, report.verified_files

    # ---- Option 2: Continue previous work ----

    def workflow_continue(self) -> None:
        saved: list[tuple[ProjectRegistryEntry, ProjectCheckpoint, float]] = []
        for entry in self.registry.list_projects():
            try:
                cp = self.checkpoints.load_checkpoint(entry.id)
            except CorruptedCheckpointError as exc:
                self.console.print(f"Warning: {exc}")
                continue
            if cp is not None and cp.state not in (ProjectState.DISCOVERED,):
                prog = self.checkpoints.load_progress(entry.id)
                pct = prog.percent_complete if prog else (100.0 if cp.verification_passed else 0.0)
                saved.append((entry, cp, pct))

        if not saved:
            self.console.print("\nNo projects with saved checkpoints found.")
            return

        choices = [
            MenuChoice(
                entry.id,
                entry.name,
                description=(
                    f"Progress: {pct:.0f}%\n"
                    f"Last file: {cp.current_file or '-'}\n"
                    f"Status: {cp.state.value}"
                ),
            )
            for entry, cp, pct in saved
        ]
        sel = self.prompts.ask_choice(
            "PROJECTS WITH SAVED PROGRESS",
            choices,
            prompt_label="Select a project to continue",
        )
        if sel.action != NavAction.SELECT or not sel.choice_key:
            return

        entry = self.registry.get(sel.choice_key)
        cp = self.checkpoints.load_checkpoint(entry.id)
        if cp is None:
            return
        if not ask_confirmation(
            self.prompts,
            title="RESUME CHECKPOINT",
            summary_lines=[
                f"Project: {entry.name}",
                f"Current state: {cp.state.value}",
                "Completed files will be re-verified; partial files will never be assumed valid.",
            ],
            default_yes=True,
            question="Resume this project?",
        ):
            return

        if cp.source_cache_dir and cp.workspace_dir:
            self._do_reproduce(cp)
        else:
            self.console.print("Checkpoint is missing source-cache/workspace. Use Prepare first.")

    # ---- Option 3: Verify a project ----

    def workflow_verify(self) -> None:
        entry = self._ask_project("Which project would you like to verify?")
        if entry is None:
            return
        sel = self.prompts.ask_choice(
            f"Verification mode for {entry.name}:",
            VERIFY_ACTION_CHOICES,
            default_index=1,
        )
        if sel.action != NavAction.SELECT or not sel.choice_key:
            return

        if sel.choice_key == "view_report":
            self._print_verification_report(entry.id)
            return

        cp = self.checkpoints.load_checkpoint(entry.id)
        if cp is None or not cp.source_cache_dir or not cp.workspace_dir or not cp.commit:
            self.console.print("Project is not prepared yet. Prepare it first.")
            return

        report = verify_project(
            cp.project_id, cp.commit, Path(cp.source_cache_dir), Path(cp.workspace_dir)
        )
        if sel.choice_key == "verify_modified":
            self.console.print(
                f"Modified files ({len(report.modified_files)}): "
                f"{', '.join(report.modified_files) or 'None'}"
            )
            return
        if sel.choice_key == "verify_commit":
            self.console.print(f"Pinned commit: {cp.commit} ({cp.branch})")

        self.checkpoints.save_verification(report)
        if report.verified:
            cp.verification_passed = True
            self.checkpoints.transition(cp, ProjectState.VERIFYING)
            self.checkpoints.transition(cp, ProjectState.VERIFIED)
            self.checkpoints.transition(cp, ProjectState.READY_TO_RUN)
            self.console.print(
                f"VERIFIED: {report.verified_files}/{report.total_files} files match source commit."
            )
        else:
            self.console.print(
                f"VERIFICATION FAILED: {report.verified_files}/{report.total_files} verified, "
                f"{len(report.missing_files)} missing, {len(report.modified_files)} modified, "
                f"{len(report.unexpected_files)} unexpected."
            )

    def _print_verification_report(self, project_id: str) -> None:
        rep = self.checkpoints.load_verification(project_id)
        if rep is None:
            self.console.print(f"No previous verification report found for '{project_id}'.")
            return
        self.console.print(
            f"\nVerification Report ({rep.project_id} @ {rep.commit[:12]}): "
            f"{'PASS' if rep.verified else 'FAIL'} ({rep.verified_files}/{rep.total_files})"
        )

    # ---- Option 4: Run a project ----

    def workflow_run(self) -> None:
        entry = self._ask_project("Which project would you like to run?")
        if entry is None:
            return
        cp = self.checkpoints.load_checkpoint(entry.id)
        if cp is None:
            self.console.print("Project has not been prepared or verified yet.")
            return
        self._run_project_checked(entry, cp)

    def _run_project_checked(self, entry: ProjectRegistryEntry, cp: ProjectCheckpoint) -> None:
        if not cp.workspace_dir or not cp.commit:
            self.console.print("Missing provenance or workspace. Prepare the project first.")
            return
        if not cp.license_approved:
            self.console.print("License requirements are not satisfied. Cannot run.")
            return
        if not cp.verification_passed or cp.state != ProjectState.READY_TO_RUN:
            self.console.print(
                f"Project is not READY_TO_RUN (current state: {cp.state.value}). Verify it first."
            )
            return

        insp_path = Path(cp.workspace_dir) / ".provenance" / "inspection-report.json"
        if not insp_path.is_file():
            self.console.print("Inspection report missing. Re-run preparation.")
            return
        insp = InspectionReport.model_validate_json(insp_path.read_text(encoding="utf-8"))
        exec_orch = ExecutionOrchestrator(checkpoint_manager=self.checkpoints)
        try:
            plan = exec_orch.build_plan(insp, Path(cp.workspace_dir))
        except ExecutionError as exc:
            self.console.print(f"Cannot build execution plan: {exc}")
            return

        if not ask_confirmation(
            self.prompts,
            title="CONFIRM PROJECT EXECUTION",
            summary_lines=[
                f"Project: {entry.name}",
                f"Commit:  {cp.commit}",
                f"Runtime: {plan.runtime_name}",
                f"Command: {shlex.join(plan.run_command)}",
            ],
            default_yes=False,
            question="Execute this project now?",
        ):
            self.console.print("Execution cancelled.")
            return

        try:
            result = exec_orch.execute(
                cp,
                insp,
                Path(cp.workspace_dir),
                approve_fn=lambda cmd: ask_confirmation(
                    self.prompts,
                    title="DEPENDENCY INSTALLATION APPROVAL",
                    summary_lines=[f"Command: {cmd}"],
                    default_yes=False,
                    question="Approve installing dependencies?",
                ),
                require_approval=self.config.execution.require_dependency_approval,
            )
        except ExecutionError as exc:
            self.console.print(f"Execution halted: {exc}")
            return

        if result.stdout:
            self.console.print(result.stdout)
        if result.stderr:
            self.console.print(result.stderr)
        if result.detected_url:
            self.console.print(f"Local URL: {result.detected_url}")

    # ---- Option 5: Automated safety tests ----

    def workflow_safety_tests(self) -> None:
        sel = self.prompts.ask_choice(
            "What would you like to test?",
            SAFETY_TEST_CHOICES,
            default_index=1,
        )
        if sel.action != NavAction.SELECT or not sel.choice_key:
            return

        report_txt = self.config.root_dir / "test-results" / "summary.txt"
        if sel.choice_key == "view_report":
            if not report_txt.is_file():
                self.console.print("No previous self-test report found.")
            else:
                self.console.print(report_txt.read_text(encoding="utf-8"))
            return

        orch = SelfTestOrchestrator(self.config)
        if sel.choice_key == "test_runner":
            summary, _, paths = orch.run(input_only=True)
            self.console.print(render_summary_text(summary))
            if paths:
                self.console.print(f"Report saved to {paths['json'].parent}")
            return

        if sel.choice_key == "test_one":
            entry = self._ask_project("Which project would you like to test in a sandbox?")
            if entry is None:
                return
            if not ask_confirmation(
                self.prompts,
                title="START SANDBOX TEST",
                summary_lines=[
                    f"Project: {entry.name}",
                    "Execution will run strictly inside a disposable sandbox.",
                ],
                default_yes=False,
            ):
                return
            summary, _, paths = orch.run(project_ids=[entry.id], run_all=False)
            self.console.print(render_summary_text(summary))
            return

        # test_all or safety_gate
        allow_net = sel.choice_key == "safety_gate"
        if not ask_confirmation(
            self.prompts,
            title="RUN AUTOMATED SANDBOX SAFETY TESTS",
            summary_lines=[
                "Scope: All four configured projects in isolated disposable sandboxes",
                f"Dependency network access: {'ENABLED' if allow_net else 'DISABLED'}",
            ],
            default_yes=False,
        ):
            return
        summary, _, _ = orch.run(run_all=True, allow_network=allow_net)
        self.console.print(render_summary_text(summary))

    # ---- Option 6: Project status ----

    def workflow_status(self) -> None:
        rows: list[tuple[str, str, str]] = []
        projects = self.registry.list_projects()
        for entry in projects:
            cp = self.checkpoints.load_checkpoint(entry.id)
            if cp is None:
                rows.append((entry.name, ProjectState.DISCOVERED.value, "0%"))
            else:
                prog = self.checkpoints.load_progress(entry.id)
                pct = prog.percent_complete if prog else (100.0 if cp.verification_passed else 0.0)
                rows.append((entry.name, cp.state.value, f"{pct:.0f}%"))

        self.console.print("")
        render_status_table(self.console, self.caps, rows)

        choices = [MenuChoice(p.id, f"Inspect {p.name}") for p in projects]
        sel = self.prompts.ask_choice(
            "Select a project for details (or press 'b' to return):",
            choices,
            allow_back=True,
            prompt_label="Project details",
        )
        if sel.action == NavAction.SELECT and sel.choice_key:
            cp = self.checkpoints.load_checkpoint(sel.choice_key)
            if cp is None:
                self.console.print(f"{sel.choice_key}: DISCOVERED (not prepared yet).")
            else:
                self.console.print(
                    f"\n{cp.project_name} ({cp.project_id})\n"
                    f"  State:      {cp.state.value}\n"
                    f"  Commit:     {cp.commit or '-'}\n"
                    f"  Runtime:    {cp.runtime or '-'}\n"
                    f"  Verified:   {cp.verification_passed}\n"
                    f"  Workspace:  {cp.workspace_dir or '-'}"
                )

    # ---- Option 7: Settings ----

    def workflow_settings(self) -> None:
        sel = self.prompts.ask_choice(
            "Which setting would you like to change?",
            SETTINGS_CHOICES,
            prompt_label="Select setting",
        )
        if sel.action != NavAction.SELECT or not sel.choice_key:
            return

        key = sel.choice_key
        if key == "typing_speed":
            act, val = self.prompts.ask_text(
                "Enter typing speed (characters per second, 1-500)",
                default=str(self.config.typing.typing_speed),
            )
            if act == NavAction.SELECT and val.isdigit():
                new_speed = max(1, min(500, int(val)))
                if ask_confirmation(
                    self.prompts,
                    title="SAVE SETTING",
                    summary_lines=[
                        f"typing_speed: {self.config.typing.typing_speed} -> {new_speed}"
                    ],
                    default_yes=True,
                ):
                    self.config.typing.typing_speed = new_speed
                    save_config(self.config)
                    self.console.print("Saved typing speed.")
        elif key == "vscode_path":
            act, val = self.prompts.ask_text(
                "VS Code executable path (leave empty for auto-detect)",
                default=self.config.typing.vscode_path,
            )
            if act == NavAction.SELECT and ask_confirmation(
                self.prompts,
                title="SAVE SETTING",
                summary_lines=[f"vscode_path -> '{val}'"],
                default_yes=True,
            ):
                self.config.typing.vscode_path = val
                save_config(self.config)
        elif key == "workspace_dir":
            act, val = self.prompts.ask_text(
                "Workspace directory", default=self.config.paths.workspace_dir.as_posix()
            )
            if (
                act == NavAction.SELECT
                and val
                and ask_confirmation(
                    self.prompts,
                    title="SAVE SETTING",
                    summary_lines=[f"workspace_dir -> '{val}'"],
                    default_yes=True,
                )
            ):
                self.config.paths.workspace_dir = Path(val)
                save_config(self.config)
        elif key == "source_cache_dir":
            act, val = self.prompts.ask_text(
                "Source cache directory", default=self.config.paths.source_cache_dir.as_posix()
            )
            if (
                act == NavAction.SELECT
                and val
                and ask_confirmation(
                    self.prompts,
                    title="SAVE SETTING",
                    summary_lines=[f"source_cache_dir -> '{val}'"],
                    default_yes=True,
                )
            ):
                self.config.paths.source_cache_dir = Path(val)
                save_config(self.config)
        elif key == "sandbox":
            act, val = self.prompts.ask_text(
                "Sandbox execution timeout (seconds)",
                default=str(self.config.sandbox.execution_timeout_seconds),
            )
            if (
                act == NavAction.SELECT
                and val.isdigit()
                and ask_confirmation(
                    self.prompts,
                    title="SAVE SANDBOX SETTING",
                    summary_lines=[f"execution_timeout_seconds -> {val}"],
                    default_yes=False,
                )
            ):
                self.config.sandbox.execution_timeout_seconds = max(5, int(val))
                save_config(self.config)
        elif key == "dependency_approval":
            new_val = not self.config.execution.require_dependency_approval
            if ask_confirmation(
                self.prompts,
                title="SECURITY SETTING CHANGE",
                summary_lines=[
                    f"require_dependency_approval: {self.config.execution.require_dependency_approval} -> {new_val}"
                ],
                default_yes=False,
            ):
                self.config.execution.require_dependency_approval = new_val
                save_config(self.config)
        elif key == "network_policy":
            new_val = not self.config.sandbox.network_enabled
            if ask_confirmation(
                self.prompts,
                title="SECURITY SETTING CHANGE",
                summary_lines=[
                    f"sandbox.network_enabled: {self.config.sandbox.network_enabled} -> {new_val}"
                ],
                default_yes=False,
            ):
                self.config.sandbox.network_enabled = new_val
                save_config(self.config)
        elif key == "appearance":
            app_sel = self.prompts.ask_choice(
                "Select terminal appearance:",
                [
                    MenuChoice("auto", "Auto-detect"),
                    MenuChoice("rich", "Rich (color + Unicode)"),
                    MenuChoice("plain", "Plain text (ASCII fallback)"),
                ],
                default_index=1,
            )
            if app_sel.action == NavAction.SELECT and app_sel.choice_key in (
                "auto",
                "rich",
                "plain",
            ):
                if ask_confirmation(
                    self.prompts,
                    title="SAVE SETTING",
                    summary_lines=[f"appearance -> {app_sel.choice_key}"],
                    default_yes=True,
                ):
                    self.config.ui.appearance = app_sel.choice_key  # type: ignore[assignment]
                    save_config(self.config)
        elif key == "confirmations":
            new_val = not self.config.ui.confirm_all_operations
            if ask_confirmation(
                self.prompts,
                title="CONFIRMATION PREFERENCE",
                summary_lines=[
                    f"confirm_all_operations: {self.config.ui.confirm_all_operations} -> {new_val}"
                ],
                default_yes=False,
            ):
                self.config.ui.confirm_all_operations = new_val
                save_config(self.config)
