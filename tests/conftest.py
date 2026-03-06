"""Shared pytest configuration for the HydroModPy test suite."""

from pathlib import Path

import pytest

_ALLOWED_REGRESSION_FILES = {
    "test_example12_npy_regression.py",
    "test_launcher_simulation_regression.py",
    "test_launcher_data_overview_regression.py",
}


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


def pytest_collection_modifyitems(config, items):
    """Keep only selected non-regression scenarios in tests/regression."""
    selected = []
    deselected = []

    for item in items:
        item_path = Path(str(getattr(item, "fspath", item.path)))
        is_regression_file = "regression" in item_path.parts
        is_regression_test = "regression" in item.keywords

        if is_regression_file and is_regression_test:
            if item_path.name not in _ALLOWED_REGRESSION_FILES:
                deselected.append(item)
                continue

        selected.append(item)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected


def pytest_ignore_collect(collection_path, config):
    """Skip non-selected regression test files before import/collection."""
    path = Path(str(collection_path))
    if path.suffix != ".py":
        return False

    is_regression_file = len(path.parts) >= 2 and path.parts[-2] == "regression"
    is_test_file = path.name.startswith("test_")
    if is_regression_file and is_test_file:
        return path.name not in _ALLOWED_REGRESSION_FILES
    return False

