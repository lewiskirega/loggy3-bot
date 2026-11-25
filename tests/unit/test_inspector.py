"""Unit tests for multi-stack project inspection."""

from __future__ import annotations

from pathlib import Path

from opensource_runner.projects.inspector import inspect_project


def test_inspect_python_stdlib_flappy(tmp_path: Path) -> None:
    (tmp_path / "Flappy.py").write_text(
        "import random\nimport tkinter as tk\nif __name__ == '__main__':\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("# Flappy\n", encoding="utf-8")

    report = inspect_project("flappy", "abc123", tmp_path)
    assert report.runtime == "Python"
    assert "tkinter" in report.frameworks
    assert report.dependencies == []
    assert report.entry_point == "Flappy.py"
    assert report.run_command == "python Flappy.py"


def test_inspect_flask_without_requirements(tmp_path: Path) -> None:
    (tmp_path / "flaskmain.py").write_text(
        "from flask import Flask\nimport sqlite3\napp = Flask(__name__)\nif __name__ == '__main__':\n    app.run()\n",
        encoding="utf-8",
    )
    (tmp_path / "flaskDB.db").write_bytes(b"SQLite format 3\x00" + b"\x00" * 32)

    report = inspect_project("flask-inv", "abc123", tmp_path)
    assert report.runtime == "Python"
    assert "Flask" in report.frameworks
    assert "flask" in report.dependencies
    assert "SQLite" in report.database_requirements
    assert "flaskDB.db" in report.binary_assets
    assert report.entry_point == "flaskmain.py"
    assert report.expected_url == "http://127.0.0.1:5000"


def test_inspect_nested_uv_flask_project(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "pyproject.toml").write_text(
        '[project]\nname = "flaskBlog"\nrequires-python = ">=3.10"\ndependencies = ["flask==3.1.3"]\n',
        encoding="utf-8",
    )
    (app_dir / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (app_dir / "app.py").write_text(
        "from flask import Flask\napp = Flask(__name__)\nif __name__ == '__main__':\n    app.run()\n",
        encoding="utf-8",
    )
    (tmp_path / ".env.example").write_text("APP_PORT=1283\nAPP_HOST=localhost\n", encoding="utf-8")

    report = inspect_project("flaskblog", "abc123", tmp_path)
    assert report.runtime == "Python"
    assert "uv" in report.package_managers
    assert report.working_subdir == "app"
    assert report.run_command == "uv run app.py"
    assert report.expected_url == "http://127.0.0.1:1283"
    assert "APP_PORT" in report.env_vars


def test_inspect_nodejs_project(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"name":"demo","scripts":{"build":"vite build","start":"node index.js"},"dependencies":{"vue":"3.5.0"}}',
        encoding="utf-8",
    )
    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
    (tmp_path / "index.js").write_text("console.log('hi');\n", encoding="utf-8")

    report = inspect_project("node-demo", "abc123", tmp_path)
    assert report.runtime == "Node.js"
    assert "npm" in report.package_managers
    assert "Vue" in report.frameworks
    assert "npm ci" in report.setup_commands
    assert report.run_command == "npm start"


def test_inspect_php_project(tmp_path: Path) -> None:
    (tmp_path / "composer.json").write_text(
        '{"require":{"monolog/monolog":"^3.0"}}', encoding="utf-8"
    )
    (tmp_path / "index.php").write_text("<?php echo 'ok';", encoding="utf-8")

    report = inspect_project("php-demo", "abc123", tmp_path)
    assert report.runtime == "PHP"
    assert "composer" in report.package_managers
    assert report.entry_point == "index.php"
    assert report.run_command == "php -S 127.0.0.1:8000 -t ."


def test_inspect_polyglot_flatnotes_style(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"name":"flatnotes","scripts":{"build":"vite build"},"dependencies":{"vue":"3.5.40"}}',
        encoding="utf-8",
    )
    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="flatnotes"\nrequires-python=">=3.13,<3.14"\ndependencies=["fastapi==0.141.1"]\n',
        encoding="utf-8",
    )
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (tmp_path / "Dockerfile").write_text("FROM python:3.13-slim\n", encoding="utf-8")
    server = tmp_path / "server"
    server.mkdir()
    (server / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8"
    )

    report = inspect_project("flatnotes", "abc123", tmp_path)
    assert report.runtime == "Python+Node.js"
    assert "FastAPI" in report.frameworks
    assert "Vue" in report.frameworks
    assert "Dockerfile" in report.docker_files
    assert report.expected_url == "http://127.0.0.1:8080"


def test_inspect_unknown_empty_project(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("plain text only\n", encoding="utf-8")
    report = inspect_project("unknown", "abc123", tmp_path)
    assert report.runtime == "UNKNOWN"
    assert report.run_command is None
