"""Integration tests verifying Phases 2-4 and isolation across all four project archetypes."""

from __future__ import annotations

import subprocess
from pathlib import Path

from typer.testing import CliRunner

from opensource_runner.cli.app import app

runner = CliRunner()

MIT_TEXT = (
    "MIT License\n\nCopyright (c) 2024 Example Author\n\n"
    "Permission is hereby granted, free of charge, to any person obtaining a copy "
    "of this software and associated documentation files.\n"
)


def _init_git_repo(repo_dir: Path, files: dict[str, bytes | str], branch: str = "main") -> str:
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", branch], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo_dir, check=True)
    for rel, content in files.items():
        p = repo_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_bytes(content.encode("utf-8"))
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"], cwd=repo_dir, check=True, capture_output=True
    )
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_dir, text=True).strip()


def test_builtin_registry_lists_all_four_projects() -> None:
    r = runner.invoke(app, ["list"])
    assert r.exit_code == 0
    for pid in ("flappy", "flask-inventory-management", "flaskblog", "flatnotes"):
        assert pid in r.stdout


def test_all_three_additional_project_archetypes_end_to_end(tmp_path: Path) -> None:
    bot_root = tmp_path / "bot"
    (bot_root / "projects").mkdir(parents=True)

    # Phase 2: flask-inventory-management (CRLF + AST flask import + SQLite binary + JPEG)
    inv_repo = tmp_path / "remote-inv"
    _init_git_repo(
        inv_repo,
        {
            "LICENSE": MIT_TEXT,
            "flaskmain.py": b"from flask import Flask\r\nimport sqlite3\r\napp = Flask(__name__)\r\nif __name__ == '__main__':\r\n    app.run(debug=True)\r\n",
            "templates/index.html": "<h1>Inventory</h1>\r\n",
            "flaskDB.db": b"SQLite format 3\x00" + b"\x00" * 64,
            "static/image/image1.jpg": b"\xff\xd8\xff\xe0\x00\x10JFIF",
        },
        branch="main",
    )
    (bot_root / "projects" / "flask-inventory-management.toml").write_text(
        f'id = "flask-inventory-management"\nname = "Flask Inventory Management"\nrepository = "{inv_repo.as_posix()}"\nrevision = "auto"\nenabled = true\n',
        encoding="utf-8",
    )

    # Phase 3: flaskblog (nested app/pyproject.toml + uv.lock + UTF-8 multibyte + binary PNG)
    blog_repo = tmp_path / "remote-blog"
    _init_git_repo(
        blog_repo,
        {
            "LICENSE": MIT_TEXT,
            ".env.example": "APP_PORT=1283\nAPP_HOST=localhost\n",
            "app/pyproject.toml": '[project]\nname = "flaskBlog"\nrequires-python = ">=3.10"\ndependencies = ["flask==3.1.3"]\n',
            "app/uv.lock": "version = 1\n",
            "app/app.py": "from flask import Flask\napp = Flask(__name__)\nif __name__ == '__main__':\n    app.run()\n",
            "app/translations/hi.json": '{"greeting": "नमस्ते दुनिया"}\n',
            "images/LogoSmall.png": b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
        },
        branch="main",
    )
    (bot_root / "projects" / "flaskblog.toml").write_text(
        f'id = "flaskblog"\nname = "FlaskBlog"\nrepository = "{blog_repo.as_posix()}"\nrevision = "auto"\nenabled = true\n',
        encoding="utf-8",
    )

    # Phase 4: flatnotes (develop branch + polyglot Vue/Vite + FastAPI/Uvicorn + Dockerfile + OFL)
    notes_repo = tmp_path / "remote-flatnotes"
    _init_git_repo(
        notes_repo,
        {
            "LICENSE": MIT_TEXT,
            "Dockerfile": "FROM python:3.13-slim\n",
            "package.json": '{"name":"flatnotes","scripts":{"build":"vite build"},"dependencies":{"vue":"3.5.40"}}',
            "package-lock.json": '{"lockfileVersion": 3}\n',
            "pyproject.toml": '[project]\nname = "flatnotes"\nrequires-python = ">=3.13,<3.14"\ndependencies = ["fastapi==0.141.1"]\n',
            "uv.lock": "version = 1\n",
            "server/main.py": "from fastapi import FastAPI\napp = FastAPI()\n",
            "client/assets/fonts/Poppins/OFL.txt": "SIL Open Font License\n",
            "client/assets/favicon.ico": b"\x00\x00\x01\x00\x01\x00",
        },
        branch="develop",
    )
    (bot_root / "projects" / "flatnotes.toml").write_text(
        f'id = "flatnotes"\nname = "flatnotes"\nrepository = "{notes_repo.as_posix()}"\nrevision = "auto"\nenabled = true\n',
        encoding="utf-8",
    )

    expected_checks = {
        "flask-inventory-management": ("flaskmain.py", "5000"),
        "flaskblog": ("app.py", "1283"),
        "flatnotes": ("uvicorn", "8080"),
    }

    for pid, (cmd_token, port_token) in expected_checks.items():
        r = runner.invoke(app, ["select", pid, "--root", str(bot_root)])
        assert r.exit_code == 0

        r = runner.invoke(app, ["prepare", "--yes", "--root", str(bot_root)])
        assert r.exit_code == 0, r.stdout
        assert "LICENSE REVIEW REQUIRED" not in r.stdout
        assert (bot_root / "workspace" / pid / ".provenance" / "run-config.json").is_file()

        r = runner.invoke(app, ["type", "--input-backend", "mock", "--root", str(bot_root)])
        assert r.exit_code == 0, r.stdout

        r = runner.invoke(app, ["verify", "--root", str(bot_root)])
        assert r.exit_code == 0, r.stdout
        assert "TYPING AND VERIFICATION COMPLETE" in r.stdout

        r = runner.invoke(app, ["run", "--dry-run", "--root", str(bot_root)])
        assert r.exit_code == 0, r.stdout
        flat_out = "".join(r.stdout.splitlines())
        assert cmd_token in flat_out
        assert port_token in flat_out

    # Confirm workspaces are strictly isolated
    assert (bot_root / "workspace" / "flask-inventory-management" / "flaskmain.py").is_file()
    assert not (bot_root / "workspace" / "flask-inventory-management" / "server").exists()
    assert (bot_root / "workspace" / "flaskblog" / "app" / "translations" / "hi.json").is_file()
    assert (bot_root / "workspace" / "flatnotes" / "server" / "main.py").is_file()


