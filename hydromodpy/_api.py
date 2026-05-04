"""Top-level functional API for HydroModPy.

Mirrors the CLI verbs so ``hmp run config.toml`` and ``hmp.run("config.toml")``
execute the same workflow. Kept as a private module so the package facade
stays minimal.
"""

from __future__ import annotations

import importlib
import platform
import shutil
from pathlib import Path
from typing import Any

from hydromodpy.core.version import __version__


def open(workspace_path: Any) -> Any:
    """Open a HydroModPy project catalog.

    Mirrors ``xarray.open_dataset`` / ``pandas.read_csv`` in intent: one call,
    a ready-to-query object backed by ``hydromodpy.duckdb``.

    Parameters
    ----------
    workspace_path
        Workspace directory, or a direct path to ``hydromodpy.duckdb``.

    Returns
    -------
    SimulationCatalog
        Catalog object used to find runs, query metadata, and open persisted
        field stores.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> catalog = hmp.open("~/hmp_workspace")
    >>> catalog.latest()

    See Also
    --------
    hydromodpy.results.catalog.SimulationCatalog
        Workspace-level catalog implementation.
    hydromodpy.results.run.Run
        Per-simulation result view returned by catalog queries.
    """
    from hydromodpy.results.catalog import SimulationCatalog

    return SimulationCatalog(workspace_path)


def catalog(path: Any = None) -> Any:
    """Open the hidden global catalog index for inter-project queries.

    Parameters
    ----------
    path
        Optional path to the catalog index database. ``None`` uses the default
        user-level index location.

    Returns
    -------
    CatalogIndex
        Index object that can discover registered project catalogs.
    """
    from hydromodpy.results.catalog import CatalogIndex

    return CatalogIndex(path)


def run(config: Any, **kwargs: Any) -> Any:
    """Run a HydroModPy workflow from Python.

    Passing a path executes the same dispatcher as ``hmp run``. Passing an
    already-built configuration object opens a temporary ``Project`` and calls
    ``Project.run``.

    Parameters
    ----------
    config
        TOML path or validated configuration object.
    kwargs
        Runtime options forwarded to the selected workflow or to
        ``Project.run``.

    Returns
    -------
    Any
        Workflow result. Simulation workflows usually return a ``Run`` object;
        overview, mesh, batch, and calibration workflows return their own
        summary objects.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> run = hmp.run("run_transient_nwt.toml", name="baseline")

    See Also
    --------
    hydromodpy.project.Project.run
        Object-oriented form for repeated runs from one project.
    """
    if isinstance(config, (str, Path)):
        from hydromodpy.workflow.dispatch import dispatch_workflow, resolve_workflow

        config_path = Path(config).expanduser().resolve()
        workflow = resolve_workflow(
            config_path,
            cli_workflow=None,
            require_toml_field=True,
        )
        return dispatch_workflow(workflow, config_path, **kwargs)

    from hydromodpy.project import Project

    with Project(config, headless=kwargs.pop("headless", False)) as project:
        return project.run(**kwargs)


def calibrate(config: Any, **kwargs: Any) -> Any:
    """Run a calibration workflow from a TOML file or config object.

    This helper opens a lazy ``Project`` and delegates to
    ``Project.calibrate``. It is the Python equivalent of launching a
    calibration TOML through the CLI dispatcher.

    Parameters
    ----------
    config
        Calibration TOML path or validated configuration object.
    kwargs
        Options forwarded to ``Project.calibrate``.

    Returns
    -------
    Any
        Calibration report or workflow-specific result.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> report = hmp.calibrate("calibration.toml")

    See Also
    --------
    hydromodpy.project.Project.calibrate
        Project method used by this facade.
    hydromodpy.calibration.CalibrationReport
        Structured calibration result.
    """
    from hydromodpy.project import Project

    if isinstance(config, (str, Path)):
        config_path = Path(config).expanduser().resolve()
        with Project.lazy(config_path, headless=kwargs.pop("headless", True)) as project:
            return project.calibrate(config_path=config_path, **kwargs)

    with Project.lazy(config, headless=kwargs.pop("headless", True)) as project:
        return project.calibrate(**kwargs)


def overview(config: Any, **kwargs: Any) -> Any:
    """Run the overview workflow declared by a TOML file.

    Parameters
    ----------
    config
        TOML file containing ``workflow = "overview"``.
    kwargs
        Runtime options forwarded to the workflow dispatcher.

    Returns
    -------
    Any
        Overview workflow summary.
    """
    from hydromodpy.workflow.dispatch import dispatch_workflow, resolve_workflow

    config_path = Path(config).expanduser().resolve()
    workflow = resolve_workflow(
        config_path,
        cli_workflow="overview",
        require_toml_field=True,
    )
    return dispatch_workflow(workflow, config_path, **kwargs)


