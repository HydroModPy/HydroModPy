"""Custom data loader for water quality (user-provided CSV files).

Same conventions as hydrometry/piezometry: location file + chronicle CSVs.
Single-row CSVs are expanded as constants over the project period.

Unit resolution: each station **must** have a ``unit`` column in the
LOC file.  Error if missing.
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


def _resolve_station_unit(loc: StationLocation) -> str:
    """Return the source unit from LOC metadata, or raise."""
    unit = loc.metadata.get("unit")
    if unit is not None and str(unit).strip():
        return str(unit).strip()
    raise ValueError(
        f"No unit for site {loc.id!r}. "
        f"Add a 'unit' column in the LOC file."
    )


def load_custom(
    config: WaterQualitySourceConfig,
    *,
    project_period: tuple[datetime, datetime] | None = None,
    internal_unit: str = "mg/L",
) -> list[PointRecord]:
    """Load water quality records from user CSV files."""

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
                station_id=loc.id, variable="water_quality", source="custom",
                unit=internal_unit, frequency=freq, data=df,
                date_start=df["datetime"].min().to_pydatetime(),
                date_end=df["datetime"].max().to_pydatetime(),
                location=loc, is_constant=is_constant,
            )
        )

    print(f"  Custom: loaded {len(records)} water quality records")
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
