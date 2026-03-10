"""Custom data loader for water quality (user-provided CSV/SHP files).

Same conventions as hydrometry/piezometry: location file + chronicle CSVs.
Single-row CSVs are expanded as constants over the project period.

Unit resolution per station:
  1. ``unit`` column in LOC file (per-station metadata)
  2. ``source_unit`` field in TOML config (applies to all stations)
  3. Error if neither is specified
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
from hydromodpy.data_managers.water_quality.config import WaterQualitySourceConfig


def _resolve_station_unit(
    loc: StationLocation, config: WaterQualitySourceConfig,
) -> str:
    """Return the source unit for *loc*, or raise if unspecified."""
    unit = loc.metadata.get("unit")
    if unit is not None and str(unit).strip():
        return str(unit).strip()
    if config.source_unit is not None:
        return config.source_unit
    raise ValueError(
        f"No unit for site {loc.id!r}. "
        f"Add a 'unit' column in the LOC file or set 'source_unit' in the TOML."
    )


def load_custom(
    config: WaterQualitySourceConfig,
    *,
    project_period: tuple[datetime, datetime] | None = None,
    internal_unit: str = "mg/L",
) -> list[PointRecord]:
    """Load water quality records from user files or fixed values."""

    if config.fixed_value is not None or config.fixed_values is not None:
        return _load_fixed_values(
            config, project_period=project_period, internal_unit=internal_unit,
        )

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

    print(f"  Custom: {len(locations)} water quality sites from {loc_file.name}")

    records: list[PointRecord] = []

    for loc in locations:
        chronicle_path = _find_chronicle_file(data_dir, loc.id)
        if chronicle_path is None:
            print(f"  WARNING: no chronicle for site {loc.id}")
            continue

        df = read_timeseries_csv(
            chronicle_path, col_datetime=config.col_datetime, col_value=config.col_value,
        )
        if df.empty:
            continue

        source_unit = _resolve_station_unit(loc, config)
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
                station_id=loc.id, variable="water_quality", source="custom",
                unit=internal_unit, frequency=freq, data=df,
                date_start=df["datetime"].min().to_pydatetime(),
                date_end=df["datetime"].max().to_pydatetime(),
                location=loc, is_constant=is_constant,
            )
        )

    print(f"  Custom: loaded {len(records)} water quality records")
    return records


def _load_fixed_values(
    config: WaterQualitySourceConfig,
    *,
    project_period: tuple[datetime, datetime] | None,
    internal_unit: str,
) -> list[PointRecord]:
    if project_period is None:
        raise ValueError("project_period required to expand fixed values.")
    if config.source_unit is None:
        raise ValueError(
            "source_unit required for fixed values (no LOC file to read unit from)."
        )

    entries: dict[str, float] = {}
    if config.fixed_values:
        entries = dict(config.fixed_values)
    elif config.fixed_value is not None:
        if not config.station_ids:
            raise ValueError("fixed_value requires station_ids.")
        entries = {sid: config.fixed_value for sid in config.station_ids}

    factor = get_conversion_factor(config.source_unit, internal_unit)
    records: list[PointRecord] = []
    for station_id, val in entries.items():
        df = _expand_constant(val * factor, project_period)
        records.append(
            PointRecord(
                station_id=station_id, variable="water_quality", source="custom",
                unit=internal_unit, frequency="D", data=df,
                date_start=project_period[0], date_end=project_period[1],
                is_constant=True,
            )
        )
    return records


def _expand_constant(value: float, period: tuple[datetime, datetime]) -> pd.DataFrame:
    dates = pd.date_range(start=period[0], end=period[1], freq="D")
    return pd.DataFrame({"datetime": dates, "value": value, "quality": "constant"})


def _find_location_file(data_dir: Path) -> Path:
    for ext in ("csv", "shp", "gpkg", "geojson"):
        candidate = data_dir / f"waterquality_custom_LOC.{ext}"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"No waterquality_custom_LOC.* in {data_dir}")


def _find_chronicle_file(data_dir: Path, station_id: str) -> Path | None:
    safe_id = safe_file_token(station_id)
    for pattern in (f"waterquality_custom_{safe_id}_*.csv", f"waterquality_custom_{station_id}_*.csv"):
        matches = sorted(data_dir.glob(pattern))
        if matches:
            return matches[0]
    exact = data_dir / f"waterquality_custom_{safe_id}.csv"
    return exact if exact.exists() else None
