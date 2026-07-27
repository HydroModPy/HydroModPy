"""Top-level functional API for HydroModPy.

Mirrors the CLI verbs so ``hmp run config.toml`` and ``hmp.run("config.toml")``
execute the same workflow. Kept as a private module so the package facade
stays minimal.

The run-management CLI verbs (``hmp catalog trash/restore/tag/note/rename/
rerun/diff/reindex/gc/watch``) are intentionally not mirrored as top-level
``hmp.*`` symbols. Their Python surface is the :class:`Catalog` handle returned
by :func:`open`: ``cat.trash(ref)``, ``cat.restore(ref)``, ``cat.add_tag(...)``,
``cat.rename_simulation(...)``, ``cat.diff(...)``, plus
:func:`hydromodpy.results.catalog.reindex.rebuild_index`. The
``hmp.cli._workers`` package is a CLI-private implementation detail, not a
public API.
"""

from __future__ import annotations

import importlib
import platform
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.core.version import __version__

if TYPE_CHECKING:
    import geopandas as gpd
    import pandas as pd
    import xarray as xr

    from hydromodpy.core.state.global_index import GlobalIndex
    from hydromodpy.project.spinup import SpinupResult
    from hydromodpy.results.catalog import Catalog
    from hydromodpy.results.run import Run

    Readable = xr.DataArray | pd.Series | pd.DataFrame | gpd.GeoDataFrame


def open(workspace: Any, *, create: bool = False, read_only: bool = True) -> Catalog:
    """Open a HydroModPy project catalog.

    The single door to a workspace catalog: returns a
    :class:`hydromodpy.results.catalog.Catalog` backed by
    ``<project>/.hmp/index.duckdb``. It exposes object access (``latest``, ``best``,
    ``find``, ``cat[ref]``), tabular access (``frame``, ``sql``,
    ``list_simulations``), schema discovery (``describe``, ``tables``,
    ``columns``, ``variables``, ``metrics``, ``stations``), and per-id reads
    (``read``).

    The default open is **read-only**: inspecting a catalog never migrates it,
    never rewrites a view, and never touches its mtime, so an archived project
    can be browsed without leaving a trace and a reader never contends with a
    running solve. Pass ``read_only=False`` (or ``create=True``) for the
    writable handle used to initialise or annotate a catalog.

    Parameters
    ----------
    workspace
        Project directory holding ``.hmp/index.duckdb`` (or a direct path to
        the ``.duckdb`` file).
    create
        ``False`` (default) raises :class:`FileNotFoundError` when no catalog
        exists yet (no phantom catalog is created). ``True`` opens a writable
        handle and initialises an empty catalog.
    read_only
        ``True`` (default) opens the catalog read-only. Ignored when
        ``create=True`` (initialisation requires a writable handle).

    Returns
    -------
    hydromodpy.results.catalog.Catalog
        Catalog handle for the project.

    Raises
    ------
    FileNotFoundError
        If no index database is found and ``create`` is ``False``.
    hydromodpy.core.exceptions.CatalogError
        If the DuckDB catalog file is locked, corrupted, or unreadable.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> cat = hmp.open("~/ws/projects/naizin")  # doctest: +SKIP
    >>> cat.latest()  # doctest: +SKIP

    See Also
    --------
    hydromodpy.index
        Machine-wide federation across registered workspaces.
    """
    from hydromodpy.core.state.paths import catalog_path_for, resolve_project_root
    from hydromodpy.results.catalog import Catalog

    ws = Path(workspace).expanduser().resolve()
    if ws.suffix == ".duckdb":
        catalog_file = ws
    else:
        catalog_file = catalog_path_for(resolve_project_root(ws))
    if not create and not catalog_file.is_file():
        raise FileNotFoundError(
            f"No catalog at {catalog_file.parent}. Run a workflow there first, "
            f"or pass create=True to initialise an empty catalog."
        )
    if create:
        return Catalog(ws)
    return Catalog(ws, read_only=read_only)


