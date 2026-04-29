"""Public entry points for HydroModPy."""

import importlib

from hydromodpy.core.io.proj_bootstrap import bootstrap_proj
from hydromodpy.core.version import __version__

__author__ = "Alexandre Gauvain, Ronan Abherve, Jean-Raynald de Dreuzy"
__email__ = (
    "alexandre.gauvain.ag@gmail.com, ronan.abherve@gmail.com, jean-raynald.de-dreuzy@univ-rennes.fr"
)

# Initialize logging system
from hydromodpy.core.logging import LogManager

_log_manager = LogManager(mode="verbose", log_dir=None, overwrite=False)
# Public access to log manager for users
log_manager = _log_manager

# Resolve HydroModPyConfig forward references (sibling configs imported here,
# never from core/config/, to keep core/ a leaf of the import DAG).
from hydromodpy._bootstrap import bootstrap

bootstrap()

_MODULE_EXPORTS = {
    "analysis": "hydromodpy.analysis",
    "calibration": "hydromodpy.calibration",
    "core": "hydromodpy.core",
    "data": "hydromodpy.data",
    "physics": "hydromodpy.physics",
    "results": "hydromodpy.results",
    "simulation": "hydromodpy.simulation",
    "solver": "hydromodpy.solver",
    "spatial": "hydromodpy.spatial",
}

_LAZY_IMPORTS = {
    # Spatial / geographic
    "CatchmentDelineation": "hydromodpy.spatial.geographic.catchment_delineation",
    "GeographicConfig": "hydromodpy.spatial.geographic.geographic_config",
    "Subbasin": "hydromodpy.spatial.geographic.subbasin",
    "HydroMesh": "hydromodpy.spatial.mesh.hydro_mesh",
    "DomainConfig": "hydromodpy.spatial.domain.domain_config",
    # Processes (factories expose FlowConfig/TransportConfig)
    "FlowConfig": "hydromodpy.physics.flow.flow_config",
    "FlowProcess": "hydromodpy.physics.flow.flow:Flow",
    "TransportConfig": "hydromodpy.physics.transport.transport_config",
    "TransportProcess": "hydromodpy.physics.transport.transport:Transport",
    # Solvers
    "Modflow": "hydromodpy.solver.modflow_nwt",
    "Modflow6": "hydromodpy.solver.modflow6.modflow6",
    "Modpath": "hydromodpy.solver.modflow_nwt",
    "Mt3dms": "hydromodpy.solver.modflow_nwt",
    "Boussinesq": "hydromodpy.solver.boussinesq.boussinesq",
    # Core infrastructure
    "Workspace": "hydromodpy.core.workspace",
    "WorkspaceConfig": "hydromodpy.core.workspace",
    "HydroModPyConfig": "hydromodpy.core.config.hydromodpy_config",
    # Simulation orchestration
    "SimulationConfig": "hydromodpy.simulation.planning.config",
    # Data variables (public surface)
    "DataManagersConfig": "hydromodpy.data.data_managers_config",
    "RechargeConfig": "hydromodpy.data.variables.recharge.config",
    "HydrometryConfig": "hydromodpy.data.variables.hydrometry.config",
    "PiezometryConfig": "hydromodpy.data.variables.piezometry.config",
    "GeologyConfig": "hydromodpy.data.variables.geology.config",
    "DemConfig": "hydromodpy.data.variables.dem.config",
    "HydrographyConfig": "hydromodpy.data.variables.hydrography.config",
    "HydrographyManager": "hydromodpy.data.variables.hydrography.manager",
    "HydrographyResult": "hydromodpy.data.variables.hydrography.result",
    "IntermittencyConfig": "hydromodpy.data.variables.intermittency.config",
    "IntermittencyManager": "hydromodpy.data.variables.intermittency.manager",
    "OceanicConfig": "hydromodpy.data.variables.oceanic",
    "OceanicManager": "hydromodpy.data.variables.oceanic",
    # Project / run API (programmatic façade)
    "Project": "hydromodpy.project",
    "SimulationPlan": "hydromodpy.simulation.planning.plan",
    # Catalog API
    "Catalog": "hydromodpy.results.catalog:SimulationCatalog",
    "SimulationCatalog": "hydromodpy.results.catalog",
    "SimulationGroup": "hydromodpy.results.simulation_group",
    "Run": "hydromodpy.results.run",
}


def __getattr__(name):
    if name in _MODULE_EXPORTS:
        module = importlib.import_module(_MODULE_EXPORTS[name])
        globals()[name] = module
        return module
    if name in _LAZY_IMPORTS:
        target = _LAZY_IMPORTS[name]
        if ":" in target:
            module_path, attr_name = target.split(":", 1)
        else:
            module_path, attr_name = target, name
        module = importlib.import_module(module_path)
        attr = getattr(module, attr_name)
        globals()[name] = attr
        return attr
    raise AttributeError(f"module 'hydromodpy' has no attribute {name!r}")


