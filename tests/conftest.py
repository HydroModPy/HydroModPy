"""Shared pytest configuration for the HydroModPy test suite."""

import os
from pathlib import Path
import tempfile
import pytest


def _resolve_test_scratch_root() -> Path:
    """Return the shared scratch root used by pytest and subprocesses."""
    override = os.environ.get("HYDROMODPY_TEST_SCRATCH_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return (Path(tempfile.gettempdir()) / "hydromodpy_tests").resolve()


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


def pytest_ignore_collect(collection_path, config):
    """Skip non-selected regression test files before import/collection."""
    path = Path(str(collection_path))
    if path.suffix != ".py":
        return False
    return False

