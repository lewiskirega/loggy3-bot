"""Machine-readable (JSON) and human-readable (TXT, HTML) test report generator."""

from __future__ import annotations

import html
import json
from pathlib import Path

from opensource_runner.testing.models import SelfTestSummaryReport


def render_summary_text(summary: SelfTestSummaryReport) -> str:
    """Render the formatted ASCII summary table."""
    lines: list[str] = [
        "========================================",
        "OpenSource Runner Self-Test",
        "========================================",
        f"Platform: {summary.runner.os_pretty_name} ({summary.runner.architecture})",
        f"Python:   {summary.runner.python}",
        f"Display:  {summary.runner.display_server}",
        f"Sandbox:  {summary.runner.container_engine or 'isolated-tempdir'}",
        "",
    ]
    for label, stage in summary.core_stages.items():
        lines.append(f"{label}: {stage.status.value}")
        if stage.message:
            lines.append(f"  {stage.message}")
    lines.extend(["", "----------------------------------------", "Projects", ""])
    if not summary.projects:
        lines.append("  (none executed)")
    for pid, proj in summary.projects.items():
        lines.append(f"{proj.project_name} ({pid}): {proj.result.value}")
        lines.append(
            f"  commit={proj.commit_sha or 'N/A'} runtime={proj.runtime} "
            f"deps={proj.dependencies_status.value} exec={proj.execution_status.value} "
            f"health={proj.healthcheck_status.value} cleanup={proj.cleanup_status.value}"
        )
    lines.extend(["", "----------------------------------------", "Security Checks", ""])
    for label, stage in summary.security_stages.items():
        lines.append(f"{label}: {stage.status.value}")
    lines.extend(
        [
            "",
            "----------------------------------------",
            f"FINAL RESULT: {summary.result.value}",
            "========================================",
        ]
    )
    return "\n".join(lines) + "\n"


def render_summary_html(summary: SelfTestSummaryReport) -> str:
    """Render a self-contained HTML summary report."""
    rows: list[str] = []
    for label, st in summary.core_stages.items():
        rows.append(
            f"<tr><td>{html.escape(label)}</td><td><b>{st.status.value}</b></td>"
            f"<td>{html.escape(st.message)}</td></tr>"
        )
    proj_rows: list[str] = []
    for pid, proj in summary.projects.items():
        proj_rows.append(
            f"<tr><td>{html.escape(proj.project_name)} ({html.escape(pid)})</td>"
            f"<td><b>{proj.result.value}</b></td>"
            f"<td>{html.escape(proj.commit_sha or 'N/A')}</td>"
            f"<td>{html.escape(proj.runtime)}</td>"
            f"<td>{proj.dependencies_status.value}</td>"
            f"<td>{proj.execution_status.value}</td>"
            f"<td>{proj.healthcheck_status.value}</td>"
            f"<td>{proj.cleanup_status.value}</td></tr>"
        )
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<title>OpenSource Runner Self-Test Report</title>"
        "<style>body{font-family:sans-serif;margin:2rem;}table{border-collapse:collapse;width:100%;margin-bottom:1.5rem;}"
        "th,td{border:1px solid #ccc;padding:0.5rem;text-align:left;}th{background:#f4f4f4;}</style>"
        "</head><body>"
        f"<h1>OpenSource Runner Self-Test — {summary.result.value}</h1>"
        f"<p>OS: {html.escape(summary.runner.os_pretty_name)} | Python: {html.escape(summary.runner.python)} "
        f"| Display: {html.escape(summary.runner.display_server)}</p>"
        "<h2>Core Checks</h2><table><tr><th>Stage</th><th>Status</th><th>Details</th></tr>"
        + "".join(rows)
        + "</table><h2>Projects</h2><table><tr><th>Project</th><th>Result</th><th>Commit</th>"
        "<th>Runtime</th><th>Deps</th><th>Exec</th><th>Health</th><th>Cleanup</th></tr>"
        + "".join(proj_rows)
        + "</table></body></html>"
    )


def write_test_reports(
    output_dir: Path,
    summary: SelfTestSummaryReport,
    project_artifacts: dict[str, dict[str, object]],
) -> dict[str, Path]:
    """Write summary.json, summary.txt, summary.html, and per-project reports."""
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "summary.json"
    txt_path = output_dir / "summary.txt"
    html_path = output_dir / "summary.html"

    json_path.write_text(summary.model_dump_json(indent=2), encoding="utf-8")
    txt_path.write_text(render_summary_text(summary), encoding="utf-8")
    html_path.write_text(render_summary_html(summary), encoding="utf-8")

    projects_root = output_dir / "projects"
    for pid, proj in summary.projects.items():
        pdir = projects_root / pid
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / "project-report.json").write_text(proj.model_dump_json(indent=2), encoding="utf-8")
        (pdir / "stdout.log").write_text(proj.stdout_log, encoding="utf-8")
        (pdir / "stderr.log").write_text(proj.stderr_log, encoding="utf-8")
        arts = project_artifacts.get(pid, {})
        for name in ("runtime", "dependencies", "verification", "sandbox"):
            if name in arts:
                (pdir / f"{name}.json").write_text(
                    json.dumps(arts[name], indent=2), encoding="utf-8"
                )

    return {"json": json_path, "txt": txt_path, "html": html_path}
