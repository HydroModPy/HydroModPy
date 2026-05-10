"""Shared pytest configuration for the HydroModPy test suite."""

import os
import platform
import random
import shutil
import tempfile
import uuid
from importlib.util import find_spec
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
_WHITEBOX_XDIST_GROUP = "whitebox_backend"
_WHITEBOX_XDIST_GROUP_TEST_FILES = frozenset(
    {
        "test_catchment_from_point.py",
        "test_reference_river_network_nancon_case.py",
        "test_run_geographic_case_golden.py",
        "test_run_geographic_case_regression.py",
        "test_run_geographic_case_river_network_regression.py",
        "test_run_geographic_dem_processing_golden.py",
        "test_run_geographic_river_network_golden.py",
        "test_whitebox_workflows_backend.py",
    }
)
_SCRATCH_ROOT_ENV = "HYDROMODPY_TEST_SCRATCH_ROOT"
_SCRATCH_SESSION_ENV = "HYDROMODPY_TEST_SESSION_SCRATCH_ROOT"
_SCRATCH_OWNER_ENV = "HYDROMODPY_TEST_SCRATCH_OWNER"
_XDIST_WORKER_ENV = "PYTEST_XDIST_WORKER"
_INHERITED_SCRATCH_OWNER = os.environ.get(_SCRATCH_OWNER_ENV)
_SCRATCH_OWNER_TOKEN = _INHERITED_SCRATCH_OWNER or f"{os.getpid()}-{uuid.uuid4().hex[:12]}"
_OWNS_TEST_SCRATCH = _INHERITED_SCRATCH_OWNER is None


def _resolve_test_scratch_root() -> Path:
    """Return the shared scratch root used by pytest and subprocesses."""
    override = os.environ.get(_SCRATCH_ROOT_ENV)
    if override:
        return Path(override).expanduser().resolve()
    return (Path(tempfile.gettempdir()) / "hydromodpy_tests").resolve()


def _resolve_test_session_root(scratch_root: Path) -> Path:
    """Return the per-session scratch root used by this pytest process tree."""
    override = os.environ.get(_SCRATCH_SESSION_ENV)
    if override:
        return Path(override).expanduser().resolve()
    return (scratch_root / "sessions" / _SCRATCH_OWNER_TOKEN).resolve()


def _path_has_suffix_parts(path: Path, suffix_parts: tuple[str, ...]) -> bool:
    """Return True when ``path`` ends with the requested path-part suffix."""
    parts = path.parts
    return len(parts) >= len(suffix_parts) and tuple(parts[-len(suffix_parts) :]) == suffix_parts


def _session_owner_pid(session_name: str) -> int | None:
    """Return the owning process id encoded in a managed scratch-session name."""
    if session_name.startswith("cli_"):
        token = session_name.split("_", 2)[1] if "_" in session_name else ""
    else:
        token = session_name.split("-", 1)[0]
    if not token.isdigit():
        return None
    return int(token)


def _is_xdist_worker_process() -> bool:
    """Return True when the current process is a pytest-xdist worker."""
    worker = os.environ.get(_XDIST_WORKER_ENV)
    return bool(worker and worker != "master")


def _windows_process_is_running(pid: int) -> bool:
    """Return True when *pid* appears alive, avoiding ``os.kill`` on Windows."""
    import ctypes
    from ctypes import wintypes

    error_access_denied = 5
    process_query_limited_information = 0x1000
    still_active = 259

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return ctypes.get_last_error() == error_access_denied

    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _windows_long_path(path: Path) -> str:
    """Return a Windows long-path string for recursive deletion."""
    value = str(path.resolve())
    if value.startswith("\\\\?\\"):
        return value
    if value.startswith("\\\\"):
        return "\\\\?\\UNC\\" + value[2:]
    return "\\\\?\\" + value


def _rmtree_ignore_errors(path: Path) -> None:
    """Best-effort recursive delete with Windows long-path support."""
    target: str | Path = path
    if platform.system().strip().lower() == "windows":
        target = _windows_long_path(path)
    shutil.rmtree(target, ignore_errors=True)


def _process_is_running(pid: int) -> bool:
    """Return True when *pid* still appears to own a live process."""
    if pid <= 0 or pid == os.getpid():
        return True
    try:
        if platform.system().strip().lower() == "windows":
            return _windows_process_is_running(pid)
        os.kill(pid, 0)
    except PermissionError:
        return True
    except (OSError, OverflowError, SystemError, ValueError):
        return False
    return True


