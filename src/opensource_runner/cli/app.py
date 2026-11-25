"""Typer CLI entrypoint for opensource-runner."""

from __future__ import annotations

import json
import os
import platform
import shlex
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn
from rich.table import Table

from opensource_runner import __version__
from opensource_runner.checkpoint import CheckpointManager
from opensource_runner.config import load_config
from opensource_runner.execution import ExecutionError, ExecutionOrchestrator
from opensource_runner.execution.runtimes import detect_available_tools
from opensource_runner.github import GitHubRetriever, GitRetrievalError, classify_file
from opensource_runner.licensing import inspect_license, write_license_reports
from opensource_runner.logging_utils import get_project_logger
from opensource_runner.models import (
    InspectionReport,
    LicenseReport,
    LicenseStatus,
    ProjectCheckpoint,
    ProjectProgress,
    ProjectRunConfig,
    ProjectState,
    RunnerConfig,
    utc_now,
)
from opensource_runner.projects import ProjectNotFoundError, ProjectRegistry, inspect_project
from opensource_runner.security import force_rmtree, is_running_as_root
from opensource_runner.typing import TypingOrchestrator, VSCodeController, discover_vscode_cli
from opensource_runner.typing.platforms import (
    InputBackendError,
    create_input_controller,
    detect_display_platform,
)
from opensource_runner.verification import verify_project

app = typer.Typer(
    name="opensource-runner",
    help="Cross-platform open-source project typing, verification, and runner bot.",
    add_completion=False,
)
console = Console()


@app.callback(invoke_without_command=True)
def cmd_default(
    ctx: typer.Context,
    root_dir: Optional[Path] = typer.Option(None, "--root", hidden=True),
) -> None:
    """Launch the interactive terminal wizard when invoked without a subcommand."""
    if ctx.invoked_subcommand is None:
        from opensource_runner.interactive import run_interactive_wizard

        code = run_interactive_wizard(root_dir=root_dir)
        raise typer.Exit(code=code)


ATTRIBUTION_NOTICE = (
    "This source originates from a third-party GitHub repository.\n\n"
    "The bot will reproduce the source for learning, development,\n"
    "and transparent demonstration purposes.\n\n"
    "Original licensing and attribution information will be preserved.\n\n"
    "The bot will not claim authorship of the imported source."
)


def _ctx(
    root_dir: Optional[Path] = None,
) -> tuple[RunnerConfig, ProjectRegistry, CheckpointManager]:
    cfg = load_config(root_dir=root_dir)
    return cfg, ProjectRegistry(cfg.projects_path), CheckpointManager(cfg.state_path)


def _require_active_checkpoint(
    checkpoints: CheckpointManager,
) -> ProjectCheckpoint:
    active_id = checkpoints.get_active_project()
    if not active_id:
        console.print(
            "[red]No project selected.[/red] Run `opensource-runner select <project-id>` first."
        )
        raise typer.Exit(code=1)
    cp = checkpoints.load_checkpoint(active_id)
    if cp is None:
        console.print(f"[red]Missing checkpoint for '{active_id}'.[/red] Re-select the project.")
        raise typer.Exit(code=1)
    return cp


def _provenance_dir(workspace_dir: Path) -> Path:
    return workspace_dir / ".provenance"


def _load_inspection(workspace_dir: Path) -> InspectionReport | None:
    path = _provenance_dir(workspace_dir) / "inspection-report.json"
    if not path.is_file():
        return None
    return InspectionReport.model_validate_json(path.read_text(encoding="utf-8"))


def _load_license(workspace_dir: Path) -> LicenseReport | None:
    path = _provenance_dir(workspace_dir) / "license-report.json"
    if not path.is_file():
        return None
    return LicenseReport.model_validate_json(path.read_text(encoding="utf-8"))


@app.command("list")
def cmd_list(
    root_dir: Optional[Path] = typer.Option(None, "--root", hidden=True),
) -> None:
    """List all configured open-source projects in the registry."""
    _, registry, _ = _ctx(root_dir)
    projects = registry.list_projects()
    if not projects:
        console.print("[yellow]No projects configured in projects/.[/yellow]")
        return

    console.print("\n[bold]AVAILABLE PROJECTS[/bold]\n")
    for idx, entry in enumerate(projects, start=1):
        console.print(f"{idx}. [bold cyan]{entry.id}[/bold cyan]")
        console.print(f"   {entry.name}")
        console.print(f"   {entry.repository}\n")


@app.command("select")
def cmd_select(
    project_id: str = typer.Argument(..., help="Project ID from `opensource-runner list`"),
    root_dir: Optional[Path] = typer.Option(None, "--root", hidden=True),
) -> None:
    """Select an open-source project to work with."""
    cfg, registry, checkpoints = _ctx(root_dir)
    try:
        entry = registry.get(project_id)
    except ProjectNotFoundError:
        console.print(
            f"[red]Unknown project ID:[/red] '{project_id}'. Run `opensource-runner list`."
        )
        raise typer.Exit(code=1)

    checkpoints.set_active_project(entry.id)
    existing = checkpoints.load_checkpoint(entry.id)
    if existing is None:
        cp = ProjectCheckpoint(
            project_id=entry.id,
            project_name=entry.name,
            repository=entry.repository,
            state=ProjectState.DISCOVERED,
        )
        checkpoints.save_checkpoint(cp)
        display_state = ProjectState.DISCOVERED.value
        checkpoints.transition(cp, ProjectState.SELECTED)
    else:
        cp = existing
        display_state = cp.state.value

    logger = get_project_logger(cfg.logs_path, entry.id)
    logger.info("Selected project %s (%s)", entry.id, entry.repository)

    console.print(
        Panel(ATTRIBUTION_NOTICE, title="Third-Party Source Attribution", border_style="cyan")
    )
    console.print("\n[bold]PROJECT SELECTED[/bold]\n")
    console.print(f"Name:\n{entry.name}\n")
    console.print(f"Repository:\n{entry.repository}\n")
    console.print(f"Project ID:\n{entry.id}\n")
    console.print(f"Current state:\n{display_state}\n")
    console.print("Next step: run `opensource-runner prepare`")


