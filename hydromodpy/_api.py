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
    """Open a HydroModPy workspace and return the unified catalog.

    Mirrors ``xarray.open_dataset`` / ``pandas.read_csv`` in intent: one call,
    a ready-to-query object backed by ``hydromodpy.duckdb``.
    """
    from hydromodpy.results.catalog import SimulationCatalog

    return SimulationCatalog(workspace_path)


def run(config: Any, **kwargs: Any) -> Any:
    """Functional facade for ``hmp run <config.toml>``."""
    if isinstance(config, (str, Path)):
        from hydromodpy.cli.workflows import dispatch_workflow, resolve_workflow

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
    """Functional facade for :meth:`hydromodpy.Project.calibrate`."""
    from hydromodpy.project import Project

    if isinstance(config, (str, Path)):
        config_path = Path(config).expanduser().resolve()
        with Project.lazy(config_path, headless=kwargs.pop("headless", True)) as project:
            return project.calibrate(config_path=config_path, **kwargs)

    with Project.lazy(config, headless=kwargs.pop("headless", True)) as project:
        return project.calibrate(**kwargs)


def overview(config: Any, **kwargs: Any) -> Any:
    """Functional facade for ``hmp run`` with ``workflow = "overview"``."""
    from hydromodpy.cli.workflows import dispatch_workflow, resolve_workflow

    config_path = Path(config).expanduser().resolve()
    workflow = resolve_workflow(
        config_path,
        cli_workflow="overview",
        require_toml_field=True,
    )
    return dispatch_workflow(workflow, config_path, **kwargs)


def batch(config: Any, **kwargs: Any) -> Any:
    """Functional facade for ``hmp run`` with ``workflow = "batch"``."""
    from hydromodpy.cli.workflows import dispatch_workflow, resolve_workflow

    config_path = Path(config).expanduser().resolve()
    workflow = resolve_workflow(
        config_path,
        cli_workflow="batch",
        require_toml_field=True,
    )
    return dispatch_workflow(workflow, config_path, **kwargs)


def compare_pair(sim_a: Any, sim_b: Any, *, workspace: Any = None) -> Any:
    """Pivot two simulations' metrics side-by-side as a DataFrame."""
    from hydromodpy.analysis.comparison.pairwise import compare_pair as _compare_pair

    return _compare_pair(sim_a, sim_b, workspace=workspace)


def compare_methods(toml_path: Any) -> Any:
    """Run a TOML-driven multi-variant method comparison."""
    from hydromodpy.analysis.comparison.orchestrator import MethodComparisonLauncher

    return MethodComparisonLauncher(toml_path).run()


def mesh(toml_path: Any) -> dict:
    """Functional facade for the mesh-only workflow.

    Mirrors ``hmp run`` for ``workflow = "mesh"`` configs: one call,
    returns the launcher summary dict.
    """
    from hydromodpy.workflow.pipelines.mesh import MeshCatchmentLauncher

    return MeshCatchmentLauncher(Path(toml_path).expanduser().resolve()).run()


def report(session_id_or_prefix: Any = None, *, workspace: Any = None) -> Any:
    """Render the HTML report for a calibration session.

    ``session_id_or_prefix`` accepts a full UUID, a unique hex prefix,
    or ``None`` to fall back to the most recently started session.
    ``workspace`` defaults to the nearest ancestor of the current
    working directory containing ``hydromodpy.duckdb``.
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
