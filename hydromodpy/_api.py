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


def export_schema(output_dir: Any) -> dict:
    """Export the HydroModPy JSON Schema + companion files for frontend hooks."""
    from hydromodpy.schema import export_full_schema

    out_path = Path(output_dir).expanduser().resolve()
    out_path.mkdir(parents=True, exist_ok=True)
    return export_full_schema(out_path)


def validate_field(path: str, value: str, *, context: dict | None = None) -> dict:
    """Validate one configuration field value without loading a full config."""
    from hydromodpy.schema import validate_field as _validate

    return _validate(path, value, context=context).as_dict()


def rank_simulations(
    project: str,
    *,
    workspace: Any = None,
    metric: str = "nse",
    top: bool = True,
    n: int = 5,
) -> Any:
    """Rank simulations of one project by a metric. Returns a DataFrame."""
    from hydromodpy.cli.helpers import find_catalog_root
    from hydromodpy.results.catalog import SimulationCatalog

    workspace_root = find_catalog_root(
        Path(workspace).expanduser().resolve() if workspace else Path.cwd().resolve()
    )
    with SimulationCatalog(workspace_root) as catalog:
        order = "DESC" if top else "ASC"
        sql = (
            "SELECT s.sim_id, s.name, s.solver, m.metric_name, m.value "
            "FROM simulations s JOIN metrics m ON s.sim_id = m.sim_id "
            "WHERE s.project = ? AND m.metric_name = ? "
            f"ORDER BY m.value {order} LIMIT ?"
        )
        return catalog.connection.execute(sql, [project, metric, int(n)]).fetchdf()


def install_binaries(
    *,
    subset: list[str] | None = None,
    mf6_prt: bool = False,
    bindir: Any = None,
    upgrade: bool = False,
) -> dict:
    """Pre-warm the MODFLOW / MODPATH / MT3D-USGS binary cache."""
    from hydromodpy.core.binaries import install as install_impl

    return install_impl(
        subset=subset,
        mf6_prt=mf6_prt,
        bindir=Path(bindir).expanduser().resolve() if bindir else None,
        upgrade=upgrade,
    )


def lock_update(workspace: Any = None, *, output: Any = None) -> Path:
    """Scan the cache and write/update the workspace lockfile."""
    from hydromodpy.cli.helpers import resolve_workspace as _resolve_ws
    from hydromodpy.config.schema_export import schema_sha256
    from hydromodpy.data.data_freeze import LOCKFILE_NAME, write_lockfile
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB
    from hydromodpy.results.parquet_schemas import PARQUET_SCHEMA_VERSION
    from hydromodpy.results.zarr_store.constants import ZARR_SCHEMA_VERSION

    workspace_root = _resolve_ws(str(workspace) if workspace else None)
    db_path = workspace_root / "data" / "cache.duckdb"
    dest = Path(output).expanduser().resolve() if output else (workspace_root / LOCKFILE_NAME)
    with DataCatalogDuckDB(db_path) as catalog:
        return write_lockfile(
            catalog,
            dest,
            schema_sha256=schema_sha256(),
            zarr_schema_version=str(ZARR_SCHEMA_VERSION),
            parquet_schema_version=str(PARQUET_SCHEMA_VERSION),
        )


def lock_archive(output: Any, *, workspace: Any = None) -> Path:
    """Create a portable archive of the lockfile + cache artefacts."""
    from hydromodpy.cli.helpers import resolve_workspace as _resolve_ws
    from hydromodpy.data.data_freeze import archive_lockfile
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

    workspace_root = _resolve_ws(str(workspace) if workspace else None)
    db_path = workspace_root / "data" / "cache.duckdb"
    dest = Path(output).expanduser().resolve()
    with DataCatalogDuckDB(db_path) as catalog:
        archive_lockfile(catalog, dest)
    return dest


def lock_restore(source: Any, *, workspace: Any = None, output: Any = None) -> Path:
    """Restore a lockfile archive and verify SHA-256."""
    from hydromodpy.cli.helpers import resolve_workspace as _resolve_ws
    from hydromodpy.data.data_freeze import restore_archive

    workspace_root = _resolve_ws(str(workspace) if workspace else None)
    src = Path(source).expanduser().resolve()
    dest_dir = (
        Path(output).expanduser().resolve() if output else (workspace_root / "data" / "restored")
    )
    restore_archive(src, dest_dir)
    return dest_dir


def lock_verify(
    workspace: Any = None,
    *,
    lockfile: Any = None,
    strict: bool = False,
) -> dict:
    """Verify the cache matches the lockfile."""
    from hydromodpy.cli.helpers import resolve_workspace as _resolve_ws
    from hydromodpy.config.schema_export import schema_sha256
    from hydromodpy.data.data_freeze import (
        LOCKFILE_NAME,
        read_lockfile_schema_sha256,
        verify_frozen,
        verify_inputs_strict,
    )
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

    workspace_root = _resolve_ws(str(workspace) if workspace else None)
    db_path = workspace_root / "data" / "cache.duckdb"
    lockfile_path = (
        Path(lockfile).expanduser().resolve() if lockfile else (workspace_root / LOCKFILE_NAME)
    )
    if not lockfile_path.is_file():
        raise FileNotFoundError(f"Lockfile not found: {lockfile_path}")

    locked_schema = read_lockfile_schema_sha256(lockfile_path)
    current_schema = schema_sha256()
    schema_diverged = locked_schema is not None and locked_schema != current_schema

    with DataCatalogDuckDB(db_path) as catalog:
        mismatches = (
            verify_inputs_strict(catalog, lockfile_path)
            if strict
            else verify_frozen(catalog, lockfile_path)
        )
    return {
        "ok": not mismatches,
        "mismatches": mismatches,
        "schema_diverged": schema_diverged,
        "locked_schema": locked_schema,
        "current_schema": current_schema,
    }


