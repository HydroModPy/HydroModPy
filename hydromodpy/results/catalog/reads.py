"""Read-side queries against the index.

Tabular ``query_*``, ``list_*``, ``read_geographic_*`` accessors plus a
DataFrame property over ``simulations``. Every method is a pure read: the
index is opened read-only, and listing, showing, querying or plotting a
project leaves its file untouched.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import numpy as np
import pandas as pd

from hydromodpy.results.catalog.constants import MESH_ENGINE_SQL, SIMULATIONS_FROM
from hydromodpy.results.storage.contract import geographic_feature_files

if TYPE_CHECKING:
    import geopandas as gpd

# Filter columns that map to a real simulations.* column (no dim join).
_SIMULATION_DIRECT_FILTERS: frozenset[str] = frozenset(
    {
        "sim_id",
        "name",
        "name_stem",
        "project",
        "site",
        "site_fingerprint",
        "recipe",
        "case_id",
        "rel_dir",
        "attempt_id",
        "label",
        "session_id",
        "hydromodpy_version",
        "mesh_hash",
        "n_cells",
        "n_layers",
        "n_timesteps",
        "crs_wkt",
        "crs_epsg",
        "period_start",
        "period_end",
        "time_unit",
        "solution_key",
        "request_id",
        "config_source",
        "parent_sim_id",
        "lineage_kind",
        "duration_s",
        "created_at",
        "scientific_objective",
        "doi",
    }
)

# Filter columns resolved via dim-table JOINs, and the engine the seal names.
_SIMULATION_DIM_FILTERS: dict[str, str] = {
    "solver": "sv.code",
    "solver_category": "sv.category",
    "flow_regime": "fr.code",
    "status": "st.code",
    "mesh_topology": "mt.code",
    "mesh_engine": MESH_ENGINE_SQL,
}

_SIMULATION_FILTER_COLUMNS: frozenset[str] = _SIMULATION_DIRECT_FILTERS | frozenset(
    _SIMULATION_DIM_FILTERS.keys()
)

_SIMULATION_ORDER_COLUMNS: frozenset[str] = _SIMULATION_FILTER_COLUMNS | frozenset(
    {
        "started_at",
        "ended_at",
        "nse",
        "calibrated_by_cost",
        "bbox_xmin",
        "bbox_ymin",
        "bbox_xmax",
        "bbox_ymax",
    }
)
_ORDER_DIRECTIONS: frozenset[str] = frozenset({"ASC", "DESC"})


def _order_clause(order_by: str | tuple[str, str] | None) -> str | None:
    if order_by is None:
        return None
    if isinstance(order_by, tuple):
        column, direction = order_by
    else:
        parts = str(order_by).strip().split()
        if len(parts) == 1:
            column, direction = parts[0], "ASC"
        elif len(parts) == 2:
            column, direction = parts
        else:
            raise ValueError("order_by must be '<column>' or '<column> ASC|DESC'")
    if column not in _SIMULATION_ORDER_COLUMNS:
        raise ValueError(f"Unknown order_by column: {column!r}")
    direction = direction.upper()
    if direction not in _ORDER_DIRECTIONS:
        raise ValueError("order_by direction must be 'ASC' or 'DESC'")
    if column in _SIMULATION_DIM_FILTERS:
        return f"{_SIMULATION_DIM_FILTERS[column]} {direction}"
    return f"s.{column} {direction}"


_SIMULATIONS_VIEW_SELECT = (
    # Listing path: never pull the two config blobs (a run reads its own row
    # through Run._load_row), so `ls` stays cheap on a project of many runs.
    "SELECT s.* EXCLUDE (config_toml, config_snapshot, mesh_engine), "
    "sv.code AS solver, sv.category AS solver_category, "
    "st.code AS status, "
    "fr.code AS flow_regime, "
    "mt.code AS mesh_topology, "
    f"{MESH_ENGINE_SQL} AS mesh_engine "
    f"{SIMULATIONS_FROM}"
)


class ReadsMixin:
    """Read-only queries for :class:`Catalog`.

    Relies on attributes provided by the facade: ``self._backend``
    (CatalogBackend port), ``self._workspace`` (the project root) and
    ``self._paths`` (StoragePathResolver), plus ``self.open_zarr`` for the
    field reads.
    """

    def query_field(
        self,
        sim_id: str | UUID,
        variable: str,
        timestep: int,
        layer: int | None = None,
    ) -> np.ndarray:
        """Read one stored period of a field as an array.

        A field the run did not store but can rebuild (water-table depth,
        seepage mask, drain outflow) is computed from the stored ones.

        Parameters
        ----------
        sim_id
            Id of the run.
        variable
            Field name, for example ``"head"``.
        timestep
            Index of the stored period, ``0`` for the first.
        layer
            Layer index of a three-dimensional field. ``None`` keeps every layer.

        Returns
        -------
        numpy.ndarray
            The values of that period, one per cell (and per layer).

        Raises
        ------
        KeyError
            If the run neither stores nor can rebuild ``variable``.

        Examples
        --------
        >>> heads = cat.query_field(
        ...     run.sim_id, "head", timestep=0, layer=0
        ... )  # doctest: +SKIP
        """
        from hydromodpy.results.derive.virtual_fields import read_field_or_virtual

        return read_field_or_virtual(self, str(sim_id), variable, timestep, layer=layer)

    def query_timeseries(
        self,
        sim_id: str | UUID,
        station_id: str,
        variable: str,
        period: tuple | None = None,
        *,
        source: str = "simulated",
    ) -> pd.Series:
        """Read one series of a run at one station.

        Parameters
        ----------
        sim_id
            Id of the run.
        station_id
            Station the series belongs to, for example ``"outlet"``.
        variable
            Series name, for example ``"discharge"``.
        period
            Window ``(start, end)``, or a year as text (``"2002"``). It keeps the
            stress periods it overlaps, as ``Run.timeseries`` reads it. ``None``
            reads the whole series.
        source
            ``"simulated"``, the default, or ``"observed"`` for the measurement
            of the same variable.

        Returns
        -------
        pandas.Series
            Values indexed by time (naive UTC timestamps), named ``variable``.

        Raises
        ------
        KeyError
            If the run holds no such series.

        Examples
        --------
        >>> q = cat.query_timeseries(
        ...     run.sim_id, "outlet", "discharge", period="2002"
        ... )  # doctest: +SKIP
        """
        return self[sim_id].timeseries(variable, station=station_id, period=period, source=source)

    def query_budget(
        self,
        sim_id: str | UUID,
        zone_id: str | None = None,
        steps: tuple[int, int] | None = None,
    ) -> pd.DataFrame:
        """Return the water budget rows of a run.

        Parameters
        ----------
        sim_id
            Id of the run.
        zone_id
            Keep only this budget zone. ``None`` keeps every zone.
        steps
            ``(first, last)`` period indexes, both included.

        Returns
        -------
        pandas.DataFrame
            One row per term, zone and timestep, as stored in the ``budgets``
            table.
        """
        return self[sim_id].budget(zone_id=zone_id, steps=steps)

    def query_mass_balance(self, sim_id: str | UUID) -> pd.DataFrame:
        """Return the mass-balance rows of a run, one per timestep, in time order."""
        return self[sim_id].mass_balance

    def get_provenance(
        self,
        sim_id: str | UUID,
        variable: str | None = None,
    ) -> pd.DataFrame:
        """Return where the input data of a run came from.

        One row per input variable: the source type (an HTTP API, a user file,
        a data manager, a derived product or the cache), the source reference,
        the SHA-256 digests and the loader that read it.

        Parameters
        ----------
        sim_id
            Id of the run.
        variable
            Keep only this input variable, for example ``"dem"``.

        Returns
        -------
        pandas.DataFrame
            The rows of the ``provenance`` table for that run.
        """
        query = "SELECT * FROM provenance WHERE sim_id = ?"
        params: list = [str(sim_id)]
        if variable is not None:
            query += " AND variable = ?"
            params.append(variable)
        return self._backend.query(query, params)

    def list_simulations(self, **filters) -> pd.DataFrame:
        """Return one DataFrame row per sealed run matching ``filters``.

        ``order_by`` accepts only whitelisted simulation columns, with an
        optional ``ASC`` or ``DESC`` direction.
        """
        order_by = filters.pop("order_by", None)
        query = _SIMULATIONS_VIEW_SELECT
        params: list = []
        clauses: list[str] = []
        for key, val in filters.items():
            if key not in _SIMULATION_FILTER_COLUMNS:
                raise ValueError(f"Unknown simulation filter: {key!r}")
            if key in _SIMULATION_DIM_FILTERS:
                clauses.append(f"{_SIMULATION_DIM_FILTERS[key]} = ?")
            else:
                clauses.append(f"s.{key} = ?")
            params.append(val)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        clause = _order_clause(order_by)
        if clause is not None:
            query += f" ORDER BY {clause}"
        return self._backend.query(query, params)

    def list_tracked_files(self, sim_id: str | UUID) -> pd.DataFrame:
        """Return the files a run recorded with their digest.

        Returns
        -------
        pandas.DataFrame
            One row per file: ``role``, ``category``, ``original_path``,
            ``canonical_path``, ``sha256``, ``size_bytes`` and ``portable``
            (whether the file travels with an exported package).
        """
        return self._backend.query(
            """SELECT role, category, original_path, canonical_path,
                      sha256, size_bytes, portable
               FROM tracked_files WHERE sim_id = ?
               ORDER BY role, canonical_path""",
            [str(sim_id)],
        )

    def read_geographic_feature(
        self,
        sim_id: str | UUID,
        feature_name: str,
    ) -> gpd.GeoDataFrame:
        """Read one vector layer of a run, the GeoParquet file of its tables directory."""
        from hydromodpy.core.io.geoparquet import read_geoparquet

        path = geographic_feature_files(self.tables_dir_for(sim_id)).get(feature_name)
        if path is None:
            raise KeyError(f"Feature '{feature_name}' not found for sim '{sim_id}'")
        return read_geoparquet(path)

    def sims_with_tag(self, tag: str) -> set[str]:
        """Return the sim_ids carrying ``tag`` as a set of strings."""
        rows = self._backend.fetch_all(
            "SELECT CAST(sim_id AS VARCHAR) FROM tags WHERE tag = ?", [str(tag)]
        )
        return {str(r[0]) for r in rows}

    def list_geographic_features(self, sim_id: str | UUID) -> list[str]:
        """Return the names of the vector layers a run stored, in name order.

        Each name reads back with :meth:`read_geographic_feature`.
        """
        return sorted(geographic_feature_files(self.tables_dir_for(sim_id)))

    def read_geographic_metadata(self, sim_id: str | UUID) -> dict[str, str]:
        """Return the catchment metadata of a run as a ``key -> value`` map.

        What the run recorded about its catchment and grid: ``epsg``,
        ``catch_area``, ``dem_res``, the outlet (``x_outlet``, ``y_outlet``
        and their snapped values), ``nrow``, ``ncol``. Every value is text.

        Examples
        --------
        >>> float(cat.read_geographic_metadata(run.sim_id)["catch_area"])  # doctest: +SKIP
        """
        from hydromodpy.results.record.label import read_sealed_manifest

        manifest = read_sealed_manifest(self.run_dir_for(sim_id))
        if manifest is None:
            return {}
        return {
            str(key): None if value is None else str(value)
            for key, value in manifest.geometry.catchment.items()
        }

    @property
    def simulations(self) -> pd.DataFrame:
        """Every sealed run of the project, newest first, as a DataFrame.

        The same columns as :meth:`list_simulations`, without a filter.
        """
        return self._backend.query(f"{_SIMULATIONS_VIEW_SELECT} ORDER BY s.created_at DESC")

    @property
    def cases(self) -> pd.DataFrame:
        """Every result directory of the project, one row each, through ``v_cases``.

        A sealed run carries its label and its headline metric; a running,
        failed or aborted attempt carries the status its outcome says.
        """
        return self._backend.query("SELECT * FROM v_cases ORDER BY started_at DESC NULLS LAST")

    @property
    def sites(self) -> pd.DataFrame:
        """The sites named by the runs and sessions of the project, with their counts."""
        return self._backend.query("SELECT * FROM sites ORDER BY site")

    def attempts(self, rel_dir: str) -> pd.DataFrame:
        """Return every attempt of one case, by attempt number."""
        return self._backend.query(
            "SELECT * FROM attempts WHERE rel_dir = ? ORDER BY attempt", [rel_dir]
        )

    @property
    def calibration_sessions(self) -> pd.DataFrame:
        """Return every calibration session row as a DataFrame."""
        return self._backend.query("SELECT * FROM calibration_sessions ORDER BY started_at DESC")

    def calibration_phases(self, session_id: str) -> pd.DataFrame:
        """Return the phases of one session, by rank."""
        return self._backend.query(
            "SELECT * FROM calibration_phases WHERE session_id = ? ORDER BY phase_index",
            [str(session_id)],
        )

    def calibration_iterations(self, session_id: str | UUID) -> pd.DataFrame:
        """Return the trials of one session, one row per trial and case, by trial number."""
        return self._backend.query(
            """
            SELECT i.trial, i.phase, i.restart, c.case_id, c.sim_id, c.rel_dir, c.params_hash,
                   i.params, i.cost, c.cost AS case_cost, c.components, i.status,
                   c.status AS case_status, i.started_at, i.ended_at
              FROM calibration_iterations i
              LEFT JOIN calibration_trial_cases c
                ON c.session_id = i.session_id AND c.trial = i.trial
             WHERE i.session_id = ?
             ORDER BY i.trial, c.case_id
            """,
            [str(session_id)],
        )

    def sql(self, query: str, params: list | None = None) -> pd.DataFrame:
        """Run an arbitrary SQL query against the catalog DuckDB store.

        Documented escape hatch for callers that need ad-hoc analytical
        queries beyond the typed catalog API. Returns the result as a
        :class:`pandas.DataFrame`.
        """
        if params:
            return self._backend.query(query, params)
        return self._backend.query(query)
