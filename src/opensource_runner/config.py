"""Configuration loader for opensource-runner."""

from __future__ import annotations

import tomllib
from pathlib import Path

from opensource_runner.models import (
    ExecutionConfig,
    PathsConfig,
    RunnerConfig,
    TypingConfig,
)


def load_config(root_dir: Path | None = None, config_file: Path | None = None) -> RunnerConfig:
    """Load RunnerConfig from config.toml if present, otherwise return defaults."""
    base = (root_dir or Path.cwd()).resolve()
    cfg_path = config_file or (base / "config.toml")

    if not cfg_path.exists():
        return RunnerConfig(root_dir=base)

    raw = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    paths_data = raw.get("paths", {})
    typing_data = raw.get("typing", {})
    exec_data = raw.get("execution", {})

    return RunnerConfig(
        root_dir=base,
        paths=PathsConfig(**paths_data),
        typing=TypingConfig(**typing_data),
        execution=ExecutionConfig(**exec_data),
    )
