"""Controlled temporary-workspace reproduction diagnostic test (Section 11 & 12)."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from opensource_runner.testing.filesystem_guard import (
    mark_harness_directory,
    safe_remove_harness_directory,
)
from opensource_runner.typing.platforms import InputBackendError, InputController
from opensource_runner.typing.vscode import VSCodeController, VSCodeNotFoundError

CONTROLLED_TEST_PYTHON = (
    "def main():\n"
    '    print("OpenSource Runner typing test")\n'
    "\n"
    'if __name__ == "__main__":\n'
    "    main()\n"
)


@dataclass
class ControlledTypingReport:
    vscode_launch: str = "NOT TESTED"
    workspace_opening: str = "NOT TESTED"
    file_opening: str = "NOT TESTED"
    window_activation: str = "NOT TESTED"
    editor_focus: str = "NOT TESTED"
    keyboard_input: str = "NOT TESTED"
    file_saving: str = "NOT TESTED"
    exact_content_verification: str = "NOT TESTED"
    overall: str = "FAIL"
    detail: str = ""


def run_controlled_typing_test(
    input_controller: InputController,
    vscode_controller: VSCodeController,
    *,
    manual_focus_confirm: Callable[[Path, str], bool] | None = None,
) -> ControlledTypingReport:
    """Run a controlled temporary-workspace typing test without modifying any user project."""
    report = ControlledTypingReport()
    health = input_controller.check_availability()
    if not health.available:
        report.keyboard_input = "UNSUPPORTED"
        report.overall = "UNSUPPORTED"
        report.detail = health.reason
        return report

    tmp_ws = Path(tempfile.mkdtemp(prefix="osr-sandbox-typing-test-")).resolve()
    mark_harness_directory(tmp_ws)
    target_file = tmp_ws / "typing_test.py"
    try:
        try:
            vscode_controller.open_workspace(tmp_ws, initial_file=target_file)
            report.vscode_launch = "PASS"
            report.workspace_opening = "PASS"
            report.file_opening = "PASS"
        except VSCodeNotFoundError as exc:
            report.vscode_launch = "FAIL"
            report.overall = "FAIL"
            report.detail = str(exc)
            return report

        input_controller.prepare_target_file(target_file)
        focus = input_controller.verify_focus("VS Code", tmp_ws)
        if focus.verified:
            report.window_activation = "PASS"
            report.editor_focus = "PASS"
        elif manual_focus_confirm is not None and manual_focus_confirm(tmp_ws, focus.reason):
            report.window_activation = "PASS"
            report.editor_focus = "PASS"
        else:
            report.window_activation = "UNSUPPORTED"
            report.editor_focus = "UNSUPPORTED"
            report.overall = "UNSUPPORTED"
            report.detail = focus.reason
            return report

        try:
            for ch in CONTROLLED_TEST_PYTHON:
                input_controller.type_character(ch)
            report.keyboard_input = "PASS"
            input_controller.send_hotkey("ctrl", "s")
            report.file_saving = "PASS"
        except InputBackendError as exc:
            report.keyboard_input = "FAIL"
            report.overall = "FAIL"
            report.detail = str(exc)
            return report

        actual_bytes = target_file.read_bytes() if target_file.is_file() else b""
        expected_bytes = CONTROLLED_TEST_PYTHON.encode("utf-8")
        if actual_bytes == expected_bytes:
            report.exact_content_verification = "PASS"
            report.overall = "PASS"
            report.detail = "Exact byte-for-byte match verified."
        else:
            report.exact_content_verification = "FAIL"
            report.overall = "FAIL"
            report.detail = (
                f"Saved file mismatch (expected {len(expected_bytes)} bytes, "
                f"got {len(actual_bytes)} bytes)."
            )
        return report
    finally:
        safe_remove_harness_directory(tmp_ws)