def config_template(
    output: Any,
    *,
    profile: str = "user",
    modules: list[str] | None = None,
    list_modules: bool = False,
) -> Any:
    """Generate a TOML configuration template (or list module names)."""
    from hydromodpy.config.template import generate_template, list_available_modules

    if list_modules:
        return list_available_modules()
    dest = Path(output).expanduser().resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    return generate_template(dest, profile=profile, modules=modules)


def config_check(toml_path: Any) -> dict:
    """Validate a TOML payload against the Pydantic schema."""
    from hydromodpy.config import HydroModPyConfig

    target = Path(toml_path).expanduser().resolve()
    if not target.is_file():
        raise FileNotFoundError(f"Config not found: {target}")
    try:
        HydroModPyConfig.from_toml(target)
    except Exception as exc:  # noqa: BLE001 - surfaced to caller
        return {"path": str(target), "ok": False, "errors": [str(exc)]}
    return {"path": str(target), "ok": True, "errors": []}


def run_tests(
    *,
    fast: bool = False,
    integration: bool = False,
    validation: bool = False,
    e2e: bool = False,
    extra: list[str] | None = None,
) -> int:
    """Invoke pytest with matching markers. Returns the pytest exit code."""
    import subprocess
    import sys as _sys

    markers: list[str] = []
    if fast:
        markers.append("fast")
    if integration:
        markers.append("integration")
    if validation:
        markers.append("validation")
    if e2e:
        markers.append("e2e")
    cmd = [_sys.executable, "-m", "pytest"]
    if markers:
        cmd.extend(["-m", " or ".join(markers)])
    if extra:
        cmd.extend(extra)
    completed = subprocess.run(cmd, check=False)
    return completed.returncode


def render_figure(
    sim_ref: str,
    figure: str,
    *,
    workspace: Any = None,
    output: Any = None,
) -> Path:
    """Render one registered figure for a simulation. Returns the output path."""
    from hydromodpy.cli.helpers import find_catalog_root
    from hydromodpy.display import get as get_figure
    from hydromodpy.results.catalog import SimulationCatalog

    workspace_root = find_catalog_root(
        Path(workspace).expanduser().resolve() if workspace else Path.cwd().resolve()
    )
    with SimulationCatalog(workspace_root) as catalog:
        sim = catalog[sim_ref]
        save = (
            Path(output).expanduser().resolve()
            if output
            else Path.cwd() / "figures" / f"{figure}.png"
        )
        save.parent.mkdir(parents=True, exist_ok=True)
        get_figure(figure).plot(sim, save_path=save)
        return save


def render_gallery(
    config_toml: Any,
    *,
    run_name: str | None = None,
    sim_ref: str | None = None,
    all_runs: bool = False,
    latest: int | None = None,
    only: list[str] | None = None,
    no_show: bool = False,
) -> list[Path]:
    """Render the ``[display]`` figure gallery for one or several runs."""
    from hydromodpy.core.toml_io.loader import load_toml_with_base_config
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.display.runs import render_figures_for_run, resolve_run_output_dir
    from hydromodpy.results.catalog import SimulationCatalog

    target_path = Path(config_toml).expanduser()
    if not target_path.is_file() or target_path.suffix != ".toml":
        raise ValueError(f"Expected a TOML file: {target_path}")

    raw_toml = load_toml_with_base_config(target_path)
    display_cfg = DisplayConfig.model_validate(raw_toml.get("display", {}))
    if no_show:
        display_cfg.show = False
    project_dir = target_path.parent.resolve()
    config_source = str(target_path.resolve())

    written_paths: list[Path] = []
    with SimulationCatalog(project_dir) as catalog:
        sims = catalog.list_simulations(config_source=config_source, order_by="created_at DESC")
        if sims.empty:
            sims = catalog.list_simulations(project=project_dir.name, order_by="created_at DESC")
        if sims.empty:
            raise FileNotFoundError(f"No simulations found for {target_path.name}.")

        if sim_ref:
            ref = sim_ref.lower()
            matches = [
                str(sid) for sid in sims["sim_id"].astype(str) if str(sid).lower().startswith(ref)
            ]
            if not matches:
                raise FileNotFoundError(f"No run matches sim_ref {sim_ref!r}")
            if len(matches) > 1:
                raise ValueError(f"sim_ref {sim_ref!r} is ambiguous")
            ids = matches
        elif run_name:
            subset = sims[sims["name"] == run_name]
            if subset.empty:
                raise FileNotFoundError(f"No run named {run_name!r}")
            ids = [str(sid) for sid in subset["sim_id"].tolist()]
        elif all_runs:
            ids = [str(sid) for sid in sims["sim_id"].tolist()]
        elif latest is not None and latest > 0:
            ids = [str(sid) for sid in sims["sim_id"].tolist()[:latest]]
        else:
            ids = [str(sims.iloc[0]["sim_id"])]

        for sid in ids:
            sim = catalog[sid]
            out_dir = resolve_run_output_dir(
                display_cfg, project_root=project_dir, run_name=sim.name, sim_id=sid
            )
            written_paths.extend(
                render_figures_for_run(sim, display_cfg, output_dir=out_dir, figure_names=only)
            )
    return written_paths


