"""Repository-level guards against legacy public vocabulary."""

from __future__ import annotations

import json
import mmap
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
    ".tmp-doc-gallery",
    "__pycache__",
    "docs/_dev_notes",
    "docs/_internal/legacy_notebooks",
    "pytest_tmp_codex",
}
_BINARY_SUFFIXES = {
    ".7z",
    ".dbf",
    ".db",
    ".duckdb",
    ".gpkg",
    ".gif",
    ".gz",
    ".h5",
    ".hdf",
    ".hdf5",
    ".ico",
    ".jpg",
    ".jpeg",
    ".log",
    ".nc",
    ".nc4",
    ".npy",
    ".npz",
    ".parquet",
    ".pdf",
    ".png",
    ".pyc",
    ".shp",
    ".shx",
    ".tif",
    ".tiff",
    ".wal",
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


def _file_contains_bytes(path: Path, needle: bytes) -> bool:
    with path.open("rb") as handle:
        try:
            with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as payload:
                return payload.find(needle) != -1
        except ValueError:
            return False


def test_legacy_regression_vocabulary_stays_out_of_active_surface() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    legacy_name = "_".join(("launcher", "simulation"))
    legacy_bytes = legacy_name.encode("utf-8")
    offenders: list[str] = []

    for path in _iter_candidate_files(repo_root):
        try:
            has_legacy_name = _file_contains_bytes(path, legacy_bytes)
        except OSError:
            continue
        if has_legacy_name:
            offenders.append(path.relative_to(repo_root).as_posix())

    assert offenders == []


def _iter_mapping_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _iter_mapping_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_mapping_keys(item)


def test_public_simulation_comparison_manifests_hide_workspace_paths() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    manifest_root = (
        repo_root / "docs" / "source" / "_static" / "capability_gallery" / "simulation_comparison"
    )
    dropped_path_keys = {
        "config_path",
        "comparison_audit_json",
        "comparison_audit_md",
        "comparison_root",
        "comparison_web_report",
        "generated_config_cleanup_errors",
        "generated_config_paths",
        "manifest_path",
        "mesh_output_exchange_bundle_dir",
        "mesh_output_mesh",
        "mesh_output_summary_json",
        "path",
        "period_diagnostics",
        "run_folder",
        "runtime_summary",
        "source_path",
        "stderr_tail",
        "stdout_tail",
        "step_diagnostics",
    }
    offenders: list[str] = []

    for path in sorted(manifest_root.glob("*_comparison_manifest.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        leaked_keys = sorted(dropped_path_keys.intersection(_iter_mapping_keys(payload)))
        text = path.read_text(encoding="utf-8")
        if (
            leaked_keys
            or ":\\\\" in text
            or "_postprocess" in text
            or "examples/projects/10_testbed_workflow/outputs" in text
        ):
            offenders.append(f"{path.relative_to(repo_root).as_posix()}: {leaked_keys}")

    assert offenders == []
