"""Repository-level guards against legacy public vocabulary."""

from __future__ import annotations

import os
from pathlib import Path

_SCAN_ROOTS = (
    "docs/source",
    "examples",
    "hydromodpy",
    "tests",
    "tools",
    "validation_cases",
)
_SKIP_DIRS = {
    ".mypy_cache",
    ".pytest_cache",
    ".pytest-tmp",
    ".ruff_cache",
    "__pycache__",
    "pytest_tmp_codex",
}
_BINARY_SUFFIXES = {
    ".7z",
    ".db",
    ".gif",
    ".gz",
    ".ico",
    ".jpg",
    ".jpeg",
    ".npy",
    ".npz",
    ".parquet",
    ".pdf",
    ".png",
    ".pyc",
    ".tif",
    ".tiff",
    ".webp",
    ".zip",
}


def _is_skipped_dir(path: Path) -> bool:
    name = path.name
    return (
        name in _SKIP_DIRS
        or name.startswith("hydromodpy_tests")
        or name.startswith("results")
        or name in {"outputs", "workspace"}
    )


def _iter_candidate_files(repo_root: Path):
    for root_name in _SCAN_ROOTS:
        scan_root = repo_root / root_name
        if not scan_root.exists():
            continue
        for root, dirs, files in os.walk(scan_root):
            root_path = Path(root)
            dirs[:] = [name for name in dirs if not _is_skipped_dir(root_path / name)]
            for filename in files:
                path = root_path / filename
                if path.suffix.lower() in _BINARY_SUFFIXES:
                    continue
                yield path


def test_legacy_regression_vocabulary_stays_out_of_active_surface() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    legacy_name = "_".join(("launcher", "simulation"))
    offenders: list[str] = []

    for path in _iter_candidate_files(repo_root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if legacy_name in text:
            offenders.append(path.relative_to(repo_root).as_posix())

    assert offenders == []
