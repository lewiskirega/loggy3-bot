"""Automated disposable sandbox test harness for OpenSource Runner."""

from opensource_runner.testing.orchestrator import SelfTestOrchestrator
from opensource_runner.testing.report import render_summary_text
from opensource_runner.testing.sandbox import DisposableSandbox, cleanup_abandoned_sandboxes

__all__ = [
    "DisposableSandbox",
    "SelfTestOrchestrator",
    "cleanup_abandoned_sandboxes",
    "render_summary_text",
]