@app.command("prepare")
def cmd_prepare(
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Preview preparation without writing files."
    ),
    approve_license: bool = typer.Option(
        False,
        "--approve-license",
        help="Explicitly approve continuing if license review is required.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Approve repository retrieval non-interactively.",
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Allow preparing into a workspace that already contains files.",
    ),
    local_source: Optional[Path] = typer.Option(
        None,
        "--local-source",
        help="Use a local source folder instead of cloning from GitHub.",
    ),
    root_dir: Optional[Path] = typer.Option(None, "--root", hidden=True),
) -> None:
    """Retrieve repository (or local folder), pin commit, check license, inspect stack, and prepare workspace."""
    cfg, registry, checkpoints = _ctx(root_dir)
    cp = _require_active_checkpoint(checkpoints)
    entry = registry.get(cp.project_id)
    logger = get_project_logger(cfg.logs_path, cp.project_id)
    retriever = GitHubRetriever()
    workspace_dir = (cfg.workspace_path / entry.id).resolve()
    effective_local = local_source or (Path(entry.local_source) if entry.local_source else None)

    if dry_run:
        if effective_local is not None:
            commit_display = "local-snapshot"
            branch_display = "local"
            source_desc = str(effective_local)
        else:
            source_desc = entry.repository
            try:
                rev = retriever.resolve_remote_revision(entry.repository, revision=entry.revision)
                commit_display = rev.commit
                branch_display = rev.branch
            except GitRetrievalError as exc:
                commit_display = f"<unresolved: {exc}>"
                branch_display = entry.revision
        console.print("\n[bold yellow]DRY RUN[/bold yellow]\n")
        console.print(f"Project:\n{entry.id}\n")
        console.print(f"Source:\n{source_desc}\n")
        console.print(f"Would retrieve:\nbranch {branch_display} @ commit {commit_display}\n")
        console.print(f"Would create cache:\n{cfg.source_cache_path / entry.id / commit_display}\n")
        console.print(f"Would create workspace:\n{workspace_dir}\n")
        return

    # Retrieval approval gate (only prompted if not yet approved and --yes not passed)
    if not cp.retrieval_approved and not yes:
        source_display = str(effective_local) if effective_local else entry.repository
        console.print("\n[bold yellow]RETRIEVAL APPROVAL REQUIRED[/bold yellow]\n")
        console.print(f"Project:       {entry.name} ({entry.id})")
        console.print(f"Source:        {source_display}")
        console.print(f"Source cache:  {cfg.source_cache_path / entry.id}")
        console.print(f"Workspace:     {workspace_dir}\n")
        if not typer.confirm("Approve retrieving this source?", default=False):
            console.print("[yellow]Retrieval cancelled by user.[/yellow]")
            raise typer.Exit(code=1)
        cp.retrieval_approved = True
        checkpoints.save_checkpoint(cp)
    elif yes and not cp.retrieval_approved:
        cp.retrieval_approved = True
        checkpoints.save_checkpoint(cp)

    # Guard against overwriting an existing populated workspace without approval
    if workspace_dir.exists() and not overwrite:
        existing_user_files = [p for p in workspace_dir.iterdir() if p.name != ".provenance"]
        if existing_user_files and not yes:
            console.print(
                f"\n[bold yellow]EXISTING WORKSPACE DETECTED[/bold yellow]\n"
                f"Workspace '{workspace_dir}' already contains {len(existing_user_files)} item(s)."
            )
            if not typer.confirm("Continue without overwriting existing files?", default=False):
                console.print("[yellow]Preparation cancelled by user.[/yellow]")
                raise typer.Exit(code=1)

    checkpoints.transition(cp, ProjectState.PREPARING)
    try:
        if effective_local is not None:
            cache_dir, provenance, manifest = retriever.import_local_folder_to_cache(
                project_id=entry.id,
                project_name=entry.name,
                local_source_dir=effective_local,
                source_cache_root=cfg.source_cache_path,
            )
        else:
            cache_dir, provenance, manifest = retriever.retrieve_to_cache(
                project_id=entry.id,
                project_name=entry.name,
                repository=entry.repository,
                source_cache_root=cfg.source_cache_path,
                revision=entry.revision,
            )
    except GitRetrievalError as exc:
        checkpoints.transition(cp, ProjectState.FAILED, error=str(exc))
        logger.error("Source retrieval failed: %s", exc)
        console.print(f"[red]Source retrieval failed:[/red] {exc}")
        raise typer.Exit(code=1)

    workspace_dir.mkdir(parents=True, exist_ok=True)
    prov_dir = _provenance_dir(workspace_dir)
    prov_dir.mkdir(parents=True, exist_ok=True)

    # Write provenance metadata
    (prov_dir / "repository.json").write_text(
        provenance.model_dump_json(indent=2), encoding="utf-8"
    )
    (prov_dir / "source-manifest.json").write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )

    # License inspection
    lic_report = inspect_license(entry.id, entry.name, cache_dir)
    if lic_report.status == LicenseStatus.REVIEW_REQUIRED and approve_license:
        lic_report.status = LicenseStatus.APPROVED
        lic_report.user_approved = True
        lic_report.approved_at = utc_now()
    write_license_reports(prov_dir, lic_report)

    # Project inspection
    insp_report = inspect_project(entry.id, provenance.commit, cache_dir)
    (prov_dir / "inspection-report.json").write_text(
        insp_report.model_dump_json(indent=2), encoding="utf-8"
    )

    # Project-specific run configuration (never stores secret values)
    run_cfg = ProjectRunConfig(
        project_id=entry.id,
        project_name=entry.name,
        repository=provenance.repository,
        revision=provenance.commit,
        license_result=f"{lic_report.detected_license} ({lic_report.status.value})",
        license_approved=lic_report.user_approved,
        project_root=str(workspace_dir),
        entry_point=insp_report.entry_point,
        runtime=insp_report.runtime,
        dependencies=insp_report.dependencies,
        setup_commands=insp_report.setup_commands,
        run_command=insp_report.run_command,
        test_command=insp_report.test_command,
        required_env_vars=insp_report.env_vars,
    )
    (prov_dir / "run-config.json").write_text(run_cfg.model_dump_json(indent=2), encoding="utf-8")

    cp.branch = provenance.branch
    cp.commit = provenance.commit
    cp.source_cache_dir = str(cache_dir)
    cp.workspace_dir = str(workspace_dir)
    cp.license_approved = lic_report.user_approved
    cp.inspection_complete = True
    cp.runtime = insp_report.runtime
    cp.remaining_files = [f.relative_path for f in manifest.files]
    checkpoints.transition(cp, ProjectState.PREPARED)

    logger.info("Prepared %s @ %s (%s)", entry.id, provenance.commit, provenance.branch)

    console.print("\n[bold green]PROJECT PREPARED[/bold green]\n")
    console.print(f"Repository:  {provenance.repository}")
    console.print(f"Branch:      {provenance.branch}")
    console.print(f"Commit:      {provenance.commit}")
    console.print(f"SourceCache: {cache_dir}")
    console.print(f"Workspace:   {workspace_dir}")
    console.print(
        f"Files:       {manifest.total_files} ({manifest.text_files} text, {manifest.binary_files} binary)"
    )
    console.print(f"Runtime:     {insp_report.runtime}")
    console.print(f"Frameworks:  {', '.join(insp_report.frameworks) or 'None'}")
    console.print(f"Entry point: {insp_report.entry_point or 'UNKNOWN'}")
    console.print(f"Run command: {insp_report.run_command or 'UNKNOWN'}")
    console.print(f"License:     {lic_report.detected_license} ({lic_report.status.value})")
    console.print(f"Run config:  {prov_dir / 'run-config.json'}")

    if not lic_report.user_approved:
        console.print("\n[bold yellow]LICENSE REVIEW REQUIRED[/bold yellow]\n")
        console.print(f"Project:\n{entry.name}\n")
        console.print(f"Reason:\n{lic_report.reason}\n")
        console.print(
            "The project will not be reproduced until you approve continuing.\n"
            "Run `opensource-runner prepare --approve-license` to approve."
        )


