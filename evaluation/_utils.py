from __future__ import annotations

import ast
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

EXCLUDED_DIRS = {
    ".git",
    ".github",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}


@dataclass(slots=True)
class PythonFileInfo:
    path: Path
    module: str
    relative: Path
    lines: int


def iter_python_files(root: Path) -> list[Path]:
    root = root.resolve()
    files: list[Path] = []
    for path in root.rglob("*.py"):
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        files.append(path)
    return sorted(files)


def module_name_from_path(root: Path, path: Path) -> str:
    root = root.resolve()
    path = path.resolve()
    relative = path.relative_to(root).with_suffix("")
    parts = list(relative.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else root.name


def relative_path(root: Path, path: Path) -> Path:
    return path.resolve().relative_to(root.resolve())


def count_lines(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
    except OSError:
        return 0


def parse_ast(path: Path) -> ast.AST | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="ignore"), filename=str(path))
    except SyntaxError:
        return None
    except OSError:
        return None


def safe_mkdir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def json_ready_path(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


@contextmanager
def resolve_repository_root(
    root: Path | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> Iterator[Path]:
    if repo is None:
        yield (root or Path.cwd()).expanduser().resolve()
        return

    with tempfile.TemporaryDirectory(prefix="evaluation-repo-") as temp_dir:
        clone_path = Path(temp_dir) / "repo"
        command = ["git", "clone", "--depth", "1"]
        if branch:
            command.extend(["--branch", branch, "--single-branch"])
        command.extend([repo, str(clone_path)])
        completed = subprocess.run(command, capture_output=True, text=True)
        if completed.returncode != 0:
            error_message = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
            raise SystemExit(f"git clone failed for {repo!r}: {error_message}")
        yield clone_path.resolve()
