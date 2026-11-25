"""Project registry backed by TOML files under projects/."""

from __future__ import annotations

import tomllib
from pathlib import Path

from opensource_runner.models import ProjectRegistryEntry


class ProjectNotFoundError(KeyError):
    """Raised when a requested project ID is not in the registry."""


class ProjectRegistry:
    """Loads and queries configured open-source projects."""

    def __init__(self, projects_dir: Path) -> None:
        self.projects_dir = projects_dir.resolve()

    def list_projects(self, include_disabled: bool = False) -> list[ProjectRegistryEntry]:
        if not self.projects_dir.exists():
            return []
        entries: list[ProjectRegistryEntry] = []
        for toml_path in sorted(self.projects_dir.glob("*.toml")):
            data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
            entry = ProjectRegistryEntry(**data)
            if include_disabled or entry.enabled:
                entries.append(entry)
        return sorted(entries, key=lambda item: item.id)

    def get(self, project_id: str) -> ProjectRegistryEntry:
        for entry in self.list_projects(include_disabled=True):
            if entry.id == project_id:
                return entry
        raise ProjectNotFoundError(f"Unknown project ID: '{project_id}'")
