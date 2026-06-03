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


def open(workspace: Any, *, create: bool = False) -> Any:
    """Open a HydroModPy project catalog.

    The single door to a workspace catalog: returns a
    :class:`hydromodpy.results.catalog.SimulationCatalog` backed by
    ``catalog.duckdb``. It exposes object access (``latest``, ``best``,
    ``find``, ``cat[ref]``), tabular access (``frame``, ``sql``,
    ``list_simulations``), schema discovery (``describe``, ``tables``,
    ``columns``, ``variables``, ``metrics``, ``stations``), per-id reads
    (``read``), and the simulation writers used by the workflow engine.

    Parameters
    ----------
    workspace
        Project directory holding ``catalog.duckdb`` (or a direct path to the
        ``.duckdb`` file).
    create
        ``False`` (default) raises :class:`FileNotFoundError` when no catalog
        exists yet (no phantom catalog is created). ``True`` opens and
        initialises an empty catalog.

    Returns
    -------
    hydromodpy.results.catalog.SimulationCatalog
        Catalog handle for the project.

    Raises
    ------
    FileNotFoundError
        If no ``catalog.duckdb`` is found and ``create`` is ``False``.
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
    from hydromodpy.core.state.paths import CATALOG_FILENAME, find_catalog_root
    from hydromodpy.results.catalog import SimulationCatalog

    ws = Path(workspace).expanduser().resolve()
    if ws.suffix == ".duckdb":
        catalog_file = ws
    else:
        catalog_file = find_catalog_root(ws) / CATALOG_FILENAME
    if not create and not catalog_file.is_file():
        raise FileNotFoundError(
            f"No catalog at {catalog_file.parent}. Run a workflow there first, "
            f"or pass create=True to initialise an empty catalog."
        )
    return SimulationCatalog(ws)


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
    hydromodpy.calibration.cli_runner.run_calibration_cli
        TOML entry point used by the path branch.
    hydromodpy.calibration.programmatic_runner.run_calibration_programmatic
        Python entry point used by the config-object branch.
    hydromodpy.calibration.CalibrationReport
        Structured calibration result.
    """
    if isinstance(config, (str, Path)):
        from hydromodpy.calibration.cli_runner import run_calibration_cli

        kwargs.pop("headless", None)
        return run_calibration_cli(Path(config).expanduser().resolve(), **kwargs)

    from hydromodpy.project import Project

    headless = bool(kwargs.pop("headless", True))
    with Project.lazy(config, headless=headless) as project:
        return project.calibrate(**kwargs)


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
) -> Any:
    """Read a variable from a simulation Run with storage-kind auto-dispatch.

    Single entry point for reads on a :class:`~hydromodpy.results.run.Run`.
    The return type follows one rule:

    - Zarr field -> ``xr.DataArray`` (lazy); when ``time`` is an ``int``, the
      eager ``np.ndarray`` of that single timestep instead.
    - timeseries -> ``pd.Series``.
    - geographic feature -> ``gpd.GeoDataFrame``.

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
    from hydromodpy.results.reading import read_variable

    return read_variable(sim, var, time=time, layer=layer, sel=sel, bbox=bbox)


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
    >>> run = hmp.open("~/hmp_workspace")["transient_nwt"]
    >>> hmp.export(run, "head", "head.tif", time="last", resolution=50)
    >>> hmp.export(run, ["head", "watertable_depth"], "fields.nc", time="all")
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
    from hydromodpy.core.state.paths import CATALOG_FILENAME, find_catalog_root
    from hydromodpy.results.catalog import SimulationCatalog
    from hydromodpy.results.catalog.audit import apply_retention

    workspace_root = find_catalog_root(
        Path(workspace).expanduser().resolve() if workspace else Path.cwd().resolve()
    )
    catalog_path = workspace_root / CATALOG_FILENAME
    if not catalog_path.is_file():
        raise FileNotFoundError(f"No catalog at {workspace_root}")
    with SimulationCatalog(workspace_root) as catalog:
        return apply_retention(catalog.connection, dry_run=not apply)


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
