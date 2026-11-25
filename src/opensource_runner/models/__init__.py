"""Core Pydantic data models and state machine definitions."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProjectState(str, Enum):
    DISCOVERED = "DISCOVERED"
    SELECTED = "SELECTED"
    PREPARING = "PREPARING"
    PREPARED = "PREPARED"
    TYPING = "TYPING"
    PAUSED = "PAUSED"
    VERIFYING = "VERIFYING"
    VERIFIED = "VERIFIED"
    READY_TO_RUN = "READY_TO_RUN"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


ALLOWED_TRANSITIONS: dict[ProjectState, set[ProjectState]] = {
    ProjectState.DISCOVERED: {ProjectState.SELECTED, ProjectState.FAILED},
    ProjectState.SELECTED: {ProjectState.PREPARING, ProjectState.SELECTED, ProjectState.FAILED},
    ProjectState.PREPARING: {ProjectState.PREPARED, ProjectState.FAILED},
    ProjectState.PREPARED: {
        ProjectState.TYPING,
        ProjectState.PREPARING,
        ProjectState.VERIFYING,
        ProjectState.FAILED,
    },
    ProjectState.TYPING: {
        ProjectState.PAUSED,
        ProjectState.VERIFYING,
        ProjectState.PREPARED,
        ProjectState.FAILED,
    },
    ProjectState.PAUSED: {
        ProjectState.TYPING,
        ProjectState.VERIFYING,
        ProjectState.PREPARED,
        ProjectState.FAILED,
    },
    ProjectState.VERIFYING: {
        ProjectState.VERIFIED,
        ProjectState.READY_TO_RUN,
        ProjectState.PAUSED,
        ProjectState.FAILED,
    },
    ProjectState.VERIFIED: {
        ProjectState.READY_TO_RUN,
        ProjectState.VERIFYING,
        ProjectState.FAILED,
    },
    ProjectState.READY_TO_RUN: {
        ProjectState.RUNNING,
        ProjectState.VERIFYING,
        ProjectState.FAILED,
    },
    ProjectState.RUNNING: {
        ProjectState.COMPLETED,
        ProjectState.READY_TO_RUN,
        ProjectState.FAILED,
    },
    ProjectState.COMPLETED: {
        ProjectState.READY_TO_RUN,
        ProjectState.VERIFYING,
        ProjectState.PREPARING,
    },
    ProjectState.FAILED: {
        ProjectState.SELECTED,
        ProjectState.PREPARING,
        ProjectState.TYPING,
        ProjectState.PAUSED,
        ProjectState.VERIFYING,
    },
}


class ProjectRegistryEntry(BaseModel):
    id: str
    name: str
    repository: str
    revision: str = "auto"
    local_source: str | None = None
    category: str = ""
    enabled: bool = True


class PathsConfig(BaseModel):
    projects_dir: Path = Path("projects")
    source_cache_dir: Path = Path("source-cache")
    workspace_dir: Path = Path("workspace")
    state_dir: Path = Path("state")
    logs_dir: Path = Path("logs")


class TypingConfig(BaseModel):
    typing_speed: int = Field(default=35, ge=1, le=500)
    character_delay_ms: int = Field(default=25, ge=0, le=5000)
    file_delay_ms: int = Field(default=500, ge=0, le=30000)
    vscode_path: str = ""
    input_backend: str = "auto"


class ExecutionConfig(BaseModel):
    require_dependency_approval: bool = True
    prefer_container: bool = False


class RunnerConfig(BaseModel):
    root_dir: Path = Field(default_factory=Path.cwd)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    typing: TypingConfig = Field(default_factory=TypingConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)

    def resolve_path(self, rel_or_abs: Path) -> Path:
        if rel_or_abs.is_absolute():
            return rel_or_abs
        return (self.root_dir / rel_or_abs).resolve()

    @property
    def projects_path(self) -> Path:
        return self.resolve_path(self.paths.projects_dir)

    @property
    def source_cache_path(self) -> Path:
        return self.resolve_path(self.paths.source_cache_dir)

    @property
    def workspace_path(self) -> Path:
        return self.resolve_path(self.paths.workspace_dir)

    @property
    def state_path(self) -> Path:
        return self.resolve_path(self.paths.state_dir)

    @property
    def logs_path(self) -> Path:
        return self.resolve_path(self.paths.logs_dir)


class RepositoryProvenance(BaseModel):
    project_id: str
    project_name: str
    repository: str
    branch: str
    commit: str
    retrieved_at: datetime = Field(default_factory=utc_now)
    source_origin: str = "GitHub"


class SourceFileEntry(BaseModel):
    relative_path: str
    file_type: Literal["text", "binary"]
    size_bytes: int
    sha256: str


class SourceManifest(BaseModel):
    project_id: str
    commit: str
    generated_at: datetime = Field(default_factory=utc_now)
    total_files: int
    text_files: int
    binary_files: int
    files: list[SourceFileEntry] = Field(default_factory=list)


class LicenseStatus(str, Enum):
    APPROVED = "APPROVED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    REJECTED = "REJECTED"


class LicenseReport(BaseModel):
    project_id: str
    project_name: str
    detected_license: str = "UNKNOWN"
    license_file: str | None = None
    readme_license_mention: str | None = None
    copyright_notices: list[str] = Field(default_factory=list)
    third_party_notices: list[str] = Field(default_factory=list)
    status: LicenseStatus = LicenseStatus.REVIEW_REQUIRED
    reason: str = ""
    user_approved: bool = False
    approved_at: datetime | None = None
    inspected_at: datetime = Field(default_factory=utc_now)


class InspectionReport(BaseModel):
    project_id: str
    commit: str
    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    runtime: str = "UNKNOWN"
    runtime_version_spec: str | None = None
    package_managers: list[str] = Field(default_factory=list)
    dependency_files: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    entry_point: str | None = None
    working_subdir: str | None = None
    config_files: list[str] = Field(default_factory=list)
    env_vars: list[str] = Field(default_factory=list)
    binary_assets: list[str] = Field(default_factory=list)
    database_requirements: list[str] = Field(default_factory=list)
    setup_commands: list[str] = Field(default_factory=list)
    run_command: str | None = None
    test_command: str | None = None
    docker_files: list[str] = Field(default_factory=list)
    expected_url: str | None = None
    notes: list[str] = Field(default_factory=list)
    inspected_at: datetime = Field(default_factory=utc_now)


class FileVerificationResult(BaseModel):
    relative_path: str
    file_type: Literal["text", "binary"]
    reproduction_method: Literal["keyboard reproduction", "verified binary copy"]
    verified: bool
    source_sha256: str
    workspace_sha256: str | None = None
    reason: str = ""


class ProjectVerificationReport(BaseModel):
    project_id: str
    commit: str
    verified: bool
    verified_at: datetime = Field(default_factory=utc_now)
    total_files: int = 0
    verified_files: int = 0
    missing_files: list[str] = Field(default_factory=list)
    unexpected_files: list[str] = Field(default_factory=list)
    modified_files: list[str] = Field(default_factory=list)
    text_mismatches: list[str] = Field(default_factory=list)
    binary_mismatches: list[str] = Field(default_factory=list)
    hash_mismatches: list[str] = Field(default_factory=list)
    file_results: list[FileVerificationResult] = Field(default_factory=list)


class ProjectCheckpoint(BaseModel):
    project_id: str
    project_name: str
    repository: str
    state: ProjectState = ProjectState.DISCOVERED
    branch: str | None = None
    commit: str | None = None
    source_cache_dir: str | None = None
    workspace_dir: str | None = None
    current_file: str | None = None
    current_position: int = 0
    completed_files: list[str] = Field(default_factory=list)
    remaining_files: list[str] = Field(default_factory=list)
    retrieval_approved: bool = False
    license_approved: bool = False
    inspection_complete: bool = False
    verification_passed: bool = False
    runtime: str | None = None
    dependencies_installed: bool = False
    execution_status: str = "NOT STARTED"
    last_error: str | None = None
    updated_at: datetime = Field(default_factory=utc_now)


class ProjectRunConfig(BaseModel):
    """Per-project persisted run configuration (secret values are never stored)."""

    project_id: str
    project_name: str
    repository: str
    revision: str
    license_result: str
    license_approved: bool
    project_root: str
    entry_point: str | None = None
    runtime: str = "UNKNOWN"
    dependencies: list[str] = Field(default_factory=list)
    setup_commands: list[str] = Field(default_factory=list)
    run_command: str | None = None
    test_command: str | None = None
    required_env_vars: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utc_now)


class ProjectProgress(BaseModel):
    project_id: str
    total_files: int = 0
    completed_files: int = 0
    remaining_files: int = 0
    current_file: str | None = None
    current_char_index: int = 0
    current_file_total_chars: int = 0
    percent_complete: float = 0.0
    updated_at: datetime = Field(default_factory=utc_now)


class ControlSignal(BaseModel):
    action: Literal["none", "pause", "stop"] = "none"
    requested_at: datetime = Field(default_factory=utc_now)