def test_local_source_folder_import_pipeline(tmp_path: Path) -> None:
    local_dir = tmp_path / "my-local-app"
    local_dir.mkdir()
    (local_dir / "LICENSE").write_text(MIT_TEXT, encoding="utf-8")
    (local_dir / "main.py").write_text("print('from local folder')\n", encoding="utf-8")

    bot_root = tmp_path / "bot"
    (bot_root / "projects").mkdir(parents=True)
    (bot_root / "projects" / "local-demo.toml").write_text(
        'id = "local-demo"\nname = "Local Demo"\nrepository = "local"\nenabled = true\n',
        encoding="utf-8",
    )

    assert runner.invoke(app, ["select", "local-demo", "--root", str(bot_root)]).exit_code == 0
    r = runner.invoke(
        app,
        ["prepare", "--yes", "--local-source", str(local_dir), "--root", str(bot_root)],
    )
    assert r.exit_code == 0, r.stdout
    assert "local-" in r.stdout
    assert (bot_root / "workspace" / "local-demo" / ".provenance" / "run-config.json").is_file()

    r = runner.invoke(app, ["type", "--input-backend", "mock", "--root", str(bot_root)])
    assert r.exit_code == 0, r.stdout

    r = runner.invoke(app, ["verify", "--root", str(bot_root)])
    assert r.exit_code == 0, r.stdout
    assert 'Enter "run" when you are ready.' in " ".join(r.stdout.split())
