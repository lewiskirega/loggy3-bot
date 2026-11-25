"""Project registry and inspection package."""

from opensource_runner.projects.inspector import inspect_project
from opensource_runner.projects.registry import ProjectNotFoundError, ProjectRegistry

__all__ = ["ProjectNotFoundError", "ProjectRegistry", "inspect_project"]