@app.command("status")
def cmd_status(
    root_dir: Optional[Path] = typer.Option(None, "--root", hidden=True),
) -> None:
    """Display the active project's state, checkpoint, and progress."""
    _, _, checkpoints = _ctx(root_dir)
    cp = _require_active_checkpoint(checkpoints)
    prog = checkpoints.load_progress(cp.project_id)

    table = Table(title=f"Project Status — {cp.project_name} ({cp.project_id})")
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    table.add_row("State", cp.state.value)
    table.add_row("Repository", cp.repository)
    table.add_row("Branch", cp.branch or "-")
    table.add_row("Commit", cp.commit or "-")
    table.add_row("Runtime", cp.runtime or "-")
    table.add_row("License Approved", str(cp.license_approved))
    table.add_row("Inspection Complete", str(cp.inspection_complete))
    table.add_row("Completed Files", str(len(cp.completed_files)))
    table.add_row("Remaining Files", str(len(cp.remaining_files)))
    table.add_row("Verification Passed", str(cp.verification_passed))
    table.add_row("Execution Status", cp.execution_status)
    if prog:
        table.add_row("Progress", f"{prog.percent_complete:.1f}%")
    if cp.last_error:
        table.add_row("Last Error", cp.last_error)
    console.print(table)


def _run_typing_flow(
    *,
    root_dir: Optional[Path],
    dry_run: bool,
    input_backend: Optional[str],
    is_resume: bool,
) -> None:
    cfg, _, checkpoints = _ctx(root_dir)
    cp = _require_active_checkpoint(checkpoints)
    logger = get_project_logger(cfg.logs_path, cp.project_id)

    if not cp.source_cache_dir or not Path(cp.source_cache_dir).is_dir():
        console.print("[red]Source cache missing.[/red] Run `opensource-runner prepare` first.")
        raise typer.Exit(code=1)
    if not cp.workspace_dir:
        console.print("[red]Workspace missing.[/red] Run `opensource-runner prepare` first.")
        raise typer.Exit(code=1)
    if not cp.inspection_complete:
        console.print(
            "[red]Project inspection not complete.[/red] Run `opensource-runner prepare` first."
        )
        raise typer.Exit(code=1)

    source_dir = Path(cp.source_cache_dir)
    workspace_dir = Path(cp.workspace_dir)

    if not cp.license_approved:
        lic = _load_license(workspace_dir)
        reason = lic.reason if lic else "License review required."
        console.print("\n[bold yellow]LICENSE REVIEW REQUIRED[/bold yellow]\n")
        console.print(f"Project:\n{cp.project_name}\n")
        console.print(f"Reason:\n{reason}\n")
        console.print("The project will not be reproduced until you approve continuing.")
        raise typer.Exit(code=1)

    all_files = [p for p in sorted(source_dir.rglob("*")) if p.is_file() and ".git" not in p.parts]
    text_count = sum(1 for p in all_files if classify_file(p) == "text")
    bin_count = len(all_files) - text_count

    if dry_run:
        console.print("\n[bold yellow]DRY RUN[/bold yellow]\n")
        console.print(f"Project:\n{cp.project_id}\n")
        console.print(f"Source:\n{source_dir}\n")
        console.print(f"Workspace:\n{workspace_dir}\n")
        console.print(f"Would reproduce:\n{text_count} text files (keyboard reproduction)\n")
        console.print(f"Would copy:\n{bin_count} binary files (verified binary copy)\n")
        console.print(f"Would verify:\n{len(all_files)} files\n")
        return

    backend_pref = input_backend or cfg.typing.input_backend
    try:
        input_ctrl = create_input_controller(backend_pref)
    except InputBackendError as exc:
        console.print(f"[red]Input backend error:[/red] {exc}")
        raise typer.Exit(code=1)

    vscode = VSCodeController(
        configured_path=cfg.typing.vscode_path,
        dry_run=(backend_pref == "mock"),
    )
    orchestrator = TypingOrchestrator(
        checkpoint_manager=checkpoints,
        input_controller=input_ctrl,
        vscode_controller=vscode,
        typing_config=cfg.typing,
        source_cache_root=cfg.source_cache_path,
        logger=logger,
        sleep_fn=(lambda _: None) if backend_pref == "mock" else __import__("time").sleep,
    )

    action_label = "RESUMING" if is_resume else "TYPING"
    console.print(f"\n[bold]PROJECT: {cp.project_name}[/bold]")
    console.print(f"SOURCE:    {source_dir}")
    console.print(f"WORKSPACE: {workspace_dir}\n")

    with Progress(
        TextColumn(f"[bold cyan]{action_label}[/bold cyan]"),
        BarColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        TextColumn("{task.fields[info]}"),
        console=console,
    ) as progress:
        task_id = progress.add_task("typing", total=100, info="Starting...")

        def on_progress(p: ProjectProgress) -> None:
            info = f"{p.current_file or ''} ({p.completed_files}/{p.total_files} verified)"
            progress.update(task_id, completed=p.percent_complete, info=info)

        try:
            outcome = orchestrator.reproduce(
                cp, source_dir, workspace_dir, progress_callback=on_progress
            )
        except InputBackendError as exc:
            logger.error("Input backend unavailable: %s", exc)
            console.print(f"\n[red]INPUT BACKEND BLOCKED[/red]\n{exc}")
            raise typer.Exit(code=1)

    logger.info("Typing outcome for %s: %s (%s)", cp.project_id, outcome.status, outcome.message)

    if outcome.status == "focus_failed":
        console.print("\n[bold yellow]PAUSED[/bold yellow]\n")
        console.print("Expected:\nVS Code\n")
        console.print(f"Expected workspace:\n{workspace_dir}\n")
        console.print("Focus could not be verified.\n")
        console.print("Activate the correct VS Code window and enter:\n\nopensource-runner resume")
        raise typer.Exit(code=2)

    if outcome.status == "verification_failed":
        console.print("\n[bold red]VERIFICATION FAILED[/bold red]\n")
        console.print(f"Project:\n{cp.project_name}\n")
        console.print(f"File:\n{outcome.failed_file}\n")
        console.print(f"Reason:\n{outcome.message}\n")
        console.print("Typing has been paused.\n\nProject cannot be executed.")
        raise typer.Exit(code=1)

    if outcome.status == "input_failed":
        console.print("\n[bold red]INPUT BACKEND FAILED[/bold red]\n")
        console.print(f"File: {outcome.failed_file or '-'}")
        console.print(f"Reason: {outcome.message}\n")
        console.print(
            "Checkpoint saved as PAUSED. Resolve the input backend issue and run `opensource-runner resume`."
        )
        raise typer.Exit(code=1)

    if outcome.status in ("paused", "stopped"):
        console.print(f"\n[yellow]{outcome.message}[/yellow]")
        return

    console.print(
        f"\n[green]Reproduction finished ({outcome.completed_files}/{outcome.total_files} files).[/green] "
        "Run `opensource-runner verify` to perform final project verification."
    )


