"""Pydantic models for the automated disposable sandbox test harness."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from opensource_runner.models import utc_now


class StageStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"
    UNAVAILABLE = "UNAVAILABLE"
    WARN = "WARN"


class StageResult(BaseModel):
    name: str
    status: StageStatus
    duration_seconds: float = 0.0
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class ProcessMetrics(BaseModel):
    pid: int | None = None
    command: list[str] = Field(default_factory=list)
    start_time: datetime = Field(default_factory=utc_now)
    end_time: datetime | None = None
    duration_seconds: float = 0.0
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    termination_reason: str = "completed"


class ProjectSelfTestReport(BaseModel):
    project_id: str
    project_name: str
    repository: str
    result: StageStatus = StageStatus.FAIL
    commit_sha: str | None = None
    branch: str | None = None
    runtime: str = "UNKNOWN"
    sandbox_mode: str = "none"
    sandbox_used: bool = False
    license_detected: str = "UNKNOWN"
    license_confidence: str = "LOW"
    network_required: bool = False
    stages: list[StageResult] = Field(default_factory=list)
    dependencies_status: StageStatus = StageStatus.SKIPPED
    execution_status: StageStatus = StageStatus.SKIPPED
    healthcheck_status: StageStatus = StageStatus.SKIPPED
    cleanup_status: StageStatus = StageStatus.SKIPPED
    timings_seconds: dict[str, float] = Field(default_factory=dict)
    stdout_log: str = ""
    stderr_log: str = ""
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None


class RunnerMetadata(BaseModel):
    version: str
    platform: str
    os_pretty_name: str = ""
    distro_id: str = ""
    kernel: str = ""
    architecture: str = ""
    desktop: str = ""
    display_server: str = ""
    python: str = ""
    container_engine: str | None = None


class SelfTestSummaryReport(BaseModel):
    runner: RunnerMetadata
    result: StageStatus = StageStatus.FAIL
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    core_stages: dict[str, StageResult] = Field(default_factory=dict)
    security_stages: dict[str, StageResult] = Field(default_factory=dict)
    projects: dict[str, ProjectSelfTestReport] = Field(default_factory=dict)
    dry_run: bool = False
