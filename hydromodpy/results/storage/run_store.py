"""The store of one run: its Zarr arrays, its Parquet tables and its facts.

Why
---
A run used to write through the project catalog: every array and table went
through a handle that also held the DuckDB index, so a hundred cases writing
at once were a hundred writers on one file, and a run that could not open
the index could not write a number. :class:`RunStore` writes into the run
directory alone. It knows the run by its directory and its ``sim_id``, keeps
the same write verbs the solvers and the extraction call (``write_field``,
``write_timeseries``, ``write_budgets`` ...), and accumulates in
:class:`~hydromodpy.results.storage.run_facts.RunFacts` what the seal needs.
The index is rebuilt from the sealed files by the indexer, never written here.

Scope
-----
Opened and closed by each step that writes, for the span of that step. The
facts are read from ``<run>/.hmp/checkpoints/facts.json`` at open and
written back at close, so a later step, or a later attempt, finds what an
earlier one recorded.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import numpy as np
import pandas as pd
import pyarrow as pa

from hydromodpy.core.config_kit.persistence import PersistenceConfig
from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.core.io.file_digest import sha256_of
from hydromodpy.core.logging import get_logger
from hydromodpy.core.scope import (
    CATCHMENT,
    DOMAIN,
    OBSERVED,
    SIMULATED,
    station_name_refusal,
    zone_name_refusal,
)
from hydromodpy.core.state.portable import encode_workspace_path
from hydromodpy.results.catalog.storage_paths import sanitize_segment
from hydromodpy.results.identity import Identity
from hydromodpy.results.record.manifest import (
    RUNTIME_VARIABLE,
    InputEntry,
    MetricRow,
    ParameterRow,
    TrackedInput,
    is_sealed,
    read_seal,
)
from hydromodpy.results.storage.array_fingerprint import fingerprint
from hydromodpy.results.storage.arrow_tables import (
    merge_with_existing,
    table_from_columns,
    table_from_records,
)
from hydromodpy.results.storage.contract import (
    FIELDS_STORE_NAME,
    GEOGRAPHIC_FEATURE_PREFIX,
    PARQUET_FILE_SUFFIX,
    RUN_EXPORTS_DIRNAME,
    TABLES_DIRNAME,
    geographic_feature_files,
)
from hydromodpy.results.storage.digests import path_size_bytes, sha256_directory
from hydromodpy.results.storage.geo_metadata import (
    geographic_feature_description,
    run_parquet_footer,
)
from hydromodpy.results.storage.licence import run_licence
from hydromodpy.results.storage.parquet_io import read_checked_table, write_table_atomic
from hydromodpy.results.storage.parquet_schemas import (
    BUDGETS_SCHEMA,
    MASS_BALANCE_SCHEMA,
    METRICS_SCHEMA,
    PROVENANCE_SCHEMA,
    TIMESERIES_SCHEMA,
    primary_key_for,
    schema_for,
)
from hydromodpy.results.storage.run_facts import (
    RunFacts,
    identity_of,
    read_facts,
    write_facts,
)
from hydromodpy.results.storage.udunits import udunits_spelling
from hydromodpy.results.zarr_store import SimulationZarr

if TYPE_CHECKING:
    import geopandas as gpd

    from hydromodpy.results.zarr_store.mesh_layout import MeshLayout

logger = get_logger(__name__)

_FEATURE_NAME_MAX_LEN = 40
"""Longest vector layer name kept whole in its file name."""

SOLVER_DIAGNOSTICS_DIRNAME = "solver_diagnostics"
"""Folder of the diagnostics a solver writes for its run, ``exports/solver_diagnostics/``."""

_PROVENANCE_SOURCE_TYPES = ("http_api", "custom_file", "data_manager", "derived", "cache")
_TIMESERIES_KEY = ("sim_id", "station_id", "variable", "source", "timestep")


def _column_units(units: Any) -> Any:
    """Return a ``unit`` column, one text or one text per row, in udunits spelling."""
    if units is None or isinstance(units, str):
        return udunits_spelling(units)
    values = np.asarray(units, dtype=object).tolist()
    spelled = {unit: udunits_spelling(unit) for unit in set(values)}
    return np.array([spelled[unit] for unit in values], dtype=object)


class RunStore:
    """Write and read the arrays, tables and facts of one run directory."""

    def __init__(
        self,
        run_dir: Path,
        facts: RunFacts,
        *,
        persistence: PersistenceConfig,
        workspace: Path | None,
    ) -> None:
        self._run_dir = run_dir
        self._facts = facts
        self._persistence = persistence
        self._workspace = workspace
        self._open_zarr_handles: list[SimulationZarr] = []
        self._closed = False
        self._sealed = False

    @classmethod
    def open(
        cls,
        run_dir: str | Path,
        *,
        facts: RunFacts | None = None,
        persistence: PersistenceConfig | None = None,
        workspace: str | Path | None = None,
    ) -> RunStore:
        """Open the store of *run_dir*.

        The facts come from the checkpoint of the attempt when there is one.
        A first open passes *facts*, which names the run; a later open may
        pass them to refresh the attempt they describe. A sealed run keeps
        no checkpoint: its facts are read from its manifest, and the store
        writes none back. ``workspace`` is the project root the tracked
        inputs are encoded against.
        """
        directory = Path(run_dir)
        if not directory.is_dir():
            raise FileNotFoundError(f"{directory} is not a run directory")
        stored = read_facts(directory)
        sealed = stored is None and facts is None and is_sealed(directory)
        if sealed:
            stored = RunFacts.from_manifest(read_seal(directory))
        if facts is None and stored is None:
            raise FileNotFoundError(f"{directory} carries no facts.json and none were given")
        current = facts if facts is not None else stored
        assert current is not None
        if stored is not None and facts is not None:
            current = _merge_facts(stored, facts)
        store = cls(
            directory,
            current,
            persistence=persistence or PersistenceConfig(),
            workspace=None if workspace is None else Path(workspace),
        )
        store._sealed = sealed
        if not sealed:
            write_facts(directory, current)
        return store

    # -- Identity --------------------------------------------------------------

    @property
    def run_dir(self) -> Path:
        """The directory of the run."""
        return self._run_dir

    @property
    def sim_id(self) -> str:
        """Id of the run."""
        return self._facts.sim_id

    @property
    def facts(self) -> RunFacts:
        """What the run knows about itself so far."""
        return self._facts

    @property
    def persistence(self) -> PersistenceConfig:
        """Which sinks this run writes."""
        return self._persistence

    @property
    def save_zarr(self) -> bool:
        """Whether the run keeps a field store."""
        return self._persistence.save_zarr

    @property
    def workspace_path(self) -> Path | None:
        """The project root, when known."""
        return self._workspace

    @property
    def data_root(self) -> Path | None:
        """Return the workspace root the inputs of the run are recorded relative to.

        The workspace that holds the project (``<workspace>/projects/<name>``),
        or the project itself when it stands alone.
        """
        if self._workspace is None:
            return None
        from hydromodpy.core.workspace.resolve import locate_workspace_root

        return locate_workspace_root(self._workspace) or Path(self._workspace).resolve()

    @property
    def fields_path(self) -> Path:
        """``<run>/fields.zarr``."""
        return self._run_dir / FIELDS_STORE_NAME

    @property
    def tables_dir(self) -> Path:
        """``<run>/tables.parquet``."""
        return self._run_dir / TABLES_DIRNAME

    @property
    def solver_diagnostics_dir(self) -> Path:
        """``<run>/exports/solver_diagnostics``, where a solver leaves its diagnostics."""
        return self._run_dir / RUN_EXPORTS_DIRNAME / SOLVER_DIAGNOSTICS_DIRNAME

    def _check_sim(self, sim_id: str | UUID) -> str:
        sid = str(sim_id)
        if sid != self._facts.sim_id:
            raise KeyError(f"this store is the run {self._facts.sim_id[:8]}, not {sid[:8]}")
        return sid

    def run_dir_for(self, sim_id: str | UUID) -> Path:
        """Return the run directory; *sim_id* must be this run."""
        self._check_sim(sim_id)
        return self._run_dir

    def fields_path_for(self, sim_id: str | UUID) -> Path:
        """Return the field store of this run."""
        self._check_sim(sim_id)
        return self.fields_path

    def tables_dir_for(self, sim_id: str | UUID) -> Path:
        """Return the tables directory of this run."""
        self._check_sim(sim_id)
        return self.tables_dir

    def table_path_for(self, sim_id: str | UUID, view_name: str) -> Path:
        """Return the Parquet payload of one view of this run."""
        return self.tables_dir_for(sim_id) / f"{view_name}{PARQUET_FILE_SUFFIX}"

    def identity(self) -> Identity:
        """Return the identity block of the run as its facts know it, label free."""
        return identity_of(self._facts)

    def licence(self) -> str:
        """Return the licence the run may state, from the inputs it read.

        A sealed run states the licence of its seal, so a table written after
        the seal carries the same licence as the tables written before it.
        """
        if self._facts.licence is not None:
            return self._facts.licence
        return run_licence(self.inputs())

    def inputs(self) -> list[InputEntry]:
        """Return the inputs of ``inputs.json``: every loaded input, then every declared file.

        A file the configuration declares and no loaded record names (the DEM a
        catchment is cut from, a mapped network) is an input the run read too. It
        enters with its role as variable, the provider its sidecar names
        (``file`` without one) and the licence its sidecar states. A declared
        folder is not an input: the files the run read in it are.
        """
        from hydromodpy.core.state.portable import decode_workspace_path
        from hydromodpy.schema.sources import input_licence, sidecar_source

        facts = self._facts
        entries = list(facts.inputs)
        named = {entry.path for entry in entries}
        for tracked in facts.tracked_inputs:
            if tracked.path in named:
                continue
            located = (
                Path(tracked.path)
                if self.data_root is None
                else decode_workspace_path(self.data_root, tracked.path)
            )
            if not located.is_file():
                continue
            entries.append(
                InputEntry(
                    variable=tracked.role,
                    provider=sidecar_source(located) or "file",
                    path=tracked.path,
                    sha256=tracked.sha256,
                    bytes=tracked.bytes,
                    license=input_licence(located).spdx,
                )
            )
            named.add(tracked.path)
        return entries

    # -- Zarr ------------------------------------------------------------------

    def open_zarr(self, sim_id: str | UUID) -> SimulationZarr:
        """Open the field store of the run, creating an empty one when it has none."""
        self._check_sim(sim_id)
        fields = self.fields_path
        if not fields.exists():
            fields.parent.mkdir(parents=True, exist_ok=True)
            SimulationZarr.create(fields, n_cells=0, n_layers=1).close()
        handle = SimulationZarr(fields, field_precision=self._persistence.field_precision)
        handle.field_digests = self._facts.field_digests
        handle._on_close = self._untrack_zarr_handle
        self._open_zarr_handles.append(handle)
        return handle

    def create_zarr(
        self,
        *,
        n_cells: int,
        n_layers: int,
        cell_types: list[str] | None = None,
        geographic_fingerprint: str | None = None,
    ) -> None:
        """Create the field store of the run with its grid size. Refused when it exists."""
        if not self._persistence.save_zarr:
            return
        if self.fields_path.exists():
            raise FileExistsError(f"Zarr store already exists: {self.fields_path}")
        SimulationZarr.create(
            self.fields_path,
            n_cells=n_cells,
            n_layers=n_layers,
            cell_types=cell_types,
            geographic_fingerprint=geographic_fingerprint,
        ).close()

    def _untrack_zarr_handle(self, handle: SimulationZarr) -> None:
        try:
            self._open_zarr_handles.remove(handle)
        except ValueError:
            pass

    def _with_zarr(self, sim_id: str | UUID, write: Callable[[SimulationZarr], None]) -> None:
        if not self._persistence.save_zarr:
            return
        sz = self.open_zarr(sim_id)
        try:
            write(sz)
        finally:
            sz.close()

    def write_geographic_raster(
        self,
        sim_id: str | UUID,
        name: str,
        data: np.ndarray,
        *,
        transform: tuple[float, ...],
        crs: str,
        nodata: float = -99999.0,
    ) -> None:
        """Store a raster of the run under ``geographic/<name>``."""
        self._with_zarr(
            sim_id,
            lambda sz: sz.write_geographic_raster(
                name, data, transform=transform, crs=crs, nodata=nodata
            ),
        )

    def write_lake_abacus(self, sim_id: str | UUID, lake_id: str, **arrays: Any) -> None:
        """Store the stage-volume-area curves of one lake."""
        self._with_zarr(sim_id, lambda sz: sz.write_lake_abacus(lake_id, **arrays))

    def write_field(
        self,
        sim_id: str | UUID,
        variable: str,
        timestep: int,
        values: np.ndarray,
        *,
        n_timesteps: int | None = None,
        subgroup: str | None = None,
    ) -> None:
        """Store one period of a field."""
        self._with_zarr(
            sim_id,
            lambda sz: sz.write_field(
                variable, timestep, values, n_timesteps=n_timesteps, subgroup=subgroup
            ),
        )

    def write_field_stack(
        self,
        sim_id: str | UUID,
        variable: str,
        values: np.ndarray,
        *,
        n_timesteps: int | None = None,
        timestep_offset: int = 0,
        subgroup: str | None = None,
    ) -> None:
        """Store many periods of a field in one write."""
        self._with_zarr(
            sim_id,
            lambda sz: sz.write_field_stack(
                variable,
                values,
                n_timesteps=n_timesteps,
                timestep_offset=timestep_offset,
                subgroup=subgroup,
            ),
        )

    def write_time(
        self,
        sim_id: str | UUID,
        values: np.ndarray,
        *,
        epoch: str = "1970-01-01T00:00:00",
        calendar: str = "proleptic_gregorian",
        units: str = "seconds since 1970-01-01T00:00:00",
    ) -> None:
        """Store the time axis of the fields (CF convention)."""
        self._with_zarr(
            sim_id, lambda sz: sz.write_time(values, epoch=epoch, calendar=calendar, units=units)
        )

    def write_crs(
        self,
        sim_id: str | UUID,
        *,
        crs_wkt: str,
        grid_mapping_name: str = "latitude_longitude",
        epsg_code: int | None = None,
        semi_major_axis: float | None = None,
        inverse_flattening: float | None = None,
    ) -> None:
        """Store the CRS of the fields (CF grid mapping)."""
        self._with_zarr(
            sim_id,
            lambda sz: sz.write_crs(
                crs_wkt=crs_wkt,
                grid_mapping_name=grid_mapping_name,
                epsg_code=epsg_code,
                semi_major_axis=semi_major_axis,
                inverse_flattening=inverse_flattening,
            ),
        )

    def write_mesh(
        self,
        sim_id: str | UUID,
        vertices: np.ndarray,
        face_node_connectivity: np.ndarray,
        z_interfaces: np.ndarray,
        layer_indices: np.ndarray | None = None,
        source_cell_indices: np.ndarray | None = None,
        *,
        structured_shape: tuple[int, int] | None = None,
        layout: MeshLayout | None = None,
    ) -> None:
        """Store the mesh of the run (UGRID 1.0)."""
        self._with_zarr(
            sim_id,
            lambda sz: sz.write_mesh(
                vertices,
                face_node_connectivity,
                z_interfaces,
                layer_indices=layer_indices,
                source_cell_indices=source_cell_indices,
                structured_shape=structured_shape,
                layout=layout,
            ),
        )

    # -- Parquet ---------------------------------------------------------------

    def write_timeseries(
        self,
        sim_id: str | UUID,
        station_id: str,
        variable: str,
        ts: pd.Series,
        unit: str = "",
        source: str = SIMULATED,
    ) -> None:
        """Append one station and variable series to ``timeseries.parquet``.

        A measurement cannot carry the word of the whole catchment: it would be
        scored against the simulated outlet.
        """
        refusal = station_name_refusal(station_id) if source == OBSERVED else None
        if refusal is not None:
            raise DataContractViolation(f"Observed {variable}: {refusal}")
        if not self._persistence.save_parquet or ts is None or len(ts) == 0:
            return
        sid = self._check_sim(sim_id)
        index = pd.DatetimeIndex(ts.index)
        index = index.tz_localize("UTC") if index.tz is None else index.tz_convert("UTC")
        self._write_parquet_table(
            target=self.table_path_for(sid, "timeseries"),
            new_table=table_from_columns(
                {
                    "station_id": station_id,
                    "variable": variable,
                    "timestep": np.arange(len(ts), dtype="int64"),
                    "time": index,
                    "value": ts.to_numpy(dtype="float64"),
                    "unit": udunits_spelling(unit),
                    "source": source,
                },
                TIMESERIES_SCHEMA,
                defaults={"sim_id": sid},
            ),
            pk_cols=_TIMESERIES_KEY,
        )

    def write_timeseries_batch(
        self, sim_id: str | UUID, records: Sequence[Mapping[str, Any]]
    ) -> None:
        """Write a batch of timeseries records in one merge."""
        if not self._persistence.save_parquet or not records:
            return
        sid = self._check_sim(sim_id)
        rows = []
        for record in records:
            row = dict(record)
            row.setdefault("sim_id", sid)
            row.setdefault("component", None)
            row["unit"] = udunits_spelling(row.get("unit"))
            row.setdefault("source", SIMULATED)
            rows.append(row)
        self._write_parquet_records(
            target=self.table_path_for(sid, "timeseries"),
            records=rows,
            schema=TIMESERIES_SCHEMA,
            pk_cols=_TIMESERIES_KEY,
        )

    def write_timeseries_columns(self, sim_id: str | UUID, columns: Mapping[str, Any]) -> None:
        """Columnar sibling of :meth:`write_timeseries_batch`."""
        if not self._persistence.save_parquet or not columns:
            return
        sid = self._check_sim(sim_id)
        table = table_from_columns(
            {**columns, "unit": _column_units(columns.get("unit", ""))},
            TIMESERIES_SCHEMA,
            defaults={"sim_id": sid, "source": SIMULATED},
        )
        if table.num_rows == 0:
            return
        self._write_parquet_table(
            target=self.table_path_for(sid, "timeseries"), new_table=table, pk_cols=_TIMESERIES_KEY
        )

    def write_budget(
        self,
        sim_id: str | UUID,
        timestep: int,
        zone_id: str,
        component: str,
        flux_in: float,
        flux_out: float,
        unit: str = "m3 s-1",
    ) -> None:
        """Store one term of the water budget."""
        self.write_budgets(
            sim_id,
            [
                {
                    "timestep": timestep,
                    "zone_id": zone_id,
                    "component": component,
                    "flux_in": flux_in,
                    "flux_out": flux_out,
                    "unit": unit,
                }
            ],
        )

    def write_budgets(self, sim_id: str | UUID, records: list[dict]) -> None:
        """Store water budget rows in ``budgets.parquet``."""
        if not self._persistence.save_parquet or not records:
            return
        sid = self._check_sim(sim_id)
        rows = []
        for record in records:
            row = dict(record)
            row.setdefault("sim_id", sid)
            zone = row.get("zone_id")
            row["zone_id"] = DOMAIN if zone is None else str(zone)
            row["unit"] = udunits_spelling(row.get("unit", "m3 s-1"))
            row["timestep"] = int(row["timestep"])
            rows.append(row)
        self._write_parquet_records(
            target=self.table_path_for(sid, "budgets"),
            records=rows,
            schema=BUDGETS_SCHEMA,
            pk_cols=("sim_id", "timestep", "zone_id", "component"),
        )

    def write_mass_balance(
        self,
        sim_id: str | UUID,
        timestep: int,
        total_in: float,
        total_out: float,
        percent_error: float,
        storage_in: float = 0.0,
        storage_out: float = 0.0,
    ) -> None:
        """Store the mass balance of one timestep."""
        self.write_mass_balances(
            sim_id,
            [
                {
                    "timestep": timestep,
                    "total_in": total_in,
                    "total_out": total_out,
                    "storage_in": storage_in,
                    "storage_out": storage_out,
                    "percent_error": percent_error,
                }
            ],
        )

    def write_mass_balances(self, sim_id: str | UUID, records: list[dict]) -> None:
        """Store mass-balance rows in ``mass_balance.parquet``."""
        if not self._persistence.save_parquet or not records:
            return
        sid = self._check_sim(sim_id)
        rows = []
        for record in records:
            row = dict(record)
            row.setdefault("sim_id", sid)
            row.setdefault("quantity", "water")
            row["unit"] = udunits_spelling(row.get("unit", "m3 s-1"))
            row.setdefault("storage_in", 0.0)
            row.setdefault("storage_out", 0.0)
            row["timestep"] = int(row["timestep"])
            rows.append(row)
        self._write_parquet_records(
            target=self.table_path_for(sid, "mass_balance"),
            records=rows,
            schema=MASS_BALANCE_SCHEMA,
            pk_cols=("sim_id", "timestep", "quantity"),
        )
        errors = [
            abs(float(row["percent_error"]))
            for row in rows
            if row.get("quantity", "water") == "water" and row.get("percent_error") is not None
        ]
        if errors:
            worst = max(errors)
            current = self._facts.budget_pct
            self._facts.budget_pct = worst if current is None else max(current, worst)

    def write_view(
        self, sim_id: str | UUID, view_name: str, records: Sequence[Mapping[str, Any]]
    ) -> None:
        """Store one declared Parquet view of the run.

        A column the schema does not declare is refused by name rather than
        dropped. A view whose schema declares ``crs_wkt`` inherits the CRS of
        the run.
        """
        if not self._persistence.save_parquet or not records:
            return
        sid = self._check_sim(sim_id)
        schema = schema_for(view_name)
        names = set(schema.names)
        unknown = {key for record in records for key in record} - names
        if unknown:
            raise KeyError(
                f"Parquet view {view_name!r} does not declare {sorted(unknown)}; "
                f"it declares {sorted(names)}."
            )
        rows = []
        for record in records:
            row = dict(record)
            row["sim_id"] = sid
            if "crs_wkt" in names:
                row.setdefault("crs_wkt", self._facts.crs_wkt or "")
                row.setdefault("crs_epsg", self._facts.crs_epsg)
            rows.append(row)
        self._write_parquet_records(
            target=self.table_path_for(sid, view_name),
            records=rows,
            schema=schema,
            pk_cols=primary_key_for(view_name),
        )

    def write_geographic_feature(
        self,
        sim_id: str | UUID,
        feature_name: str,
        gdf: gpd.GeoDataFrame,
        *,
        geoparquet_path: str | None = None,
    ) -> None:
        """Store a vector layer of the run as GeoParquet. An empty layer is not stored."""
        from hydromodpy.core.io.geoparquet import write_geoparquet_atomic

        if not self._persistence.save_parquet or gdf.empty:
            return
        sid = self._check_sim(sim_id)
        _, crs, _ = geographic_feature_description(gdf)
        target = self.geographic_feature_path(sid, feature_name, geoparquet_path=geoparquet_path)
        metadata = self.parquet_metadata()
        metadata["hmp.schema"] = "geographic_feature"
        metadata["feature_name"] = feature_name
        if crs:
            metadata["hmp.feature_crs"] = str(crs)
        write_geoparquet_atomic(gdf, target, metadata=metadata)

    def geographic_feature_path(
        self, sim_id: str | UUID, feature_name: str, *, geoparquet_path: str | None = None
    ) -> Path:
        """Return the GeoParquet file of one vector layer of the run."""
        self._check_sim(sim_id)
        if geoparquet_path:
            path = Path(geoparquet_path)
            if path.is_absolute():
                return path
            return (self._workspace or self._run_dir) / path
        # Not cut to a directory-name budget: the file name is where the
        # listing and the indexer read the feature name back from.
        safe_name = sanitize_segment(feature_name, max_len=_FEATURE_NAME_MAX_LEN)
        target = self.tables_dir / f"{GEOGRAPHIC_FEATURE_PREFIX}{safe_name}{PARQUET_FILE_SUFFIX}"
        return target

    def write_metric(self, sim_id: str | UUID, row: MetricRow) -> None:
        """Record one metric of the run: the one writer of the facts and of ``metrics.parquet``.

        A later row of the same station, variable, metric and period replaces it.
        """
        sid = self._check_sim(sim_id)
        self._facts.put_metric(row)
        if not self._persistence.save_parquet:
            return
        self._write_parquet_records(
            target=self.table_path_for(sid, "metrics"),
            records=[
                {
                    "sim_id": sid,
                    "station_id": row.station,
                    "variable": row.variable,
                    "metric": row.metric,
                    "value": row.value,
                    "window_name": row.window_name,
                    "window_role": row.window_role,
                    "window_start": row.window_start,
                    "window_end": row.window_end,
                    "n_samples": row.n_samples,
                    "n_clipped": row.n_clipped,
                    "n_sim_nan": row.n_sim_nan,
                    "metric_rule_version": row.metric_rule_version,
                    "valid_from": pd.Timestamp.now(tz="UTC"),
                }
            ],
            schema=METRICS_SCHEMA,
            pk_cols=("sim_id", "station_id", "variable", "metric", "window_name"),
        )

    def write_runtime_metric(
        self,
        sim_id: str | UUID,
        station_id: str,
        metric_name: str,
        value: float,
    ) -> None:
        """Record a number of the run itself (solve time, budget), which is no score.

        The row stays in the facts, the table and the seal; the index and the
        readers of scores leave it out (:data:`~hydromodpy.results.record.manifest.RUNTIME_VARIABLE`).
        """
        self.write_metric(
            sim_id,
            MetricRow(
                station=station_id,
                variable=RUNTIME_VARIABLE,
                metric=metric_name,
                value=None if value is None else float(value),
            ),
        )

    def write_provenance(
        self,
        sim_id: str | UUID,
        variable: str,
        source_ref: str,
        data: np.ndarray,
        *,
        source_type: str = "data_manager",
        source_sha256: str | None = None,
        loader_name: str | None = None,
        loader_version: str | None = None,
        fetched_at: Any = None,
        period_start: Any = None,
        period_end: Any = None,
    ) -> None:
        """Record the fingerprint and source of one loaded variable."""
        sid = self._check_sim(sim_id)
        if source_type not in _PROVENANCE_SOURCE_TYPES:
            raise ValueError(
                f"Unknown provenance source_type {source_type!r}. "
                f"Expected one of {_PROVENANCE_SOURCE_TYPES}."
            )
        if not self._persistence.save_parquet:
            return
        digest = fingerprint(data)
        self._write_parquet_records(
            target=self.table_path_for(sid, "provenance"),
            records=[
                {
                    "sim_id": sid,
                    "variable": variable,
                    "source_type": source_type,
                    "source_ref": source_ref,
                    "source_sha256": source_sha256,
                    "loader_name": loader_name,
                    "loader_version": loader_version,
                    "fetched_at": fetched_at,
                    "period_start": period_start,
                    "period_end": period_end,
                    "payload_sha256": digest["checksum"],
                    "n_records": int(np.prod(data.shape)),
                    "stats": json.dumps(digest["stats"]),
                }
            ],
            schema=PROVENANCE_SCHEMA,
            pk_cols=("sim_id", "variable", "source_ref"),
        )

    # -- Facts -----------------------------------------------------------------

    def write_parameters(self, sim_id: str | UUID, params: list[dict]) -> None:
        """Record the parameter values the run uses; ``parameters.parquet`` is written at the seal."""
        self._check_sim(sim_id)
        for param in params:
            parameterization = param.get("parameterization")
            calibrated = bool(param.get("calibrated", parameterization == "calibrated"))
            origin = param.get("origin") or ("calibrated" if calibrated else "declared")
            zone = param.get("zone_id")
            refusal = None if zone is None else zone_name_refusal(zone)
            if refusal is not None:
                raise DataContractViolation(
                    f"Parameter {param['param_name']}: {refusal} Write no zone for a uniform value."
                )
            value = param.get("value")
            self._facts.put_parameter(
                ParameterRow(
                    name=str(param["param_name"]),
                    zone=CATCHMENT if zone is None else str(zone),
                    value=None if value is None else float(value),
                    unit=udunits_spelling(param.get("unit")) or None,
                    parameterization=parameterization,
                    origin=origin,
                    calibrated=calibrated,
                )
            )

    def record_input(self, sim_id: str | UUID, entry: InputEntry) -> None:
        """Record one loaded input for ``inputs.json``: provider, request, digest, licence."""
        self._check_sim(sim_id)
        self._facts.put_input(entry)

    def write_run_environment(
        self,
        sim_id: str | UUID,
        *,
        project_root: Path | str | None = None,
        solver_name: str | None = None,
        solver_binary_path: Path | str | None = None,
        solver_engine: str | None = None,
        solver_execution_mode: str | None = None,
        solver_version_text: str | None = None,
        solver_options: dict[str, Any] | None = None,
        rng_seed: int | None = None,
    ) -> None:
        """Record the host environment, the solver engine and what it decided at build."""
        from hydromodpy.results.run.environment import capture_environment

        self._check_sim(sim_id)
        snapshot = dict(
            capture_environment(
                project_root=project_root,
                solver_name=solver_name,
                solver_binary_path=solver_binary_path,
            )
        )
        snapshot["solver_engine"] = solver_engine
        snapshot["solver_execution_mode"] = solver_execution_mode
        if solver_version_text:
            snapshot["solver_version_text"] = solver_version_text
        if solver_options:
            snapshot["solver_options"] = solver_options
        snapshot["rng_seed"] = None if rng_seed is None else int(rng_seed)
        self._facts.environment = snapshot

    def update_simulation_grid_metadata(
        self,
        sim_id: str | UUID,
        *,
        n_cells: int | None = None,
        n_layers: int | None = None,
        mesh_hash: str | None = None,
        mesh_topology: str | None = None,
        bbox: tuple[float, float, float, float] | list[float] | None = None,
    ) -> None:
        """Fill the grid facts known once the solver grid is built; ``None`` keeps a value."""
        self._check_sim(sim_id)
        facts = self._facts
        if n_cells is not None:
            facts.n_cells = int(n_cells)
        if n_layers is not None:
            facts.n_layers = int(n_layers)
        if mesh_hash is not None:
            facts.mesh_hash = mesh_hash
        if mesh_topology is not None:
            facts.mesh_topology = mesh_topology
        if bbox is not None and len(bbox) == 4:
            facts.bbox = tuple(float(v) for v in bbox)  # type: ignore[assignment]

    def update_run_environment_solver_binary(
        self, sim_id: str | UUID, *, solver_binary_path: Path | str | None
    ) -> None:
        """Refine the recorded executable with the one the solver ran; a library is left alone."""
        from hydromodpy.results.run.environment import solver_binary_identity

        self._check_sim(sim_id)
        if solver_binary_path is None:
            return
        environment = self._facts.environment
        if environment.get("solver_engine") not in (None, "executable"):
            return
        sha256, version_text = solver_binary_identity(solver_binary_path)
        environment["solver_binary_path"] = str(solver_binary_path)
        if sha256 is not None:
            environment["solver_binary_sha256"] = sha256
        if version_text is not None:
            environment["solver_version_text"] = version_text

    def register_tracked_files(self, sim_id: str | UUID, entries: list[Any]) -> int:
        """Record the input files the configuration declares, with their digests.

        ``path`` is relative to the workspace root when the file sits under it
        (``data/dem/dem.tif``, ``projects/<name>/zones.shp``), and
        ``declared_path`` the form the frozen ``config.toml`` writes: no copy
        of the record names the machine it ran on.
        """
        from hydromodpy.core.toml_io.paths import portable_declared_path

        self._check_sim(sim_id)
        root = self.data_root
        written = 0
        for entry in entries:
            canonical = Path(entry.canonical_path)
            if canonical.is_file():
                digest = sha256_of(canonical)
            elif canonical.is_dir():
                digest = sha256_directory(canonical)
            else:
                logger.warning(
                    "Tracked input '%s' does not exist, skipping: %s", entry.role, canonical
                )
                continue
            encoded = str(canonical)
            declared = str(entry.original_path)
            if root is not None and self._workspace is not None:
                try:
                    encoded = encode_workspace_path(root, canonical)
                except ValueError:
                    encoded = str(canonical)
                declared = portable_declared_path(
                    declared,
                    role=str(entry.role),
                    project_root=self._workspace,
                    data_dir=root / "data",
                )
            self._facts.put_tracked_input(
                TrackedInput(
                    role=str(entry.role),
                    category=str(entry.category),
                    path=encoded,
                    declared_path=declared,
                    sha256=digest,
                    bytes=int(path_size_bytes(canonical)),
                    portable=bool(entry.portable),
                )
            )
            written += 1
        return written

    def write_geographic_metadata(self, sim_id: str | UUID, metadata: dict[str, object]) -> None:
        """Record the catchment metadata of the run, one key and value each."""
        self._check_sim(sim_id)
        self._facts.geographic_metadata.update({str(key): value for key, value in metadata.items()})

    # -- Reads -----------------------------------------------------------------

    def query_field(
        self, sim_id: str | UUID, variable: str, timestep: int, layer: int | None = None
    ) -> np.ndarray:
        """Read one stored period of a field, or rebuild a virtual one."""
        from hydromodpy.results.derive.virtual_fields import read_field_or_virtual

        return read_field_or_virtual(self, self._check_sim(sim_id), variable, timestep, layer=layer)

    def read_table(self, view_name: str) -> pd.DataFrame:
        """Return one Parquet payload of the run as a frame; empty without the file."""
        path = self.table_path_for(self.sim_id, view_name)
        if not path.is_file():
            return pd.DataFrame()
        return read_checked_table(path).to_pandas()

    def query_timeseries(
        self,
        sim_id: str | UUID,
        station_id: str,
        variable: str,
        period: tuple | None = None,
        *,
        source: str = SIMULATED,
    ) -> pd.Series:
        """Read one series of the run at one station, indexed by naive UTC time.

        ``period`` is read as :meth:`hydromodpy.results.run.Run.timeseries` reads it.
        """
        from hydromodpy.results.run import Run

        self._check_sim(sim_id)
        run = Run(self.sim_id, self)  # type: ignore[arg-type]
        return run.timeseries(variable, station=station_id, period=period, source=source)

    def read_geographic_feature(self, sim_id: str | UUID, feature_name: str) -> gpd.GeoDataFrame:
        """Read one vector layer of the run."""
        from hydromodpy.core.io.geoparquet import read_geoparquet

        path = self.geographic_feature_path(sim_id, feature_name)
        if not path.is_file():
            raise KeyError(f"Feature '{feature_name}' not found for sim '{sim_id}'")
        return read_geoparquet(path)

    def list_geographic_features(self, sim_id: str | UUID) -> list[str]:
        """Return the names of the vector layers the run stored."""
        self._check_sim(sim_id)
        return sorted(geographic_feature_files(self.tables_dir))

    def read_geographic_metadata(self, sim_id: str | UUID) -> dict[str, str]:
        """Return the catchment metadata of the run, every value as text."""
        self._check_sim(sim_id)
        return {
            key: "" if value is None else str(value)
            for key, value in self._facts.geographic_metadata.items()
        }

    # -- Parquet plumbing ------------------------------------------------------

    def parquet_metadata(self) -> dict[str, str]:
        """Return the footer every Parquet payload of the run carries."""
        facts = self._facts
        return run_parquet_footer(
            sim_id=facts.sim_id,
            project=facts.project,
            name=facts.name,
            solver=facts.solver,
            licence=self.licence(),
            scientific_objective=facts.scientific_objective,
            doi=facts.doi,
            identity=self.identity(),
            created_at=facts.created_at,
            crs_epsg=facts.crs_epsg,
            crs_wkt=facts.crs_wkt,
            bbox=facts.bbox,
            period_start=facts.period_start,
            period_end=facts.period_end,
        )

    def _write_parquet_records(
        self,
        *,
        target: Path,
        records: Sequence[Mapping[str, Any]],
        schema: pa.Schema,
        pk_cols: Sequence[str],
    ) -> None:
        table = table_from_records(records, schema, defaults={"sim_id": self.sim_id})
        self._write_parquet_table(target=target, new_table=table, pk_cols=pk_cols)

    def _write_parquet_table(
        self, *, target: Path, new_table: pa.Table, pk_cols: Sequence[str]
    ) -> None:
        """Persist a table atomically, merging with the file already there."""
        merged = merge_with_existing(target, new_table, pk_cols) if target.exists() else new_table
        write_table_atomic(
            merged, target, kv_metadata=self.parquet_metadata(), pk_cols=tuple(pk_cols)
        )

    # -- Lifecycle -------------------------------------------------------------

    def close(self) -> None:
        """Close the open field stores and write the facts back.

        A sealed run keeps its seal as its facts: nothing is written back.
        """
        if self._closed:
            return
        while self._open_zarr_handles:
            handle = self._open_zarr_handles.pop()
            try:
                handle.close()
            except Exception:
                logger.warning("Could not close SimulationZarr handle", exc_info=True)
        if not self._sealed:
            write_facts(self._run_dir, self._facts)
        self._closed = True

    def __enter__(self) -> RunStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _merge_facts(stored: RunFacts, given: RunFacts) -> RunFacts:
    """Return the stored facts refreshed with the attempt the caller names."""
    if stored.sim_id != given.sim_id:
        raise ValueError(
            f"the facts on disk name sim {stored.sim_id[:8]}, the caller names {given.sim_id[:8]}"
        )
    return stored.model_copy(
        update={
            "attempt": given.attempt,
            "attempt_id": given.attempt_id,
            "started_at": given.started_at,
            "lineage": given.lineage,
            "calibrated_by": given.calibrated_by,
        }
    )


__all__ = ["RunStore"]