@app.command("type")
def cmd_type(
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview typing without sending input."),
    input_backend: Optional[str] = typer.Option(
        None, "--input-backend", help="Override input backend (auto, windows, x11, wayland, mock)."
    ),
    root_dir: Optional[Path] = typer.Option(None, "--root", hidden=True),
) -> None:
    """Reproduce source files into the isolated VS Code workspace via keyboard events."""
    _run_typing_flow(
        root_dir=root_dir, dry_run=dry_run, input_backend=input_backend, is_resume=False
    )


@app.command("pause")
def cmd_pause(
    root_dir: Optional[Path] = typer.Option(None, "--root", hidden=True),
) -> None:
    """Safely pause an active typing session."""
    _, _, checkpoints = _ctx(root_dir)
    cp = _require_active_checkpoint(checkpoints)
    checkpoints.set_control_signal(cp.project_id, "pause")
    console.print(f"[yellow]Pause requested for '{cp.project_id}'.[/yellow]")


@app.command("break", hidden=True)
def cmd_break(
    root_dir: Optional[Path] = typer.Option(None, "--root", hidden=True),
) -> None:
    """Alias for `pause`."""
    cmd_pause(root_dir=root_dir)


@app.command("resume")
def cmd_resume(
    input_backend: Optional[str] = typer.Option(
        None, "--input-backend", help="Override input backend (auto, windows, x11, wayland, mock)."
    ),
    root_dir: Optional[Path] = typer.Option(None, "--root", hidden=True),
) -> None:
    """Resume reproduction from the latest valid checkpoint."""
    _run_typing_flow(root_dir=root_dir, dry_run=False, input_backend=input_backend, is_resume=True)


