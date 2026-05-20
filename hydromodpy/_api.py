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
from typing import TYPE_CHECKING, Any

from hydromodpy.core.version import __version__

if TYPE_CHECKING:
    import geopandas as gpd
    import pandas as pd
    import xarray as xr

    Readable = xr.DataArray | pd.Series | pd.DataFrame | gpd.GeoDataFrame


def open(workspace_path: Any) -> Any:
    """Open a HydroModPy project catalog.

    Mirrors ``xarray.open_dataset`` / ``pandas.read_csv`` in intent: one call,
    a ready-to-query object backed by ``catalog.duckdb``.

    Parameters
    ----------
    workspace_path
        Workspace directory, or a direct path to ``catalog.duckdb``.

    Returns
    -------
    SimulationCatalog
        Catalog object used to find runs, query metadata, and open persisted
        field stores.

    Raises
    ------
    FileNotFoundError
        If ``workspace_path`` does not exist on disk.
    hydromodpy.core.exceptions.CatalogError
        If the DuckDB catalog file is locked, corrupted, or unreadable.
    hydromodpy.results.errors.SchemaVersionMismatchError
        If the stored catalog schema is older than the runtime expects.

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


def open_catalog(workspace: Any = None) -> Any:
    """Open the V1 catalog facade fronting the three DuckDB files.

    Returns a :class:`hydromodpy.catalog.CatalogFacade` exposing the
    ``simulations``, ``inputs`` and ``projects`` namespaces. Usable as a
    context manager.

    Parameters
    ----------
    workspace
        Workspace directory. Defaults to ``HMP_WORKSPACE`` then to the
        current working directory.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> with hmp.open_catalog("~/proj/naizin") as cat:
    ...     sims = cat.simulations.find(solver="modflow6")
    """
    from hydromodpy.catalog import open_catalog as _open

    return _open(workspace)


def index(db_path: Any = None, *, read_only: bool = False) -> Any:
    """Open the machine-wide global index that federates registered workspaces.

    Parameters
    ----------
    db_path
        Optional path to the index DuckDB file. ``None`` uses the default
        machine-state location.
    read_only
        Open the index in read-only mode. Writes (``register_workspace``,
        ``forget``, ``prune``) will raise. Pure reads (``search``, ``find``,
        ``list_workspaces``) keep working while another process holds the
        write-lock.

    Returns
    -------
    GlobalIndex
        Index object exposing ``register_workspace``, ``find``, ``search``,
        ``prune`` and ``forget``.

    Raises
    ------
    RuntimeError
        If a mutating method is called on a read-only handle.
    duckdb.IOException
        If the index database cannot be opened due to non-lock I/O errors.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> idx = hmp.index(read_only=True)
    >>> idx.list_workspaces()

    See Also
    --------
    hydromodpy.core.state.global_index.GlobalIndex
        Underlying federation implementation.
    """
    from pathlib import Path as _Path

    from hydromodpy.core.state.global_index import GlobalIndex

    resolved = _Path(db_path).expanduser().resolve() if db_path is not None else None
    return GlobalIndex(resolved, read_only=read_only)


def run(config: Any, **kwargs: Any) -> Any:
    """Run a HydroModPy workflow from Python.

    Path and config-object inputs converge on the same dispatch. Simulation
    workflows return a :class:`~hydromodpy.results.run.Run` (or ``None`` when
    nothing was persisted, e.g. ``dry_run``). Overview, calibration,
    comparison and testbed workflows return their adapter ``dict`` summary.

    Parameters
    ----------
    config
        TOML path or validated configuration object.
    kwargs
        Runtime options forwarded to the selected workflow. The ``headless``
        keyword is honored on both branches (path and config object) and
        controls the underlying ``Project`` interactive side effects.

    Returns
    -------
    Run or None or dict
        ``Run`` instance (or ``None``) for the ``simulation`` workflow.
        ``dict`` summary for ``overview``, ``calibration``, ``comparison``
        and ``testbed`` workflows.

    Raises
    ------
    FileNotFoundError
        If the TOML path does not exist.
    hydromodpy.core.exceptions.ConfigError
        If the TOML payload fails Pydantic validation.
    hydromodpy.core.exceptions.PipelineError
        If a workflow step raises during execution.
    hydromodpy.core.exceptions.SolverError
        If the configured solver fails to converge or crashes.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> run = hmp.run("run_transient_nwt.toml", name="baseline")

    See Also
    --------
    hydromodpy.project.Project.run
        Object-oriented form for repeated runs from one project.
    """
    headless = bool(kwargs.pop("headless", False))

    if isinstance(config, (str, Path)):
        from hydromodpy.project.dispatch.workflow import dispatch_workflow
        from hydromodpy.workflow.dispatch import resolve_workflow

        config_path = Path(config).expanduser().resolve()
        workflow = resolve_workflow(
            config_path,
            cli_workflow=None,
            require_toml_field=True,
        )
        return dispatch_workflow(workflow, config_path, **kwargs)

    from hydromodpy.project import Project

    with Project(config, headless=headless) as project:
        return project.run(**kwargs)


def calibrate(config: Any, **kwargs: Any) -> Any:
    """Run a calibration workflow from a TOML file or config object.

    Paths route directly to :func:`run_calibration_cli`; in-memory config
    objects open a lazy :class:`Project` so :func:`run_calibration_programmatic`
    has the project context it requires.

    Parameters
    ----------
    config
        Calibration TOML path or validated configuration object.
    kwargs
        Options forwarded to the underlying calibration runner. The
        ``headless`` keyword controls the project initialization for the
        in-memory config branch and is ignored for the TOML branch (which
        builds no project).

    Returns
    -------
    Any
        Calibration report or workflow-specific result.

    Raises
    ------
    FileNotFoundError
        If the calibration TOML path does not exist.
    hydromodpy.core.exceptions.ConfigMissingError
        If neither ``config_path`` nor ``parameters`` is supplied.
    hydromodpy.core.exceptions.CalibrationError
        If the optimizer or objective evaluation fails.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> report = hmp.calibrate("calibration.toml")

    See Also
    --------
    hydromodpy.calibration.runner.run_calibration_cli
        TOML entry point used by the path branch.
    hydromodpy.calibration.runner.run_calibration_programmatic
        Python entry point used by the config-object branch.
    hydromodpy.calibration.CalibrationReport
        Structured calibration result.
    """
    if isinstance(config, (str, Path)):
        from hydromodpy.calibration.runner import run_calibration_cli

        kwargs.pop("headless", None)
        return run_calibration_cli(Path(config).expanduser().resolve(), **kwargs)

    from hydromodpy.project import Project

    headless = bool(kwargs.pop("headless", True))
    with Project.lazy(config, headless=headless) as project:
        return project.calibrate(**kwargs)


def overview(config: Any, **kwargs: Any) -> Any:
    """Run the overview workflow declared by a TOML file.

    Parameters
    ----------
    config
        TOML file containing ``[workflow] mode = "overview"``.
    kwargs
        Runtime options forwarded to the workflow dispatcher.

    Returns
    -------
    Any
        Overview workflow summary.

    Raises
    ------
    FileNotFoundError
        If the TOML path does not exist.
    hydromodpy.core.exceptions.ConfigError
        If the TOML payload fails validation or has the wrong workflow mode.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> hmp.overview("overview.toml")
    """
    from hydromodpy.project.dispatch.workflow import dispatch_workflow
    from hydromodpy.workflow.dispatch import resolve_workflow

    config_path = Path(config).expanduser().resolve()
    workflow = resolve_workflow(
        config_path,
        cli_workflow="overview",
        require_toml_field=True,
    )
    return dispatch_workflow(workflow, config_path, **kwargs)


def compare(config: Any) -> Any:
    """Run the comparison workflow declared by a TOML file.

    Equivalent to ``hmp run cmp.toml`` when the file declares
    ``[workflow] mode = "comparison"``. For pairwise metric tables between two
    persisted simulations, see :func:`compare_pair`.

    Parameters
    ----------
    config
        TOML file containing ``[workflow] mode = "comparison"``.

    Returns
    -------
    Any
        Comparison workflow summary.

    Raises
    ------
    FileNotFoundError
        If the TOML path does not exist.
    hydromodpy.core.exceptions.ConfigError
        If the TOML payload fails validation or has the wrong workflow mode.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> hmp.compare("comparison.toml")

    See Also
    --------
    compare_pair
        Pairwise metric comparison between two already-persisted simulations.
    """
    from hydromodpy.project.dispatch.workflow import dispatch_workflow
    from hydromodpy.workflow.dispatch import resolve_workflow

    config_path = Path(config).expanduser().resolve()
    workflow = resolve_workflow(
        config_path,
        cli_workflow="comparison",
        require_toml_field=True,
    )
    return dispatch_workflow(workflow, config_path)


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

    Raises
    ------
    hydromodpy.results.errors.RunNotFoundError
        If either simulation id cannot be resolved in the workspace.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> table = hmp.compare_pair("ab12cd34", "ef56gh78", workspace="~/hmp_workspace")

    See Also
    --------
    hydromodpy.analysis.comparison
        Comparison package used by this helper.
    """
    from hydromodpy.analysis.comparison.pairwise import compare_pair as _compare_pair

    return _compare_pair(sim_a, sim_b, workspace=workspace)


