"""Unit tests for license inspection and security boundary guards."""

from __future__ import annotations

from pathlib import Path

import pytest

from opensource_runner.licensing import inspect_license, write_license_reports
from opensource_runner.models import LicenseStatus
from opensource_runner.security import (
    SecurityError,
    assert_not_in_source_cache,
    redact_secrets,
    validate_safe_relative_path,
)


def test_missing_license_requires_review(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Flappy\nLicense\nMIT — free to use.\n", encoding="utf-8")
    report = inspect_license("flappy", "Flappy", tmp_path)
    assert report.status == LicenseStatus.REVIEW_REQUIRED
    assert report.user_approved is False
    assert report.license_file is None

    json_p, md_p = write_license_reports(tmp_path / ".provenance", report)
    assert json_p.is_file() and md_p.is_file()


def test_mit_license_auto_approved(tmp_path: Path) -> None:
    (tmp_path / "LICENSE").write_text(
        "MIT License\n\nCopyright (c) 2024 Author\n\n"
        "Permission is hereby granted, free of charge, to any person obtaining a copy...",
        encoding="utf-8",
    )
    report = inspect_license("demo", "Demo", tmp_path)
    assert report.status == LicenseStatus.APPROVED
    assert report.detected_license == "MIT"
    assert report.user_approved is True


def test_path_traversal_and_source_cache_protection(tmp_path: Path) -> None:
    ws = tmp_path / "workspace" / "demo"
    cache = tmp_path / "source-cache"
    ws.mkdir(parents=True)
    cache.mkdir(parents=True)

    with pytest.raises(SecurityError):
        validate_safe_relative_path(ws, "../../etc/passwd")

    with pytest.raises(SecurityError):
        assert_not_in_source_cache(cache / "demo" / "abc" / "file.py", cache)


def test_secret_redaction() -> None:
    fake_tok = "ghp_" + "a" * 30  # gitleaks:allow
    msg = f"SMTP_PASSWORD=syntheticpass123 token={fake_tok}"
    redacted = redact_secrets(msg)
    assert "syntheticpass123" not in redacted
    assert fake_tok not in redacted