@app.command("stop")
def cmd_stop(
    root_dir: Optional[Path] = typer.Option(None, "--root", hidden=True),
) -> None:
    """Stop active typing safely without marking the project completed."""
    _, _, checkpoints = _ctx(root_dir)
    cp = _require_active_checkpoint(checkpoints)
    checkpoints.set_control_signal(cp.project_id, "stop")
    console.print(f"[yellow]Stop requested for '{cp.project_id}'.[/yellow]")


@app.command("verify")
def cmd_verify(
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Preview verification without changing state."
    ),
    root_dir: Optional[Path] = typer.Option(None, "--root", hidden=True),
) -> None:
    """Perform complete project comparison (missing, unexpected, modified, SHA-256)."""
    cfg, _, checkpoints = _ctx(root_dir)
    cp = _require_active_checkpoint(checkpoints)
    if not cp.source_cache_dir or not cp.workspace_dir or not cp.commit:
        console.print("[red]Project is not prepared.[/red] Run `opensource-runner prepare` first.")
        raise typer.Exit(code=1)

    source_dir = Path(cp.source_cache_dir)
    workspace_dir = Path(cp.workspace_dir)

    if dry_run:
        console.print("\n[bold yellow]DRY RUN[/bold yellow]\n")
        console.print(f"Would verify workspace '{workspace_dir}' against '{source_dir}'.")
        return

    checkpoints.transition(cp, ProjectState.VERIFYING)
    report = verify_project(cp.project_id, cp.commit, source_dir, workspace_dir)
    checkpoints.save_verification(report)

    prov_dir = _provenance_dir(workspace_dir)
    prov_dir.mkdir(parents=True, exist_ok=True)
    (prov_dir / "verification-report.json").write_text(
        report.model_dump_json(indent=2), encoding="utf-8"
    )

    logger = get_project_logger(cfg.logs_path, cp.project_id)
    if not report.verified:
        cp.verification_passed = False
        checkpoints.transition(
            cp,
            ProjectState.PAUSED,
            error=(
                f"Verification failed: {len(report.missing_files)} missing, "
                f"{len(report.modified_files)} modified, "
                f"{len(report.unexpected_files)} unexpected."
            ),
        )
        logger.warning("Verification failed for %s", cp.project_id)
        console.print("\n[bold red]VERIFICATION FAILED[/bold red]\n")
        console.print(f"Project: {cp.project_name}")
        console.print(f"Verified: {report.verified_files} / {report.total_files}")
        if report.missing_files:
            console.print(f"Missing files: {', '.join(report.missing_files[:10])}")
        if report.modified_files:
            console.print(f"Modified files: {', '.join(report.modified_files[:10])}")
        if report.unexpected_files:
            console.print(f"Unexpected files: {', '.join(report.unexpected_files[:10])}")
        console.print("\nProject cannot be executed.")
        raise typer.Exit(code=1)

    cp.verification_passed = True
    checkpoints.transition(cp, ProjectState.VERIFIED)
    checkpoints.transition(cp, ProjectState.READY_TO_RUN)
    logger.info(
        "Verification passed for %s (%d/%d)",
        cp.project_id,
        report.verified_files,
        report.total_files,
    )

    console.print("\n[bold green]TYPING AND VERIFICATION COMPLETE[/bold green]\n")
    console.print(
        'Typing and verification are complete. The project has not been run. Enter "run" when you are ready.\n'
    )
    console.print(f"Project:\n{cp.project_name}\n")
    console.print(f"Files:\n{report.total_files} / {report.total_files}\n")
    console.print(f"Verified:\n{report.verified_files} / {report.total_files}\n")
    console.print("Checkpoint:\nSaved\n")
    console.print("Execution:\nNOT STARTED\n")
    console.print("Enter:\n\nopensource-runner run\n\nwhen you are ready.")


