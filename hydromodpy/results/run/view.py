"""Single-simulation view on one run directory.

What
----
Read-only facade over one run. ``Run`` is opened on the handle that knows
where the run lives: the project index (:class:`Catalog`) or the store of a
run still being computed (:class:`RunStore`). It lazy-loads the row that
describes the run on first access (the index row, or the facts the run
directory states) and exposes typed properties (``solver``,
``status``, ``n_layers`` ...), tabular accessors (``parameters``, ``metrics``,
``timeseries``, ``budget``, ``mass_balance``), the seal of the run
(``record``, ``label()``, read from its directory), field-array
readers (``field``, ``mesh``, ``geographic``, ``geographic_raster``),
spatial helpers (``grid``, ``catchment_mask``, ``dem``, ``outlet``) and the
files the run wrote (``exports``, ``figures``). Heavier
xarray / UGRID readers (``dataset``, ``to_xarray_batch``) live on the
:class:`hydromodpy.results.run.array.RunArrayProvider` exposed as
``run.array``; the point interrogation (one cell, after the fact) lives on
:class:`hydromodpy.results.run.point.RunPointProvider` exposed as
``run.probe``; the stress periods placed on the calendar (``edges``,
``step_at``, ``steps_for``) live on
:class:`hydromodpy.results.run.periods.RunPeriods` exposed as
``run.periods``; the routing descent D (``receiver``, ``surface``, ``graph``
...) lives on :class:`hydromodpy.results.run.descent.RunDescent` exposed as
``run.descent``. Derived catchment views are module-level functions in
:mod:`hydromodpy.results.derive.views` (``saturated_fraction``, ``drainage_density``,
``persistence``, ``catchment_mean``, ``recharge_forcing``).

Why
---
Notebook and script users need a stable per-simulation handle that hides the
Parquet / Zarr split. The rows of the run (timeseries, budgets, parameters)
are read from its own files (:mod:`hydromodpy.results.run.tables`), never
from the index, so the same view serves a running run and a sealed one.

The class composes per-concern mixins to stay under the 50-method limit:

- :class:`RunGeographicMixin` (geographic features, rasters, grid, mesh, field I/O)
- :class:`RunTimeseriesMixin` (parameters, metrics, budgets, timeseries, time index)
- :class:`RunHydrographicMixin` (canonical hydrographic-network roles)

Per-cell views (``saturated_fraction``, ``drainage_density``, ``persistence``,
``cell_field_*``, ``release_flux_*``, ``catchment_mean``) live as
module-level functions in :mod:`hydromodpy.results.derive.views` and consume a
``Run`` instance as their first argument.

Public API
----------
- ``Run``: instantiated by ``Catalog`` resolution methods, on a
  ``RunStore`` by the steps of a running run, or on a sealed directory by
  :func:`open_run_dir` (what ``hmp.open(<run dir>)`` returns). Also
  exposes ``run.array`` for xarray / UGRID readers, ``run.probe`` for
  point interrogation, ``run.periods`` for date lookups and ``run.descent``
  for the routing descent.
- :class:`hydromodpy.results.run.array.RunArrayProvider` exposes
  ``dataset`` and ``to_xarray_batch``.
- :class:`hydromodpy.results.run.point.RunPointProvider` exposes
  ``series`` and ``declared``.
- :class:`hydromodpy.results.run.periods.RunPeriods` exposes
  ``edges``, ``step_at`` and ``steps_for``.
- :class:`hydromodpy.results.run.descent.RunDescent` exposes the
  :class:`~hydromodpy.results.run.contracts.MeshDescent` fields, loaded once.

Cross-refs
----------
- ``hydromodpy.results.catalog.Catalog`` owns this object's data.
- ``hydromodpy.results.run.group.RunSet`` iterates over
  ``Run`` instances.
- ``hydromodpy.results.grid.Grid`` describes the grid of the DEM, never the model cells.
- ``hydromodpy.results.derive.derived`` provides the derived-metric implementations.
"""

from __future__ import annotations

