"""Integration test exercising the complete Phase 1 Flappy CLI pipeline."""

from __future__ import annotations

import subprocess
from pathlib import Path

from typer.testing import CliRunner

from opensource_runner.cli.app import app

runner = CliRunner()


def _create_flappy_fixture_repo(repo_dir: Path) -> str:
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo_dir, check=True)
    (repo_dir / "Flappy.py").write_text(
        "import random\nimport tkinter as tk\n\ndef main():\n    pass\n\nif __name__ == '__main__':\n    main()\n",
        encoding="utf-8",
    )
    (repo_dir / "README.md").write_text(
        "# Flappy\n\nLicense\nMIT — free to use, modify, and share.\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"], cwd=repo_dir, check=True, capture_output=True
    )
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_dir, text=True).strip()


def test_end_to_end_flappy_pipeline(tmp_path: Path) -> None:
    origin = tmp_path / "remote-flappy"
    commit_sha = _create_flappy_fixture_repo(origin)

    bot_root = tmp_path / "bot"
    (bot_root / "projects").mkdir(parents=True)
    (bot_root / "projects" / "flappy.toml").write_text(
        f'id = "flappy"\nname = "Flappy"\nrepository = "{origin.as_posix()}"\nrevision = "auto"\nenabled = true\n',
        encoding="utf-8",
    )

    # 1. list
    r = runner.invoke(app, ["list", "--root", str(bot_root)])
    assert r.exit_code == 0
    assert "flappy" in r.stdout

    # 2. select
    r = runner.invoke(app, ["select", "flappy", "--root", str(bot_root)])
    assert r.exit_code == 0
    assert "third-party GitHub repository" in r.stdout
    assert "DISCOVERED" in r.stdout

    # 3a. prepare declined interactively aborts safely
    r = runner.invoke(app, ["prepare", "--root", str(bot_root)], input="n\n")
    assert r.exit_code != 0
    assert "RETRIEVAL APPROVAL REQUIRED" in r.stdout

    # 3b. prepare with approval (missing LICENSE triggers review gate)
    r = runner.invoke(app, ["prepare", "--yes", "--root", str(bot_root)])
    assert r.exit_code == 0
    assert commit_sha in r.stdout
    assert "LICENSE REVIEW REQUIRED" in r.stdout
    assert (bot_root / "workspace" / "flappy" / ".provenance" / "run-config.json").is_file()

    # 4. type must be blocked until license approved
    r = runner.invoke(app, ["type", "--input-backend", "mock", "--root", str(bot_root)])
    assert r.exit_code != 0
    assert "LICENSE REVIEW REQUIRED" in r.stdout

    # 5. approve license via prepare --approve-license
    r = runner.invoke(app, ["prepare", "--approve-license", "--root", str(bot_root)])
    assert r.exit_code == 0
    assert "LICENSE REVIEW REQUIRED" not in r.stdout

    # 6. dry-run type
    r = runner.invoke(app, ["type", "--dry-run", "--root", str(bot_root)])
    assert r.exit_code == 0
    assert "DRY RUN" in r.stdout
    assert "2 text files" in r.stdout

    # 7. type with mock backend
    r = runner.invoke(app, ["type", "--input-backend", "mock", "--root", str(bot_root)])
    assert r.exit_code == 0
    assert "Reproduction finished (2/2 files)" in r.stdout

    # 8. run before verify must be blocked
    r = runner.invoke(app, ["run", "--root", str(bot_root)])
    assert r.exit_code != 0
    assert "VERIFIED / READY_TO_RUN" in r.stdout

    # 9. verify -> READY_TO_RUN
    r = runner.invoke(app, ["verify", "--root", str(bot_root)])
    assert r.exit_code == 0
    assert "TYPING AND VERIFICATION COMPLETE" in r.stdout
    assert "NOT STARTED" in r.stdout

    # 10. run --dry-run
    r = runner.invoke(app, ["run", "--dry-run", "--root", str(bot_root)])
    assert r.exit_code == 0
    assert "Flappy.py" in "".join(r.stdout.splitlines())

    # 11. status
    r = runner.invoke(app, ["status", "--root", str(bot_root)])
    assert r.exit_code == 0
    assert "READY_TO_RUN" in r.stdout
