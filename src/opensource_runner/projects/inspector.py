"""Generic multi-stack project inspector (Python, Node.js, PHP, Docker/Podman)."""

from __future__ import annotations

import ast
import json
import re
import sys
import tomllib
from pathlib import Path

from opensource_runner.github import classify_file
from opensource_runner.models import InspectionReport

STDLIB_MODULES: frozenset[str] = frozenset(getattr(sys, "stdlib_module_names", set()))

IMPORT_TO_PYPI: dict[str, str] = {
    "flask": "flask",
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "django": "django",
    "pygame": "pygame",
    "requests": "requests",
    "sqlalchemy": "sqlalchemy",
    "pydantic": "pydantic",
    "dotenv": "python-dotenv",
    "PIL": "pillow",
    "yaml": "pyyaml",
    "bs4": "beautifulsoup4",
    "cv2": "opencv-python",
}

ENV_VAR_RE = re.compile(r"^([A-Z][A-Z0-9_]{2,})\s*=")
PY_GETENV_RE = re.compile(
    r"""(?:os\.getenv|os\.environ\.get|get_env)\(\s*['"]([A-Z][A-Z0-9_]{2,})['"]"""
)


def _find_files_by_name(source_dir: Path, names: tuple[str, ...], max_depth: int = 2) -> list[Path]:
    found: list[Path] = []
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(source_dir).parts
        if len(rel_parts) > max_depth + 1:
            continue
        if path.name in names:
            found.append(path)
    return found


def _extract_python_imports(py_files: list[Path], source_dir: Path) -> tuple[set[str], list[str]]:
    """Parse Python files via AST to find third-party imports and __main__ entry points."""
    local_modules: set[str] = set()
    for p in py_files:
        local_modules.add(p.stem)
        if p.parent != source_dir:
            local_modules.add(p.parent.name)

    third_party: set[str] = set()
    main_candidates: list[str] = []

    for py_file in py_files:
        try:
            text = py_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(text, filename=str(py_file))
        except SyntaxError:
            continue

        rel = py_file.relative_to(source_dir).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_mod = alias.name.split(".")[0]
                    if root_mod not in STDLIB_MODULES and root_mod not in local_modules:
                        third_party.add(IMPORT_TO_PYPI.get(root_mod, root_mod))
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                root_mod = node.module.split(".")[0]
                if root_mod not in STDLIB_MODULES and root_mod not in local_modules:
                    third_party.add(IMPORT_TO_PYPI.get(root_mod, root_mod))
            elif isinstance(node, ast.If):
                # Detect `if __name__ == "__main__":`
                src_seg = ast.unparse(node.test) if hasattr(ast, "unparse") else ""
                if "__name__" in src_seg and "__main__" in src_seg:
                    if (
                        rel not in main_candidates
                        and "test" not in rel.lower()
                        and "script" not in rel.lower()
                    ):
                        main_candidates.append(rel)

    return third_party, main_candidates


def _parse_pyproject(path: Path) -> tuple[list[str], str | None]:
    deps: list[str] = []
    requires_py: str | None = None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return deps, requires_py
    project = data.get("project", {})
    if isinstance(project, dict):
        requires_py = project.get("requires-python")
        raw_deps = project.get("dependencies", [])
        if isinstance(raw_deps, list):
            deps.extend(str(d) for d in raw_deps)
    return deps, requires_py


def _parse_requirements_txt(path: Path) -> list[str]:
    deps: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        cleaned = line.strip()
        if not cleaned or cleaned.startswith("#") or cleaned.startswith("-"):
            continue
        deps.append(cleaned)
    return deps