import json as _json
import tomllib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.old_members import refuse_old_member
from hydromodpy.core.state.layout import catalog_path_for
from hydromodpy.core.state.result_dirs import parse_rel_dir
from hydromodpy.results.annotations import add_note, add_tag, read_annotations, remove_tag
from hydromodpy.results.catalog.constants import SIMULATIONS_FROM
from hydromodpy.results.errors import RunNotFoundError, RunNotSealedError
from hydromodpy.results.ledger import Ledger
from hydromodpy.results.manifest import is_sealed
from hydromodpy.results.outcome import effective_status
from hydromodpy.results.record import RunRecord
from hydromodpy.results.run.array import RunArrayProvider
from hydromodpy.results.run.descent import RunDescent
from hydromodpy.results.run.geographic import RunGeographicMixin
from hydromodpy.results.run.hydrographic import RunHydrographicMixin
from hydromodpy.results.run.periods import RunPeriods
from hydromodpy.results.run.point import RunPointProvider
from hydromodpy.results.run.sealed import read_record
from hydromodpy.results.run.timeseries import RunTimeseriesMixin
from hydromodpy.results.run_identity import label_of
from hydromodpy.results.storage.contract import (
    RUN_CONFIG_FILENAME,
    RUN_EXPORTS_DIRNAME,
    RUN_FIGURES_DIRNAME,
    RUN_MANIFEST_FILENAME,
    RUN_OUTCOME_FILENAME,
)
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.results.validity_rules import LabelResult

logger = get_logger(__name__)

if TYPE_CHECKING:
    from pydantic import BaseModel

    from hydromodpy.results.catalog import Catalog
    from hydromodpy.results.checks import Checks
    from hydromodpy.results.manifest import InputEntry

_WORKSPACE_OUTPUT_KEYS: tuple[str, ...] = ("catalog_path", "runs_dir")
"""``[workspace]`` members that derive from ``project_root`` and name outputs."""


def live_catalog(catalog: Any) -> Any:
    """Return ``catalog``, or a fresh handle on the same files once it is closed.

    A ``Run`` taken from a ``Project`` used to die with the ``with`` block that
    closed the project's catalog (``Connection already closed``). The run keeps
    the paths, so it opens the catalog again on its next read, read-only, like
    the handle ``hmp.open`` gives.
    """
    if not getattr(catalog, "closed", False):
        return catalog
    return catalog._reopen()  # noqa: SLF001 - same package, one caller


def _reanchor_workspace(payload: dict, project_root: Path) -> dict:
    """Point the ``[workspace]`` output paths of a snapshot at ``project_root``.

    A sealed configuration names no machine, so it holds no project root. The
    project that holds the run is the only honest anchor, whatever the current
    directory, so ``project_root`` is written and every output path that derives
    from it is dropped: re-validating the payload rebuilds them. Input paths
    (``root``, ``data_dir``) are left untouched, shared data does not travel with
    the project.
    """
    workspace = payload.get("workspace")
    if not isinstance(workspace, dict):
        workspace = {}
    rebound = {k: v for k, v in workspace.items() if k not in _WORKSPACE_OUTPUT_KEYS}
    rebound["project_root"] = str(project_root)
    payload["workspace"] = rebound
    return payload


def _store_row(store: RunStore) -> dict:
    """Return the row of a run opened on its store, from its own directory.

    The facts of the run (its checkpoint, or its seal once sealed) give the
    columns of the index row; the status is read from ``outcome.json``, the
    tags from ``annotations.json`` and the snapshot from ``config.toml``.
    """
    facts = store.facts
    run_dir = store.run_dir
    config_path = run_dir / RUN_CONFIG_FILENAME
    snapshot = (
        tomllib.loads(config_path.read_text(encoding="utf-8")) if config_path.is_file() else None
    )
    tags = read_annotations(run_dir).tags
    return {
        "sim_id": facts.sim_id,
        "name": facts.name,
        "project": facts.project,
        "case_id": facts.case_id,
        "site": None if facts.site is None else facts.site.name,
        "solver": facts.solver,
        "solver_category": facts.solver_category,
        "flow_regime": facts.flow_regime,
        "status": effective_status(run_dir),
        "created_at": facts.created_at,
        "started_at": facts.started_at,
        "duration_s": None,
        "n_cells": facts.n_cells,
        "n_layers": facts.n_layers,
        "n_timesteps": facts.n_timesteps,
        "mesh_hash": facts.mesh_hash,
        "mesh_topology": facts.mesh_topology,
        "crs_wkt": facts.crs_wkt,
        "crs_epsg": facts.crs_epsg,
        "period_start": facts.period_start,
        "period_end": facts.period_end,
        "time_unit": facts.time_unit,
        "config_hash": facts.config_hash,
        "config_snapshot": snapshot,
        "tags": list(tags) or None,
    }


