"""Single-simulation view on the results catalog.

What
----
Read-only facade over one row of the ``simulations`` table. ``Run`` lazy-loads
its catalog row on first access and exposes typed properties (``solver``,
``status``, ``n_layers`` ...), tabular accessors (``parameters``, ``metrics``,
``timeseries``, ``budget``, ``mass_balance``, ``provenance``), field-array
readers (``field``, ``mesh``, ``geographic``, ``geographic_raster``) and
spatial helpers (``grid``, ``catchment_mask``, ``dem``, ``outlet``). Heavier
xarray / UGRID readers (``dataset``, ``to_xarray_batch``, ``at``) live on the
:class:`hydromodpy.results.run.array.RunArrayProvider` exposed as
``run.array``. Derived catchment views are module-level functions in
:mod:`hydromodpy.results.derive.views` (``saturated_fraction``, ``drainage_density``,
``persistence``, ``catchment_mean``, ``recharge_forcing``).

Why
---
Notebook and script users need a stable per-simulation handle that hides the
DuckDB / Zarr split. Caching is per-instance to avoid repeated catalog hits
inside a session; cross-process freshness is handled by the catalog itself.

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
- ``Run``: instantiated by ``Catalog`` resolution methods. Also
  exposes ``run.array`` for xarray / UGRID readers.
- :class:`hydromodpy.results.run.array.RunArrayProvider` exposes
  ``dataset`` and ``to_xarray_batch``.

Cross-refs
----------
- ``hydromodpy.results.catalog.Catalog`` owns this object's data.
- ``hydromodpy.results.run.group.RunSet`` iterates over
  ``Run`` instances.
- ``hydromodpy.results.grid.Grid`` backs the spatial helpers.
- ``hydromodpy.results.derive.derived`` provides the derived-metric implementations.
"""

from __future__ import annotations

import json as _json
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from hydromodpy.core.config_kit.root_config_protocol import get_root_config_provider
from hydromodpy.core.logging import get_logger
from hydromodpy.results.errors import RunNotFoundError
from hydromodpy.results.run.array import RunArrayProvider
from hydromodpy.results.run.geographic import RunGeographicMixin
from hydromodpy.results.run.hydrographic import RunHydrographicMixin
from hydromodpy.results.run.timeseries import RunTimeseriesMixin

logger = get_logger(__name__)

if TYPE_CHECKING:
    from pydantic import BaseModel

    from hydromodpy.results.catalog import Catalog

_WORKSPACE_OUTPUT_KEYS: tuple[str, ...] = (
    "catalog_path",
    "runs_dir",
    "solver_scratch_folder",
    "share_folder",
)
"""``[workspace]`` members that derive from ``project_root`` and name outputs."""