def batch(config: Any, **kwargs: Any) -> Any:
    """Run the regional batch workflow declared by a TOML file.

    Parameters
    ----------
    config
        TOML file containing ``workflow = "batch"``.
    kwargs
        Runtime options forwarded to the workflow dispatcher.

    Returns
    -------
    Any
        Batch workflow summary.
    """
    from hydromodpy.workflow.dispatch import dispatch_workflow, resolve_workflow

    config_path = Path(config).expanduser().resolve()
    workflow = resolve_workflow(
        config_path,
        cli_workflow="batch",
        require_toml_field=True,
    )
    return dispatch_workflow(workflow, config_path, **kwargs)


def compare_pair(sim_a: Any, sim_b: Any, *, workspace: Any = None) -> Any:
    """Compare two simulations by id or result object.

    Parameters
    ----------
    sim_a, sim_b
        Simulation ids or objects accepted by the comparison runtime.
    workspace
        Optional workspace used to resolve simulation ids.

    Returns
    -------
    pandas.DataFrame
        Side-by-side comparison table.

    See Also
    --------
    hydromodpy.analysis.comparison
        Comparison package used by this helper.
    """
    from hydromodpy.analysis.comparison.pairwise import compare_pair as _compare_pair

    return _compare_pair(sim_a, sim_b, workspace=workspace)


def testbed(toml_path: Any) -> Any:
    """Run a TOML-driven method testbed.

    Parameters
    ----------
    toml_path
        Testbed configuration path.

    Returns
    -------
    Any
        Testbed launcher result.
    """
    from hydromodpy.analysis.testbed.runtime import TestbedLauncher

    return TestbedLauncher(toml_path).run()


def mesh(toml_path: Any) -> dict:
    """Run the mesh-only workflow from a TOML file.

    Mirrors ``hmp run`` for ``workflow = "mesh"`` configs: one call,
    returns the launcher summary dict.

    Parameters
    ----------
    toml_path
        Mesh workflow TOML path.

    Returns
    -------
    dict
        Mesh launcher summary.
    """
    from hydromodpy.workflow.pipelines.mesh import MeshCatchmentLauncher

    return MeshCatchmentLauncher(Path(toml_path).expanduser().resolve()).run()


def report(session_id_or_prefix: Any = None, *, workspace: Any = None) -> Any:
    """Render the HTML report for a calibration session.

    ``session_id_or_prefix`` accepts a full UUID, a unique hex prefix,
    or ``None`` to fall back to the most recently started session.
    ``workspace`` defaults to the nearest ancestor of the current
    working directory containing ``hydromodpy.duckdb``.

    Parameters
    ----------
    session_id_or_prefix
        Full session UUID, unique hex prefix, or ``None`` for the latest
        session.
    workspace
        Optional workspace directory.

    Returns
    -------
    Any
        Report rendering result.
    """
    from hydromodpy.calibration.report import resolve_calibration_session_id
    from hydromodpy.results.catalog import SimulationCatalog
    from hydromodpy.workflow.steps.calibration import step_render_calibration_report

    if workspace is None:
        workspace_root = Path.cwd()
        for parent in [workspace_root] + list(workspace_root.parents):
            if (parent / "hydromodpy.duckdb").exists():
                workspace_root = parent
                break
    else:
        workspace_root = Path(workspace).expanduser().resolve()

    with SimulationCatalog(workspace_root) as catalog:
        full_id = resolve_calibration_session_id(catalog, session_id_or_prefix)
        return step_render_calibration_report(
            catalog=catalog,
            session_id=full_id,
            workspace_root=workspace_root,
        )


def doctor() -> dict:
    """Lightweight environment diagnostic.

    Returns a dict describing Python, hydromodpy, and solver versions. Quick
    by design (no actual solver invocation) and safe to call at import probing
    time.

    Returns
    -------
    dict
        Diagnostic payload with Python, HydroModPy, optional package, and solver
        executable information.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> hmp.doctor()["hydromodpy"]
    """
    info: dict = {
        "python": platform.python_version(),
        "hydromodpy": __version__,
        "solvers": {},
        "optional": {},
    }
    for pkg in ("flopy", "gmsh", "duckdb", "zarr", "pyproj", "rasterio"):
        try:
            mod = importlib.import_module(pkg)
            info["optional"][pkg] = getattr(mod, "__version__", "?")
        except Exception:
            info["optional"][pkg] = None
    for exe in ("mf2005", "mfnwt", "mf6"):
        info["solvers"][exe] = shutil.which(exe)
    return info