def open(workspace_path):
    """Open a HydroModPy workspace and return the unified catalog.

    Mirrors ``xarray.open_dataset`` / ``pandas.read_csv`` in intent: one call,
    a ready-to-query object backed by ``hydromodpy.duckdb``.
    """
    from hydromodpy.results.catalog import SimulationCatalog

    return SimulationCatalog(workspace_path)


def run(config, **kwargs):
    """Functional façade for ``hmp.Project(config).run()``.

    Keeps CLI and Python API in sync: ``hmp run config.toml`` and
    ``hmp.run("config.toml")`` execute the same workflow.
    """
    from hydromodpy.project import Project

    with Project(config, headless=kwargs.pop("headless", False)) as project:
        return project.run(**kwargs)


def calibrate(config, **kwargs):
    """Functional façade for a calibration session driven by a TOML config."""
    from pathlib import Path

    from hydromodpy.calibration.cli import run_calibration_cli

    return run_calibration_cli(Path(config).expanduser().resolve(), **kwargs)


def compare_pair(sim_a, sim_b, *, workspace=None):
    """Pivot two simulations' metrics side-by-side as a DataFrame."""
    from hydromodpy.analysis.comparison.pairwise import compare_pair as _compare_pair

    return _compare_pair(sim_a, sim_b, workspace=workspace)


def compare_methods(toml_path):
    """Run a TOML-driven multi-variant method comparison."""
    from hydromodpy.analysis.comparison.orchestrator import MethodComparisonLauncher

    return MethodComparisonLauncher(toml_path).run()


def mesh(toml_path):
    """Functional facade for the mesh-only workflow.

    Mirrors ``hmp run`` for ``workflow = "mesh"`` configs: one call,
    returns the launcher summary dict.
    """
    from pathlib import Path

    from hydromodpy.workflow.pipelines.mesh import MeshCatchmentLauncher

    return MeshCatchmentLauncher(Path(toml_path).expanduser().resolve()).run()


def report(session_id_or_prefix=None, *, workspace=None):
    """Render the HTML report for a calibration session.

    ``session_id_or_prefix`` accepts a full UUID, a unique hex prefix,
    or ``None`` to fall back to the most recently started session.
    ``workspace`` defaults to the nearest ancestor of the current
    working directory containing ``hydromodpy.duckdb``.
    """
    from pathlib import Path

    from hydromodpy.calibration.report import resolve_calibration_session_id
    from hydromodpy.results.catalog import SimulationCatalog
    from hydromodpy.workflow.steps.calibration_report import (
        step_render_calibration_report,
    )

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


__all__ = [
    # Entry points
    "open",
    "run",
    "calibrate",
    "compare_pair",
    "compare_methods",
    "mesh",
    "report",
    "bootstrap_proj",
    "doctor",
    # Core infrastructure
    "Workspace",
    "WorkspaceConfig",
    "HydroModPyConfig",
    # Spatial / physics
    "CatchmentDelineation",
    "GeographicConfig",
    "HydroMesh",
    "DomainConfig",
    "Subbasin",
    "FlowConfig",
    "TransportConfig",
    # Solvers
    "Modflow",
    "Modflow6",
    "Modpath",
    "Mt3dms",
    "Boussinesq",
    # Project / run / catalog API
    "Project",
    "Run",
    "SimulationPlan",
    "Catalog",
    "SimulationCatalog",
    "SimulationGroup",
    # Data variables
    "HydrometryConfig",
    "PiezometryConfig",
    "HydrographyConfig",
    "HydrographyManager",
    "HydrographyResult",
    "IntermittencyConfig",
    "IntermittencyManager",
    "OceanicConfig",
    "OceanicManager",
    # Sub-modules
    "analysis",
    "calibration",
    "core",
    "data",
    "physics",
    "results",
    "simulation",
    "solver",
    "spatial",
    # Misc
    "log_manager",
    "__version__",
]


def doctor() -> dict:
    """Lightweight environment diagnostic.

    Returns a dict describing Python, hydromodpy, and solver versions. Designed
    to be quick (no actual solver invocation) and safe to call at import
    probing time.
    """
    import platform
    import shutil

    report: dict = {
        "python": platform.python_version(),
        "hydromodpy": __version__,
        "solvers": {},
        "optional": {},
    }
    for pkg in ("flopy", "gmsh", "duckdb", "zarr", "pyproj", "rasterio"):
        try:
            mod = importlib.import_module(pkg)
            report["optional"][pkg] = getattr(mod, "__version__", "?")
        except Exception:
            report["optional"][pkg] = None
    for exe in ("mf2005", "mfnwt", "mf6"):
        report["solvers"][exe] = shutil.which(exe)
    return report