@app.command("run")
def cmd_run(
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show detected setup and run commands only."
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Approve proposed dependency commands non-interactively."
    ),
    container: bool = typer.Option(
        False, "--container", help="Prefer Docker/Podman workflow if available."
    ),
    root_dir: Optional[Path] = typer.Option(None, "--root", hidden=True),
) -> None:
    """Explicitly run the verified project after dependency approval."""
    cfg, _, checkpoints = _ctx(root_dir)
    cp = _require_active_checkpoint(checkpoints)
    if not cp.workspace_dir:
        console.print("[red]Workspace missing.[/red] Run `opensource-runner prepare` first.")
        raise typer.Exit(code=1)

    workspace_dir = Path(cp.workspace_dir)
    insp = _load_inspection(workspace_dir)
    if insp is None:
        console.print(
            "[red]Inspection report missing.[/red] Run `opensource-runner prepare` first."
        )
        raise typer.Exit(code=1)

    orchestrator = ExecutionOrchestrator(checkpoint_manager=checkpoints)
    prefer_container = container or cfg.execution.prefer_container

    try:
        plan = orchestrator.build_plan(insp, workspace_dir, prefer_container=prefer_container)
    except ExecutionError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)

    if dry_run:
        console.print("\n[bold yellow]DRY RUN[/bold yellow]\n")
        console.print(f"Project:\n{cp.project_id}\n")
        console.print(f"Commit:\n{cp.commit}\n")
        console.print(f"Runtime:\n{plan.runtime_name}\n")
        if plan.setup_steps:
            console.print("Would run setup:")
            for step in plan.setup_steps:
                console.print(f"  {shlex.join(step.command)}")
        console.print(f"\nWould execute:\n{shlex.join(plan.run_command)}\n")
        if plan.expected_url:
            console.print(f"Expected URL:\n{plan.expected_url}")
        return

    if not cp.verification_passed or cp.state != ProjectState.READY_TO_RUN:
        console.print(
            f"[red]Cannot run '{cp.project_id}':[/red] project must be VERIFIED / READY_TO_RUN "
            f"(current state: {cp.state.value}). Run `opensource-runner verify` first."
        )
        raise typer.Exit(code=1)

    console.print(f"\n[bold]EXECUTION PLAN — {cp.project_name}[/bold]")
    console.print(f"Commit:  {cp.commit}")
    console.print(f"Runtime: {plan.runtime_name}")
    console.print(f"Command: {shlex.join(plan.run_command)}\n")

    def approve_command(cmd_display: str) -> bool:
        if yes:
            return True
        console.print("\n[bold yellow]DEPENDENCIES / SETUP REQUIRED[/bold yellow]\n")
        console.print(f"Project: {cp.project_id}")
        console.print(f"Detected runtime: {plan.runtime_name}")
        console.print(f"Proposed command:\n\n  {cmd_display}\n")
        return typer.confirm("Approve installation?", default=False)

    logger = get_project_logger(cfg.logs_path, cp.project_id)
    try:
        result = orchestrator.execute(
            cp,
            insp,
            workspace_dir,
            approve_fn=approve_command,
            require_approval=cfg.execution.require_dependency_approval,
            prefer_container=prefer_container,
        )
    except ExecutionError as exc:
        logger.error("Execution aborted: %s", exc)
        console.print(f"[red]Execution halted:[/red] {exc}")
        raise typer.Exit(code=1)

    if result.stdout:
        console.print(result.stdout)
    if result.stderr:
        console.print(f"[yellow]{result.stderr}[/yellow]")
    if result.detected_url:
        console.print(f"\n[bold green]Local URL:[/bold green] {result.detected_url}")
    if result.returncode != 0:
        raise typer.Exit(code=result.returncode)


@app.command("logs")
def cmd_logs(
    lines: int = typer.Option(50, "--lines", "-n", help="Number of trailing log lines to show."),
    root_dir: Optional[Path] = typer.Option(None, "--root", hidden=True),
) -> None:
    """Display recent logs for the active project."""
    cfg, _, checkpoints = _ctx(root_dir)
    active_id = checkpoints.get_active_project()
    log_file = cfg.logs_path / (f"{active_id}.log" if active_id else "runner.log")
    if not log_file.is_file():
        console.print(f"[yellow]No log file found at {log_file}.[/yellow]")
        return
    all_lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in all_lines[-lines:]:
        console.print(line)


@app.command("config")
def cmd_config(
    root_dir: Optional[Path] = typer.Option(None, "--root", hidden=True),
) -> None:
    """Show active configuration and discovered system tools."""
    cfg, _, _ = _ctx(root_dir)
    console.print("[bold]CONFIGURATION[/bold]")
    console.print(json.dumps(cfg.model_dump(mode="json"), indent=2))
    console.print("\n[bold]DETECTED SYSTEM TOOLS[/bold]")
    tools = detect_available_tools()
    table = Table()
    table.add_column("Tool", style="cyan")
    table.add_column("Location")
    for name, path in tools.items():
        table.add_row(name, path or "NOT FOUND")
    console.print(table)


