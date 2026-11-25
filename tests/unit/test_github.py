"""Unit tests for GitHub/Git retrieval, branch/commit resolution, and error handling."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from opensource_runner.github import GitHubRetriever, GitRetrievalError


def _make_local_git_repo(repo_dir: Path, branch: str = "main") -> str:
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", branch], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo_dir, check=True)
    (repo_dir / "Flappy.py").write_text("print('hello')\n", encoding="utf-8")
    (repo_dir / "README.md").write_text("# Flappy\nMIT\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True, capture_output=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_dir, text=True).strip()


def test_retrieve_local_repo_resolves_branch_and_commit(tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    expected_sha = _make_local_git_repo(origin, branch="develop")
    cache_root = tmp_path / "source-cache"

    retriever = GitHubRetriever()
    cache_dir, prov, manifest = retriever.retrieve_to_cache(
        project_id="demo",
        project_name="Demo",
        repository=str(origin),
        source_cache_root=cache_root,
    )

    assert prov.branch == "develop"
    assert prov.commit == expected_sha
    assert cache_dir == (cache_root / "demo" / expected_sha).resolve()
    assert not (cache_dir / ".git").exists()
    assert manifest.total_files == 2
    assert manifest.text_files == 2
    assert manifest.binary_files == 0


def test_invalid_repository_raises_error(tmp_path: Path) -> None:
    retriever = GitHubRetriever()
    with pytest.raises(GitRetrievalError):
        retriever.resolve_remote_revision(str(tmp_path / "does-not-exist"))


def test_network_failure_is_reported_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=128,
            stdout="",
            stderr="fatal: unable to access 'https://github.com/org/repo/': Could not resolve host",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    retriever = GitHubRetriever()
    with pytest.raises(GitRetrievalError, match="Could not resolve host"):
        retriever.resolve_remote_revision("https://github.com/org/repo")
