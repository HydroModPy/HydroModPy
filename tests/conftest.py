"""Shared pytest configuration for the HydroModPy test suite."""

import os
import random
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pytest

# Force single-thread BLAS / Rayon so golden signatures are reproducible
# across CI runners (see tests/TOLERANCES.md §"Cross-platform determinism").
for _var in (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "RAYON_NUM_THREADS",
):
    os.environ.setdefault(_var, "1")
os.environ.setdefault("PYTHONHASHSEED", "42")


_LAYER_DIR_NAMES = ("unit", "integration", "validation", "regression", "e2e")
_LAYER_TIMEOUTS_SECONDS = {
    "unit": 60.0,
    "integration": 300.0,
    "validation": 900.0,
    "regression": 300.0,
    "e2e": 1800.0,
}


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


def _ensure_test_scratch_dirs() -> None:
    """Recreate shared scratch folders if a test removed them mid-session."""
    for path in (_TEST_SCRATCH_ROOT, _TEST_TMP_ROOT, _TEST_PYTEST_ROOT):
        path.mkdir(parents=True, exist_ok=True)


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


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Create one initialized HydroModPy workspace under *tmp_path*.

    Populates the standard layout (``data/``, ``projects/``, the
    per-variable ``*_custom/`` seed folders) using the same code path as
    ``hmp init``, so integration tests can open the workspace with
    ``hmp.open(...)`` or instantiate a :class:`~hydromodpy.results.catalog.SimulationCatalog`
    on top of it.  The catalog itself is opened lazily - this fixture
    only creates folders, keeping the fixture cheap and free of DuckDB
    I/O until a test explicitly needs it.
    """
    from hydromodpy.data.scaffold import scaffold

    root = scaffold(tmp_path / "workspace")
    return root


@pytest.fixture
def minimal_config(tmp_path: Path):
    """Return a minimal valid :class:`~hydromodpy.core.config.hydromodpy_config.HydroModPyConfig`.

    Only the two required sub-configs are populated: ``workspace``
    (``project_root`` pointing at *tmp_path*) and ``geographic``
    (``source_mode='synthetic'``, avoiding the DEM/outlet requirements
    of ``'standard'``).  All other sections fall back to their
    ``default_factory``.  Tests that need a specific flow/solver block
    should extend the returned instance via ``model_copy(update=...)``.
    """
    from hydromodpy.core.config import HydroModPyConfig
    from hydromodpy.core.workspace.config import WorkspaceConfig
    from hydromodpy.spatial.geographic.geographic_config import GeographicConfig

    return HydroModPyConfig(
        workflow="simulation",
        workspace=WorkspaceConfig(
            project_root=tmp_path / "project",
            root=tmp_path,
        ),
        geographic=GeographicConfig(source_mode="synthetic"),
    )


@pytest.fixture(autouse=True)
def _deterministic_seeds():
    """Reset Python and NumPy RNG seeds before each test for reproducibility."""
    random.seed(42)
    np.random.seed(42)
    yield


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

    scratch_cwd = hydromodpy_test_scratch_root / "cwd" / "gmsh_grid" / test_path.stem
    scratch_cwd.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(scratch_cwd)


def pytest_collection_modifyitems(config, items):
    """Auto-tag tests with their layer marker and default regression tier.

    * Any test in ``tests/<layer>/...`` gets ``@pytest.mark.<layer>``.
    * Regression tests default to ``fast`` unless they already carry
      ``fast`` or ``extensive``; the ``extensive/`` directory forces
      ``extensive``.
    """

    for item in items:
        item_path = Path(str(getattr(item, "fspath", item.path)))
        parts = item_path.parts

        # 1) Auto-tag layer marker by path + default timeout.
        for layer in _LAYER_DIR_NAMES:
            if layer in parts:
                if layer not in item.keywords:
                    item.add_marker(getattr(pytest.mark, layer))
                if not any(mark.name == "timeout" for mark in item.iter_markers()):
                    item.add_marker(pytest.mark.timeout(_LAYER_TIMEOUTS_SECONDS[layer]))
                break

        # 2) Regression tier default markers (fast vs extensive).
        is_regression_file = "regression" in parts
        is_regression_test = "regression" in item.keywords
        if is_regression_file and is_regression_test:
            if "fast" in item.keywords or "extensive" in item.keywords:
                continue
            if "extensive" in parts:
                item.add_marker(pytest.mark.extensive)
            else:
                item.add_marker(pytest.mark.fast)


def pytest_runtest_setup(item):
    """Keep pytest's shared temp roots available even after test-side cleanup."""
    _ensure_test_scratch_dirs()
    tmp_path_factory = getattr(item.session.config, "_tmp_path_factory", None)
    if tmp_path_factory is None:
        return
    tmp_path_factory.getbasetemp().mkdir(parents=True, exist_ok=True)


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