def _cleanup_stale_test_scratch_sessions(scratch_root: Path, current_token: str) -> None:
    """Remove managed scratch sessions whose owning process is no longer alive."""
    if _is_xdist_worker_process() or not _OWNS_TEST_SCRATCH:
        return
    sessions_root = scratch_root / "sessions"
    if not sessions_root.is_dir():
        return

    try:
        session_dirs = list(sessions_root.iterdir())
    except (OSError, RuntimeError, SystemError):
        return

    for session_dir in session_dirs:
        try:
            if not session_dir.is_dir() or session_dir.name == current_token:
                continue
            owner_pid = _session_owner_pid(session_dir.name)
            if owner_pid is None or _process_is_running(owner_pid):
                continue
        except (OSError, RuntimeError, SystemError, ValueError):
            continue
        _rmtree_ignore_errors(session_dir)


_TEST_SCRATCH_ROOT = _resolve_test_scratch_root()
_cleanup_stale_test_scratch_sessions(_TEST_SCRATCH_ROOT, _SCRATCH_OWNER_TOKEN)
_TEST_SESSION_ROOT = _resolve_test_session_root(_TEST_SCRATCH_ROOT)
_TEST_TMP_ROOT = _TEST_SESSION_ROOT / "tmp"
_TEST_PYTEST_ROOT = _TEST_SESSION_ROOT / "pytest"
for _path in (_TEST_SCRATCH_ROOT, _TEST_SESSION_ROOT, _TEST_TMP_ROOT, _TEST_PYTEST_ROOT):
    _path.mkdir(parents=True, exist_ok=True)

# Configure scratch locations at import time so pytest internals and spawned
# subprocesses inherit one repository-external root by default.
os.environ.setdefault(_SCRATCH_ROOT_ENV, str(_TEST_SCRATCH_ROOT))
os.environ.setdefault(_SCRATCH_SESSION_ENV, str(_TEST_SESSION_ROOT))
if _OWNS_TEST_SCRATCH:
    os.environ[_SCRATCH_OWNER_ENV] = _SCRATCH_OWNER_TOKEN
os.environ.setdefault("PYTEST_DEBUG_TEMPROOT", str(_TEST_PYTEST_ROOT))
os.environ.setdefault("TMPDIR", str(_TEST_TMP_ROOT))
os.environ.setdefault("TMP", str(_TEST_TMP_ROOT))
os.environ.setdefault("TEMP", str(_TEST_TMP_ROOT))


def _ensure_test_scratch_dirs() -> None:
    """Recreate shared scratch folders if a test removed them mid-session."""
    for path in (_TEST_SCRATCH_ROOT, _TEST_SESSION_ROOT, _TEST_TMP_ROOT, _TEST_PYTEST_ROOT):
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
    """Expose this session's repository-external scratch root to tests."""
    return _TEST_SESSION_ROOT


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
    """Return a minimal valid :class:`~hydromodpy.config.HydroModPyConfig`.

    Only the two required sub-configs are populated: ``workspace``
    (``project_root`` pointing at *tmp_path*) and ``geographic``
    (``source_mode='synthetic'``, avoiding the DEM/outlet requirements
    of ``'standard'``).  All other sections fall back to their
    ``default_factory``.  Tests that need a specific flow/solver block
    should extend the returned instance via ``model_copy(update=...)``.
    """
    from hydromodpy.config import HydroModPyConfig
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

        if "validation" in parts and "analytical" in parts:
            callspec = getattr(item, "callspec", None)
            if callspec is not None and callspec.params.get("solver") == "boussinesq":
                item.add_marker(pytest.mark.petsc)
            elif callspec is None and "boussinesq" in item.nodeid.lower():
                item.add_marker(pytest.mark.petsc)

        if item_path.name in _WHITEBOX_XDIST_GROUP_TEST_FILES and not any(
            mark.name == "xdist_group" for mark in item.iter_markers()
        ):
            item.add_marker(pytest.mark.xdist_group(name=_WHITEBOX_XDIST_GROUP))

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
    if "petsc" in item.keywords:
        if platform.system().strip().lower() != "linux" or find_spec("petsc4py") is None:
            pytest.skip("Boussinesq PETSc runtime is Linux-only and requires petsc4py.")

    _ensure_test_scratch_dirs()
    tmp_path_factory = getattr(item.session.config, "_tmp_path_factory", None)
    if tmp_path_factory is None:
        return
    tmp_path_factory.getbasetemp().mkdir(parents=True, exist_ok=True)


def pytest_sessionfinish(session, exitstatus):
    """Clean up this session's scratch root at the end of the test session.

    Only runs on the controller process (not on xdist workers) to avoid
    races.  Silently ignores missing or locked files.
    """
    is_xdist_worker = hasattr(session.config, "workerinput")
    if is_xdist_worker or not _OWNS_TEST_SCRATCH:
        return
    scratch = _TEST_SESSION_ROOT
    if scratch.exists():
        _rmtree_ignore_errors(scratch)
