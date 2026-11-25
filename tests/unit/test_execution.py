"""Unit tests for execution orchestrator, dependency approval, and runtime adapters."""

from __future__ import annotations

from pathlib import Path

import pytest

from opensource_runner.checkpoint import CheckpointManager
from opensource_runner.execution import ExecutionError, ExecutionOrchestrator
from opensource_runner.execution.runtimes import ExecutionResult
from opensource_runner.models import InspectionReport, ProjectCheckpoint, ProjectState


def test_execution_blocked_if_not_verified(tmp_path: Path) -> None:
    mgr = CheckpointManager(tmp_path / "state")
    cp = ProjectCheckpoint(
        project_id="flappy",
        project_name="Flappy",
        repository="https://example.com/flappy",
        state=ProjectState.PREPARED,
        verification_passed=False,
    )
    mgr.save_checkpoint(cp)
    report = InspectionReport(
        project_id="flappy",
        commit="sha1",
        runtime="Python",
        entry_point="Flappy.py",
        run_command="python Flappy.py",
    )
    orch = ExecutionOrchestrator(checkpoint_manager=mgr)
    with pytest.raises(ExecutionError, match="full verification"):
        orch.execute(cp, report, tmp_path / "ws", approve_fn=lambda _: True)


def test_dependency_approval_decline_aborts_execution(tmp_path: Path) -> None:
    mgr = CheckpointManager(tmp_path / "state")
    cp = ProjectCheckpoint(
        project_id="flask-inv",
        project_name="Flask Inv",
        repository="https://example.com/flask-inv",
        state=ProjectState.READY_TO_RUN,
        verification_passed=True,
    )
    mgr.save_checkpoint(cp)
    report = InspectionReport(
        project_id="flask-inv",
        commit="sha1",
        runtime="Python",
        dependencies=["flask"],
        setup_commands=["python -m pip install flask"],
        entry_point="flaskmain.py",
        run_command="python flaskmain.py",
    )
    called: list[list[str]] = []

    def fake_runner(cmd, cwd, env):
        called.append(cmd)
        return ExecutionResult(0, "ok", "")

    orch = ExecutionOrchestrator(checkpoint_manager=mgr, command_runner=fake_runner)
    with pytest.raises(ExecutionError, match="declined"):
        orch.execute(cp, report, tmp_path / "ws", approve_fn=lambda _: False)
    assert called == []


def test_execution_runs_with_mock_runner_and_detects_url(tmp_path: Path) -> None:
    mgr = CheckpointManager(tmp_path / "state")
    cp = ProjectCheckpoint(
        project_id="flask-inv",
        project_name="Flask Inv",
        repository="https://example.com/flask-inv",
        state=ProjectState.READY_TO_RUN,
        verification_passed=True,
    )
    mgr.save_checkpoint(cp)
    ws = tmp_path / "ws"
    ws.mkdir()
    report = InspectionReport(
        project_id="flask-inv",
        commit="sha1",
        runtime="Python",
        dependencies=["flask"],
        setup_commands=["python -m pip install flask"],
        entry_point="flaskmain.py",
        run_command="python flaskmain.py",
    )
    executed: list[list[str]] = []

    def fake_runner(cmd, cwd, env):
        executed.append(cmd)
        return ExecutionResult(0, "Running on http://127.0.0.1:5000", "")

    orch = ExecutionOrchestrator(checkpoint_manager=mgr, command_runner=fake_runner)
    res = orch.execute(cp, report, ws, approve_fn=lambda _: True)
    assert res.returncode == 0
    assert res.detected_url == "http://127.0.0.1:5000"
    assert len(executed) == 3  # venv create, pip install, python flaskmain.py
    assert mgr.load_checkpoint("flask-inv").state == ProjectState.COMPLETED
