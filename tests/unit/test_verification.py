"""Unit tests for file-level and project-level verification."""

from __future__ import annotations

from pathlib import Path

from opensource_runner.verification import verify_project, verify_single_file


def test_verify_identical_text_and_binary(tmp_path: Path) -> None:
    src = tmp_path / "src"
    ws = tmp_path / "ws"
    src.mkdir()
    ws.mkdir()

    (src / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (ws / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (src / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x01")
    (ws / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x01")
    # Provenance directory in workspace should be ignored
    (ws / ".provenance").mkdir()
    (ws / ".provenance" / "repository.json").write_text("{}", encoding="utf-8")

    report = verify_project("demo", "sha1", src, ws)
    assert report.verified is True
    assert report.verified_files == 2
    methods = {r.relative_path: r.reproduction_method for r in report.file_results}
    assert methods["app.py"] == "keyboard reproduction"
    assert methods["logo.png"] == "verified binary copy"


def test_verify_detects_missing_modified_and_unexpected(tmp_path: Path) -> None:
    src = tmp_path / "src"
    ws = tmp_path / "ws"
    src.mkdir()
    ws.mkdir()

    (src / "a.py").write_text("x = 1\n", encoding="utf-8")
    (src / "b.py").write_text("y = 2\n", encoding="utf-8")
    (src / "img.png").write_bytes(b"\x89PNG\x00\x01")

    (ws / "a.py").write_text("x = 999\n", encoding="utf-8")  # modified
    # b.py missing
    (ws / "img.png").write_bytes(b"\x89PNG\x00\x02")  # binary hash mismatch
    (ws / "extra.py").write_text("extra\n", encoding="utf-8")  # unexpected

    report = verify_project("demo", "sha1", src, ws)
    assert report.verified is False
    assert report.missing_files == ["b.py"]
    assert report.unexpected_files == ["extra.py"]
    assert "a.py" in report.text_mismatches
    assert "img.png" in report.binary_mismatches
    assert "img.png" in report.hash_mismatches


def test_verify_single_file_missing(tmp_path: Path) -> None:
    src_file = tmp_path / "a.txt"
    src_file.write_text("hello", encoding="utf-8")
    res = verify_single_file("a.txt", src_file, tmp_path / "missing.txt", "text")
    assert res.verified is False
    assert "Missing" in res.reason
