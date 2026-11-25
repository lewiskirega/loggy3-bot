"""Menu definitions for the OpenSource Runner interactive wizard."""

from __future__ import annotations

from opensource_runner.interactive.navigation import MenuChoice

MAIN_MENU_CHOICES: list[MenuChoice] = [
    MenuChoice("prepare", "Prepare a project"),
    MenuChoice("continue", "Continue previous work"),
    MenuChoice("verify", "Verify a project"),
    MenuChoice("run", "Run a project"),
    MenuChoice("safety_tests", "Automated safety tests"),
    MenuChoice("status", "Project status"),
    MenuChoice("settings", "Settings"),
    MenuChoice("exit", "Exit"),
]

PREPARE_ACTION_CHOICES: list[MenuChoice] = [
    MenuChoice("download_inspect", "Download and inspect project"),
    MenuChoice("workspace", "Prepare VS Code workspace"),
    MenuChoice("reproduce", "Reproduce source files"),
    MenuChoice("complete", "Complete preparation"),
    MenuChoice("back", "Go back"),
]

VERIFY_ACTION_CHOICES: list[MenuChoice] = [
    MenuChoice("verify_all", "Verify all files"),
    MenuChoice("verify_modified", "Verify modified files"),
    MenuChoice("verify_commit", "Verify source against original commit"),
    MenuChoice("view_report", "View previous verification report"),
]

SAFETY_TEST_CHOICES: list[MenuChoice] = [
    MenuChoice("test_runner", "Test the OpenSource Runner itself"),
    MenuChoice("test_all", "Test all four projects in isolated sandboxes"),
    MenuChoice("test_one", "Test one selected project"),
    MenuChoice("safety_gate", "Run the complete safety gate"),
    MenuChoice("view_report", "View previous test report"),
]

SETTINGS_CHOICES: list[MenuChoice] = [
    MenuChoice("typing_speed", "Typing speed"),
    MenuChoice("vscode_path", "VS Code executable"),
    MenuChoice("workspace_dir", "Workspace directory"),
    MenuChoice("source_cache_dir", "Source cache directory"),
    MenuChoice("sandbox", "Sandbox configuration"),
    MenuChoice("dependency_approval", "Dependency installation preference"),
    MenuChoice("network_policy", "Network policy"),
    MenuChoice("appearance", "Terminal appearance"),
    MenuChoice("confirmations", "Confirmation preferences"),
]

POST_PREPARE_CHOICES: list[MenuChoice] = [
    MenuChoice("run", "Run project"),
    MenuChoice("view_report", "View verification report"),
    MenuChoice("main_menu", "Return to main menu"),
    MenuChoice("exit", "Exit"),
]
