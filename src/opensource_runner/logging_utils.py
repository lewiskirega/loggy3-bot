"""Logging utilities with automatic secret redaction."""

from __future__ import annotations

import logging
from pathlib import Path

from opensource_runner.security import redact_secrets


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        rendered = super().format(record)
        return redact_secrets(rendered)


def get_project_logger(logs_dir: Path, project_id: str | None = None) -> logging.Logger:
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_name = f"opensource_runner.{project_id}" if project_id else "opensource_runner"
    logger = logging.getLogger(log_name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    log_file = logs_dir / (f"{project_id}.log" if project_id else "runner.log")
    expected_path = str(log_file.resolve())

    for handler in list(logger.handlers):
        if isinstance(handler, logging.FileHandler) and handler.baseFilename == expected_path:
            return logger
        logger.removeHandler(handler)
        handler.close()

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(RedactingFormatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(file_handler)
    return logger