@app.command("doctor")
def cmd_doctor(
    input_diag: bool = typer.Option(
        False,
        "--input",
        help="Run detailed input backend, VS Code, focus, and keyboard-event diagnostics.",
    ),
    root_dir: Optional[Path] = typer.Option(None, "--root", hidden=True),
) -> None:
    """Diagnose host OS, tools, display server, input backend, and directory permissions."""
    cfg, registry, _ = _ctx(root_dir)
    tools = detect_available_tools()
    vscode_cli = discover_vscode_cli(cfg.typing.vscode_path)
    display = detect_display_platform()

    backend_name = "unknown"
    backend_status = "Unavailable"
    backend_detail = ""
    backend_ok = False
    ctrl = None
    try:
        ctrl = create_input_controller(cfg.typing.input_backend)
        health = ctrl.check_availability()
        backend_name = health.backend_name
        backend_ok = health.available
        backend_status = f"Available ({health.backend_name})" if health.available else "Unavailable"
        backend_detail = health.reason
    except InputBackendError as exc:
        backend_detail = str(exc)

    if input_diag:
        from opensource_runner.testing.environment import parse_os_release

        os_rel = parse_os_release() if platform.system() == "Linux" else {}
        os_name = os_rel.get("PRETTY_NAME", f"{platform.system()} {platform.release()}")
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "") or platform.system()
        focus_status = "NOT TESTED"
        win_det = "NOT TESTED"
        if ctrl is not None:
            focus_res = ctrl.verify_focus("VS Code", cfg.workspace_path)
            if focus_res.verified:
                focus_status = "PASS"
                win_det = "PASS"
            elif display == "wayland" and "gnome" in desktop.lower():
                focus_status = "UNSUPPORTED"
                win_det = "UNSUPPORTED"
            else:
                focus_status = "FAIL"
                win_det = "PASS" if focus_res.active_window_title else "FAIL"

        overall = "PASS" if (vscode_cli is not None and backend_ok) else "FAIL"
        console.print("\n[bold]OPEN SOURCE RUNNER INPUT DIAGNOSTICS[/bold]\n")
        console.print(f"Operating system:          {os_name}")
        console.print(f"Desktop environment:       {desktop}")
        console.print(f"Display session:           {display}")
        console.print(f"VS Code executable:        {vscode_cli or 'NOT FOUND'}")
        console.print("")
        console.print(f"Input backend:             {backend_name}")
        console.print(f"Backend installed:         {'PASS' if ctrl is not None else 'FAIL'}")
        console.print(f"Backend available:         {'PASS' if backend_ok else 'FAIL'}")
        if backend_detail:
            console.print(f"Backend detail:            {backend_detail}")
        console.print(f"Window detection:          {win_det}")
        console.print(
            f"Window activation:         {'UNSUPPORTED' if display == 'wayland' and 'gnome' in desktop.lower() else 'NOT TESTED'}"
        )
        console.print(f"Editor focus detection:    {focus_status}")
        console.print("")
        console.print(f"Keyboard event test:       {'NOT TESTED' if backend_ok else 'UNSUPPORTED'}")
        console.print(f"File save test:            {'NOT TESTED' if backend_ok else 'UNSUPPORTED'}")
        console.print(f"Exact content verification:{'NOT TESTED' if backend_ok else 'UNSUPPORTED'}")
        console.print(f"\nOverall result:            {overall}")
        return

    def _is_writable_dir(path: Path) -> bool:
        try:
            path.mkdir(parents=True, exist_ok=True)
            return os.access(path, os.W_OK)
        except OSError:
            return False

    ws_ok = _is_writable_dir(cfg.workspace_path)
    cache_ok = _is_writable_dir(cfg.source_cache_path)
    state_ok = _is_writable_dir(cfg.state_path)
    logs_ok = _is_writable_dir(cfg.logs_path)
    root_user = is_running_as_root()

    blockers: list[str] = []
    if sys.version_info < (3, 12):
        blockers.append("Python 3.12+ is required.")
    if not tools.get("git"):
        blockers.append("Git CLI not found on PATH.")
    if vscode_cli is None:
        blockers.append("VS Code CLI ('code') not found.")
    if not backend_ok:
        blockers.append(f"Keyboard input backend unavailable: {backend_detail}")
    if not all((ws_ok, cache_ok, state_ok, logs_ok)):
        blockers.append("One or more runtime directories are not writable.")
    if root_user:
        blockers.append("Running as root/UID-0 is discouraged; use least privilege.")

    table = Table(title="OpenSource Runner Doctor")
    table.add_column("Check", style="cyan")
    table.add_column("Status")
    table.add_row("OS", f"{platform.system()} {platform.release()} ({platform.machine()})")
    table.add_row(
        "Python", f"{platform.python_version()} {'OK' if sys.version_info >= (3, 12) else 'FAIL'}"
    )
    table.add_row("Git", tools.get("git") or "Not installed")
    table.add_row("VS Code CLI", str(vscode_cli) if vscode_cli else "Not found")
    table.add_row("Node.js", tools.get("node") or "Not installed")
    table.add_row("npm", tools.get("npm") or "Not installed")
    table.add_row("pnpm", tools.get("pnpm") or "Not installed")
    table.add_row("yarn", tools.get("yarn") or "Not installed")
    table.add_row("PHP", tools.get("php") or "Not installed")
    table.add_row("Composer", tools.get("composer") or "Not installed")
    table.add_row("Docker", tools.get("docker") or "Not installed")
    table.add_row("Podman", tools.get("podman") or "Not installed")
    table.add_row("Display", display)
    table.add_row("Keyboard backend", backend_status)
    table.add_row("Permissions", "Non-root OK" if not root_user else "WARNING: running as root")
    table.add_row("Workspace", "Writable" if ws_ok else "NOT WRITABLE")
    table.add_row("Source cache", "Writable" if cache_ok else "NOT WRITABLE")
    table.add_row("State", "Writable" if state_ok else "NOT WRITABLE")
    table.add_row("Logs", "Writable" if logs_ok else "NOT WRITABLE")
    table.add_row("Configured projects", str(len(registry.list_projects())))
    console.print(table)

    if blockers:
        console.print("\n[bold yellow]Overall: ACTION REQUIRED[/bold yellow]")
        for item in blockers:
            console.print(f"  - {item}")
    else:
        console.print("\n[bold green]Overall: READY[/bold green]")


