"""Minimal single-block progress display for interactive operations."""

from __future__ import annotations

from rich.console import Console

from opensource_runner.interactive.formatting import TerminalCapabilities
from opensource_runner.models import ProjectProgress


def render_progress_snapshot(
    console: Console,
    caps: TerminalCapabilities,
    project_name: str,
    task_label: str,
    progress: ProjectProgress,
) -> None:
    """Render a compact progress summary using Unicode or plain ASCII bars."""
    width = 20
    filled = int(round((progress.percent_complete / 100.0) * width))
    filled = max(0, min(width, filled))
    if caps.plain_mode or not caps.supports_unicode:
        bar = "#" * filled + "-" * (width - filled)
    else:
        bar = "█" * filled + "░" * (width - filled)

    console.print(
        f"\r{project_name} [{bar}] {progress.percent_complete:>5.1f}% | "
        f"{task_label} | verified: {progress.completed_files}/{progress.total_files} | "
        f"file: {progress.current_file or '-'}",
        end="" if progress.percent_complete < 100.0 else "\n",
    )
