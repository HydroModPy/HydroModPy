"""Custom data loader for recharge (CSV directory, NetCDF, or GeoTIFF).

CSV mode expects a location file (recharge_custom_LOC.*) and chronicle CSVs
per station following the naming convention.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from hydromodpy.data_managers.common.io_helpers import (
    parse_chronicle_filename, read_locations, read_timeseries_csv, safe_file_token,
)
from hydromodpy.data_managers.common.unit_helpers import get_conversion_factor
from hydromodpy.data_managers.contracts.location import StationLocation
from hydromodpy.data_managers.contracts.timeseries import PointRecord
from hydromodpy.data_managers.recharge.config import RechargeSourceConfig

VARIABLE_NAME = "recharge"


def _resolve_station_unit(loc: StationLocation) -> str:
    unit = loc.metadata.get("unit")
    if unit is not None and str(unit).strip():
        return str(unit).strip()
    return "mm/day"


def load_custom(
    config: RechargeSourceConfig,
    *,
    project_period: tuple[datetime, datetime] | None = None,
    internal_unit: str = "mm/day",
) -> list:
    """Load custom data: CSV directory, NetCDF, or GeoTIFF."""
    path = Path(config.path)
    if path.is_dir():
        return _load_csv(config, project_period=project_period, internal_unit=internal_unit)
    elif path.suffix == ".nc":
        from hydromodpy.data_managers.common.custom_grid_loader import load_custom_nc
        return load_custom_nc(path, variable=VARIABLE_NAME, unit=internal_unit, project_period=project_period)
    elif path.suffix in (".tif", ".tiff"):
        from hydromodpy.data_managers.common.custom_grid_loader import load_custom_tif
        return load_custom_tif(path, variable=VARIABLE_NAME, unit=internal_unit)
    else:
        raise ValueError(f"Unsupported custom format: {path.suffix}. Use a directory (CSV), .nc, or .tif.")


def _load_csv(
    config: RechargeSourceConfig,
    *,
    project_period: tuple[datetime, datetime] | None = None,
    internal_unit: str = "mm/day",
) -> list[PointRecord]:
    """Load recharge records from user CSV files."""
    data_dir = Path(config.path)
    if not data_dir.is_dir():
        raise FileNotFoundError(f"Custom data directory not found: {data_dir}")

    loc_file = _find_location_file(data_dir)
    locations = read_locations(
        loc_file, col_id=config.col_id, col_x=config.col_x,
        col_y=config.col_y, col_crs=config.col_crs, default_crs=config.default_crs,
    )

    if config.station_ids:
        requested = set(config.station_ids)
        locations = [loc for loc in locations if loc.id in requested]

    print(f"  Custom: {len(locations)} stations from {loc_file.name}")

    records: list[PointRecord] = []
    for loc in locations:
        chronicle_path = _find_chronicle_file(data_dir, loc.id)
        if chronicle_path is None:
            print(f"  WARNING: no chronicle for station {loc.id}")
            continue

        df = read_timeseries_csv(
            chronicle_path, col_datetime=config.col_datetime, col_value=config.col_value,
        )
        if df.empty:
            continue

        source_unit = _resolve_station_unit(loc)
        factor = get_conversion_factor(source_unit, internal_unit)
        if factor != 1.0:
            df["value"] = df["value"] * factor

        is_constant = len(df) == 1
        if is_constant and project_period is not None:
            df = _expand_constant(df.iloc[0]["value"], project_period)

        parsed = parse_chronicle_filename(chronicle_path.name)
        freq = parsed["freq"] if parsed else "D"

        records.append(
            PointRecord(
                station_id=loc.id, variable=VARIABLE_NAME, source="custom",
                unit=internal_unit, frequency=freq, data=df,
                date_start=df["datetime"].min().to_pydatetime(),
                date_end=df["datetime"].max().to_pydatetime(),
                location=loc, is_constant=is_constant,
                file_path=chronicle_path,
            )
        )

    print(f"  Custom: loaded {len(records)} station records")
    return records


def _expand_constant(value: float, period: tuple[datetime, datetime]) -> pd.DataFrame:
    dates = pd.date_range(start=period[0], end=period[1], freq="D")
    return pd.DataFrame({"datetime": dates, "value": value})


def _find_location_file(data_dir: Path) -> Path:
    for ext in ("csv", "shp", "gpkg", "geojson"):
        candidate = data_dir / f"recharge_custom_LOC.{ext}"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"No recharge_custom_LOC.* in {data_dir}")


def _find_chronicle_file(data_dir: Path, station_id: str) -> Path | None:
    safe_id = safe_file_token(station_id)
    for pattern in (f"recharge_custom_{safe_id}_*.csv", f"recharge_custom_{station_id}_*.csv"):
        matches = sorted(data_dir.glob(pattern))
        if matches:
            return matches[0]
    exact = data_dir / f"recharge_custom_{safe_id}.csv"
    return exact if exact.exists() else None