def project_root_of(run_dir: Path) -> tuple[Path, str] | None:
    """Return the project a run directory sits in and its relative form, or None.

    The two forms a run directory takes are those ``parse_rel_dir`` knows,
    ``runs/<name>`` and ``sessions/<name>/trials/<nnnn>``: the trailing parts
    of the path are tried against them, the shorter first.
    """
    parts = Path(run_dir).expanduser().resolve().parts
    for depth in (2, 4):
        if len(parts) <= depth:
            continue
        rel = "/".join(parts[-depth:])
        try:
            parsed = parse_rel_dir(rel)
        except ValueError:
            continue
        if parsed.kind in ("run", "trial"):
            return Path(*parts[:-depth]), rel
    return None


def open_run_dir(
    run_dir: str | Path,
    *,
    read_config: Callable[[Mapping[str, Any]], BaseModel] | None = None,
) -> Run:
    """Open the sealed run in *run_dir* from its own files, without the index.

    The run reads its row from its seal, its tables and fields from its
    directory, so a run copied out of its project or a project never indexed
    reads the same. *read_config* is the function that validates a sealed
    configuration snapshot; without one, :attr:`Run.hydromodpy_config` is
    refused and the raw mapping stays on :attr:`Run.config_snapshot`. Raises
    :class:`~hydromodpy.results.errors.RunNotSealedError` for a directory
    without ``manifest.json``: a run that never completed is read through the
    index of its project, or from its ``outcome.json``.
    """
    directory = Path(run_dir).expanduser().resolve()
    if not directory.is_dir():
        raise FileNotFoundError(f"{directory} is not a run directory")
    if not is_sealed(directory):
        raise RunNotSealedError(
            f"{directory} has no {RUN_MANIFEST_FILENAME}: the run never completed and has no "
            f"seal to read alone. Read its {RUN_OUTCOME_FILENAME}, or open its project."
        )
    located = project_root_of(directory)
    store = RunStore.open(directory, workspace=None if located is None else located[0])
    return Run(store.sim_id, store, read_config=read_config)  # type: ignore[arg-type]


def _ledger_files(directory: Path) -> list[Path]:
    """Return the files the ledger of *directory* records and that are still there."""
    found = (directory / entry.file for entry in Ledger.read(directory).entries)
    return sorted(path for path in found if path.is_file())


