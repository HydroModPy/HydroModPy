"""Custom data loader for piezometry (user-provided CSV/SHP files).

Same conventions as hydrometry: location file + chronicle CSVs.
Single-row CSVs are expanded as constants over the project period.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from hydromodpy.data_managers.common.io_helpers import (
    parse_chronicle_filename, read_locations, read_timeseries_csv, safe_file_token,
)
from hydromodpy.data_managers.common.unit_helpers import get_conversion_factor
from hydromodpy.data_managers.contracts.timeseries import PointRecord
from hydromodpy.data_managers.piezometry.config import PiezometrySourceConfig


def load_custom(
    config: PiezometrySourceConfig,
    *,
    project_period: tuple[datetime, datetime] | None = None,
) -> list[PointRecord]:
    """Load piezometry records from user files or fixed values."""

    if config.fixed_value is not None or config.fixed_values is not None:
        return _load_fixed_values(config, project_period=project_period)

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

    print(f"  Custom: {len(locations)} piezometers from {loc_file.name}")

    factor = get_conversion_factor(config.source_unit, config.target_unit)
    records: list[PointRecord] = []

    for loc in locations:
        chronicle_path = _find_chronicle_file(data_dir, loc.id)
        if chronicle_path is None:
            print(f"  WARNING: no chronicle for piezometer {loc.id}")
            continue

        df = read_timeseries_csv(
            chronicle_path, col_datetime=config.col_datetime, col_value=config.col_value,
        )
        if df.empty:
            continue

        if factor != 1.0:
            df["value"] = df["value"] * factor

        is_constant = len(df) == 1
        if is_constant and project_period is not None:
            df = _expand_constant(df.iloc[0]["value"], project_period)

        parsed = parse_chronicle_filename(chronicle_path.name)
        freq = parsed["freq"] if parsed else "D"

        records.append(
            PointRecord(
                station_id=loc.id, variable="groundwater_level", source="custom",
                unit=config.target_unit, frequency=freq, data=df,
                date_start=df["datetime"].min().to_pydatetime(),
                date_end=df["datetime"].max().to_pydatetime(),
                location=loc, is_constant=is_constant,
            )
        )

    print(f"  Custom: loaded {len(records)} piezometer records")
    return records


def _load_fixed_values(
    config: PiezometrySourceConfig,
    *,
    project_period: tuple[datetime, datetime] | None,
) -> list[PointRecord]:
    if project_period is None:
        raise ValueError("project_period required to expand fixed values.")

    entries: dict[str, float] = {}
    if config.fixed_values:
        entries = dict(config.fixed_values)
    elif config.fixed_value is not None:
        if not config.station_ids:
            raise ValueError("fixed_value requires station_ids.")
        entries = {sid: config.fixed_value for sid in config.station_ids}

    factor = get_conversion_factor(config.source_unit, config.target_unit)
    records: list[PointRecord] = []
    for station_id, val in entries.items():
        df = _expand_constant(val * factor, project_period)
        records.append(
            PointRecord(
                station_id=station_id, variable="groundwater_level", source="custom",
                unit=config.target_unit, frequency="D", data=df,
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
        candidate = data_dir / f"piezometry_custom_LOC.{ext}"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"No piezometry_custom_LOC.* in {data_dir}")


def _find_chronicle_file(data_dir: Path, station_id: str) -> Path | None:
    safe_id = safe_file_token(station_id)
    for pattern in (f"piezometry_custom_{safe_id}_*.csv", f"piezometry_custom_{station_id}_*.csv"):
        matches = sorted(data_dir.glob(pattern))
        if matches:
            return matches[0]
    exact = data_dir / f"piezometry_custom_{safe_id}.csv"
    return exact if exact.exists() else None
