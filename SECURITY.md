# Security Policy

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Instead, report security issues privately via GitHub Security Advisories (or directly to the repository maintainers) with:

- A clear description of the vulnerability and affected component
- Steps to reproduce or a minimal proof of concept
- Any suggested mitigation

We will acknowledge receipt and work on a coordinated fix before public disclosure.

## Security Guarantees & Design Boundaries

- **Untrusted third-party code**: Retrieved GitHub repositories are never executed automatically during `prepare`, `type`, or `verify`.
- **Explicit execution & dependency approval**: `opensource-runner run` requires verified state (`READY_TO_RUN`) and explicit user approval before installing dependencies.
- **No shell injection**: Subprocess commands are validated through `validate_command_argv` and invoked with structured `argv` lists (`shell=False`).
- **Least privilege**: The bot does not require root/administrator privileges and warns if run as UID 0.
- **Secret hygiene**: Potential tokens, passwords, and API keys are redacted from logs; secrets are never written into checkpoints or `.provenance/run-config.json`.
- **Immutable source cache & workspace boundaries**: Path traversal (`..`) and out-of-tree symlinks are rejected.