def testbed(toml_path: Any) -> Any:
    """Run a TOML-driven method testbed.

    Delegates to the workflow dispatcher (``run_testbed``) so the launcher
    resolution (``TestbedLauncher`` vs ``RegionalLabProfileLauncher``) matches
    the CLI path. The profile is read from the TOML payload.

    Parameters
    ----------
    toml_path
        Testbed configuration path.

    Returns
    -------
    Any
        Testbed launcher result.

    Raises
    ------
    FileNotFoundError
        If ``toml_path`` does not exist on disk.
    hydromodpy.core.exceptions.ConfigError
        If the testbed TOML fails validation.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> hmp.testbed("testbed_methods.toml")
    """
    from hydromodpy.project.dispatch.workflow import run_testbed

    return run_testbed(Path(toml_path).expanduser().resolve())


def mesh(toml_path: Any) -> dict:
    """Run the standalone mesh launcher from a TOML file.

    This is a direct API for single mesh artifacts. Public ``hmp run`` configs
    should model mesh-only work as ``[workflow] mode = "simulation"`` with a
    ``[[simulation.process]]`` block whose ``type`` is ``"mesh"``.

    Parameters
    ----------
    toml_path
        Standalone mesh launcher TOML path.

    Returns
    -------
    dict
        Mesh launcher summary.

    Raises
    ------
    FileNotFoundError
        If ``toml_path`` does not exist on disk.
    hydromodpy.core.exceptions.MeshGenerationError
        If the mesh generator (gmsh / FloPy helper) fails to build a mesh.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> summary = hmp.mesh("mesh_only.toml")
    """
    from hydromodpy.workflow.pipelines.mesh import MeshCatchmentLauncher

    return MeshCatchmentLauncher(Path(toml_path).expanduser().resolve()).run()


