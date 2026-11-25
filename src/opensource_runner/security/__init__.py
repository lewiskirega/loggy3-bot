"""Security utilities: path sandboxing, symlink validation, and log secret redaction."""

from __future__ import annotations

import os
import re
import shutil
import stat
from pathlib import Path
from typing import Callable

SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key)\s*[:=]\s*([^\s'\"`]+)"),
    re.compile(r"(?i)(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
)


class SecurityError(Exception):
    """Raised when a security or boundary invariant is violated."""


def ensure_within_directory(base_dir: Path, target_path: Path) -> Path:
    """Resolve target_path and assert it stays strictly inside base_dir."""
    resolved_base = base_dir.resolve()
    resolved_target = target_path.resolve()
    try:
        resolved_target.relative_to(resolved_base)
    except ValueError as exc:
        raise SecurityError(
            f"Path escape detected: '{target_path}' resolves outside '{resolved_base}'"
        ) from exc
    return resolved_target


def validate_safe_relative_path(base_dir: Path, relative_path: str) -> Path:
    """Validate that a relative path has no traversal segments and stays within base_dir."""
    rel = Path(relative_path)
    if rel.is_absolute():
        raise SecurityError(f"Absolute paths are not allowed: '{relative_path}'")
    if ".." in rel.parts:
        raise SecurityError(f"Parent traversal ('..') is not allowed: '{relative_path}'")
    candidate = base_dir / rel
    if candidate.is_symlink():
        ensure_within_directory(base_dir, candidate)
    return ensure_within_directory(base_dir, candidate)


def assert_not_in_source_cache(target_path: Path, source_cache_root: Path) -> None:
    """Prevent any write operation from targeting the immutable source cache."""
    resolved_cache = source_cache_root.resolve()
    resolved_target = target_path.resolve()
    try:
        resolved_target.relative_to(resolved_cache)
    except ValueError:
        return
    raise SecurityError(f"Refusing to modify immutable source cache path: '{resolved_target}'")


def redact_secrets(text: str) -> str:
    """Redact potential credentials and tokens from log or terminal messages."""
    redacted = text
    for pattern in SECRET_PATTERNS:
        if pattern.groups == 2:
            redacted = pattern.sub(r"\1=[REDACTED]", redacted)
        else:
            redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def is_running_as_root() -> bool:
    """Return True if the process has root/UID-0 privileges on POSIX."""
    if hasattr(os, "geteuid"):
        return os.geteuid() == 0
    return False


DISALLOWED_COMMAND_BINARIES: frozenset[str] = frozenset(
    {"sudo", "su", "doas", "mkfs", "dd", "shutdown", "reboot", "format", "diskpart"}
)

SHELL_INJECTION_TOKENS: frozenset[str] = frozenset({"&&", "||", ";", "|", "`", "$("})


def validate_command_argv(command: list[str]) -> list[str]:
    """Validate structured argv commands before subprocess execution (no shell=True)."""
    if not command or not command[0].strip():
        raise SecurityError("Refusing to execute an empty command.")

    binary_name = Path(command[0]).name.lower().removesuffix(".exe").removesuffix(".cmd")
    if binary_name in DISALLOWED_COMMAND_BINARIES:
        raise SecurityError(f"Refusing to execute privileged or destructive binary '{command[0]}'.")

    for arg in command:
        for bad in SHELL_INJECTION_TOKENS:
            if bad in arg:
                raise SecurityError(
                    f"Refusing to execute command containing shell operator '{bad}': {command!r}"
                )
    return command


def force_rmtree(path: Path) -> None:
    """Remove a directory tree cleanly on both POSIX and Windows (handles read-only .git files)."""
    if not path.exists():
        return

    def _handle_readonly(func: Callable[[str], None], target: str, _exc: BaseException) -> None:
        try:
            os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
        except OSError:
            pass
        func(target)

    shutil.rmtree(path, onexc=_handle_readonly)
