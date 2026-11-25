"""Configuration loader for opensource-runner."""

from __future__ import annotations

import tomllib
from pathlib import Path

from opensource_runner.models import (
    ExecutionConfig,
    PathsConfig,
    RunnerConfig,
    SandboxConfig,
    TypingConfig,
    UIConfig,
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
    sandbox_data = raw.get("sandbox", {})
    ui_data = raw.get("ui", {})

    return RunnerConfig(
        root_dir=base,
        paths=PathsConfig(**paths_data),
        typing=TypingConfig(**typing_data),
        execution=ExecutionConfig(**exec_data),
        sandbox=SandboxConfig(**sandbox_data),
        ui=UIConfig(**ui_data),
    )


def save_config(config: RunnerConfig, config_file: Path | None = None) -> Path:
    """Persist non-sensitive user preferences to config.toml."""
    target = config_file or (config.root_dir / "config.toml")

    def _toml_str(value: str) -> str:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    def _toml_bool(value: bool) -> str:
        return "true" if value else "false"

    lines = [
        "# OpenSource Runner user preferences (no secrets stored)",
        "",
        "[paths]",
        f"projects_dir = {_toml_str(config.paths.projects_dir.as_posix())}",
        f"source_cache_dir = {_toml_str(config.paths.source_cache_dir.as_posix())}",
        f"workspace_dir = {_toml_str(config.paths.workspace_dir.as_posix())}",
        f"state_dir = {_toml_str(config.paths.state_dir.as_posix())}",
        f"logs_dir = {_toml_str(config.paths.logs_dir.as_posix())}",
        "",
        "[typing]",
        f"typing_speed = {config.typing.typing_speed}",
        f"character_delay_ms = {config.typing.character_delay_ms}",
        f"file_delay_ms = {config.typing.file_delay_ms}",
        f"vscode_path = {_toml_str(config.typing.vscode_path)}",
        f"input_backend = {_toml_str(config.typing.input_backend)}",
        "",
        "[execution]",
        f"require_dependency_approval = {_toml_bool(config.execution.require_dependency_approval)}",
        f"prefer_container = {_toml_bool(config.execution.prefer_container)}",
        "",
        "[sandbox]",
        f"cpu_limit = {config.sandbox.cpu_limit}",
        f"memory_limit_mb = {config.sandbox.memory_limit_mb}",
        f"process_limit = {config.sandbox.process_limit}",
        f"execution_timeout_seconds = {config.sandbox.execution_timeout_seconds}",
        f"dependency_timeout_seconds = {config.sandbox.dependency_timeout_seconds}",
        f"healthcheck_timeout_seconds = {config.sandbox.healthcheck_timeout_seconds}",
        f"network_enabled = {_toml_bool(config.sandbox.network_enabled)}",
        "",
        "[ui]",
        f"appearance = {_toml_str(config.ui.appearance)}",
        f"confirm_all_operations = {_toml_bool(config.ui.confirm_all_operations)}",
    ]
    if config.ui.last_project_id:
        lines.append(f"last_project_id = {_toml_str(config.ui.last_project_id)}")
    lines.append("")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines), encoding="utf-8")
    return target
