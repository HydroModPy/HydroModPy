"""Shared pytest configuration for the HydroModPy test suite."""

import os
import shutil
from pathlib import Path
import tempfile
import pytest


def _resolve_test_scratch_root() -> Path:
    """Return the shared scratch root used by pytest and subprocesses."""
    override = os.environ.get("HYDROMODPY_TEST_SCRATCH_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return (Path(tempfile.gettempdir()) / "hydromodpy_tests").resolve()


def _path_has_suffix_parts(path: Path, suffix_parts: tuple[str, ...]) -> bool:
    """Return True when ``path`` ends with the requested path-part suffix."""
    parts = path.parts
    return len(parts) >= len(suffix_parts) and tuple(parts[-len(suffix_parts) :]) == suffix_parts


_TEST_SCRATCH_ROOT = _resolve_test_scratch_root()
_TEST_TMP_ROOT = _TEST_SCRATCH_ROOT / "tmp"
_TEST_PYTEST_ROOT = _TEST_SCRATCH_ROOT / "pytest"
for _path in (_TEST_SCRATCH_ROOT, _TEST_TMP_ROOT, _TEST_PYTEST_ROOT):
    _path.mkdir(parents=True, exist_ok=True)

# Configure scratch locations at import time so pytest internals and spawned
# subprocesses inherit one repository-external root by default.
os.environ.setdefault("HYDROMODPY_TEST_SCRATCH_ROOT", str(_TEST_SCRATCH_ROOT))
os.environ.setdefault("PYTEST_DEBUG_TEMPROOT", str(_TEST_PYTEST_ROOT))
os.environ.setdefault("TMPDIR", str(_TEST_TMP_ROOT))
os.environ.setdefault("TMP", str(_TEST_TMP_ROOT))
os.environ.setdefault("TEMP", str(_TEST_TMP_ROOT))


def pytest_addoption(parser):
    """Add a CLI switch to refresh regression golden references."""
    parser.addoption(
        "--update-goldens",
        action="store_true",
        default=False,
        help="Rewrite regression golden JSON files with current outputs.",
    )


@pytest.fixture(scope="session")
def update_goldens(request):
    """Return True when regression tests should rewrite golden references."""
    return bool(request.config.getoption("--update-goldens"))


@pytest.fixture(scope="session")
def hydromodpy_test_scratch_root() -> Path:
    """Expose the shared repository-external scratch root to tests."""
    return _TEST_SCRATCH_ROOT


@pytest.fixture(autouse=True)
def _redirect_repo_root_cwd_for_gmsh_grid_tests(
    request,
    monkeypatch: pytest.MonkeyPatch,
    hydromodpy_test_scratch_root: Path,
) -> None:
    """Keep gmsh-grid tests from materializing scratch folders in the repo root."""
    test_path = Path(str(getattr(request.node, "fspath", request.node.path))).resolve()
    if not _path_has_suffix_parts(
        test_path.parent,
        ("tests", "unit", "solver", "utils", "mesh", "gmsh_grid"),
    ):
        return

    scratch_cwd = (
        hydromodpy_test_scratch_root / "cwd" / "gmsh_grid" / test_path.stem
    )
    scratch_cwd.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(scratch_cwd)


def pytest_collection_modifyitems(config, items):
    """Assign default regression tier markers for selected regression tests."""

    for item in items:
        item_path = Path(str(getattr(item, "fspath", item.path)))
        is_regression_file = "regression" in item_path.parts
        is_regression_test = "regression" in item.keywords

        if not is_regression_file or not is_regression_test:
            continue

        if "fast" in item.keywords or "extensive" in item.keywords:
            continue
        if "extensive" in item_path.parts:
            item.add_marker(pytest.mark.extensive)
        else:
            item.add_marker(pytest.mark.fast)


def pytest_sessionfinish(session, exitstatus):
    """Clean up the shared scratch root at the end of the test session.

    Only runs on the controller process (not on xdist workers) to avoid
    races.  Silently ignores missing or locked files.
    """
    is_xdist_worker = hasattr(session.config, "workerinput")
    if is_xdist_worker:
        return
    scratch = _TEST_SCRATCH_ROOT
    if scratch.exists():
        shutil.rmtree(scratch, ignore_errors=True)


def pytest_ignore_collect(collection_path, config):
    """Skip non-selected regression test files before import/collection."""
    path = Path(str(collection_path))
    if path.suffix != ".py":
        return False
    return False