def index(db_path: Any = None, *, read_only: bool = True) -> GlobalIndex:
    """Open the machine-wide global index that federates registered workspaces.

    Read-only by default, mirroring :func:`open`: browsing the federation index
    never migrates it or touches its mtime, and a reader never contends with a
    concurrent solve. Pass ``read_only=False`` for the writable handle used to
    ``register_workspace`` / ``forget`` / ``prune``.

    Parameters
    ----------
    db_path
        Optional path to the index DuckDB file. ``None`` uses the default
        machine-state location.
    read_only
        Open the index in read-only mode (default ``True``). Writes
        (``register_workspace``, ``forget``, ``prune``) will raise. Pure reads
        (``search``, ``find``, ``list_workspaces``) keep working while another
        process holds the write-lock.

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
    >>> idx = hmp.index(read_only=True)  # doctest: +SKIP
    >>> idx.list_workspaces()  # doctest: +SKIP

    See Also
    --------
    hydromodpy.core.state.global_index.GlobalIndex
        Underlying federation implementation.
    """
    from pathlib import Path as _Path

    from hydromodpy.core.state.global_index import GlobalIndex

    resolved = _Path(db_path).expanduser().resolve() if db_path is not None else None
    return GlobalIndex(resolved, read_only=read_only)


def _open_run(project_root: Any, sim_id: Any) -> Any:
    """Return the :class:`Run` for ``sim_id`` bound to an open catalog.

    Both :func:`run` branches expose the ``simulation`` workflow as a ``Run``
    (or ``None`` for a dry-run / no persisted result) so :func:`read` /
    :func:`export` accept the result directly. The catalog is intentionally
    **not** context-managed here: the Run reads through it, so it must stay
    open after :func:`run` returns (matching ``cat = hmp.open(...); cat[ref]``).
    Returns ``None`` on any resolution failure rather than raising.
    """
    if not sim_id:
        return None
    try:
        return open(project_root)[sim_id]
    except Exception:
        return None


def _write_lock_for_run(config_source: Any, *, no_lock: bool) -> None:
    """Write ``hydromodpy.lock`` after a Python-driven simulation.

    Mirrors the CLI post-run lock write so ``hmp.run`` records the same
    reproducibility provenance the terminal does. Best-effort and silent on
    failure. ``config_source`` is a TOML path or a resolved config object.
    """
    if no_lock:
        return
    try:
        from hydromodpy.project.lockfile import write_project_lockfile

        if isinstance(config_source, (str, Path)):
            from hydromodpy.config import HydroModPyConfig

            cfg = HydroModPyConfig.from_toml(config_source)
        else:
            cfg = config_source
        write_project_lockfile(cfg)
    except Exception:
        pass


@contextmanager
def _materialized_config(config: Any):
    """Write a resolved config to a temp TOML in its project_root and yield it.

    Lets the config-object branch of :func:`run` reuse the same path-based
    workflow adapters as the TOML branch. The temp file lives inside
    ``project_root`` so relative paths resolve identically; it is removed
    afterwards.
    """
    import uuid

    root = Path(config.workspace.project_root).expanduser().resolve()
    materialized = root / f".hmp_effective_{uuid.uuid4().hex[:8]}.toml"
    config.to_toml(materialized)
    try:
        yield materialized
    finally:
        materialized.unlink(missing_ok=True)


def run(config: Any, **kwargs: Any) -> Run | dict | None:
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
        controls the underlying ``Project`` interactive side effects. Set
        ``no_lock=True`` to skip the post-run ``hydromodpy.lock`` write (a
        successful simulation writes the reproducibility lock by default,
        matching ``hmp run``).

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
    >>> run = hmp.run("run_transient_nwt.toml", name="baseline")  # doctest: +SKIP

    See Also
    --------
    hydromodpy.project.Project.simulate
        Object-oriented form for repeated runs from one project.
    """
    headless = bool(kwargs.pop("headless", False))
    no_lock = bool(kwargs.pop("no_lock", False))

    if isinstance(config, (str, Path)):
        from hydromodpy.project.dispatch.workflow import dispatch_workflow
        from hydromodpy.workflow.dispatch import resolve_workflow

        config_path = Path(config).expanduser().resolve()
        workflow = resolve_workflow(
            config_path,
            cli_workflow=None,
            require_toml_field=True,
        )
        summary = dispatch_workflow(workflow, config_path, **kwargs)
        # The simulation adapter returns a summary dict; expose it as the Run
        # so hmp.read / hmp.export accept the result on either branch.
        if workflow == "simulation":
            sim_id = summary.get("sim_id") if isinstance(summary, dict) else None
            run_obj = _open_run(config_path.parent, sim_id)
            if run_obj is not None:
                _write_lock_for_run(config_path, no_lock=no_lock)
            return run_obj
        return summary

    # In-memory config object: dispatch on the declared workflow mode so a
    # pure-Python config reaches every workflow, not only a plain simulation.
    mode = getattr(getattr(config, "workflow", None), "mode", "simulation")
    if mode == "simulation":
        from hydromodpy.project import Project

        with Project(config, headless=headless) as project:
            result = project.simulate(**kwargs)
        if result is None:
            return None
        _write_lock_for_run(config, no_lock=no_lock)
        # Re-bind to a freshly opened catalog so hmp.read works after the
        # project context (and its catalog connection) has closed.
        return _open_run(config.workspace.project_root, result.sim_id) or result

    from hydromodpy.project.dispatch.workflow import dispatch_workflow

    with _materialized_config(config) as materialized_path:
        return dispatch_workflow(mode, materialized_path, **kwargs)


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
    >>> report = hmp.calibrate("calibration.toml")  # doctest: +SKIP

    See Also
    --------
    hydromodpy.calibration.runners.cli_runner.run_calibration_cli
        TOML entry point used by the path branch.
    hydromodpy.calibration.runners.programmatic_runner.run_calibration_programmatic
        Python entry point used by the config-object branch.
    hydromodpy.calibration.CalibrationReport
        Structured calibration result.
    """
    if isinstance(config, (str, Path)):
        from hydromodpy.calibration.runners.cli_runner import run_calibration_cli

        kwargs.pop("headless", None)
        return run_calibration_cli(Path(config).expanduser().resolve(), **kwargs)

    from hydromodpy.project import Project

    headless = bool(kwargs.pop("headless", True))
    with Project(config, headless=headless) as project:
        return project.calibrate(**kwargs)


