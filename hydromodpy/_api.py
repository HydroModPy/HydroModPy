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
        overview, mesh, testbed, comparison, and calibration workflows return
        their own summary objects.

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


def init_workspace(
    path: Any = None,
    *,
    force: bool = False,
    project_name: str | None = None,
    creator_name: str | None = None,
    creator_email: str | None = None,
) -> dict:
    """Scaffold a HydroModPy workspace (data + projects + ``workspace.toml``).

    Returns a dict with ``path`` and ``workspace_toml``.
    """
    from hydromodpy.core.state.global_index import auto_register_workspace
    from hydromodpy.core.workspace.workspace_toml import write_workspace_toml
    from hydromodpy.data.scaffold import DEFAULT_ROOT, scaffold

    target = Path(path).expanduser().resolve() if path else DEFAULT_ROOT
    if target.exists() and any(target.iterdir()) and not force:
        raise FileExistsError(
            f"Workspace already initialized at {target}. Re-run with force=True to reuse it."
        )
    result = scaffold(target)
    workspace_toml = write_workspace_toml(
        result,
        project_name=project_name or result.name,
        creator_name=creator_name or "",
        creator_email=creator_email or "",
        force=force,
    )
    auto_register_workspace(result, label=project_name or result.name)
    return {"path": str(result), "workspace_toml": str(workspace_toml)}


def list_workspaces() -> Any:
    """List workspaces registered in the machine-wide global index."""
    from hydromodpy.core.state.global_index import GlobalIndex

    with GlobalIndex(read_only=True) as gi:
        return gi.list_workspaces()


def register_workspace(uri: str, *, label: str | None = None) -> str:
    """Register a workspace ``catalog.duckdb`` in the global index.

    Returns the assigned ``workspace_id``.
    """
    from hydromodpy.core.state.global_index import GlobalIndex
    from hydromodpy.core.state.paths import CATALOG_FILENAME
    from hydromodpy.core.state.paths import resolve_workspace as _resolve

    local = _resolve(uri)
    catalog = Path(local) / CATALOG_FILENAME
    if not catalog.is_file():
        raise FileNotFoundError(f"Workspace {uri!r} has no {CATALOG_FILENAME} at {catalog}.")
    with GlobalIndex() as gi:
        return gi.register_workspace(uri, label=label)


def search_workspaces(term: str, *, limit: int = 20) -> Any:
    """Full-text search across registered workspaces."""
    from hydromodpy.core.state.global_index import GlobalIndex

    with GlobalIndex(read_only=True) as gi:
        df = gi.search(term)
    if df is None or df.empty:
        return df
    return df.head(limit)


def forget_workspace(workspace_id: str) -> None:
    """Drop a workspace registration from the global index."""
    from hydromodpy.core.state.global_index import GlobalIndex

    with GlobalIndex() as gi:
        gi.forget(workspace_id)


def prune_workspaces() -> list[str]:
    """Drop registrations whose ``catalog.duckdb`` is missing."""
    from hydromodpy.core.state.global_index import GlobalIndex

    with GlobalIndex() as gi:
        return gi.prune()