def _reanchor_workspace(payload: dict, project_root: Path) -> dict:
    """Point the ``[workspace]`` output paths of a snapshot at ``project_root``.

    The snapshot froze absolute paths resolved on the machine that produced the
    run. Replaying it verbatim on a project that was copied or moved would
    write into the original directory. The project that holds the run is the
    only honest anchor, so ``project_root`` is rewritten and every output path
    that derives from it is dropped: re-validating the payload rebuilds them.
    Input paths (``root``, ``data_dir``) are left untouched, shared data does
    not travel with the project.
    """
    workspace = payload.get("workspace")
    if not isinstance(workspace, dict):
        return payload
    rebound = {k: v for k, v in workspace.items() if k not in _WORKSPACE_OUTPUT_KEYS}
    rebound["project_root"] = str(project_root)
    payload["workspace"] = rebound
    return payload


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
    >>> catalog = hmp.open("~/hmp_workspace")
    >>> run = catalog.latest()
    >>> run.summary()
    >>> run.field("head", timestep=-1)

    See Also
    --------
    hydromodpy.results.catalog.Catalog
        Workspace-level catalog that creates ``Run`` instances.
    hydromodpy.results.run.group.RunSet
        Collection view for many runs.
    """

    def __init__(self, sim_id: str, catalog: Catalog) -> None:
        self._sim_id = sim_id
        self._catalog = catalog
        self._row: dict | None = None
        self.array = RunArrayProvider(self)

    def _load_row(self) -> dict:
        if self._row is None:
            df = self._catalog.backend.query(
                """SELECT s.*,
                          sv.code AS solver,
                          sv.category AS solver_category,
                          st.code AS status,
                          fr.code AS flow_regime,
                          mt.code AS mesh_topology
                     FROM simulations s
                     JOIN solvers sv ON s.solver_id = sv.id
                     JOIN statuses st ON s.status_id = st.id
                     LEFT JOIN flow_regimes fr ON s.flow_regime_id = fr.id
                     LEFT JOIN mesh_topologies mt ON s.mesh_topology_id = mt.id
                    WHERE s.sim_id = ?""",
                [self._sim_id],
            )
            if df.empty:
                raise RunNotFoundError(
                    f"Simulation '{self._sim_id}' not found", sim_id=self._sim_id
                )
            self._row = df.iloc[0].to_dict()
            # Tags moved to a per-sim table in v2. Populate as a Python list.
            tag_rows = self._catalog.backend.fetch_all(
                "SELECT tag FROM tags WHERE sim_id = ? ORDER BY tag",
                [self._sim_id],
            )
            self._row["tags"] = [r[0] for r in tag_rows] if tag_rows else None
        return self._row

    # -- Export --------------------------------------------------------------

    def export(
        self,
        var: str | list[str],
        dest: str | Path,
        *,
        fmt: str | None = None,
        time: int | Literal["first", "last", "all"] | None = None,
        layer: int | None = None,
        resolution: float | None = None,
        crs: str | None = None,
        nodata: float = -9999.0,
    ) -> Path:
        """Export one or more variables of this run to a standalone file.

        The natural Python gesture: no UUID handling, the run already knows
        which simulation to read. ``fmt`` is optional when ``dest`` has a known
        extension (``.nc``, ``.tif``, ``.csv``, ``.shp``, ``.vtu``, ``.hmp``).

        Examples
        --------
        >>> run.export("head", "head.tif", time="last", resolution=50)
        >>> run.export(["head", "watertable_depth"], "fields.nc", time="all")
        >>> run.export("*", "timeseries.csv")
        """
        from hydromodpy.core.config_kit.export_spec import ExportSpec

        spec = ExportSpec(
            var=var,
            dest=Path(dest),
            fmt=fmt,
            time=time,
            layer=layer,
            resolution=resolution,
            crs=crs,
            nodata=nodata,
        )
        return self._catalog.export(self._sim_id, spec)

    # -- Mutations (require a writable catalog) -------------------------------

    def tag(self, *specs: str) -> Run:
        """Add (``+tag`` or bare) or remove (``-tag``) tags. Returns self."""
        for spec in specs:
            spec = str(spec).strip()
            if not spec:
                continue
            if spec.startswith("-"):
                self._catalog.remove_tag(self._sim_id, spec[1:])
            else:
                self._catalog.add_tag(self._sim_id, spec.lstrip("+"))
        return self

    def note(self, text: str) -> Run:
        """Append a timestamped note to this run. Returns self."""
        self._catalog.add_note(self._sim_id, text)
        return self

    def delete(self) -> None:
        """Move this run to the trash (reversible). Raises if pinned."""
        self._catalog.trash(self._sim_id)

    @property
    def parent(self) -> Run | None:
        """Parent :class:`Run` (lineage) or ``None``."""
        parent_sid = self._load_row().get("parent_sim_id")
        if not parent_sid:
            return None
        return Run(str(parent_sid), self._catalog)

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
    def solver_category(self) -> str | None:
        """Solver family category, such as ``"distributed"`` or ``"lumped"``."""
        return self._load_row().get("solver_category")

    @property
    def flow_regime(self) -> str | None:
        """Flow regime recorded by the workflow, such as steady or transient."""
        return self._load_row().get("flow_regime")

    @property
    def status(self) -> str | None:
        """Run status stored in the catalog."""
        return self._load_row().get("status")

    @property
    def created_at(self):
        """Catalog timestamp for run creation."""
        return self._load_row().get("created_at")

    @property
    def duration_s(self) -> float | None:
        """Wall-clock run duration in seconds when available."""
        return self._load_row().get("duration_s")

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
        return _reanchor_workspace(payload, Path(self._catalog.workspace_path))

    @property
    def hydromodpy_config(self) -> BaseModel:
        """Validated :class:`HydroModPyConfig` rebuilt from the stored snapshot.

        Raises ``ValueError`` when no snapshot was persisted for this run.
        """
        snapshot = self.config_snapshot
        if snapshot is None:
            raise ValueError(
                f"Simulation '{self._sim_id}' has no config snapshot; "
                "cannot rebuild HydroModPyConfig."
            )
        return get_root_config_provider().from_dict(snapshot)

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

    @property
    def parent_sim_id(self) -> str | None:
        """Parent simulation id when this run was created from another run."""
        val = self._load_row().get("parent_sim_id")
        return str(val) if val is not None else None

    # -- Summary -------------------------------------------------------------

    def summary(self, json: bool = False) -> dict | str:
        """Return a compact metadata snapshot of this run.

        Picks the headline catalog fields (identity, solver, status,
        timing, mesh sizes, tags). Datetime values are kept as Python
        objects in dict form; with ``json=True`` they are stringified
        and the whole payload is returned as a JSON string.

        Parameters
        ----------
        json
            If ``True``, return a JSON string instead of a dict.

        Returns
        -------
        dict or str
            Headline fields as a dict, or as a JSON-encoded string when
            ``json=True``.

        Raises
        ------
        hydromodpy.results.errors.RunNotFoundError
            If the run row has been deleted between catalog open and call.
        """
        row = self._load_row()
        keys = (
            "name",
            "project",
            "solver",
            "solver_category",
            "flow_regime",
            "status",
            "created_at",
            "duration_s",
            "n_layers",
            "n_cells",
            "n_timesteps",
            "tags",
        )
        data: dict = {"sim_id": self._sim_id}
        for key in keys:
            data[key] = row.get(key)
        if json:
            return _json.dumps(data, default=str, indent=2, sort_keys=False)
        return data

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