@app.command("clean")
def cmd_clean(
    project_id: Optional[str] = typer.Argument(
        None, help="Project ID to clean (defaults to active project)."
    ),
    include_cache: bool = typer.Option(
        False,
        "--include-cache",
        help="Also remove immutable source-cache snapshots for this project.",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirm deletion non-interactively."),
    root_dir: Optional[Path] = typer.Option(None, "--root", hidden=True),
) -> None:
    """Safely clean workspace and checkpoint state for a project after explicit confirmation."""
    cfg, _, checkpoints = _ctx(root_dir)
    target_id = project_id or checkpoints.get_active_project()
    if not target_id:
        console.print("[red]No project specified or selected.[/red]")
        raise typer.Exit(code=1)

    targets: list[Path] = [
        cfg.workspace_path / target_id,
        checkpoints.project_dir(target_id),
    ]
    if include_cache:
        targets.append(cfg.source_cache_path / target_id)

    existing = [p for p in targets if p.exists()]
    if not existing:
        console.print(f"[yellow]Nothing to clean for '{target_id}'.[/yellow]")
        return

    console.print(f"\n[bold yellow]CLEAN CONFIRMATION — {target_id}[/bold yellow]")
    for p in existing:
        console.print(f"  Would remove: {p}")

    if not yes and not typer.confirm(
        "Proceed with deleting these generated directories?", default=False
    ):
        console.print("[yellow]Clean cancelled.[/yellow]")
        return

    for p in existing:
        force_rmtree(p)
    console.print(f"[green]Cleaned generated data for '{target_id}'.[/green]")


@app.command("self-test")
def cmd_self_test(
    project: Optional[list[str]] = typer.Option(
        None, "--project", "-p", help="Specific project ID(s) to test (defaults to --all)."
    ),
    all_projects: bool = typer.Option(True, "--all/--no-all", help="Test all registered projects."),
    input_test: bool = typer.Option(
        False, "--input", help="Run only the safe isolated input test."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Preview sandbox self-test without executing."
    ),
    cleanup: bool = typer.Option(
        False, "--cleanup", help="Clean abandoned harness sandbox directories."
    ),
    allow_network: bool = typer.Option(
        False,
        "--allow-network",
        help="Allow network access during sandbox dependency installation.",
    ),
    no_execute: bool = typer.Option(
        False, "--no-execute", help="Skip project execution/health checks."
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose tagged logs."),
    debug: bool = typer.Option(False, "--debug", help="Enable debug tagged logs."),
    output_dir: Optional[Path] = typer.Option(
        None, "--output-dir", help="Directory for test-results/."
    ),
    root_dir: Optional[Path] = typer.Option(None, "--root", hidden=True),
) -> None:
    """Run the automated disposable sandbox test harness for OpenSource Runner."""
    from opensource_runner.testing import (
        SelfTestOrchestrator,
        cleanup_abandoned_sandboxes,
        render_summary_text,
    )

    if cleanup:
        removed = cleanup_abandoned_sandboxes()
        if not removed:
            console.print("[green]No abandoned sandbox directories found.[/green]")
        else:
            console.print(
                f"[green]Removed {len(removed)} abandoned sandbox directory(ies):[/green]"
            )
            for item in removed:
                console.print(f"  - {item}")
        return

    cfg, _, _ = _ctx(root_dir)
    show_logs = verbose or debug

    def _log(tag: str, msg: str) -> None:
        if show_logs:
            console.print(f"[{tag}] {msg}")

    orch = SelfTestOrchestrator(cfg, log_fn=_log)
    try:
        summary, exit_code, report_paths = orch.run(
            project_ids=project,
            run_all=all_projects if not project else False,
            input_only=input_test,
            dry_run=dry_run,
            allow_network=allow_network,
            allow_execution=not no_execute,
            output_dir=output_dir,
        )
    except ProjectNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2)
    except Exception as exc:
        console.print(f"[red]Self-test infrastructure failure:[/red] {exc}")
        raise typer.Exit(code=2)

    if dry_run:
        console.print("\n[bold yellow]SELF-TEST DRY RUN[/bold yellow]\n")
        for pid, proj in summary.projects.items():
            console.print(f"- {proj.project_name} ({pid})")
            console.print(f"  Would retrieve: {proj.repository}")
            console.print(f"  Would create sandbox: {proj.sandbox_mode}")
            console.print(
                f"  Limits: {cfg.sandbox.cpu_limit} CPU, {cfg.sandbox.memory_limit_mb}MB RAM, "
                f"timeout={cfg.sandbox.execution_timeout_seconds}s"
            )
        return

    console.print(render_summary_text(summary))
    if report_paths:
        console.print(f"Reports written to: {report_paths['json'].parent}")
    if exit_code != 0:
        raise typer.Exit(code=exit_code)


@app.command("version")
def cmd_version() -> None:
    """Display the installed opensource-runner version."""
    console.print(f"opensource-runner {__version__}")


@app.command("help")
def cmd_help(ctx: typer.Context) -> None:
    """Display CLI help information."""
    console.print(f"opensource-runner v{__version__}\n")
    console.print(ctx.parent.get_help() if ctx.parent else (app.info.name or "opensource-runner"))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
