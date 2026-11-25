"""Environment secret-isolation allowlist and network policy enforcement."""

from __future__ import annotations

import os
import re
from pathlib import Path

SAFE_ENV_ALLOWLIST: tuple[str, ...] = (
    "PATH",
    "LANG",
    "LC_ALL",
    "TEMP",
    "TMP",
    "SYSTEMROOT",
    "COMSPEC",
    "PATHEXT",
)

FORBIDDEN_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)SSH_PRIVATE_KEY"),
    re.compile(r"(?i)GITHUB_TOKEN|GH_TOKEN"),
    re.compile(r"(?i)^AWS_"),
    re.compile(r"(?i)^AZURE_"),
    re.compile(r"(?i)^GCP_|GOOGLE_APPLICATION_CREDENTIALS"),
    re.compile(r"(?i)PASSWORD|PASSWD|SECRET|API_KEY|ACCESS_TOKEN|PRIVATE_KEY"),
)


def build_sandbox_env(
    sandbox_home: Path,
    extra_env: dict[str, str] | None = None,
    source_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Construct a minimal allowlisted environment free of host secrets."""
    host_env = source_env if source_env is not None else dict(os.environ)
    clean: dict[str, str] = {}
    for key in SAFE_ENV_ALLOWLIST:
        if key in host_env:
            clean[key] = host_env[key]
    clean["HOME"] = str(sandbox_home.resolve())
    clean["USERPROFILE"] = str(sandbox_home.resolve())
    clean["TEMP"] = str(sandbox_home.resolve())
    clean["TMP"] = str(sandbox_home.resolve())
    clean["PYTHONUNBUFFERED"] = "1"
    if extra_env:
        clean.update(extra_env)
    return clean


def detect_leaked_secrets(env: dict[str, str]) -> list[str]:
    """Return any environment variable names that match forbidden secret patterns."""
    leaked: list[str] = []
    for key in env:
        if any(pat.search(key) for pat in FORBIDDEN_SECRET_PATTERNS):
            leaked.append(key)
    return sorted(leaked)