def audit_list(
    workspace: Any = None,
    *,
    since: str | None = None,
    limit: int = 50,
) -> Any:
    """Return recent audit log entries as a DataFrame."""
    import duckdb

    from hydromodpy.cli.helpers import find_catalog_root
    from hydromodpy.core.state.paths import CATALOG_FILENAME

    workspace_root = find_catalog_root(
        Path(workspace).expanduser().resolve() if workspace else Path.cwd().resolve()
    )
    catalog_path = workspace_root / CATALOG_FILENAME
    if not catalog_path.exists():
        raise FileNotFoundError(f"No catalog at {workspace_root}")
    sql = "SELECT * FROM audit_log"
    params: list[object] = []
    if since:
        sql += " WHERE event_ts >= ?"
        params.append(since)
    sql += " ORDER BY event_ts DESC LIMIT ?"
    params.append(int(limit))
    conn = duckdb.connect(str(catalog_path), read_only=True)
    try:
        return conn.execute(sql, params).fetchdf()
    finally:
        conn.close()


def audit_verify(workspace: Any = None, *, strict: bool = False) -> dict:
    """Verify the workspace audit log hash chain.

    Returns ``{"status": "ok"|"placeholder"|"missing", "message": str}``.
    """
    import duckdb

    from hydromodpy.cli.helpers import find_catalog_root
    from hydromodpy.core.state.paths import CATALOG_FILENAME

    workspace_root = find_catalog_root(
        Path(workspace).expanduser().resolve() if workspace else Path.cwd().resolve()
    )
    catalog_path = workspace_root / CATALOG_FILENAME
    if not catalog_path.exists():
        raise FileNotFoundError(f"No catalog at {workspace_root}")
    conn = duckdb.connect(str(catalog_path), read_only=True)
    try:
        cols = [row[0] for row in conn.execute("PRAGMA table_info(audit_log)").fetchall()]
    finally:
        conn.close()
    if "hash_chain" not in cols and "row_hash" not in cols:
        msg = "hash chain not yet wired into audit_log"
        if strict:
            raise RuntimeError(msg)
        return {"status": "placeholder", "message": msg}
    return {"status": "ok", "message": "audit_log hash chain verifies (placeholder check)"}