def report(session_id_or_prefix: Any = None, *, workspace: Any = None) -> Any:
    """Render the HTML report for a calibration session.

    ``session_id_or_prefix`` accepts a full UUID, a unique hex prefix,
    or ``None`` to fall back to the most recently started session.
    ``workspace`` defaults to the nearest ancestor of the current
    working directory containing ``catalog.duckdb``.

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

    Raises
    ------
    hydromodpy.results.errors.RunNotFoundError
        If no calibration session matches ``session_id_or_prefix``.
    hydromodpy.core.exceptions.DisplayError
        If the report template or one of its figures fails to render.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> hmp.report()  # latest session in the current workspace
    >>> hmp.report("ab12cd34", workspace="~/hmp_workspace")
    """
    from hydromodpy.calibration.report import resolve_calibration_session_id
    from hydromodpy.core.state.paths import CATALOG_FILENAME
    from hydromodpy.results.catalog import SimulationCatalog
    from hydromodpy.workflow.steps.calibration import step_render_calibration_report

    if workspace is None:
        workspace_root = Path.cwd()
        for parent in [workspace_root] + list(workspace_root.parents):
            if (parent / CATALOG_FILENAME).exists():
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


def read(
    sim: Any,
    var: str,
    *,
    time: int | slice | None = None,
    layer: int | None = None,
    sel: dict | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    lazy: bool | None = None,
) -> Any:
    """Read a variable from a simulation with auto-dispatch.

    Single entry point for reads: dispatches on the variable kind via the
    canonical :mod:`hydromodpy.results.field_registry` (Zarr fields), the
    DuckDB ``timeseries`` table, and the GeoParquet ``geographic_features``
    table.

    Return type depends on the storage kind AND on the ``time``/``layer``
    selectors when reading a Zarr field:

    +----------------+--------------------+------------------------+----------------------+
    | storage        | time / layer       | ``lazy`` value         | return type          |
    +================+====================+========================+======================+
    | Zarr field     | both ``None``      | ``None`` or ``True``   | ``xr.DataArray``     |
    +----------------+--------------------+------------------------+----------------------+
    | Zarr field     | ``slice`` only     | ``None`` or ``True``   | ``xr.DataArray``     |
    +----------------+--------------------+------------------------+----------------------+
    | Zarr field     | ``time`` is ``int``| ``None`` (auto)        | ``np.ndarray``       |
    +----------------+--------------------+------------------------+----------------------+
    | Zarr field     | any                | ``True``               | ``xr.DataArray``     |
    +----------------+--------------------+------------------------+----------------------+
    | Zarr field     | any                | ``False``              | ``np.ndarray``       |
    +----------------+--------------------+------------------------+----------------------+
    | timeseries     | n/a                | any                    | ``pd.Series``        |
    +----------------+--------------------+------------------------+----------------------+
    | geo. feature   | n/a                | any                    | ``gpd.GeoDataFrame`` |
    +----------------+--------------------+------------------------+----------------------+

    Parameters
    ----------
    sim
        :class:`hydromodpy.results.run.Run` or simulation id resolvable
        through a :class:`SimulationCatalog`. When passing an id, callers
        must have set the catalog through ``sim=("sim_id", catalog)``.
    var
        Variable name. Looked up against ``field_registry`` first, then
        against the DuckDB timeseries variables, then against the
        ``geographic_features`` table.
    time
        Timestep index (``int``) or slice for Zarr fields. ``None`` means
        load every persisted timestep (lazy).
    layer
        Optional layer index for three-dimensional fields.
    sel
        Optional kwargs forwarded to the appropriate reader:
        ``{"station": ...}`` for timeseries, ``{"feature_name": ...}`` for
        geographic features.
    bbox
        Optional ``(xmin, ymin, xmax, ymax)`` in the simulation CRS;
        restricts Zarr fields to faces whose centroid lies in the box.
    lazy
        Force the return type for Zarr fields. ``True`` -> always
        ``xr.DataArray`` (load values manually via ``.values``); ``False``
        -> always ``np.ndarray`` (eager load); ``None`` -> auto (eager
        when ``time`` is an int, lazy otherwise). Ignored for timeseries
        and geographic features.

    Returns
    -------
    object
        See the table above for the resolved return type.

    Raises
    ------
    TypeError
        If ``sim`` is not a :class:`Run` instance.
    hydromodpy.results.errors.FieldNotFoundError
        If ``var`` could not be resolved by any backend.
    hydromodpy.results.errors.RunNotFoundError
        If the underlying run row was deleted between catalog open and read.
    hydromodpy.results.errors.SchemaVersionMismatchError
        If the on-disk Zarr or Parquet schema is older than the runtime.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> catalog = hmp.open("~/hmp_workspace")
    >>> run = catalog.latest()
    >>> da = hmp.read(run, "head")  # xr.DataArray lazy
    >>> arr = hmp.read(run, "head", time=-1, layer=0)  # numpy via DataArray
    >>> da2 = hmp.read(run, "head", time=-1, lazy=True)  # force DataArray
    >>> arr2 = hmp.read(run, "head", lazy=False)  # force eager ndarray
    >>> ts = hmp.read(run, "discharge", sel={"station": "outlet"})
    >>> gdf = hmp.read(run, "watershed_polygon")  # geographic feature
    """
    from hydromodpy.results import field_registry
    from hydromodpy.results.errors import FieldNotFoundError
    from hydromodpy.results.run import Run

    if not isinstance(sim, Run):
        raise TypeError(
            f"hmp.read expects a Run object as first argument, got {type(sim).__name__}"
        )

    sel_kw: dict = dict(sel or {})

    if field_registry.has(var):
        return _read_zarr_field(sim, var, time=time, layer=layer, bbox=bbox, lazy=lazy)

    if _has_timeseries_var(sim, var):
        station = sel_kw.pop("station", None)
        period = sel_kw.pop("period", None)
        return sim.timeseries(var, station=station, period=period)

    if _has_geographic_feature(sim, var):
        return sim.geographic(var)

    available = ", ".join(sorted(field_registry.all_names()))
    raise FieldNotFoundError(
        f"Variable '{var}' not found in any backend (field_registry, timeseries, "
        f"geographic_features). Known field-registry names: {available}.",
        sim_id=sim.sim_id,
        variable=var,
    )


