"""License inspection, provenance report generation, and approval gating."""

from __future__ import annotations

import re
from pathlib import Path

from opensource_runner.models import LicenseReport, LicenseStatus, utc_now

LICENSE_FILENAMES = (
    "LICENSE",
    "LICENSE.md",
    "LICENSE.txt",
    "LICENCE",
    "LICENCE.md",
    "LICENCE.txt",
    "COPYING",
    "COPYING.txt",
)

PERMISSIVE_LICENSES: frozenset[str] = frozenset(
    {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "Unlicense", "0BSD"}
)

COPYRIGHT_RE = re.compile(r"(?im)^.*copyright\s+(?:\(c\)|©)?\s*\d{4}.*$")


def _identify_license_text(text: str) -> str:
    lower = text.lower()
    if "permission is hereby granted, free of charge" in lower and "mit license" in lower:
        return "MIT"
    if (
        "permission is hereby granted, free of charge" in lower
        and 'the software is provided "as is"' in lower
    ):
        return "MIT"
    if "apache license" in lower and "version 2.0" in lower:
        return "Apache-2.0"
    if "redistribution and use in source and binary forms" in lower:
        if "neither the name of" in lower:
            return "BSD-3-Clause"
        return "BSD-2-Clause"
    if "permission to use, copy, modify, and/or distribute this software for any purpose" in lower:
        return "ISC"
    if "gnu general public license" in lower:
        if "version 3" in lower:
            return "GPL-3.0"
        if "version 2" in lower:
            return "GPL-2.0"
        return "GPL"
    if "gnu affero general public license" in lower:
        return "AGPL-3.0"
    if "mozilla public license" in lower:
        return "MPL-2.0"
    return "UNKNOWN"


def _extract_readme_license_mention(readme_text: str) -> str | None:
    lines = readme_text.splitlines()
    for idx, line in enumerate(lines):
        if re.search(r"(?i)license", line):
            snippet = " ".join(
                part.strip() for part in lines[idx : min(idx + 3, len(lines))] if part.strip()
            )
            if snippet:
                return snippet[:200]
    return None


def inspect_license(project_id: str, project_name: str, source_dir: Path) -> LicenseReport:
    """Inspect LICENSE, README, copyright notices, and third-party notices."""
    license_file: Path | None = None
    for candidate in LICENSE_FILENAMES:
        p = source_dir / candidate
        if p.is_file():
            license_file = p
            break

    copyright_notices: list[str] = []
    third_party_notices: list[str] = []
    detected = "UNKNOWN"
    readme_mention: str | None = None

    if license_file is not None:
        text = license_file.read_text(encoding="utf-8", errors="replace")
        detected = _identify_license_text(text)
        for match in COPYRIGHT_RE.findall(text):
            cleaned = match.strip()
            if cleaned and cleaned not in copyright_notices:
                copyright_notices.append(cleaned)

    for readme_name in ("README.md", "README.txt", "README", "readme.md"):
        readme_path = source_dir / readme_name
        if readme_path.is_file():
            readme_text = readme_path.read_text(encoding="utf-8", errors="replace")
            readme_mention = _extract_readme_license_mention(readme_text)
            break

    # Scan for bundled third-party license/notice files (e.g., OFL.txt, NOTICE)
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(source_dir).as_posix()
        if license_file and path == license_file:
            continue
        upper = path.name.upper()
        if upper in {"NOTICE", "NOTICE.TXT", "THIRD_PARTY_LICENSES", "OFL.TXT"} or (
            "LICENSE" in upper and path.parent != source_dir
        ):
            third_party_notices.append(rel)

    if license_file is None:
        status = LicenseStatus.REVIEW_REQUIRED
        if readme_mention:
            reason = (
                "No dedicated LICENSE file was found in the repository root "
                f"(README mentions: '{readme_mention}'). Explicit user approval is required."
            )
        else:
            reason = (
                "No LICENSE file or clear license declaration was found in the repository. "
                "Explicit user approval is required."
            )
        user_approved = False
    elif detected == "UNKNOWN":
        status = LicenseStatus.REVIEW_REQUIRED
        reason = (
            f"Found '{license_file.name}' but could not confidently identify a standard "
            "permissive SPDX license. Explicit user approval is required."
        )
        user_approved = False
    elif detected not in PERMISSIVE_LICENSES:
        status = LicenseStatus.REVIEW_REQUIRED
        reason = (
            f"Detected copyleft or non-permissive license '{detected}' in '{license_file.name}'. "
            "Explicit user approval is required."
        )
        user_approved = False
    else:
        status = LicenseStatus.APPROVED
        reason = f"Standard permissive license '{detected}' verified in '{license_file.name}'."
        user_approved = True

    return LicenseReport(
        project_id=project_id,
        project_name=project_name,
        detected_license=detected,
        license_file=license_file.relative_to(source_dir).as_posix() if license_file else None,
        readme_license_mention=readme_mention,
        copyright_notices=copyright_notices,
        third_party_notices=third_party_notices,
        status=status,
        reason=reason,
        user_approved=user_approved,
        approved_at=utc_now() if user_approved else None,
    )


def write_license_reports(provenance_dir: Path, report: LicenseReport) -> tuple[Path, Path]:
    """Write .provenance/license-report.json and .provenance/LICENSE-REPORT.md."""
    provenance_dir.mkdir(parents=True, exist_ok=True)
    json_path = provenance_dir / "license-report.json"
    md_path = provenance_dir / "LICENSE-REPORT.md"

    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    md_lines = [
        f"# License Report — {report.project_name} (`{report.project_id}`)",
        "",
        f"- **Status**: `{report.status.value}`",
        f"- **Detected License**: `{report.detected_license}`",
        f"- **License File**: `{report.license_file or 'MISSING'}`",
        f"- **User Approved**: `{report.user_approved}`",
        f"- **Reason**: {report.reason}",
        "",
    ]
    if report.readme_license_mention:
        md_lines.extend(["## README License Mention", "", f"> {report.readme_license_mention}", ""])
    if report.copyright_notices:
        md_lines.append("## Copyright Notices")
        md_lines.append("")
        md_lines.extend(f"- {notice}" for notice in report.copyright_notices)
        md_lines.append("")
    if report.third_party_notices:
        md_lines.append("## Third-Party Notices / Bundled Licenses")
        md_lines.append("")
        md_lines.extend(f"- `{item}`" for item in report.third_party_notices)
        md_lines.append("")

    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    return json_path, md_path
