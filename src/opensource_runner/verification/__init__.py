"""Per-file and full-project verification engine (content diff + SHA-256)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from opensource_runner.github import classify_file, compute_sha256
from opensource_runner.models import FileVerificationResult, ProjectVerificationReport
from opensource_runner.security import ensure_within_directory

IGNORED_WORKSPACE_TOP_DIRS: frozenset[str] = frozenset(
    {
        ".provenance",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".vscode",
        ".git",
    }
)


def verify_single_file(
    relative_path: str,
    source_file: Path,
    workspace_file: Path,
    file_type: Literal["text", "binary"],
) -> FileVerificationResult:
    """Verify a single reproduced file against the immutable source cache."""
    method: Literal["keyboard reproduction", "verified binary copy"] = (
        "keyboard reproduction" if file_type == "text" else "verified binary copy"
    )
    source_hash = compute_sha256(source_file)

    if not workspace_file.is_file():
        return FileVerificationResult(
            relative_path=relative_path,
            file_type=file_type,
            reproduction_method=method,
            verified=False,
            source_sha256=source_hash,
            workspace_sha256=None,
            reason="Missing file in workspace",
        )

    workspace_hash = compute_sha256(workspace_file)
    if file_type == "text":
        src_bytes = source_file.read_bytes()
        ws_bytes = workspace_file.read_bytes()
        if src_bytes != ws_bytes:
            return FileVerificationResult(
                relative_path=relative_path,
                file_type="text",
                reproduction_method="keyboard reproduction",
                verified=False,
                source_sha256=source_hash,
                workspace_sha256=workspace_hash,
                reason="Content mismatch",
            )
    if source_hash != workspace_hash:
        return FileVerificationResult(
            relative_path=relative_path,
            file_type=file_type,
            reproduction_method=method,
            verified=False,
            source_sha256=source_hash,
            workspace_sha256=workspace_hash,
            reason="SHA-256 hash mismatch",
        )

    return FileVerificationResult(
        relative_path=relative_path,
        file_type=file_type,
        reproduction_method=method,
        verified=True,
        source_sha256=source_hash,
        workspace_sha256=workspace_hash,
        reason="Verified identical",
    )


def _iter_source_files(source_dir: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file() or ".git" in path.parts:
            continue
        ensure_within_directory(source_dir, path)
        files[path.relative_to(source_dir).as_posix()] = path
    return files


def _iter_workspace_files(workspace_dir: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    if not workspace_dir.exists():
        return files
    for path in sorted(workspace_dir.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(workspace_dir).parts
        if rel_parts and rel_parts[0] in IGNORED_WORKSPACE_TOP_DIRS:
            continue
        if "__pycache__" in rel_parts:
            continue
        ensure_within_directory(workspace_dir, path)
        files[path.relative_to(workspace_dir).as_posix()] = path
    return files


def verify_project(
    project_id: str,
    commit: str,
    source_dir: Path,
    workspace_dir: Path,
) -> ProjectVerificationReport:
    """Perform a complete project comparison between source-cache and workspace."""
    source_files = _iter_source_files(source_dir)
    workspace_files = _iter_workspace_files(workspace_dir)

    missing_files: list[str] = []
    unexpected_files: list[str] = []
    modified_files: list[str] = []
    text_mismatches: list[str] = []
    binary_mismatches: list[str] = []
    hash_mismatches: list[str] = []
    file_results: list[FileVerificationResult] = []
    verified_count = 0

    for rel_path, src_path in source_files.items():
        ftype = classify_file(src_path)
        ws_path = workspace_dir / rel_path
        result = verify_single_file(rel_path, src_path, ws_path, ftype)
        file_results.append(result)
        if result.verified:
            verified_count += 1
        else:
            if not ws_path.is_file():
                missing_files.append(rel_path)
            else:
                modified_files.append(rel_path)
                if ftype == "text":
                    text_mismatches.append(rel_path)
                else:
                    binary_mismatches.append(rel_path)
                if result.workspace_sha256 != result.source_sha256:
                    hash_mismatches.append(rel_path)

    for rel_path in workspace_files:
        if rel_path not in source_files:
            unexpected_files.append(rel_path)

    all_ok = (
        len(missing_files) == 0
        and len(unexpected_files) == 0
        and len(modified_files) == 0
        and len(hash_mismatches) == 0
        and verified_count == len(source_files)
    )

    return ProjectVerificationReport(
        project_id=project_id,
        commit=commit,
        verified=all_ok,
        total_files=len(source_files),
        verified_files=verified_count,
        missing_files=missing_files,
        unexpected_files=unexpected_files,
        modified_files=modified_files,
        text_mismatches=text_mismatches,
        binary_mismatches=binary_mismatches,
        hash_mismatches=hash_mismatches,
        file_results=file_results,
    )