def _read_zarr_field(
    sim: Any,
    var: str,
    *,
    time: int | slice | None,
    layer: int | None,
    bbox: tuple[float, float, float, float] | None,
    lazy: bool | None,
) -> Any:
    """Dispatch a Zarr field read to the lazy xarray loader.

    ``lazy`` controls the return type:

    - ``None`` (auto): eager ``np.ndarray`` when ``time`` is an int (single
      timestep selection), lazy ``xr.DataArray`` otherwise.
    - ``True``: always return an ``xr.DataArray`` (call ``.values`` for the
      eager numpy equivalent).
    - ``False``: always return an ``np.ndarray`` (eager load).
    """
    if lazy is False:
        if isinstance(time, int):
            return sim.field(var, timestep=time, layer=layer, bbox=bbox)
        da = sim.array.to_xarray_batch((var,), bbox=bbox)[var]
        if isinstance(time, slice):
            da = da.isel(time=time)
        if layer is not None and "layer" in da.dims:
            da = da.isel(layer=layer)
        import numpy as np

        return np.asarray(da.values)

    if lazy is True or not isinstance(time, int):
        da = sim.array.to_xarray_batch((var,), bbox=bbox)[var]
        if isinstance(time, int):
            da = da.isel(time=time)
        elif isinstance(time, slice):
            da = da.isel(time=time)
        if layer is not None and "layer" in da.dims:
            da = da.isel(layer=layer)
        return da

    return sim.field(var, timestep=time, layer=layer, bbox=bbox)


