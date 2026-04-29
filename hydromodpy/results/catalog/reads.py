"""Read-side queries against the catalog.

Tabular ``query_*``, ``list_*``, ``read_geographic_*`` accessors plus a
DataFrame property over ``simulations`` and the ``export`` dispatch. All
methods are pure reads and never mutate DuckDB or the on-disk artefacts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    import geopandas as gpd


class ReadsMixin:
    """Read-only queries for :class:`SimulationCatalog`.

    Relies on attributes provided by the facade: ``self._db`` and
    ``self._paths`` (StoragePathResolver), plus ``self.open_zarr`` and
    ``self.zarr_path_for`` for field reads / exports.
    """

    def query_field(
        self,
        sim_id: str | UUID,
        variable: str,
        timestep: int,
        layer: int | None = None,
    ) -> np.ndarray:
        sz = self.open_zarr(sim_id)
        try:
            return sz.read_field(variable, timestep, layer=layer)
        except KeyError:
            from hydromodpy.results.virtual_fields import compute_virtual_field

            result = compute_virtual_field(self, str(sim_id), variable, timestep)
            if result is not None:
                if layer is not None and result.ndim == 2:
                    return result[layer]
                return result
            raise KeyError(f"Variable '{variable}' not found for sim={sim_id}") from None
        finally:
            sz.close()

    def query_timeseries(
        self,
        sim_id: str | UUID,
        station_id: str,
        variable: str,
        period: tuple | None = None,
    ) -> pd.Series:
        query = (
            "SELECT datetime, value FROM timeseries "
            "WHERE sim_id = ? AND station_id = ? AND variable = ?"
        )
        params: list = [str(sim_id), station_id, variable]
        if period is not None:
            # Datetimes are stored as UTC-aware TIMESTAMPTZ; normalize the
            # caller's bounds to tz-aware UTC so the comparison is stable
            # regardless of DuckDB's session timezone.
            lo = pd.Timestamp(period[0])
            hi = pd.Timestamp(period[1])
            lo = lo.tz_localize("UTC") if lo.tz is None else lo.tz_convert("UTC")
            hi = hi.tz_localize("UTC") if hi.tz is None else hi.tz_convert("UTC")
            query += " AND datetime >= ? AND datetime <= ?"
            params.extend([lo.to_pydatetime(), hi.to_pydatetime()])
        query += " ORDER BY datetime"
        result = self._db.execute(query, params).fetchdf()
        if result.empty:
            raise KeyError(f"No timeseries for sim={sim_id}, station={station_id}, var={variable}")
        # Strip tz back to naive so the returned series aligns with
        # simulation-internal tz-naive time indexes.
        idx = pd.DatetimeIndex(result["datetime"])
        if idx.tz is not None:
            idx = idx.tz_convert("UTC").tz_localize(None)
        return pd.Series(
            result["value"].values,
            index=idx,
            name=variable,
        )

    def query_budget(
        self,
        sim_id: str | UUID,
        zone_id: str | None = None,
        period: tuple[int, int] | None = None,
    ) -> pd.DataFrame:
        query = "SELECT * FROM budgets WHERE sim_id = ?"
        params: list = [str(sim_id)]
        if zone_id is not None:
            query += " AND zone_id = ?"
            params.append(zone_id)
        if period is not None:
            query += " AND timestep >= ? AND timestep <= ?"
            params.extend(period)
        return self._db.execute(query, params).fetchdf()

    def query_mass_balance(self, sim_id: str | UUID) -> pd.DataFrame:
        return self._db.execute(
            "SELECT * FROM mass_balance WHERE sim_id = ? ORDER BY timestep",
            [str(sim_id)],
        ).fetchdf()

    def get_provenance(
        self,
        sim_id: str | UUID,
        variable: str | None = None,
    ) -> pd.DataFrame:
        query = "SELECT * FROM provenance WHERE sim_id = ?"
        params: list = [str(sim_id)]
        if variable is not None:
            query += " AND variable = ?"
            params.append(variable)
        return self._db.execute(query, params).fetchdf()

    def list_simulations(self, **filters) -> pd.DataFrame:
        """Return one DataFrame row per simulation matching ``filters``.

        ``order_by`` is an optional SQL ORDER BY clause (e.g. ``"created_at DESC"``).
        When omitted, rows are returned in DuckDB storage order - which is
        typically insertion order but not guaranteed by SQL. Callers that need
        the most recent run should pass ``order_by="created_at DESC"`` and
        read ``iloc[0]``.
        """
        order_by = filters.pop("order_by", None)
        query = "SELECT * FROM simulations"
        params: list = []
        if filters:
            clauses = []
            for key, val in filters.items():
                clauses.append(f"{key} = ?")
                params.append(val)
            query += " WHERE " + " AND ".join(clauses)
        if order_by:
            query += f" ORDER BY {order_by}"
        return self._db.execute(query, params).fetchdf()

    def list_tracked_files(self, sim_id: str | UUID) -> pd.DataFrame:
        return self._db.execute(
            """SELECT role, category, original_path, canonical_path,
                      sha256, size_bytes, portable
               FROM tracked_files WHERE sim_id = ?
               ORDER BY role, canonical_path""",
            [str(sim_id)],
        ).fetchdf()

    def read_geographic_feature(
        self,
        sim_id: str | UUID,
        feature_name: str,
    ) -> gpd.GeoDataFrame:
        import geopandas as gpd_mod

        row = self._db.execute(
            "SELECT properties, crs_wkt FROM geographic_features "
            "WHERE sim_id = ? AND feature_name = ?",
            [str(sim_id), feature_name],
        ).fetchone()
        if row is None:
            raise KeyError(f"Feature '{feature_name}' not found for sim '{sim_id}'")
        properties_json, crs = row
        if not properties_json:
            raise KeyError(f"No payload for feature '{feature_name}'")
        props = json.loads(properties_json) if isinstance(properties_json, str) else properties_json
        geojson_str = props.get("geojson") if isinstance(props, dict) else None
        if not geojson_str:
            raise KeyError(f"No GeoJSON data for feature '{feature_name}'")
        gdf = gpd_mod.read_file(geojson_str)
        if crs and gdf.crs is None:
            gdf = gdf.set_crs(crs)
        return gdf

    def list_geographic_features(self, sim_id: str | UUID) -> list[str]:
        rows = self._db.execute(
            "SELECT feature_name FROM geographic_features WHERE sim_id = ? ORDER BY feature_name",
            [str(sim_id)],
        ).fetchall()
        return [r[0] for r in rows]

    def read_geographic_metadata(self, sim_id: str | UUID) -> dict[str, str]:
        rows = self._db.execute(
            "SELECT key, value FROM geographic_metadata WHERE sim_id = ?",
            [str(sim_id)],
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    @property
    def simulations(self) -> pd.DataFrame:
        return self._db.execute("SELECT * FROM simulations ORDER BY created_at DESC").fetchdf()

    @property
    def calibration_sessions(self) -> pd.DataFrame:
        """Return every calibration session row as a DataFrame."""
        return self._db.execute(
            "SELECT * FROM calibration_sessions ORDER BY started_at DESC"
        ).fetchdf()

    def calibration_iterations(self, session_id: str | UUID) -> pd.DataFrame:
        """Return the iteration history for one session as a DataFrame."""
        sid = UUID(str(session_id)) if len(str(session_id).replace("-", "")) == 32 else session_id
        return self._db.execute(
            """
            SELECT iteration, sim_id, params_hash, parameters,
                   objective_value, metrics, status, from_cache, duration_s
              FROM calibration_iterations
             WHERE session_id = ?
             ORDER BY iteration
            """,
            [sid],
        ).fetchdf()

    def sql(self, query: str, params: list | None = None) -> pd.DataFrame:
        if params:
            return self._db.execute(query, params).fetchdf()
        return self._db.execute(query).fetchdf()

    def export(
        self,
        sim_id: str | UUID,
        variable: str,
        fmt: str,
        path: Path | str,
        **kwargs,
    ) -> Path:
        sid = str(sim_id)
        path = Path(path)
        zarr_path = str(self.zarr_path_for(sim_id))

        if fmt == "netcdf":
            from hydromodpy.results.exporters.netcdf import export_netcdf

            variables = [v.strip() for v in variable.split(",")]
            return export_netcdf(zarr_path, sid, variables, path, **kwargs)
        elif fmt == "csv":
            from hydromodpy.results.exporters.csv import export_csv

            return export_csv(
                self._db,
                sid,
                path,
                variable=variable if variable != "*" else None,
                **kwargs,
            )
        elif fmt == "vtu":
            from hydromodpy.results.exporters.vtu import export_vtu

            timestep = kwargs.pop("timestep", 0)
            return export_vtu(zarr_path, sid, variable, timestep, path, **kwargs)
        elif fmt == "geotiff":
            from hydromodpy.results.exporters.geotiff import export_geotiff

            timestep = kwargs.pop("timestep", 0)
            return export_geotiff(zarr_path, sid, variable, timestep, path, **kwargs)
        elif fmt == "shapefile":
            from hydromodpy.results.exporters.shapefile import export_shapefile

            timestep = kwargs.pop("timestep", 0)
            return export_shapefile(zarr_path, sid, variable, timestep, path, **kwargs)
        else:
            raise ValueError(f"Unknown export format '{fmt}'")