def inspect_project(project_id: str, commit: str, source_dir: Path) -> InspectionReport:
    """Inspect a checked-out repository to determine runtime, deps, entry point, and commands."""
    all_files = [p for p in sorted(source_dir.rglob("*")) if p.is_file() and ".git" not in p.parts]
    rel_paths = [p.relative_to(source_dir).as_posix() for p in all_files]

    languages: list[str] = []
    frameworks: list[str] = []
    package_managers: list[str] = []
    dependency_files: list[str] = []
    dependencies: list[str] = []
    config_files: list[str] = []
    env_vars: list[str] = []
    binary_assets: list[str] = []
    database_reqs: list[str] = []
    setup_commands: list[str] = []
    docker_files: list[str] = []
    notes: list[str] = []

    runtime = "UNKNOWN"
    runtime_version_spec: str | None = None
    entry_point: str | None = None
    working_subdir: str | None = None
    run_command: str | None = None
    test_command: str | None = None
    expected_url: str | None = None

    # Classify binary assets & languages by extension
    ext_set: set[str] = set()
    py_files: list[Path] = []
    for p in all_files:
        rel = p.relative_to(source_dir).as_posix()
        ext = p.suffix.lower()
        ext_set.add(ext)
        if ext == ".py":
            py_files.append(p)
        if classify_file(p) == "binary":
            binary_assets.append(rel)
        if ext in {".db", ".sqlite", ".sqlite3"} and "SQLite" not in database_reqs:
            database_reqs.append("SQLite")

    if ".py" in ext_set:
        languages.append("Python")
    if any(e in ext_set for e in (".js", ".mjs", ".cjs", ".vue")):
        languages.append("JavaScript")
    if any(e in ext_set for e in (".ts", ".tsx")):
        languages.append("TypeScript")
    if ".php" in ext_set:
        languages.append("PHP")
    if ".html" in ext_set:
        languages.append("HTML")
    if any(e in ext_set for e in (".css", ".scss")):
        languages.append("CSS")

    # Detect config / Docker / env files
    for p in _find_files_by_name(
        source_dir,
        (
            "Dockerfile",
            "docker-compose.yml",
            "docker-compose.yaml",
            "compose.yaml",
            "compose.yml",
            "Makefile",
            ".env.example",
            ".python-version",
            "vite.config.js",
            "vite.config.ts",
            "entrypoint.sh",
        ),
        max_depth=2,
    ):
        rel = p.relative_to(source_dir).as_posix()
        config_files.append(rel)
        if p.name in {
            "Dockerfile",
            "docker-compose.yml",
            "docker-compose.yaml",
            "compose.yaml",
            "compose.yml",
        }:
            docker_files.append(rel)
        if p.name == ".env.example":
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                m = ENV_VAR_RE.match(line.strip())
                if m and m.group(1) not in env_vars:
                    env_vars.append(m.group(1))
        if p.name == ".python-version":
            pyver = p.read_text(encoding="utf-8", errors="replace").strip()
            if pyver and not runtime_version_spec:
                runtime_version_spec = pyver

    # Scan Python files for env vars as well
    for py_file in py_files:
        text = py_file.read_text(encoding="utf-8", errors="replace")
        for m in PY_GETENV_RE.findall(text):
            if m not in env_vars:
                env_vars.append(m)
        if "sqlite3" in text or "sqlite://" in text:
            if "SQLite" not in database_reqs:
                database_reqs.append("SQLite")
        if "tkinter" in text and "tkinter" not in frameworks:
            frameworks.append("tkinter")
        if "from flask" in text or "import flask" in text:
            if "Flask" not in frameworks:
                frameworks.append("Flask")
        if "from fastapi" in text or "import fastapi" in text:
            if "FastAPI" not in frameworks:
                frameworks.append("FastAPI")

    # ---- Node.js detection ----
    pkg_json_files = _find_files_by_name(source_dir, ("package.json",), max_depth=1)
    node_present = False
    node_pkg_data: dict = {}
    if pkg_json_files:
        node_present = True
        pkg_path = pkg_json_files[0]
        dependency_files.append(pkg_path.relative_to(source_dir).as_posix())
        try:
            node_pkg_data = json.loads(pkg_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            node_pkg_data = {}

        if (pkg_path.parent / "pnpm-lock.yaml").is_file():
            node_pm = "pnpm"
            dependency_files.append(
                (pkg_path.parent / "pnpm-lock.yaml").relative_to(source_dir).as_posix()
            )
            node_install = "pnpm install --frozen-lockfile"
        elif (pkg_path.parent / "yarn.lock").is_file():
            node_pm = "yarn"
            dependency_files.append(
                (pkg_path.parent / "yarn.lock").relative_to(source_dir).as_posix()
            )
            node_install = "yarn install --frozen-lockfile"
        elif (pkg_path.parent / "package-lock.json").is_file():
            node_pm = "npm"
            dependency_files.append(
                (pkg_path.parent / "package-lock.json").relative_to(source_dir).as_posix()
            )
            node_install = "npm ci"
        else:
            node_pm = "npm"
            node_install = "npm install"

        if node_pm not in package_managers:
            package_managers.append(node_pm)
        setup_commands.append(node_install)

        node_deps = node_pkg_data.get("dependencies", {})
        node_dev_deps = node_pkg_data.get("devDependencies", {})
        for k, v in node_deps.items():
            dependencies.append(f"{k}@{v}")
        if "vue" in node_deps and "Vue" not in frameworks:
            frameworks.append("Vue")
        if "react" in node_deps and "React" not in frameworks:
            frameworks.append("React")
        if "vite" in node_dev_deps or "vite" in node_deps:
            if "Vite" not in frameworks:
                frameworks.append("Vite")

        scripts = node_pkg_data.get("scripts", {})
        if isinstance(scripts, dict):
            if "build" in scripts:
                setup_commands.append(f"{node_pm} run build")
            if "test" in scripts and "no test specified" not in str(scripts["test"]).lower():
                test_command = f"{node_pm} test"

    # ---- PHP / Composer detection ----
    composer_files = _find_files_by_name(source_dir, ("composer.json",), max_depth=1)
    php_present = bool(composer_files) or (".php" in ext_set and not py_files and not node_present)
    if composer_files:
        comp_path = composer_files[0]
        dependency_files.append(comp_path.relative_to(source_dir).as_posix())
        package_managers.append("composer")
        setup_commands.append("composer install")
        try:
            comp_data = json.loads(comp_path.read_text(encoding="utf-8"))
            for k, v in comp_data.get("require", {}).items():
                if k != "php":
                    dependencies.append(f"{k}:{v}")
        except json.JSONDecodeError:
            pass

    # ---- Python detection ----
    py_present = bool(py_files)
    pyproject_files = _find_files_by_name(source_dir, ("pyproject.toml",), max_depth=1)
    req_files = _find_files_by_name(source_dir, ("requirements.txt",), max_depth=1)
    uv_lock_files = _find_files_by_name(source_dir, ("uv.lock",), max_depth=1)

    py_project_dir: Path | None = None
    if pyproject_files:
        pp = pyproject_files[0]
        py_project_dir = pp.parent
        dependency_files.append(pp.relative_to(source_dir).as_posix())
        pp_deps, req_py = _parse_pyproject(pp)
        dependencies.extend(pp_deps)
        if req_py:
            runtime_version_spec = req_py
        if uv_lock_files:
            dependency_files.append(uv_lock_files[0].relative_to(source_dir).as_posix())
            if "uv" not in package_managers:
                package_managers.append("uv")
            setup_commands.append("uv sync --no-dev")
        else:
            if "pip" not in package_managers:
                package_managers.append("pip")
            setup_commands.append("python -m pip install -e .")
    elif req_files:
        rf = req_files[0]
        py_project_dir = rf.parent
        dependency_files.append(rf.relative_to(source_dir).as_posix())
        dependencies.extend(_parse_requirements_txt(rf))
        if "pip" not in package_managers:
            package_managers.append("pip")
        setup_commands.append(f"python -m pip install -r {rf.name}")

    ast_deps, main_candidates = _extract_python_imports(py_files, source_dir)
    if py_present and not pyproject_files and not req_files and ast_deps:
        # Infer dependencies from AST imports when no manifest is present
        inferred = sorted(ast_deps)
        dependencies.extend(inferred)
        if "pip" not in package_managers:
            package_managers.append("pip")
        setup_commands.append(f"python -m pip install {' '.join(inferred)}")
        notes.append(
            "No Python dependency manifest found; inferred third-party imports via AST inspection."
        )

    # Determine primary runtime & entry point / run command
    if py_present and node_present:
        runtime = "Python+Node.js"
    elif py_present:
        runtime = "Python"
    elif node_present:
        runtime = "Node.js"
    elif php_present:
        runtime = "PHP"
    elif docker_files:
        runtime = "Docker"
    else:
        runtime = "UNKNOWN"

    # Determine working_subdir if Python project lives in a subdir (e.g. app/pyproject.toml)
    if py_project_dir is not None and py_project_dir != source_dir:
        working_subdir = py_project_dir.relative_to(source_dir).as_posix()

    # Detect FastAPI/Uvicorn entrypoint (e.g. server/main.py + entrypoint.sh)
    if "FastAPI" in frameworks and "server/main.py" in rel_paths:
        entry_point = "server/main.py"
        if "uv" in package_managers:
            run_command = (
                "uv run python -m uvicorn main:app --app-dir server --host 127.0.0.1 --port 8080"
            )
        else:
            run_command = "python -m uvicorn main:app --app-dir server --host 127.0.0.1 --port 8080"
        expected_url = "http://127.0.0.1:8080"
    elif py_present:
        if main_candidates:
            entry_point = main_candidates[0]
        elif py_files:
            entry_point = py_files[0].relative_to(source_dir).as_posix()

        if entry_point:
            ep_path = Path(entry_point)
            if working_subdir and entry_point.startswith(working_subdir + "/"):
                rel_ep = ep_path.relative_to(working_subdir).as_posix()
                run_command = f"uv run {rel_ep}" if "uv" in package_managers else f"python {rel_ep}"
            else:
                run_command = (
                    f"uv run {entry_point}" if "uv" in package_managers else f"python {entry_point}"
                )

        if "Flask" in frameworks:
            # Check for custom port in .env.example or source
            port = "5000"
            env_ex = source_dir / ".env.example"
            if env_ex.is_file():
                m = re.search(
                    r"APP_PORT\s*=\s*(\d+)", env_ex.read_text(encoding="utf-8", errors="replace")
                )
                if m:
                    port = m.group(1)
            expected_url = f"http://127.0.0.1:{port}"
    elif node_present:
        scripts = node_pkg_data.get("scripts", {})
        node_pm = package_managers[0] if package_managers else "npm"
        entry_point = str(node_pkg_data.get("main", "index.js"))
        if "start" in scripts:
            run_command = f"{node_pm} start"
        elif "dev" in scripts:
            run_command = f"{node_pm} run dev"
        expected_url = "http://127.0.0.1:3000"
    elif php_present:
        for candidate in ("public/index.php", "index.php"):
            if candidate in rel_paths:
                entry_point = candidate
                docroot = "public" if candidate.startswith("public/") else "."
                run_command = f"php -S 127.0.0.1:8000 -t {docroot}"
                expected_url = "http://127.0.0.1:8000"
                break

    # Detect pytest tests if present
    if py_present and test_command is None:
        if any(p.startswith("tests/") and p.endswith(".py") for p in rel_paths):
            if "uv" in package_managers and working_subdir:
                test_command = "uv run pytest ../tests -v"
            elif "uv" in package_managers:
                test_command = "uv run pytest -v"
            else:
                test_command = "pytest -v"

    return InspectionReport(
        project_id=project_id,
        commit=commit,
        languages=languages,
        frameworks=frameworks,
        runtime=runtime,
        runtime_version_spec=runtime_version_spec,
        package_managers=package_managers,
        dependency_files=dependency_files,
        dependencies=dependencies,
        entry_point=entry_point,
        working_subdir=working_subdir,
        config_files=config_files,
        env_vars=env_vars,
        binary_assets=binary_assets,
        database_requirements=database_reqs,
        setup_commands=setup_commands,
        run_command=run_command,
        test_command=test_command,
        docker_files=docker_files,
        expected_url=expected_url,
        notes=notes,
    )
