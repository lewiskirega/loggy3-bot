"""Host environment and OS/distribution/container/display inspection for self-test."""

from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path

from opensource_runner import __version__
from opensource_runner.testing.models import RunnerMetadata
from opensource_runner.typing.platforms import detect_display_platform


def parse_os_release(os_release_path: Path = Path("/etc/os-release")) -> dict[str, str]:
    """Parse /etc/os-release key=value pairs on Linux hosts."""
    info: dict[str, str] = {}
    if not os_release_path.is_file():
        return info
    for line in os_release_path.read_text(encoding="utf-8", errors="replace").splitlines():
        cleaned = line.strip()
        if not cleaned or cleaned.startswith("#") or "=" not in cleaned:
            continue
        key, val = cleaned.split("=", 1)
        info[key.strip()] = val.strip().strip('"').strip("'")
    return info


def detect_container_engine() -> str | None:
    """Detect Docker or Podman availability."""
    for engine in ("docker", "podman"):
        if shutil.which(engine):
            return engine
    return None


def collect_runner_metadata() -> RunnerMetadata:
    """Collect OS, Fedora/Linux release info, display server, Python, and container runtime."""
    os_rel = parse_os_release() if platform.system() == "Linux" else {}
    return RunnerMetadata(
        version=__version__,
        platform=platform.system(),
        os_pretty_name=os_rel.get("PRETTY_NAME", f"{platform.system()} {platform.release()}"),
        distro_id=os_rel.get("ID", platform.system().lower()),
        kernel=platform.release(),
        architecture=platform.machine(),
        desktop=os.environ.get("XDG_CURRENT_DESKTOP", ""),
        display_server=detect_display_platform(),
        python=platform.python_version(),
        container_engine=detect_container_engine(),
    )