def spinup(config: Any, **kwargs: Any) -> SpinupResult:
    """Run a cyclic spin-up from a TOML file or config object.

    Repeats the representative window (``[spinup] window_*``, else
    ``[simulation.time]``), restarting each cycle from the previous cycle's state,
    until the aquifer heads and the lake stage converge. One :class:`Project` is
    reused so the mesh is identical across cycles.

    Parameters
    ----------
    config
        TOML path or validated configuration object.
    kwargs
        Forwarded to :func:`~hydromodpy.project.spinup.run_spinup` (``spinup``
        settings override, ``name_prefix``). ``headless`` controls the project.

    Returns
    -------
    hydromodpy.project.spinup.SpinupResult
        The loop outcome. Feed ``result.restart_from`` to a production run's
        ``[flow] restart_from`` (enable ``[mesh_catchment] cache`` for a gmsh grid
        so that run reproduces this mesh).

    See Also
    --------
    hydromodpy.project.spinup.run_spinup
        The underlying driver, callable on an existing Project.
    """
    import copy
    import dataclasses

    from hydromodpy.project import Project
    from hydromodpy.project.facade import _resolve_config
    from hydromodpy.project.spinup import run_spinup

    headless = bool(kwargs.pop("headless", True))
    then_run = bool(kwargs.pop("then_run", False))
    source = Path(config).expanduser().resolve() if isinstance(config, (str, Path)) else config

    # Snapshot a clean production config before the spin-up mutates the model's
    # (cycle window, restart_from, IC).
    prod_cfg = None
    if then_run:
        if isinstance(source, Path):
            from hydromodpy.config import HydroModPyConfig

            prod_cfg = HydroModPyConfig.from_toml(source)
        else:
            prod_cfg = copy.deepcopy(_resolve_config(source))

    with Project(source, headless=headless, no_display=True) as project:
        result = run_spinup(project, **kwargs)

    if not then_run or not result.restart_from:
        return result

    # Production run: a fresh project over the full [simulation.time] window,
    # seeded from the converged state. Its mesh must reproduce the spin-up mesh,
    # so a gmsh grid needs [mesh_catchment] cache = true.
    prod_cfg.flow.restart_from = result.restart_from
    production = run(prod_cfg, headless=headless)
    return dataclasses.replace(result, production_sim_id=getattr(production, "sim_id", None))


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
    >>> table = hmp.compare_pair(
    ...     "ab12cd34", "ef56gh78", workspace="~/hmp_workspace"
    ... )  # doctest: +SKIP

    See Also
    --------
    hydromodpy.analysis.comparison
        Comparison package used by this helper.
    """
    from hydromodpy.analysis.comparison.pairwise import compare_pair as _compare_pair

    return _compare_pair(sim_a, sim_b, workspace=workspace)


def report(session_id_or_prefix: Any = None, *, workspace: Any = None) -> Any:
    """Render the HTML report for a calibration session.

    ``session_id_or_prefix`` accepts a full UUID or a unique hex prefix
    of either a calibration session or one of its runs (an iteration or the
    promoted best run, as printed by ``hmp catalog ls``); the run reference is
    mapped to its parent session. ``None`` falls back to the most recently
    started session. ``workspace`` defaults to the nearest ancestor of the
    current working directory holding a project index database.

    When ``workspace`` is a workspace root, the lookup federates across every
    ``projects/<name>`` catalog, matching how ``hmp catalog ls`` lists runs.

    Parameters
    ----------
    session_id_or_prefix
        Full UUID or unique hex prefix of a session or one of its runs, or
        ``None`` for the latest session.
    workspace
        Optional workspace root or project directory.

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
    >>> hmp.report()  # latest session in the current workspace  # doctest: +SKIP
    >>> hmp.report("ab12cd34", workspace="~/hmp_workspace")  # doctest: +SKIP
    """
    from hydromodpy.calibration.report import resolve_session_in_workspace
    from hydromodpy.core.state.paths import catalog_path_for
    from hydromodpy.results.catalog import Catalog
    from hydromodpy.workflow.steps.calibration import step_render_calibration_report

    if workspace is None:
        workspace_root = Path.cwd()
        for parent in [workspace_root] + list(workspace_root.parents):
            if (catalog_path_for(parent)).exists():
                workspace_root = parent
                break
    else:
        workspace_root = Path(workspace).expanduser().resolve()

    catalog_root, full_id = resolve_session_in_workspace(workspace_root, session_id_or_prefix)
    with Catalog(catalog_root) as catalog:
        return step_render_calibration_report(
            catalog=catalog,
            session_id=full_id,
            workspace_root=catalog_root,
        )


def read(
    sim: Any,
    var: str,
    *,
    time: int | slice | None = None,
    layer: int | None = None,
    sel: dict | None = None,
    bbox: tuple[float, float, float, float] | None = None,
) -> Readable:
    """Read a variable from a simulation Run with storage-kind auto-dispatch.

    Single entry point for reads on a :class:`~hydromodpy.results.run.Run`.
    The return type follows one rule:

    - Zarr field -> ``xr.DataArray`` (lazy); when ``time`` is an ``int``, the
      eager ``np.ndarray`` of that single timestep instead.
    - timeseries -> ``pd.Series``.
    - geographic feature -> ``gpd.GeoDataFrame``.

    Every field a run reports through ``has_field`` reads back here. Fields
    rebuilt on the fly (water-table elevation/depth, seepage mask, drain
    outflow) are loaded eagerly rather than lazily, and ``time`` is ignored
    for a field with no time dimension.

    To read by reference (id / unique prefix / name) instead of a ``Run``, use
    ``cat.read(ref, var)`` on a :class:`hydromodpy.catalog.Catalog`.

    Parameters
    ----------
    sim
        A :class:`~hydromodpy.results.run.Run` (e.g. ``cat.latest()`` or
        ``cat[ref]``).
    var
        Variable name, resolved against the field registry, then the DuckDB
        ``timeseries`` table, then the geographic features.
    time
        Timestep index (``int``) or ``slice`` for Zarr fields. ``None`` loads
        every persisted timestep lazily.
    layer
        Optional layer index for three-dimensional fields.
    sel
        Optional selectors forwarded to the reader: ``{"station": ...}`` for
        timeseries, ``{"period": ...}`` for a time window.
    bbox
        Optional ``(xmin, ymin, xmax, ymax)`` in the simulation CRS;
        restricts Zarr fields to faces whose centroid lies in the box.

    Returns
    -------
    xarray.DataArray or numpy.ndarray or pandas.Series or geopandas.GeoDataFrame
        See the rule above.

    Raises
    ------
    TypeError
        If ``sim`` is not a :class:`Run` instance.
    hydromodpy.results.errors.FieldNotFoundError
        If ``var`` could not be resolved by any backend.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> cat = hmp.open("~/ws/projects/naizin")  # doctest: +SKIP
    >>> run = cat.latest()  # doctest: +SKIP
    >>> da = hmp.read(run, "head")  # lazy DataArray  # doctest: +SKIP
    >>> arr = hmp.read(run, "head", time=-1, layer=0)  # ndarray  # doctest: +SKIP
    >>> ts = hmp.read(run, "discharge", sel={"station": "outlet"})  # doctest: +SKIP
    >>> gdf = hmp.read(run, "watershed_polygon")  # doctest: +SKIP
    """
    from hydromodpy.results.derive.reading import read_variable

    return read_variable(sim, var, time=time, layer=layer, sel=sel, bbox=bbox)


def figure(
    sim: Any,
    name: str,
    *,
    save: Any = None,
    dpi: int = 150,
    **opts: Any,
) -> Any:
    """Render one registered figure for a simulation Run.

    The Python counterpart of ``[display].figures``: the same registry, the
    same names, the same options, so a figure produced by ``hmp run`` can be
    reproduced (or re-styled) from a script without importing anything from
    the display internals. List the names with
    :func:`hydromodpy.display.list_figures`.

    Parameters
    ----------
    sim
        A :class:`~hydromodpy.results.run.Run` (e.g. ``cat.latest()``).
    name
        Registered figure name, for example ``"piezometric_map"``.
    save
        Optional output path. A directory (or an extension-less path) gets
        ``<name>.png`` appended.
    dpi
        Raster resolution used when saving.
    **opts
        Figure-specific options, identical to the ``[display.overrides]``
        entries (``timestep``, ``overlays``, ``cmap``, ``units``, ...).

    Returns
    -------
    matplotlib.figure.Figure
        The rendered figure.

    Raises
    ------
    KeyError
        If ``name`` is not registered.
    ValueError
        If the run does not carry what the figure needs.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> cat = hmp.open("~/ws/projects/aber")  # doctest: +SKIP
    >>> run = cat.latest()  # doctest: +SKIP
    >>> hmp.figure(run, "cross_section", orientation="sn")  # doctest: +SKIP
    """
    from pathlib import Path as _Path

    from hydromodpy.display import get as _get_figure

    renderer = _get_figure(name)
    reason = renderer.unavailable_reason(sim)
    if reason is not None:
        raise ValueError(f"figure '{name}' does not apply to this run: {reason}")

    save_path = None
    if save is not None:
        target = _Path(save)
        save_path = target / f"{name}.png" if target.suffix == "" else target
    return renderer.plot(sim, dpi=dpi, save_path=save_path, **opts)


def export(
    sim: Any,
    var: str | list[str],
    dest: Any,
    *,
    fmt: str | None = None,
    time: int | str | None = None,
    layer: int | None = None,
    resolution: float | None = None,
    crs: str | None = None,
    nodata: float = -9999.0,
) -> Path:
    """Export a variable from a simulation to a standalone file.

    Functional mirror of :func:`read`: same selector (``sim`` / ``var`` /
    ``time`` / ``layer``) plus an output format and destination. ``sim`` must
    be a :class:`~hydromodpy.results.run.Run`, as returned by
    ``hmp.open(workspace)[ref]`` or ``catalog.latest()``.

    ``fmt`` is optional when ``dest`` carries a known extension
    (``.nc`` -> netcdf, ``.tif`` -> geotiff, ``.csv`` -> csv, ``.shp`` ->
    shapefile, ``.vtu`` -> vtu, ``.hmp`` -> portable package).

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> run = hmp.open("~/hmp_workspace")["transient_nwt"]  # doctest: +SKIP
    >>> hmp.export(
    ...     run, "head", "head.tif", time="last", resolution=50
    ... )  # doctest: +SKIP
    >>> hmp.export(
    ...     run, ["head", "watertable_depth"], "fields.nc", time="all"
    ... )  # doctest: +SKIP
    """
    from hydromodpy.results.run import Run

    if not isinstance(sim, Run):
        raise TypeError(
            f"hmp.export expects a Run object as first argument, got {type(sim).__name__}. "
            f"Obtain one with hmp.open(workspace)[ref] or catalog.latest()."
        )
    return sim.export(
        var,
        dest,
        fmt=fmt,
        time=time,
        layer=layer,
        resolution=resolution,
        crs=crs,
        nodata=nodata,
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
    >>> hmp.doctor()["hydromodpy"]  # doctest: +SKIP
    """
    info: dict = {
        "python": platform.python_version(),
        "hydromodpy": __version__,
        "solvers": {},
        "optional": {},
    }
    for pkg in (
        "numpy",
        "pandas",
        "scipy",
        "duckdb",
        "zarr",
        "pyproj",
        "rasterio",
        "shapely",
        "xarray",
        "flopy",
        "pydantic",
        "pint",
        "matplotlib",
        "gmsh",
        "whitebox_workflows",
        "geopandas",
        "pyvista",
    ):
        try:
            mod = importlib.import_module(pkg)
            info["optional"][pkg] = getattr(mod, "__version__", "?")
        except Exception:
            info["optional"][pkg] = None
    for exe in ("mf2005", "mfnwt", "mf6", "mp6", "mp7", "mt3dusgs"):
        info["solvers"][exe] = shutil.which(exe)
    return info