class Run(
    RunGeographicMixin,
    RunTimeseriesMixin,
    RunHydrographicMixin,
):
    """Read one persisted simulation from a HydroModPy catalog.

    ``Run`` is a lightweight view over one row in the ``simulations`` table.
    It exposes metadata, tabular outputs, field arrays, geographic features,
    and convenience helpers without requiring callers to know whether data are
    stored in DuckDB, Parquet, or Zarr.

    Parameters
    ----------
    sim_id
        Simulation UUID stored in the catalog.
    catalog
        Open ``Catalog`` that owns the run metadata and storage paths.

    Raises
    ------
    hydromodpy.results.errors.RunNotFoundError
        On first attribute access if ``sim_id`` is not present in the catalog.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> proj = hmp.open("~/hmp_workspace/projects/nancon")  # doctest: +SKIP
    >>> run = proj["baseline"]  # doctest: +SKIP
    >>> run.label()  # doctest: +SKIP
    >>> run.field("head", time=-1)  # doctest: +SKIP

    See Also
    --------
    hydromodpy.results.catalog.Catalog
        Workspace-level catalog that creates ``Run`` instances.
    hydromodpy.results.run.group.RunSet
        Collection view for many runs.
    """

    def __getattr__(self, name: str) -> Any:
        """Refuse an old member with its new name; anything else is not there."""
        refuse_old_member("Run", name)
        raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")

    def __init__(
        self,
        sim_id: str,
        catalog: Catalog,
        *,
        read_config: Callable[[Mapping[str, Any]], BaseModel] | None = None,
    ) -> None:
        self._sim_id = sim_id
        self._catalog_handle = catalog
        self._read_config = (
            read_config if read_config is not None else getattr(catalog, "read_config", None)
        )
        self._row: dict | None = None
        self._sealed: RunRecord | None = None
        self.array = RunArrayProvider(self)
        self.probe = RunPointProvider(self)
        self.periods = RunPeriods(self)
        self.descent = RunDescent.of_run(self)

    @property
    def _catalog(self) -> Catalog:
        """The catalog this run reads through, reopened if its owner closed it."""
        self._catalog_handle = live_catalog(self._catalog_handle)
        return self._catalog_handle

    @_catalog.setter
    def _catalog(self, catalog: Catalog) -> None:
        self._catalog_handle = catalog

    def _iter_runs(self) -> tuple[Run, ...]:
        """Runs this object stands for, so ``probe`` serves one run and a set alike."""
        return (self,)

    def _load_row(self) -> dict:
        if self._row is None and isinstance(self._catalog_handle, RunStore):
            self._row = _store_row(self._catalog_handle)
        if self._row is None:
            df = self._catalog.backend.query(
                "SELECT s.*, sv.code AS solver, sv.category AS solver_category, "
                "st.code AS status, fr.code AS flow_regime, mt.code AS mesh_topology "
                f"{SIMULATIONS_FROM} WHERE CAST(s.sim_id AS VARCHAR) = ?",
                [self._sim_id],
            )
            if df.empty:
                raise RunNotFoundError(
                    f"Simulation '{self._sim_id}' not found", sim_id=self._sim_id
                )
            self._row = df.iloc[0].to_dict()
            # Tags moved to a per-sim table in v2. Populate as a Python list.
            tag_rows = self._catalog.backend.fetch_all(
                "SELECT tag FROM tags WHERE CAST(sim_id AS VARCHAR) = ? ORDER BY tag",
                [self._sim_id],
            )
            self._row["tags"] = [r[0] for r in tag_rows] if tag_rows else None
        return self._row

    def _record(self) -> RunRecord:
        """The seal of this run, read once from its directory.

        Raises :class:`~hydromodpy.results.errors.RunNotSealedError` for a
        run that never completed.
        """
        if self._sealed is None:
            self._sealed = read_record(self.dir, self._sim_id)
        return self._sealed

    # -- Sealed facts ----------------------------------------------------------

    @property
    def dir(self) -> Path:
        """Directory of this run, ``runs/<name>`` or a trial of a session."""
        return Path(self._catalog.run_dir_for(self._sim_id))

    @property
    def record(self) -> RunRecord:
        """The seal of this run, read from its directory, never from the index.

        ``record.site`` is the basin (``None`` on a synthetic domain),
        ``record.run.case_id`` the case, ``record.lineage`` where the run
        comes from, ``record.checks`` what the seal measured, ``record.inputs``
        every input it loaded (``inputs.json``), ``record.metrics`` and
        ``record.score`` its scores under the metric rule. Raises
        :class:`~hydromodpy.results.errors.RunNotSealedError` for a run
        that never completed.
        """
        return self._record()

    @property
    def site(self) -> str | None:
        """Name of the site this run was computed on, ``None`` on a synthetic domain.

        The whole site block (gauge, outlet, fingerprint) is ``record.site``.
        """
        return self._load_row().get("site")

    @property
    def checks(self) -> Checks:
        """What the seal measured: budget, convergence, coverage, calibration.

        Raises :class:`~hydromodpy.results.errors.RunNotSealedError` for a
        run that never completed.
        """
        return self._record().checks

    @property
    def inputs(self) -> list[InputEntry]:
        """Every input this run loaded, as ``inputs.json`` lists it.

        Raises :class:`~hydromodpy.results.errors.RunNotSealedError` for a
        run that never completed.
        """
        return list(self._record().inputs)

    @property
    def exports(self) -> list[Path]:
        """Files under ``exports/`` that ``exports/index.json`` records, by path."""
        return _ledger_files(self.dir / RUN_EXPORTS_DIRNAME)

    @property
    def figures(self) -> list[Path]:
        """Figures under ``figures/`` that ``figures/index.json`` records, by path."""
        return _ledger_files(self.dir / RUN_FIGURES_DIRNAME)

    def label(self) -> LabelResult:
        """Return the label of this run today, with its rule version and reasons.

        The label is computed on each call from the sealed checks, the version
        that produced the run and the known issues of this build: a newer
        build may declass a run without rewriting it.
        """
        return label_of(self._record(), self.dir)

    # -- Export --------------------------------------------------------------

    def export(
        self,
        variables: str | list[str],
        *,
        time: Any = None,
        period: tuple[Any, Any] | None = None,
        format: str | None = None,
        folder: str | Path | None = None,
        file: str | Path | None = None,
        crs: str | None = None,
        resolution: float | None = None,
        layer: int | None = None,
        nodata: float = -9999.0,
    ) -> list[Path]:
        """Export data of this run to files; return the files written.

        The words of an ``[[export]]`` block: ``variables`` says what (a name,
        a list, or ``"all"``), ``time`` or ``period`` when, ``folder`` or
        ``file`` where. The format follows the data unless ``format`` or the
        extension of ``file`` names one: a field at one date goes to GeoTIFF,
        over several dates to one NetCDF, a series or the budget to CSV, a
        vector layer to GeoPackage, a raster layer to GeoTIFF. Files land in
        ``runs/<run>/exports/``; a relative ``folder`` or ``file`` is read
        from there. Each file carries the identity of the run and is recorded
        in ``exports/index.json``.

        Examples
        --------
        >>> run.export("all")  # doctest: +SKIP
        >>> run.export(["head", "watertable_depth"], time="2001-08-15")  # doctest: +SKIP
        >>> run.export("discharge", period=("2001-01-01", "2002-12-31"))  # doctest: +SKIP
        >>> run.export(
        ...     "watertable_depth", time="last", file="nappe_wgs84.tif", crs="EPSG:4326"
        ... )  # doctest: +SKIP
        """
        from hydromodpy.results.exporters.export_spec import ExportRequest
        from hydromodpy.results.exporters.request import export_run

        fields = {
            "variables": variables,
            "time": time,
            "period": period,
            "format": format,
            "folder": folder,
            "file": file,
            "crs": crs,
            "resolution": resolution,
            "layer": layer,
            "nodata": nodata,
        }
        request = ExportRequest.model_validate(
            {key: value for key, value in fields.items() if value is not None}
        )
        return export_run(self._catalog, self._sim_id, request)

    # -- Mutations (written in the run directory) ------------------------------

    def tag(self, *specs: str) -> Run:
        """Add (``+tag`` or bare) or remove (``-tag``) tags. Returns self.

        The tags live in ``annotations.json`` of the run; the index, when the
        project has one, reads them back.
        """
        changed = False
        for spec in specs:
            spec = str(spec).strip()
            if not spec:
                continue
            if spec.startswith("-"):
                remove_tag(self.dir, spec[1:])
            else:
                add_tag(self.dir, spec.lstrip("+"))
            changed = True
        if changed:
            self._annotated()
        return self

    def note(self, text: str) -> Run:
        """Append a timestamped note to ``annotations.json`` of this run. Returns self."""
        add_note(self.dir, text)
        self._annotated()
        return self

    def delete(self) -> None:
        """Move this run to ``trash/`` (reversible). Raises if protected or running."""
        from hydromodpy.results.trash import trash_run

        root = self._project_root()
        trash_run(root, self.dir.relative_to(root).as_posix(), now=datetime.now(UTC))
        self._refresh_index(root)

    def _annotated(self) -> None:
        """Forget the cached row and bring the index up to date with the annotations."""
        self._row = None
        self._refresh_index(self._project_root())

    def _project_root(self) -> Path:
        """The project that holds this run."""
        root = self._catalog.workspace_path
        return Path(root) if root is not None else self.dir.parent.parent

    @staticmethod
    def _refresh_index(project_root: Path) -> None:
        """Re-index the project after a change on disk, when it keeps an index."""
        if not catalog_path_for(project_root).is_file():
            return
        from hydromodpy.results.catalog.indexer import index_new_runs

        index_new_runs(project_root)

    # -- Metadata properties -------------------------------------------------

    @property
    def sim_id(self) -> str:
        """Simulation UUID persisted in the catalog."""
        return self._sim_id

    @property
    def name(self) -> str | None:
        """Optional human-readable run name."""
        return self._load_row().get("name")

    @property
    def project(self) -> str:
        """Project label associated with this run."""
        return self._load_row()["project"]

    @property
    def solver(self) -> str | None:
        """Flow solver name recorded for this run."""
        return self._load_row().get("solver")

    @property
    def flow_regime(self) -> str | None:
        """Flow regime recorded by the workflow, such as steady or transient."""
        return self._load_row().get("flow_regime")

    @property
    def status(self) -> str | None:
        """Run status stored in the catalog."""
        return self._load_row().get("status")

    @property
    def config_snapshot(self) -> dict | None:
        """Raw config payload stored in the catalog as a dict.

        Returns the JSON-decoded snapshot persisted at registration time
        (full ``HydroModPyConfig.model_dump(mode='json')``), re-anchored on the
        project that holds this run. Use :attr:`hydromodpy_config` for a
        validated Pydantic instance.
        """
        val = self._load_row().get("config_snapshot")
        if val is None:
            return None
        payload = _json.loads(val) if isinstance(val, str) else dict(val)
        return _reanchor_workspace(payload, self._project_root())

    @property
    def hydromodpy_config(self) -> BaseModel:
        """Validated :class:`HydroModPyConfig` rebuilt from the stored snapshot.

        The run reads it through the ``read_config`` function its opener
        passed: a run opened by ``hmp.open`` or by a ``Project`` carries the
        one that validates a sealed snapshot, migration included. Raises
        ``ConfigError`` when this handle carries none: open the run through
        ``hmp.open`` or pass ``read_config``, the validation of
        ``HydroModPyConfig.from_dict(run.config_snapshot, sealed=True)``. With
        a function, a snapshot this version no longer validates raises
        ``ValueError`` and :attr:`config_snapshot` still gives the raw mapping.
        """
        snapshot = self.config_snapshot
        if snapshot is None:
            raise ValueError(
                f"Simulation '{self._sim_id}' has no config snapshot; "
                "cannot rebuild HydroModPyConfig."
            )
        if self._read_config is None:
            raise ConfigError(
                f"This run handle does not carry the function that validates a sealed "
                f"configuration. Open the run with hmp.open({self.dir}) or by its project, "
                "or pass read_config to open_run_dir, built on "
                "HydroModPyConfig.from_dict(run.config_snapshot, sealed=True). "
                "The raw mapping stays on run.config_snapshot."
            )
        try:
            return self._read_config(snapshot)
        except ConfigError:
            raise
        except Exception as exc:
            raise ValueError(
                f"The configuration of run '{self._sim_id[:8]}' no longer validates "
                f"under this version of HydroModPy, which renamed or removed some "
                f"of its keys since the run was made. Read the raw mapping with "
                f"run.config_snapshot. Validation said: {exc}"
            ) from exc

    @property
    def tags(self) -> list[str] | None:
        """Optional tags attached to this simulation."""
        return self._load_row().get("tags")

    @property
    def n_layers(self) -> int | None:
        """Number of vertical layers in the persisted simulation mesh."""
        return self._load_row().get("n_layers")

    @property
    def n_cells(self) -> int | None:
        """Number of active cells or faces in the persisted simulation mesh."""
        return self._load_row().get("n_cells")

    @property
    def n_timesteps(self) -> int | None:
        """Number of persisted timesteps when the workflow is time-dependent."""
        return self._load_row().get("n_timesteps")

    # -- Repr ----------------------------------------------------------------

    def __repr__(self) -> str:
        try:
            row = self._load_row()
            return (
                f"Run(sim_id={self._sim_id!r}, "
                f"project={row.get('project')!r}, "
                f"solver={row.get('solver')!r}, "
                f"status={row.get('status')!r})"
            )
        except RunNotFoundError:
            return f"Run(sim_id={self._sim_id!r}, <not found>)"

    def _repr_html_(self) -> str:
        try:
            row = self._load_row()
        except RunNotFoundError:
            return f"<b>Run</b> <code>{self._sim_id[:8]}</code> <i>(not found)</i>"
        dur = row.get("duration_s")
        dur_str = f"{dur:.1f} s" if isinstance(dur, (int, float)) else "&mdash;"
        rows = [
            ("sim_id", f"<code>{self._sim_id}</code>"),
            ("name", str(row.get("name") or "&mdash;")),
            ("project", str(row.get("project") or "&mdash;")),
            ("solver", str(row.get("solver") or "&mdash;")),
            ("status", str(row.get("status") or "&mdash;")),
            ("duration", dur_str),
            ("n_cells", str(row.get("n_cells") or "&mdash;")),
            ("n_timesteps", str(row.get("n_timesteps") or "&mdash;")),
        ]
        body = "".join(
            f"<tr><th style='text-align:left'>{k}</th><td>{v}</td></tr>" for k, v in rows
        )
        return (
            "<div><b>Run</b>"
            "<table style='font-size:0.85em;border-collapse:collapse'>"
            f"{body}</table></div>"
        )