def clean_workspace(
    workspace: Any,
    *,
    groups: set[str] | None = None,
    dry_run: bool = True,
) -> dict:
    """Remove generated workspace artefacts.

    ``groups`` selects which artefact families to remove. Default is empty
    (the caller is expected to pass at least one of ``results``,
    ``data_cache``, ``runtime``, ``exports``, ``scratch``, ``figures``, or
    use ``{"all"}``).
    """
    import shutil

    from hydromodpy.cli.helpers import find_workspace_root
    from hydromodpy.core.state.paths import CATALOG_FILENAME

    start = Path(workspace).expanduser().resolve() if workspace else Path.cwd().resolve()
    workspace_root = find_workspace_root(start)
    if not workspace_root.is_dir():
        raise FileNotFoundError(f"Workspace not found: {workspace_root}")

    selected = set(groups or set())
    if "all" in selected or selected == {"all"}:
        selected = {"results", "data_cache", "runtime", "exports", "scratch", "figures"}
    if not selected:
        raise ValueError("Select at least one cleanup group, or pass groups={'all'}.")

    targets: list[Path] = []
    if "results" in selected:
        targets.extend(
            [
                workspace_root / CATALOG_FILENAME,
                workspace_root / f"{CATALOG_FILENAME}.wal",
                workspace_root / "simulations",
            ]
        )
        for project_dir in sorted(workspace_root.glob("projects/*")):
            if project_dir.is_dir():
                targets.extend(
                    [
                        project_dir / CATALOG_FILENAME,
                        project_dir / f"{CATALOG_FILENAME}.wal",
                        project_dir / "simulations",
                    ]
                )
    if "data_cache" in selected:
        targets.extend(
            [
                workspace_root / "data" / "cache.duckdb",
                workspace_root / "data" / "cache.duckdb.wal",
                workspace_root / "data" / "blobs",
            ]
        )
    if "runtime" in selected:
        targets.append(workspace_root / ".hmp")
    if "exports" in selected:
        targets.append(workspace_root / "exports")
    if "scratch" in selected:
        targets.extend(sorted(workspace_root.glob("projects/*/.solver_scratch")))
        targets.append(workspace_root / ".solver_scratch")
    if "figures" in selected:
        targets.extend(sorted(workspace_root.glob("projects/*/figures")))

    seen: set[Path] = set()
    unique: list[Path] = []
    for target in targets:
        resolved = target.resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(target)
    existing = [t for t in unique if t.exists() or t.is_symlink()]

    removed: list[str] = []
    if not dry_run:
        for target in existing:
            resolved_workspace = workspace_root.resolve()
            resolved_target = target.resolve(strict=False)
            if (
                resolved_target == resolved_workspace
                or resolved_workspace not in resolved_target.parents
            ):
                raise ValueError(f"Refusing to delete path outside workspace: {target}")
            if target.is_symlink() or target.is_file():
                target.unlink()
            elif target.is_dir():
                shutil.rmtree(target)
            removed.append(str(target))

    return {
        "workspace": str(workspace_root),
        "candidates": [str(t) for t in existing],
        "removed": removed,
        "dry_run": dry_run,
    }


def create_project(name: str, *, workspace: Any = None) -> Path:
    """Scaffold a new project directory inside a workspace.

    Parameters
    ----------
    name
        Project name (created under ``<workspace>/projects/<name>``).
    workspace
        Workspace root. Defaults to :data:`hydromodpy.data.scaffold.DEFAULT_ROOT`.

    Returns
    -------
    pathlib.Path
        Path to the new project directory.

    Raises
    ------
    FileNotFoundError
        If ``workspace`` does not look like a scaffolded HydroModPy workspace.
    """
    from hydromodpy.data.scaffold import DEFAULT_ROOT
    from hydromodpy.data.scaffold import create_project as _create

    workspace_root = Path(workspace).expanduser().resolve() if workspace else DEFAULT_ROOT
    layout_ok = (workspace_root / "data").is_dir() or (workspace_root / "projects").is_dir()
    if not layout_ok:
        raise FileNotFoundError(
            f"{workspace_root} is not a HydroModPy workspace; run 'hmp workspace init' first"
        )
    return _create(workspace_root, name)


def list_projects(workspace: Any = None) -> list[dict]:
    """List projects inside a workspace.

    Returns a list of dicts (one per project) with ``name``, ``path``,
    ``has_project_toml``, ``run_tomls``.
    """
    import os

    from hydromodpy.cli.helpers import find_workspace_root
    from hydromodpy.core.state.paths import PROJECT_TOML_FILENAME
    from hydromodpy.data.scaffold import DEFAULT_ROOT

    if workspace:
        workspace_root = Path(workspace).expanduser().resolve()
    else:
        ws_override = os.environ.get("HMP_WORKSPACE")
        start = Path(ws_override).expanduser().resolve() if ws_override else Path.cwd()
        found = find_workspace_root(start)
        workspace_root = (
            found
            if (found / "projects").is_dir() or (found / "data").is_dir()
            else Path(DEFAULT_ROOT).expanduser().resolve()
        )

    projects_dir = workspace_root / "projects"
    if not projects_dir.is_dir():
        raise FileNotFoundError(f"No projects/ directory in {workspace_root}")

    out: list[dict] = []
    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        out.append(
            {
                "name": project_dir.name,
                "path": str(project_dir),
                "has_project_toml": (project_dir / PROJECT_TOML_FILENAME).is_file(),
                "run_tomls": [p.name for p in project_dir.glob("run_*.toml")],
            }
        )
    return out


