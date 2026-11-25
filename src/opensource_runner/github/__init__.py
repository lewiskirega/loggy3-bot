"""GitHub repository retrieval, commit pinning, and immutable source-cache management."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from opensource_runner.models import (
    RepositoryProvenance,
    SourceFileEntry,
    SourceManifest,
)
from opensource_runner.security import ensure_within_directory, force_rmtree

KNOWN_BINARY_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".bmp",
        ".tiff",
        ".mp3",
        ".mp4",
        ".wav",
        ".ogg",
        ".avi",
        ".mov",
        ".sqlite",
        ".sqlite3",
        ".db",
        ".zip",
        ".tar",
        ".gz",
        ".bz2",
        ".xz",
        ".7z",
        ".pdf",
        ".ttf",
        ".otf",
        ".woff",
        ".woff2",
        ".eot",
        ".pyc",
        ".pyo",
        ".so",
        ".dll",
        ".exe",
        ".bin",
    }
)


class GitRetrievalError(RuntimeError):
    """Raised when Git metadata resolution or repository cloning fails."""


@dataclass(frozen=True)
class RemoteRevision:
    repository: str
    branch: str
    commit: str


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def classify_file(path: Path) -> Literal["text", "binary"]:
    """Classify a file as text or binary using extension + NUL + full UTF-8 validation."""
    if path.suffix.lower() in KNOWN_BINARY_EXTENSIONS:
        return "binary"
    raw = path.read_bytes()
    if b"\x00" in raw:
        return "binary"
    try:
        raw.decode("utf-8")
        return "text"
    except UnicodeDecodeError:
        return "binary"


class GitHubRetriever:
    """Retrieves repositories via Git CLI into an immutable source-cache/<id>/<commit>/."""

    def __init__(self, git_bin: str | None = None) -> None:
        self.git_bin = git_bin or shutil.which("git") or "git"

    def _run_git(
        self, args: list[str], *, cwd: Path | None = None, timeout: int = 180
    ) -> subprocess.CompletedProcess[str]:
        cmd = [self.git_bin, *args]
        try:
            result = subprocess.run(
                cmd,
                cwd=str(cwd) if cwd else None,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise GitRetrievalError("Git CLI was not found on PATH.") from exc
        except subprocess.TimeoutExpired as exc:
            raise GitRetrievalError(f"Git command timed out: {' '.join(cmd)}") from exc

        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip()
            raise GitRetrievalError(f"Git command failed ({' '.join(cmd)}): {stderr}")
        return result

    def resolve_remote_revision(self, repository: str, revision: str = "auto") -> RemoteRevision:
        """Resolve default branch and exact commit SHA using `git ls-remote`."""
        if revision != "auto":
            res = self._run_git(["ls-remote", repository, revision])
            lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]
            if lines:
                sha, ref = lines[0].split(None, 1)
                branch = ref.removeprefix("refs/heads/").removeprefix("refs/tags/")
                return RemoteRevision(repository=repository, branch=branch, commit=sha)
            # Assume explicit 40-char commit SHA
            if len(revision) == 40 and all(c in "0123456789abcdefABCDEF" for c in revision):
                return RemoteRevision(
                    repository=repository, branch="detached", commit=revision.lower()
                )
            raise GitRetrievalError(
                f"Could not resolve revision '{revision}' in repository '{repository}'."
            )

        res = self._run_git(["ls-remote", "--symref", repository, "HEAD"])
        branch = "main"
        commit = ""
        for raw_line in res.stdout.splitlines():
            line = raw_line.strip()
            if line.startswith("ref:"):
                parts = line.split()
                if len(parts) >= 2 and parts[1].startswith("refs/heads/"):
                    branch = parts[1].removeprefix("refs/heads/")
            elif line.endswith("\tHEAD") or line.endswith(" HEAD"):
                commit = line.split()[0]

        if not commit:
            raise GitRetrievalError(
                f"Could not determine HEAD commit for repository '{repository}'."
            )
        return RemoteRevision(repository=repository, branch=branch, commit=commit)

    def retrieve_to_cache(
        self,
        *,
        project_id: str,
        project_name: str,
        repository: str,
        source_cache_root: Path,
        revision: str = "auto",
    ) -> tuple[Path, RepositoryProvenance, SourceManifest]:
        """Clone repository into immutable source-cache/<project-id>/<commit>/."""
        remote_rev = self.resolve_remote_revision(repository, revision=revision)
        cache_dir = (source_cache_root / project_id / remote_rev.commit).resolve()
        ensure_within_directory(source_cache_root, cache_dir)

        if not cache_dir.exists():
            staging_dir = source_cache_root / project_id / f".tmp-{remote_rev.commit}"
            if staging_dir.exists():
                force_rmtree(staging_dir)
            staging_dir.parent.mkdir(parents=True, exist_ok=True)
            try:
                if remote_rev.branch != "detached":
                    self._run_git(
                        [
                            "clone",
                            "--depth",
                            "1",
                            "--branch",
                            remote_rev.branch,
                            repository,
                            str(staging_dir),
                        ]
                    )
                else:
                    self._run_git(["clone", repository, str(staging_dir)])
                    self._run_git(["checkout", remote_rev.commit], cwd=staging_dir)

                checked_out_sha = self._run_git(
                    ["rev-parse", "HEAD"], cwd=staging_dir
                ).stdout.strip()
                if checked_out_sha != remote_rev.commit:
                    # Fallback full fetch for exact commit pinning
                    self._run_git(["fetch", "--unshallow"], cwd=staging_dir)
                    self._run_git(["checkout", remote_rev.commit], cwd=staging_dir)

                # Remove .git directory so source-cache contains pure source files only
                git_meta = staging_dir / ".git"
                if git_meta.exists():
                    force_rmtree(git_meta)

                staging_dir.replace(cache_dir)
            except Exception:
                if staging_dir.exists():
                    force_rmtree(staging_dir)
                raise

        source_origin = "GitHub" if "github.com" in repository.lower() else "Local/Git"
        provenance = RepositoryProvenance(
            project_id=project_id,
            project_name=project_name,
            repository=repository,
            branch=remote_rev.branch,
            commit=remote_rev.commit,
            source_origin=source_origin,
        )
        manifest = build_source_manifest(project_id, remote_rev.commit, cache_dir)
        return cache_dir, provenance, manifest

    def import_local_folder_to_cache(
        self,
        *,
        project_id: str,
        project_name: str,
        local_source_dir: Path,
        source_cache_root: Path,
    ) -> tuple[Path, RepositoryProvenance, SourceManifest]:
        """Copy a user-supplied local source folder into an immutable source-cache snapshot."""
        src = local_source_dir.expanduser().resolve()
        if not src.is_dir():
            raise GitRetrievalError(f"Local source folder does not exist: '{src}'")

        # Compute deterministic tree hash for immutable snapshot ID
        tree_hasher = hashlib.sha256()
        for p in sorted(src.rglob("*")):
            if not p.is_file() or ".git" in p.parts:
                continue
            ensure_within_directory(src, p)
            rel = p.relative_to(src).as_posix()
            tree_hasher.update(rel.encode("utf-8"))
            tree_hasher.update(compute_sha256(p).encode("ascii"))
        snapshot_id = f"local-{tree_hasher.hexdigest()[:16]}"

        cache_dir = (source_cache_root / project_id / snapshot_id).resolve()
        ensure_within_directory(source_cache_root, cache_dir)
        if not cache_dir.exists():
            staging = source_cache_root / project_id / f".tmp-{snapshot_id}"
            if staging.exists():
                force_rmtree(staging)
            staging.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(
                src, staging, ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv")
            )
            staging.replace(cache_dir)

        provenance = RepositoryProvenance(
            project_id=project_id,
            project_name=project_name,
            repository=str(src),
            branch="local",
            commit=snapshot_id,
            source_origin="Local Directory",
        )
        manifest = build_source_manifest(project_id, snapshot_id, cache_dir)
        return cache_dir, provenance, manifest


def build_source_manifest(project_id: str, commit: str, source_dir: Path) -> SourceManifest:
    """Walk an immutable source directory and hash every file."""
    entries: list[SourceFileEntry] = []
    text_count = 0
    binary_count = 0
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file() or ".git" in path.parts:
            continue
        ensure_within_directory(source_dir, path)
        rel = path.relative_to(source_dir).as_posix()
        ftype = classify_file(path)
        if ftype == "text":
            text_count += 1
        else:
            binary_count += 1
        entries.append(
            SourceFileEntry(
                relative_path=rel,
                file_type=ftype,
                size_bytes=path.stat().st_size,
                sha256=compute_sha256(path),
            )
        )
    return SourceManifest(
        project_id=project_id,
        commit=commit,
        total_files=len(entries),
        text_files=text_count,
        binary_files=binary_count,
        files=entries,
    )