def _has_timeseries_var(sim: Any, variable: str) -> bool:
    """True when ``variable`` appears in the simulation ``timeseries`` table."""
    df = sim._catalog.backend.query(
        "SELECT 1 FROM timeseries WHERE sim_id = ? AND variable = ? LIMIT 1",
        [sim.sim_id, variable],
    )
    return not df.empty


def _has_geographic_feature(sim: Any, feature_name: str) -> bool:
    """True when ``feature_name`` is a persisted geographic feature."""
    try:
        names = sim._catalog.list_geographic_features(sim.sim_id)
    except Exception:
        return False
    return feature_name in names


def audit_prune(workspace: Any = None, *, apply: bool = False) -> dict[str, int]:
    """Apply ``retention_policies`` to ``audit_log`` for the workspace catalog.

    Parameters
    ----------
    workspace
        Path to a workspace or project directory. Resolved via
        :func:`hydromodpy.cli.helpers.find_catalog_root` so any path under
        the project tree works. ``None`` resolves to the current directory.
    apply
        ``False`` (default) counts rows that would be removed without
        modifying the file. ``True`` actually deletes rows.

    Returns
    -------
    dict[str, int]
        Mapping ``event_type -> rows_affected``. Empty when no retention
        policy is registered.

    Raises
    ------
    FileNotFoundError
        If the workspace does not host a ``catalog.duckdb``.
    """
    import duckdb

    from hydromodpy.cli.helpers import find_catalog_root
    from hydromodpy.core.state.paths import CATALOG_FILENAME
    from hydromodpy.results.catalog.audit import apply_retention

    workspace_root = find_catalog_root(
        Path(workspace).expanduser().resolve() if workspace else Path.cwd().resolve()
    )
    catalog_path = workspace_root / CATALOG_FILENAME
    if not catalog_path.is_file():
        raise FileNotFoundError(f"No catalog at {workspace_root}")
    conn = duckdb.connect(str(catalog_path))
    try:
        return apply_retention(conn, dry_run=not apply)
    finally:
        conn.close()


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