def show_project(name: str, *, workspace: Any = None) -> dict:
    """Return a summary dict for one project (TOMLs + catalog stats)."""
    import os

    from hydromodpy.cli.helpers import find_workspace_root
    from hydromodpy.core.state.paths import CATALOG_FILENAME, PROJECT_TOML_FILENAME
    from hydromodpy.data.scaffold import DEFAULT_ROOT

    if workspace:
        workspace_root = Path(workspace).expanduser().resolve()
    else:
        ws_override = os.environ.get("HMP_WORKSPACE")
        start = Path(ws_override).expanduser().resolve() if ws_override else Path.cwd()
        found = find_workspace_root(start)
        workspace_root = (
            found
            if (found / "projects").is_dir() or (found / "data").is_dir()
            else Path(DEFAULT_ROOT).expanduser().resolve()
        )

    project_dir = workspace_root / "projects" / name
    if not project_dir.is_dir():
        raise FileNotFoundError(f"No such project: {project_dir}")

    payload: dict = {
        "name": name,
        "path": str(project_dir),
        "has_project_toml": (project_dir / PROJECT_TOML_FILENAME).is_file(),
        "run_tomls": [p.name for p in sorted(project_dir.glob("run_*.toml"))],
        "simulations": [],
    }
    db_path = project_dir / CATALOG_FILENAME
    if db_path.exists():
        from hydromodpy.results.catalog import SimulationCatalog, short_id

        try:
            with SimulationCatalog(project_dir) as catalog:
                sims = catalog.list_simulations(order_by="created_at DESC")
            payload["simulations"] = [
                {
                    "sim_id": str(row["sim_id"]),
                    "short_id": short_id(str(row["sim_id"])),
                    "name": row.get("name", "") or "(no name)",
                    "solver": row.get("solver", ""),
                    "status": row.get("status", ""),
                }
                for _, row in sims.iterrows()
            ]
        except Exception as exc:  # pragma: no cover - defensive
            payload["catalog_error"] = str(exc)
    return payload


def delete_project(name: str, *, workspace: Any = None, force: bool = False) -> dict:
    """Delete a project directory (catalog + Zarr + Parquet).

    Returns a dict with ``path``, ``bytes_freed``. Raises if the project does
    not exist. ``force`` is informational only (the CLI layer enforces it).
    """
    import os
    import shutil

    from hydromodpy.cli.helpers import find_workspace_root
    from hydromodpy.data.scaffold import DEFAULT_ROOT

    if workspace:
        workspace_root = Path(workspace).expanduser().resolve()
    else:
        ws_override = os.environ.get("HMP_WORKSPACE")
        start = Path(ws_override).expanduser().resolve() if ws_override else Path.cwd()
        found = find_workspace_root(start)
        workspace_root = (
            found
            if (found / "projects").is_dir() or (found / "data").is_dir()
            else Path(DEFAULT_ROOT).expanduser().resolve()
        )

    project_dir = workspace_root / "projects" / name
    if not project_dir.is_dir():
        raise FileNotFoundError(f"No such project: {project_dir}")

    bytes_freed = 0
    for child in project_dir.rglob("*"):
        try:
            if child.is_file():
                bytes_freed += int(child.stat().st_size)
        except OSError:
            continue
    shutil.rmtree(project_dir)
    return {"path": str(project_dir), "bytes_freed": bytes_freed, "force": force}