def purge_simulation(
    sim_ref: str,
    *,
    workspace: Any = None,
    reason: str = "unspecified",
    archive_pii: bool = False,
) -> dict:
    """Hard-delete a simulation and emit a JSON purge certificate.

    Returns a dict with ``sim_id``, ``removed_paths``, ``certificate``,
    ``archive``, ``sha256_snapshot``.
    """
    import hashlib
    import json

    from hydromodpy.cli.helpers import find_catalog_root
    from hydromodpy.core.state.paths import CATALOG_FILENAME
    from hydromodpy.results.catalog import SimulationCatalog
    from hydromodpy.results.catalog.audit import emit_deletion_tombstone

    workspace_root = find_catalog_root(
        Path(workspace).expanduser().resolve() if workspace else Path.cwd().resolve()
    )
    if not (workspace_root / CATALOG_FILENAME).exists():
        raise FileNotFoundError(f"No catalog at {workspace_root}")

    with SimulationCatalog(workspace_root) as catalog:
        sid = catalog.resolve(sim_ref)
        snapshot = _purge_collect_snapshot(catalog, sid)
        zarr_path = catalog.zarr_path_for(sid)
        parquet_dir = catalog.parquet_dir_for(sid)
        existing = [str(p) for p in (zarr_path, parquet_dir) if p.exists()]
        sha256_snapshot = hashlib.sha256(
            json.dumps(snapshot, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        catalog.delete(
            sid,
            remove_storage=True,
            audit_event_type="sim.purge",
            audit_payload={"reason": reason, "sha256_snapshot": sha256_snapshot},
        )
        emit_deletion_tombstone(
            catalog._db,  # type: ignore[attr-defined]
            sim_id=sid,
            sha256_snapshot=sha256_snapshot,
            reason=reason,
            components={"removed_paths": existing},
        )

    workspace_top = _purge_resolve_workspace_top(workspace_root)
    extra_removed = _purge_prune_orphan_geographic_cache(workspace_top)
    cert_path = _purge_write_certificate(
        workspace_top, sim_id=sid, reason=reason, sha256_snapshot=sha256_snapshot
    )
    archive_path: Path | None = None
    if archive_pii:
        archive_path = _purge_write_pii_archive(
            workspace_top,
            sim_id=sid,
            snapshot=snapshot,
            reason=reason,
            removed_paths=[*existing, *extra_removed],
            sha256_snapshot=sha256_snapshot,
        )

    return {
        "sim_id": sid,
        "removed_paths": existing + extra_removed,
        "certificate": str(cert_path),
        "archive": str(archive_path) if archive_path else None,
        "sha256_snapshot": sha256_snapshot,
    }


def _purge_resolve_workspace_top(project_root: Path) -> Path:
    if project_root.parent.name == "projects":
        return project_root.parent.parent
    return project_root


def _purge_collect_snapshot(catalog: Any, sim_id: str) -> dict[str, object]:
    from datetime import datetime

    row = catalog._db.execute(  # type: ignore[attr-defined]
        """
        SELECT sim_id, name, project, config_hash, config_snapshot,
               geographic_fingerprint, period_start, period_end, created_at
          FROM simulations
         WHERE sim_id = ?
        """,
        [sim_id],
    ).fetchone()
    if row is None:
        return {"sim_id": sim_id}
    cols = (
        "sim_id",
        "name",
        "project",
        "config_hash",
        "config_snapshot",
        "geographic_fingerprint",
        "period_start",
        "period_end",
        "created_at",
    )

    def _coerce(value: object) -> object:
        if isinstance(value, datetime):
            return value.isoformat()
        if hasattr(value, "hex") and not isinstance(value, (bytes, bytearray)):
            return str(value)
        return value

    return dict(zip(cols, [_coerce(value) for value in row], strict=False))


def _purge_prune_orphan_geographic_cache(workspace: Path) -> list[str]:
    cache_dir = workspace / "geographic"
    if not cache_dir.is_dir():
        return []
    referenced = _gc_referenced_geographic_fingerprints(_gc_iter_project_roots(workspace))
    removed: list[str] = []
    for entry in sorted(cache_dir.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name in referenced:
            continue
        try:
            shutil.rmtree(entry)
            removed.append(str(entry))
        except OSError:
            continue
    return removed


def _purge_resolve_operator() -> str:
    import os

    for key in ("HMP_USER", "USER", "USERNAME"):
        value = os.environ.get(key)
        if value:
            return value
    try:
        import getpass

        return getpass.getuser()
    except OSError:
        return "anonymous"


def _purge_write_certificate(
    workspace_root: Path, *, sim_id: str, reason: str, sha256_snapshot: str
) -> Path:
    import json
    import os
    from datetime import UTC, datetime

    cert_dir = workspace_root / ".hmp" / "purge_certificates"
    cert_dir.mkdir(parents=True, exist_ok=True)
    cert_path = cert_dir / f"{sim_id}.json"
    certificate = {
        "sim_id": sim_id,
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "operator": _purge_resolve_operator(),
        "reason": reason,
        "sha256_snapshot": sha256_snapshot,
    }
    cert_path.write_text(
        json.dumps(certificate, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )
    try:
        os.chmod(cert_path, 0o600)
    except OSError:
        pass
    return cert_path


def _purge_write_pii_archive(
    workspace_root: Path,
    *,
    sim_id: str,
    snapshot: dict[str, object],
    reason: str,
    removed_paths: list[str],
    sha256_snapshot: str,
) -> Path:
    import json
    import os
    from datetime import UTC, datetime

    cert_dir = workspace_root / ".hmp" / "purge_certificates"
    cert_dir.mkdir(parents=True, exist_ok=True)
    archive_path = cert_dir / f"{sim_id}.pii.json"
    archive = {
        "sim_id": sim_id,
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "operator": _purge_resolve_operator(),
        "reason": reason,
        "sha256_snapshot": sha256_snapshot,
        "removed_paths": removed_paths,
        "snapshot": snapshot,
    }
    archive_path.write_text(
        json.dumps(archive, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )
    try:
        os.chmod(archive_path, 0o600)
    except OSError:
        pass
    return archive_path


def verify_purge_certificate(certificate: Any, *, strict: bool = False) -> dict:
    """Verify a purge certificate JSON file. Returns the parsed payload + status."""
    import json

    cert_path = Path(certificate).expanduser().resolve()
    if not cert_path.is_file():
        raise FileNotFoundError(f"Certificate not found: {cert_path}")
    try:
        payload = json.loads(cert_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Certificate is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Certificate must be a JSON object")
    required = ("sim_id", "timestamp_utc", "operator", "reason", "sha256_snapshot")
    missing = [field for field in required if field not in payload]
    if missing:
        raise ValueError(f"Certificate missing required fields: {', '.join(missing)}")
    digest = str(payload.get("sha256_snapshot", ""))
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest.lower()):
        raise ValueError(f"sha256_snapshot has invalid form: {digest!r}")
    try:
        stat = cert_path.stat()
        mode = stat.st_mode & 0o777
    except OSError:
        mode = None
    permissions_ok = mode == 0o600 if mode is not None else True
    if not permissions_ok and strict:
        raise ValueError(f"certificate permissions {oct(mode)} != 0o600")
    return {
        "certificate": str(cert_path),
        "permissions_ok": permissions_ok,
        "permissions": oct(mode) if mode is not None else None,
        "payload": payload,
    }


def list_data_cache(
    workspace: Any = None,
    *,
    variable: str | None = None,
    provider: str | None = None,
) -> Any:
    """List artefacts indexed in the workspace data cache."""
    from hydromodpy.cli.helpers import resolve_workspace as _resolve_ws
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

    workspace_root = _resolve_ws(str(workspace) if workspace else None)
    db_path = workspace_root / "data" / "cache.duckdb"
    if not db_path.exists():
        return None
    with DataCatalogDuckDB(db_path) as catalog:
        return catalog.list_entries(variable=variable, source=provider)


def fetch_data_variable(
    variable: str,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    workspace: Any = None,
    source: str = "upstream",
) -> dict:
    """Fetch an upstream variable into the cache and write a sidecar."""
    from datetime import UTC, datetime

    from hydromodpy.cli.helpers import resolve_workspace as _resolve_ws
    from hydromodpy.data.scaffold import VARIABLES
    from hydromodpy.data.sidecars import (
        Sidecar,
        compute_sha256,
        resolve_fetched_at,
        write_sidecar,
    )

    workspace_root = _resolve_ws(str(workspace) if workspace else None)
    spec = next((s for s in VARIABLES if s.name == variable), None)
    if spec is None:
        raise ValueError(f"Unknown variable {variable!r}")

    raw_dir = workspace_root / "data" / spec.name / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    suffix = {"raster": ".tif", "vector": ".gpkg", "timeseries": ".parquet"}.get(spec.kind, ".bin")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = raw_dir / f"{spec.name}_{stamp}{suffix}"

    payload = (
        f"placeholder fetch for variable={spec.name} bbox={bbox} "
        f"at {datetime.now(UTC).isoformat()}\n"
    )
    target.write_bytes(payload.encode("utf-8"))
    sidecar = Sidecar(
        source=source,
        fetched_at=resolve_fetched_at(source),
        sha256=compute_sha256(target),
        license=None,
        crs=None,
        bbox=bbox,
        notes=f"auto-generated by 'hmp data get {spec.name}'",
    )
    sidecar_path = write_sidecar(target, sidecar)
    return {"target": str(target), "sidecar": str(sidecar_path)}


def check_data_cache(
    workspace: Any = None,
    *,
    variable: str | None = None,
    fix: bool = False,
) -> dict:
    """Validate ``<variable>_custom/`` folders. Returns issues + optional fix summary."""
    from hydromodpy.cli.helpers import resolve_workspace as _resolve_ws
    from hydromodpy.data.auto_scan import check_custom
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

    workspace_root = _resolve_ws(str(workspace) if workspace else None)
    issues = check_custom(workspace_root, variable=variable)
    fix_summary: dict | None = None
    if fix:
        db_path = workspace_root / "data" / "cache.duckdb"
        if db_path.exists():
            with DataCatalogDuckDB(db_path) as catalog:
                fix_summary = catalog.check_and_fix()
    return {
        "workspace": str(workspace_root),
        "issues": [(str(path), str(msg)) for path, msg in issues],
        "fix_summary": fix_summary,
    }


def add_data_entry(
    file: Any,
    *,
    variable: str,
    provider: str = "custom",
    crs: str | None = None,
    unit: str | None = None,
    station_id: str | None = None,
    workspace: Any = None,
    frozen: bool = False,
) -> dict:
    """Ingest a single file into the workspace data cache."""
    from hydromodpy.cli.helpers import resolve_workspace as _resolve_ws
    from hydromodpy.data.adapters import (
        convert_asc_to_geotiff,
        convert_timeseries_csv_to_parquet,
        convert_vector_to_geoparquet,
    )
    from hydromodpy.data.data_freeze import LOCKFILE_NAME, read_lockfile, sha256_of
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB
    from hydromodpy.data.scaffold import VARIABLES

    workspace_root = _resolve_ws(str(workspace) if workspace else None)
    src = Path(file).expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(f"File not found: {src}")
    if frozen:
        lockfile = workspace_root / LOCKFILE_NAME
        if not lockfile.is_file():
            raise FileNotFoundError(f"--frozen requested but no {lockfile}")
        expected = {la.sha256 for la in read_lockfile(lockfile)}
        if sha256_of(src) not in expected:
            raise ValueError(f"--frozen: {src} SHA-256 does not match any lockfile entry")

    spec = next((s for s in VARIABLES if s.name == variable), None)
    if spec is None:
        raise ValueError(f"Unknown variable {variable!r}")

    blobs = workspace_root / "data" / "blobs" / spec.name / provider
    blobs.mkdir(parents=True, exist_ok=True)
    if spec.kind == "timeseries":
        sid = station_id or src.stem
        dest = blobs / f"{sid}.parquet"
        convert_timeseries_csv_to_parquet(src, dest)
    elif spec.kind == "raster":
        sid = None
        dest = blobs / f"{src.stem}.tif"
        convert_asc_to_geotiff(src, dest)
    elif spec.kind == "vector":
        sid = None
        dest = blobs / f"{src.stem}.parquet"
        convert_vector_to_geoparquet(src, dest)
    else:
        raise ValueError(f"Unsupported kind {spec.kind!r}")

    with DataCatalogDuckDB(workspace_root / "data" / "cache.duckdb") as catalog:
        catalog.register(
            variable=spec.name,
            source=provider,
            station_id=sid,
            file_path=str(src),
            crs=crs,
            unit=unit or spec.unit,
            is_custom=True,
            fetch_metadata={"pivot_path": str(dest), "pivot_format": spec.pivot},
        )
    return {"variable": spec.name, "provider": provider, "station_id": sid, "dest": str(dest)}


def remove_data_entries(
    workspace: Any = None,
    *,
    variable: str | None = None,
    provider: str | None = None,
    station_id: str | None = None,
    delete_files: bool = False,
) -> int:
    """Remove cache entries matching the filters. Returns the removed count."""
    from hydromodpy.cli.helpers import resolve_workspace as _resolve_ws
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

    workspace_root = _resolve_ws(str(workspace) if workspace else None)
    db_path = workspace_root / "data" / "cache.duckdb"
    if not db_path.exists():
        return 0
    with DataCatalogDuckDB(db_path) as catalog:
        return catalog.invalidate(
            variable=variable,
            source=provider,
            station_id=station_id,
            delete_files=delete_files,
        )


def prune_data_cache(
    workspace: Any = None,
    *,
    older_than_days: int = 30,
    delete_files: bool = False,
) -> int:
    """Drop cache entries older than N days. Returns the removed count."""
    from hydromodpy.cli.helpers import resolve_workspace as _resolve_ws
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

    workspace_root = _resolve_ws(str(workspace) if workspace else None)
    db_path = workspace_root / "data" / "cache.duckdb"
    if not db_path.exists():
        return 0
    with DataCatalogDuckDB(db_path) as catalog:
        return catalog.prune_older_than(days=older_than_days, delete_files=delete_files)


def archive_data_cache(output: Any, *, workspace: Any = None) -> Path:
    """Archive the workspace cache + lockfile to a portable file."""
    from hydromodpy.cli.helpers import resolve_workspace as _resolve_ws
    from hydromodpy.data.data_freeze import archive_lockfile
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

    workspace_root = _resolve_ws(str(workspace) if workspace else None)
    db_path = workspace_root / "data" / "cache.duckdb"
    dest = Path(output).expanduser().resolve()
    with DataCatalogDuckDB(db_path) as catalog:
        archive_lockfile(catalog, dest)
    return dest


def restore_data_cache(source: Any, *, workspace: Any = None) -> Path:
    """Restore a cache archive into the workspace. Returns destination path."""
    from hydromodpy.cli.helpers import resolve_workspace as _resolve_ws
    from hydromodpy.data.data_freeze import restore_archive

    workspace_root = _resolve_ws(str(workspace) if workspace else None)
    src = Path(source).expanduser().resolve()
    dest = workspace_root / "data" / "imported"
    restore_archive(src, dest)
    return dest


def import_package(
    package: Any,
    *,
    workspace: Any = None,
    as_project: str | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> str:
    """Import a ``.hmp`` archive into a workspace catalog. Returns the sim_id."""
    from hydromodpy.results.catalog import SimulationCatalog

    src = Path(package).expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(f"Archive not found: {src}")
    workspace_root = Path(workspace).expanduser().resolve() if workspace else Path.cwd().resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    with SimulationCatalog(workspace_root) as catalog:
        return catalog.import_package(src, force=force, as_project=as_project, dry_run=dry_run)


def export_simulation_package(
    sim_ref: str,
    *,
    output: Any,
    workspace: Any = None,
    project: str | None = None,
) -> Path:
    """Export a simulation as a portable ``.hmp`` archive."""
    from hydromodpy.core.state.paths import CATALOG_FILENAME
    from hydromodpy.results.catalog import SimulationCatalog

    workspace_root = Path(workspace).expanduser().resolve() if workspace else Path.cwd().resolve()
    if not (workspace_root / CATALOG_FILENAME).exists():
        raise FileNotFoundError(f"No catalog found at {workspace_root}")
    output_path = Path(output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with SimulationCatalog(workspace_root) as catalog:
        sim_id = catalog.resolve(sim_ref, project=project)
        return catalog.export_package(sim_id, output_path)


def gc(workspace: Any = None, *, dry_run: bool = False) -> dict:
    """Garbage-collect orphan caches, tmp parquet, and stale running sims.

    Returns a dict with ``plan`` (mapping category -> candidate list) and
    ``summary`` (mapping category -> applied count, empty when ``dry_run``).
    """
    workspace_root = _gc_resolve_workspace(workspace)
    plan = _gc_collect_plan(workspace_root)
    summary: dict[str, int] = {}
    if not dry_run:
        summary = _gc_apply_plan(workspace_root, plan)
    return {"workspace": str(workspace_root), "plan": plan, "summary": summary, "dry_run": dry_run}


def _gc_resolve_workspace(workspace: Any) -> Path:
    import sys as _sys

    from hydromodpy.cli.helpers import resolve_workspace as _resolve_ws

    if workspace is not None:
        root = Path(workspace).expanduser().resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"Workspace {root} does not exist.")
        return root
    try:
        return _resolve_ws(None)
    except SystemExit:  # pragma: no cover - defensive
        print("Workspace resolution failed", file=_sys.stderr)
        raise


def _gc_iter_project_roots(workspace: Path) -> list[Path]:
    from hydromodpy.core.state.paths import CATALOG_FILENAME

    roots: list[Path] = []
    if (workspace / CATALOG_FILENAME).is_file():
        roots.append(workspace)
    projects_dir = workspace / "projects"
    if projects_dir.is_dir():
        for entry in sorted(projects_dir.iterdir()):
            if entry.is_dir() and (entry / CATALOG_FILENAME).is_file():
                roots.append(entry)
    return roots


def _gc_collect_plan(workspace: Path) -> dict[str, list[str]]:
    plan: dict[str, list[str]] = {
        "calibration_sessions": [],
        "geographic_cache": [],
        "tmp_parquet": [],
        "stale_running_sims": [],
    }
    project_roots = _gc_iter_project_roots(workspace)
    for project_root in project_roots:
        plan["calibration_sessions"].extend(_gc_orphan_calibration_sessions(project_root))
        plan["stale_running_sims"].extend(_gc_stale_running_simulations(project_root))
    plan["geographic_cache"].extend(_gc_orphan_geographic_cache(workspace, project_roots))
    plan["tmp_parquet"].extend(_gc_tmp_parquet_files(workspace))
    return plan


def _gc_orphan_calibration_sessions(project_root: Path) -> list[str]:
    import duckdb

    from hydromodpy.core.state.paths import CATALOG_FILENAME

    catalog_path = project_root / CATALOG_FILENAME
    try:
        conn = duckdb.connect(str(catalog_path), read_only=True)
    except duckdb.Error:
        return []
    try:
        rows = conn.execute(
            """
            SELECT cs.session_id
              FROM calibration_sessions cs
         LEFT JOIN simulations s ON s.sim_id = cs.best_sim_id
             WHERE cs.best_sim_id IS NOT NULL AND s.sim_id IS NULL
            """,
        ).fetchall()
    except duckdb.Error:
        rows = []
    finally:
        conn.close()
    return [f"{project_root.name}:{r[0]!s}" for r in rows]


def _gc_stale_running_simulations(project_root: Path) -> list[str]:
    from datetime import UTC, datetime, timedelta

    import duckdb

    from hydromodpy.core.state.paths import CATALOG_FILENAME

    catalog_path = project_root / CATALOG_FILENAME
    cutoff = datetime.now(UTC) - timedelta(minutes=10)
    try:
        conn = duckdb.connect(str(catalog_path), read_only=True)
    except duckdb.Error:
        return []
    try:
        rows = conn.execute(
            """
            SELECT s.sim_id
              FROM simulations s
              JOIN statuses st ON s.status_id = st.id
             WHERE st.code = 'running'
               AND (s.last_heartbeat IS NULL OR s.last_heartbeat < ?)
            """,
            [cutoff],
        ).fetchall()
    except duckdb.Error:
        rows = []
    finally:
        conn.close()
    return [f"{project_root.name}:{r[0]!s}" for r in rows]


def _gc_orphan_geographic_cache(workspace: Path, project_roots: list[Path]) -> list[str]:
    cache_dir = workspace / "geographic"
    if not cache_dir.is_dir():
        return []
    referenced = _gc_referenced_geographic_fingerprints(project_roots)
    orphans: list[str] = []
    for entry in sorted(cache_dir.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name in referenced:
            continue
        orphans.append(str(entry))
    return orphans


def _gc_referenced_geographic_fingerprints(project_roots: list[Path]) -> set[str]:
    import duckdb

    from hydromodpy.core.state.paths import CATALOG_FILENAME

    referenced: set[str] = set()
    for project_root in project_roots:
        catalog_path = project_root / CATALOG_FILENAME
        try:
            conn = duckdb.connect(str(catalog_path), read_only=True)
        except duckdb.Error:
            continue
        try:
            rows = conn.execute(
                "SELECT DISTINCT geographic_fingerprint FROM simulations "
                "WHERE geographic_fingerprint IS NOT NULL"
            ).fetchall()
        except duckdb.Error:
            rows = []
        finally:
            conn.close()
        for (fp,) in rows:
            referenced.add(str(fp))
    return referenced


def _gc_tmp_parquet_files(workspace: Path) -> list[str]:
    found: list[str] = []
    if not workspace.is_dir():
        return found
    for tmp in workspace.rglob("*.tmp-*"):
        try:
            if tmp.is_file() or tmp.is_dir():
                found.append(str(tmp))
        except OSError:
            continue
    return found


def _gc_apply_plan(workspace: Path, plan: dict[str, list[str]]) -> dict[str, int]:
    import shutil

    summary: dict[str, int] = dict.fromkeys(plan, 0)
    for ref in plan["calibration_sessions"]:
        project_name, session_id = ref.split(":", 1)
        if _gc_delete_calibration_session(workspace, project_name, session_id):
            summary["calibration_sessions"] += 1
    for ref in plan["stale_running_sims"]:
        project_name, sim_id = ref.split(":", 1)
        if _gc_mark_simulation_failed(workspace, project_name, sim_id):
            summary["stale_running_sims"] += 1
    for path_str in plan["geographic_cache"]:
        path = Path(path_str)
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
            summary["geographic_cache"] += 1
    for path_str in plan["tmp_parquet"]:
        path = Path(path_str)
        try:
            if path.is_file():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            summary["tmp_parquet"] += 1
        except OSError:
            continue
    return summary


def _gc_project_root_by_name(workspace: Path, project_name: str) -> Path | None:
    from hydromodpy.core.state.paths import CATALOG_FILENAME

    candidate = workspace / "projects" / project_name
    if candidate.is_dir() and (candidate / CATALOG_FILENAME).is_file():
        return candidate
    if workspace.name == project_name and (workspace / CATALOG_FILENAME).is_file():
        return workspace
    return None


def _gc_delete_calibration_session(workspace: Path, project_name: str, session_id: str) -> bool:
    import duckdb

    from hydromodpy.core.state.paths import CATALOG_FILENAME

    project_root = _gc_project_root_by_name(workspace, project_name)
    if project_root is None:
        return False
    conn = duckdb.connect(str(project_root / CATALOG_FILENAME))
    try:
        conn.execute("DELETE FROM calibration_iterations WHERE session_id = ?", [session_id])
        conn.execute("DELETE FROM calibration_sessions WHERE session_id = ?", [session_id])
    finally:
        conn.close()
    return True


def _gc_mark_simulation_failed(workspace: Path, project_name: str, sim_id: str) -> bool:
    import duckdb

    from hydromodpy.core.state.paths import CATALOG_FILENAME

    project_root = _gc_project_root_by_name(workspace, project_name)
    if project_root is None:
        return False
    conn = duckdb.connect(str(project_root / CATALOG_FILENAME))
    try:
        conn.execute(
            """
            UPDATE simulations
               SET status_id = (SELECT id FROM statuses WHERE code = 'failed'),
                   ended_at = current_timestamp,
                   updated_at = current_timestamp
             WHERE sim_id = ?
            """,
            [sim_id],
        )
    finally:
        conn.close()
    return True


def vacuum(
    workspace: Any = None,
    *,
    catalog: bool = True,
    cache: bool = True,
) -> dict:
    """Compact DuckDB catalogs and consolidate Zarr metadata.

    Returns a dict with ``catalog_checkpoints``, ``cache_checkpoints``,
    ``zarr_consolidated`` counts.
    """
    from hydromodpy.cli.helpers import resolve_workspace as _resolve_ws

    workspace_root = Path(workspace).expanduser().resolve() if workspace else _resolve_ws(None)
    counts = {"catalog_checkpoints": 0, "cache_checkpoints": 0, "zarr_consolidated": 0}
    if catalog:
        counts["catalog_checkpoints"] = _vacuum_checkpoint_catalogs(workspace_root)
    if cache:
        counts["cache_checkpoints"] = _vacuum_checkpoint_data_cache(workspace_root)
        counts["zarr_consolidated"] = _vacuum_consolidate_zarr_stores(workspace_root)
    return {"workspace": str(workspace_root), "counts": counts}


def _vacuum_iter_catalog_files(workspace: Path) -> list[Path]:
    from hydromodpy.core.state.paths import CATALOG_FILENAME

    catalogs: list[Path] = []
    candidate = workspace / CATALOG_FILENAME
    if candidate.is_file():
        catalogs.append(candidate)
    projects_dir = workspace / "projects"
    if projects_dir.is_dir():
        for entry in sorted(projects_dir.iterdir()):
            if not entry.is_dir():
                continue
            cat = entry / CATALOG_FILENAME
            if cat.is_file():
                catalogs.append(cat)
    return catalogs


def _vacuum_checkpoint_catalogs(workspace: Path) -> int:
    import duckdb

    count = 0
    for catalog_path in _vacuum_iter_catalog_files(workspace):
        try:
            conn = duckdb.connect(str(catalog_path))
            try:
                conn.execute("CHECKPOINT")
            finally:
                conn.close()
            count += 1
        except duckdb.Error:
            continue
    return count


def _vacuum_checkpoint_data_cache(workspace: Path) -> int:
    import duckdb

    cache_path = workspace / "data" / "cache.duckdb"
    if not cache_path.is_file():
        return 0
    try:
        conn = duckdb.connect(str(cache_path))
        try:
            conn.execute("CHECKPOINT")
        finally:
            conn.close()
        return 1
    except duckdb.Error:
        return 0


def _vacuum_consolidate_zarr_stores(workspace: Path) -> int:
    try:
        import zarr  # noqa: F401
    except ImportError:
        return 0
    from hydromodpy.results.zarr_store import SimulationZarr

    count = 0
    for sim_dir in workspace.rglob("simulations"):
        if not sim_dir.is_dir():
            continue
        for entry in sorted(sim_dir.iterdir()):
            if entry.is_dir() and entry.suffix == ".zarr":
                try:
                    sz = SimulationZarr(entry)
                    try:
                        sz.consolidate_metadata()
                    finally:
                        sz.close()
                    count += 1
                except Exception:
                    continue
    return count


def delete_simulation(
    sim_ref: str,
    *,
    workspace: Any,
    keep_storage: bool = False,
) -> dict:
    """Delete one simulation row and (optionally) its Zarr / Parquet store.

    Returns a dict with ``sim_id``, ``freed_bytes``, ``removed_paths``.
    """
    from hydromodpy.core.state.paths import CATALOG_FILENAME
    from hydromodpy.results.catalog import SimulationCatalog

    workspace_root = Path(workspace).expanduser().resolve()
    if not (workspace_root / CATALOG_FILENAME).exists():
        raise FileNotFoundError(f"No catalog at {workspace_root}")

    with SimulationCatalog(workspace_root) as catalog:
        sid = catalog.resolve(sim_ref)
        zarr_path = catalog.zarr_path_for(sid)
        parquet_dir = catalog.parquet_dir_for(sid)
        existing = [path for path in (zarr_path, parquet_dir) if path.exists()]
        freed_bytes = sum(_path_size(path) for path in existing) if not keep_storage else 0
        catalog.delete(sid, remove_storage=not keep_storage)
        return {
            "sim_id": sid,
            "freed_bytes": freed_bytes,
            "removed_paths": [str(p) for p in existing] if not keep_storage else [],
        }


def _path_size(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        if path.is_file():
            return int(path.stat().st_size)
    except OSError:
        return 0
    total = 0
    try:
        for child in path.rglob("*"):
            try:
                if child.is_file():
                    total += int(child.stat().st_size)
            except OSError:
                continue
    except OSError:
        return total
    return total


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
