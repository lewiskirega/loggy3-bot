"""Terminal capability detection and cross-platform formatting (Rich + plain-text fallback)."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from rich.console import Console
from rich.panel import Panel
from rich.table import Table


@dataclass(frozen=True)
class TerminalCapabilities:
    is_tty: bool
    supports_unicode: bool
    supports_color: bool
    plain_mode: bool


def detect_terminal_capabilities(appearance: str = "auto") -> TerminalCapabilities:
    """Detect TTY, color, and Unicode capabilities without assuming ANSI/UTF-8."""
    pref = appearance.lower().strip()
    is_tty = bool(getattr(sys.stdout, "isatty", lambda: False)())
    encoding = (getattr(sys.stdout, "encoding", None) or "").lower()
    supports_unicode = "utf" in encoding
    no_color = bool(os.environ.get("NO_COLOR")) or os.environ.get("TERM", "").lower() == "dumb"
    supports_color = is_tty and not no_color

    if pref == "plain":
        return TerminalCapabilities(
            is_tty=is_tty,
            supports_unicode=False,
            supports_color=False,
            plain_mode=True,
        )
    if pref == "rich":
        return TerminalCapabilities(
            is_tty=is_tty,
            supports_unicode=True,
            supports_color=True,
            plain_mode=False,
        )
    plain = not supports_color and not supports_unicode
    return TerminalCapabilities(
        is_tty=is_tty,
        supports_unicode=supports_unicode,
        supports_color=supports_color,
        plain_mode=plain,
    )


def create_console(caps: TerminalCapabilities) -> Console:
    """Build a Rich Console configured for detected terminal capabilities."""
    return Console(
        no_color=not caps.supports_color or caps.plain_mode,
        force_terminal=caps.supports_color and not caps.plain_mode,
        legacy_windows=(sys.platform == "win32" and caps.plain_mode),
    )


def render_banner(console: Console, caps: TerminalCapabilities) -> None:
    """Display the minimal OpenSource Runner interactive header."""
    if caps.plain_mode or not caps.supports_unicode:
        console.print("+------------------------------------------+")
        console.print("|           OPENSOURCE RUNNER              |")
        console.print("|         Interactive Terminal             |")
        console.print("+------------------------------------------+")
        return
    console.print(
        Panel(
            "[bold]OPENSOURCE RUNNER[/bold]\nInteractive Terminal",
            width=46,
            expand=False,
            border_style="cyan",
        )
    )


def render_status_table(
    console: Console,
    caps: TerminalCapabilities,
    rows: list[tuple[str, str, str]],
) -> None:
    """Render a compact project status table with plain-text fallback."""
    if caps.plain_mode:
        console.print(f"{'PROJECT':<28} {'STATUS':<14} {'PROGRESS':>8}")
        console.print("-" * 52)
        for name, status, progress in rows:
            console.print(f"{name:<28} {status:<14} {progress:>8}")
        return

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("PROJECT", min_width=24)
    table.add_column("STATUS", min_width=12)
    table.add_column("PROGRESS", justify="right", min_width=8)
    for name, status, progress in rows:
        table.add_row(name, status, progress)
    console.print(table)
