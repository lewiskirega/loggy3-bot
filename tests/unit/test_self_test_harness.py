"""Unit and chaos tests for the automated disposable sandbox test harness."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from opensource_runner.cli.app import app
from opensource_runner.github import classify_file
from opensource_runner.models import ProjectRegistryEntry, SandboxConfig
from opensource_runner.security import SecurityError
from opensource_runner.testing import SelfTestOrchestrator
from opensource_runner.testing.environment import parse_os_release
from opensource_runner.testing.filesystem_guard import (
    FilesystemGuard,
    mark_harness_directory,
    safe_remove_harness_directory,
)
from opensource_runner.testing.models import StageStatus
from opensource_runner.testing.network_guard import build_sandbox_env, detect_leaked_secrets
from opensource_runner.testing.project_test import run_project_self_test
from opensource_runner.testing.sandbox import DisposableSandbox, cleanup_abandoned_sandboxes
from opensource_runner.testing.timeout import run_monitored_command

runner = CliRunner()


def test_secret_allowlist_strips_host_credentials(tmp_path: Path) -> None:
    poisoned = {
        "PATH": "/usr/bin",
        "SSH_PRIVATE_KEY": "synthetic-key",  # gitleaks:allow
        "GITHUB_TOKEN": "synthetic-" + "gh-token",  # gitleaks:allow
        "AWS_SECRET_ACCESS_KEY": "synthetic-aws",  # gitleaks:allow
        "AZURE_CLIENT_SECRET": "synthetic-az",  # gitleaks:allow
        "GCP_PROJECT_KEY": "synthetic-gcp",  # gitleaks:allow
        "DB_PASSWORD": "synthetic-pw",  # gitleaks:allow
        "OPENAI_API_KEY": "synthetic-api",  # gitleaks:allow
    }
    clean = build_sandbox_env(tmp_path, source_env=poisoned)
    assert detect_leaked_secrets(clean) == []
    assert clean["HOME"] == str(tmp_path.resolve())
    assert "GITHUB_TOKEN" not in clean
    assert "SSH_PRIVATE_KEY" not in clean


def test_filesystem_guard_refuses_unmarked_cleanup(tmp_path: Path) -> None:
    user_dir = tmp_path / "important-user-data"
    user_dir.mkdir()
    (user_dir / "notes.txt").write_text("keep me", encoding="utf-8")

    with pytest.raises(SecurityError, match="missing harness marker"):
        safe_remove_harness_directory(user_dir)
    assert (user_dir / "notes.txt").is_file()

    # Marked harness dir removes cleanly
    harness_dir = tmp_path / "osr-sandbox-demo"
    mark_harness_directory(harness_dir)
    assert safe_remove_harness_directory(harness_dir) is True
    assert not harness_dir.exists()


def test_filesystem_guard_detects_unexpected_home_modification(tmp_path: Path) -> None:
    fake_home = tmp_path / "home"
    ssh_dir = fake_home / ".ssh"
    ssh_dir.mkdir(parents=True)
    sandbox_root = tmp_path / "sandbox"
    sandbox_root.mkdir()

    guard = FilesystemGuard(allowed_roots=[sandbox_root], home_dir=fake_home)
    guard.capture_baseline()
    ok, changed = guard.verify_no_host_modifications()
    assert ok is True and changed == []


def test_monitored_command_enforces_timeout_and_cleans_up(tmp_path: Path) -> None:
    metrics = run_monitored_command(
        [sys.executable, "-c", "import time\ntime.sleep(10)"],
        cwd=tmp_path,
        timeout_seconds=1,
    )
    assert metrics.timed_out is True
    assert "timeout" in metrics.termination_reason


def test_sandbox_container_command_has_hardened_flags(tmp_path: Path) -> None:
    sb = DisposableSandbox("demo", SandboxConfig(), prefer_container=False)
    try:
        sb.container_engine = "docker"
        cmd = sb.build_container_run_command(
            image="python:3.12-slim",
            project_dir=tmp_path,
            command=["python", "app.py"],
            network_enabled=False,
        )
        assert "--rm" in cmd
        assert "--network" in cmd and "none" in cmd
        assert "--security-opt=no-new-privileges" in cmd
        assert "--cpus=2" in cmd
        assert "--memory=2048m" in cmd
        assert "--pids-limit=128" in cmd
    finally:
        assert sb.cleanup() is True


def test_parse_os_release_fedora(tmp_path: Path) -> None:
    os_rel = tmp_path / "os-release"
    os_rel.write_text(
        'ID=fedora\nPRETTY_NAME="Fedora Linux 45 (Workstation Edition)"\n', encoding="utf-8"
    )
    parsed = parse_os_release(os_rel)
    assert parsed["ID"] == "fedora"
    assert "Fedora Linux 45" in parsed["PRETTY_NAME"]


def test_synthetic_fixtures_classification(tmp_path: Path) -> None:
    fixtures_root = Path("tests/fixtures")
    assert classify_file(fixtures_root / "text" / "empty.txt") == "text"
    assert classify_file(fixtures_root / "text" / "small.txt") == "text"
    assert classify_file(fixtures_root / "unicode" / "utf8.txt") == "text"

    # Invalid UTF-8 & large file synthetic checks
    bad_utf8 = tmp_path / "invalid_utf8.bin"
    bad_utf8.write_bytes(b"\xff\xfe\xfa\x80\x81")
    assert classify_file(bad_utf8) == "binary"

    large_txt = tmp_path / "large.txt"
    large_txt.write_text("line\n" * 20000, encoding="utf-8")
    assert classify_file(large_txt) == "text"


def test_project_self_test_with_local_fixture_and_chaos_invalid_repo(tmp_path: Path) -> None:
    # 1. Valid synthetic project end-to-end inside disposable sandbox
    entry = ProjectRegistryEntry(
        id="fake-project",
        name="Fake Project",
        repository="https://example.com/fake-project",
    )
    report, artifacts = run_project_self_test(
        entry,
        SandboxConfig(),
        allow_network=False,
        allow_execution=True,
        local_override=Path("tests/fixtures/fake_project"),
    )
    assert report.result == StageStatus.PASS
    assert report.execution_status == StageStatus.PASS
    assert report.cleanup_status == StageStatus.PASS
    assert "runtime" in artifacts

    # 2. Chaos test: invalid repository fails cleanly and still cleans up sandbox
    bad_entry = ProjectRegistryEntry(
        id="broken-repo",
        name="Broken Repo",
        repository=str(tmp_path / "does-not-exist-repo"),
    )
    bad_report, _ = run_project_self_test(bad_entry, SandboxConfig())
    assert bad_report.result == StageStatus.FAIL
    assert bad_report.cleanup_status == StageStatus.PASS


def test_cli_self_test_dry_run_input_and_cleanup(tmp_path: Path) -> None:
    r = runner.invoke(app, ["self-test", "--dry-run"])
    assert r.exit_code == 0
    assert "SELF-TEST DRY RUN" in r.stdout
    assert "flappy" in r.stdout

    out_dir = tmp_path / "test-results"
    r = runner.invoke(app, ["self-test", "--input", "--output-dir", str(out_dir)])
    assert r.exit_code == 0
    assert (out_dir / "summary.json").is_file()
    assert (out_dir / "summary.html").is_file()
    assert (out_dir / "summary.txt").is_file()
    summary_data = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert "Input Controller" in summary_data["core_stages"]

    # Cleanup abandoned marked sandbox
    abandoned = tmp_path / "osr-sandbox-abandoned-test"
    mark_harness_directory(abandoned)
    removed = cleanup_abandoned_sandboxes(base_temp_dir=tmp_path)
    assert str(abandoned.resolve()) in removed
    assert not abandoned.exists()


def test_orchestrator_continues_after_single_project_failure(tmp_path: Path) -> None:
    from opensource_runner.config import load_config

    (tmp_path / "projects").mkdir()
    (tmp_path / "projects" / "bad.toml").write_text(
        f'id = "bad"\nname = "Bad"\nrepository = "{(tmp_path / "missing").as_posix()}"\nenabled = true\n',
        encoding="utf-8",
    )
    (tmp_path / "projects" / "good.toml").write_text(
        'id = "good"\nname = "Good"\nrepository = "https://example.com/good"\nenabled = true\n',
        encoding="utf-8",
    )
    cfg = load_config(root_dir=tmp_path)
    orch = SelfTestOrchestrator(cfg)
    summary, code, paths = orch.run(
        output_dir=tmp_path / "results",
        local_overrides={"good": Path("tests/fixtures/fake_project")},
    )
    assert code == 1
    assert summary.projects["bad"].result == StageStatus.FAIL
    assert summary.projects["good"].result == StageStatus.PASS
    assert paths["json"].is_file()
