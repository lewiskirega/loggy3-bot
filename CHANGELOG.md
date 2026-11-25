# Changelog

All notable changes to **OpenSource Runner** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-11-25

### Added
- Built-in project registry supporting `flappy`, `flask-inventory-management`, `flaskblog`, and `flatnotes`.
- GitHub retrieval with exact branch/commit SHA pinning, immutable `source-cache/`, and local source folder import (`--local-source`).
- License inspection and approval gating with `.provenance/license-report.json` and `LICENSE-REPORT.md`.
- Multi-stack project inspection (Python, Node.js, PHP, polyglot, Docker/Podman) and `.provenance/run-config.json`.
- Cross-platform `InputController` abstraction (`WindowsInputController`, `LinuxX11InputController`, `LinuxWaylandInputController`, `MockInputController`) with dynamic VS Code discovery and focus protection.
- Per-file and full-project verification (content diff + SHA-256) and atomic checkpoint/resume/pause/stop recovery.
- Approval-gated isolated execution (`PythonRuntime`, `NodeRuntime`, `PhpRuntime`, `ContainerRuntime`) with command validation.
- Full CLI including `doctor`, `clean`, `version`, and `--dry-run` support.
- GitHub Actions CI/CD workflows (`ci.yml`, `security.yml`, `build.yml`, `release.yml`), issue/PR templates, and Windows/Linux documentation.

