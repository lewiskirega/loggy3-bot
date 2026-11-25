"""Filesystem isolation guard and safe harness-owned cleanup verification."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from opensource_runner.security import SecurityError

HARNESS_MARKER_FILE = ".opensource-runner-sandbox-marker"

SENSITIVE_HOME_RELPATHS: tuple[str, ...] = (
    ".ssh",
    ".gitconfig",
    ".aws",
    ".azure",
    ".config/gcloud",
    "Desktop",
    "Documents",
    "Downloads",
)


@dataclass
class FilesystemSnapshot:
    watched_mtimes: dict[str, float | None]


class FilesystemGuard:
    """Verifies that sandbox tests do not modify host paths outside allowed directories."""

    def __init__(self, allowed_roots: list[Path], home_dir: Path | None = None) -> None:
        self.allowed_roots = [p.resolve() for p in allowed_roots]
        self.home_dir = (home_dir or Path.home()).resolve()
        self._baseline: FilesystemSnapshot | None = None

    def _collect_mtimes(self) -> dict[str, float | None]:
        mtimes: dict[str, float | None] = {}
        for rel in SENSITIVE_HOME_RELPATHS:
            p = self.home_dir / rel
            # Skip if a watched path is explicitly inside an allowed test root
            if any(self._is_within(p, root) for root in self.allowed_roots):
                continue
            try:
                mtimes[str(p)] = p.stat().st_mtime if p.exists() else None
            except OSError:
                mtimes[str(p)] = None
        return mtimes

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except ValueError:
            return False

    def capture_baseline(self) -> FilesystemSnapshot:
        self._baseline = FilesystemSnapshot(watched_mtimes=self._collect_mtimes())
        return self._baseline

    def verify_no_host_modifications(self) -> tuple[bool, list[str]]:
        if self._baseline is None:
            return True, []
        current = self._collect_mtimes()
        changed: list[str] = []
        for path_str, old_mtime in self._baseline.watched_mtimes.items():
            if current.get(path_str) != old_mtime:
                changed.append(path_str)
        return len(changed) == 0, changed


def mark_harness_directory(directory: Path) -> None:
    """Tag a temporary directory so cleanup only ever removes harness-owned directories."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / HARNESS_MARKER_FILE).write_text("opensource-runner-self-test\n", encoding="utf-8")


def safe_remove_harness_directory(directory: Path) -> bool:
    """Remove a directory ONLY if it bears the harness ownership marker."""
    resolved = directory.resolve()
    if not resolved.exists():
        return True
    marker = resolved / HARNESS_MARKER_FILE
    if not marker.is_file():
        raise SecurityError(
            f"Refusing to delete '{resolved}': missing harness marker '{HARNESS_MARKER_FILE}'."
        )
    shutil.rmtree(resolved)
    return not resolved.exists()
