"""Shared pytest configuration for the HydroModPy test suite."""

from pathlib import Path
import pytest


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
    """Assign default regression tier markers for selected regression tests."""

    for item in items:
        item_path = Path(str(getattr(item, "fspath", item.path)))
        is_regression_file = "regression" in item_path.parts
        is_regression_test = "regression" in item.keywords

        if not is_regression_file or not is_regression_test:
            continue

        if "normal" in item.keywords or "extensive" in item.keywords:
            continue
        if "extensive" in item_path.parts:
            item.add_marker(pytest.mark.extensive)
        else:
            item.add_marker(pytest.mark.normal)


def pytest_ignore_collect(collection_path, config):
    """Skip non-selected regression test files before import/collection."""
    path = Path(str(collection_path))
    if path.suffix != ".py":
        return False
    return False