def list_simulations(
    workspace: Any,
    *,
    project: str | None = None,
    solver: str | None = None,
    catchment: str | None = None,
    limit: int | None = None,
) -> Any:
    """List simulations recorded in a workspace catalog.

    Iterates over per-project ``catalog.duckdb`` files inside ``workspace``
    and returns a concatenated DataFrame of simulation rows ordered by
    ``created_at DESC``. Filters apply as substring matches on ``solver``
    and ``catchment``, exact match on ``project``.

    Parameters
    ----------
    workspace
        Workspace directory containing a ``projects/`` tree.
    project, solver, catchment, limit
        Optional filters.

    Returns
    -------
    pandas.DataFrame
        Combined simulation rows. Empty when the workspace has no project
        catalog or no row matches the filters.
    """
    from hydromodpy.core.state.paths import CATALOG_FILENAME
    from hydromodpy.results.catalog import SimulationCatalog

    workspace_root = Path(workspace).expanduser().resolve()
    projects_dir = workspace_root / "projects"
    if not projects_dir.is_dir():
        import pandas as pd

        return pd.DataFrame()

    if project:
        project_roots = [projects_dir / project]
    else:
        project_roots = sorted(
            p for p in projects_dir.iterdir() if p.is_dir() and (p / CATALOG_FILENAME).exists()
        )

    import pandas as pd

    frames: list[pd.DataFrame] = []
    for project_dir in project_roots:
        if not (project_dir / CATALOG_FILENAME).exists():
            continue
        with SimulationCatalog(project_dir) as catalog:
            sims = catalog.list_simulations(order_by="created_at DESC")
        if sims.empty:
            continue
        if solver:
            sims = sims[sims["solver"].fillna("").str.contains(solver, case=False)]
        if catchment and "catchment" in sims.columns:
            sims = sims[sims["catchment"].fillna("").str.contains(catchment, case=False)]
        sims = sims.assign(project=project_dir.name)
        frames.append(sims)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    if limit is not None:
        out = out.head(int(limit))
    return out


def show_simulation(
    sim_ref: str,
    *,
    workspace: Any,
    detail: bool = False,
) -> dict:
    """Return a metadata dict describing one simulation.

    Parameters
    ----------
    sim_ref
        Full sim id, unique prefix (>= 4 chars), or simulation name.
    workspace
        Project catalog root.
    detail
        When ``True``, also reports the Zarr store layout (groups, paths).

    Returns
    -------
    dict
        Simulation metadata. Includes ``zarr_path``, ``zarr_exists`` and
        ``zarr_groups`` when ``detail=True``.

    Raises
    ------
    FileNotFoundError
        If the workspace has no ``catalog.duckdb``.
    hydromodpy.results.catalog.SimulationNotFoundError
        If ``sim_ref`` cannot be resolved.
    """
    from hydromodpy.core.state.paths import CATALOG_FILENAME
    from hydromodpy.results.catalog import SimulationCatalog

    workspace_root = Path(workspace).expanduser().resolve()
    if not (workspace_root / CATALOG_FILENAME).exists():
        raise FileNotFoundError(f"No catalog at {workspace_root}")

    with SimulationCatalog(workspace_root) as catalog:
        sid = catalog.resolve(sim_ref)
        sim = catalog[sid]
        payload: dict = {
            "sim_id": sim.sim_id,
            "name": sim.name,
            "project": sim.project,
            "solver": sim.solver,
            "status": sim.status,
            "duration_s": sim.duration_s,
            "n_cells": sim.n_cells,
            "n_timesteps": sim.n_timesteps,
        }
        if detail:
            zarr_path = catalog.zarr_path_for(sid)
            payload["zarr_path"] = str(zarr_path)
            payload["zarr_exists"] = zarr_path.exists()
            groups: list[str] = []
            if zarr_path.exists() and zarr_path.is_dir():
                try:
                    groups = sorted(p.name for p in zarr_path.iterdir() if p.is_dir())[:20]
                except OSError:
                    groups = []
            payload["zarr_groups"] = groups
        return payload


def query_catalog(
    sql: str,
    *,
    workspace: Any,
    limit: int | None = None,
) -> Any:
    """Run a read-only SQL statement against the workspace catalog DuckDB.

    Parameters
    ----------
    sql
        SQL statement (SELECT, PRAGMA, ...).
    workspace
        Project catalog root.
    limit
        Optional outer ``LIMIT`` wrapped around the statement.

    Returns
    -------
    pandas.DataFrame
        Result rows.

    Raises
    ------
    FileNotFoundError
        If the workspace has no ``catalog.duckdb``.
    duckdb.Error
        If the SQL statement is invalid or the catalog rejects it.
    """
    import duckdb

    from hydromodpy.core.state.paths import CATALOG_FILENAME

    workspace_root = Path(workspace).expanduser().resolve()
    catalog_path = workspace_root / CATALOG_FILENAME
    if not catalog_path.exists():
        raise FileNotFoundError(f"No catalog at {workspace_root}")

    statement = sql.strip()
    if limit is not None:
        statement = f"SELECT * FROM ({statement}) LIMIT {int(limit)}"
    conn = duckdb.connect(str(catalog_path), read_only=True)
    try:
        return conn.execute(statement).fetchdf()
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
