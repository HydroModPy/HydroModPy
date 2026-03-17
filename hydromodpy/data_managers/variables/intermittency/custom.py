"""Custom data loader for intermittency (user-provided CSV files).

Expects a location file (intermittency_custom_LOC.*) and chronicle CSVs
per station following the naming convention.

Values are expected as integer flow codes (1-5):
    1 = Assec (dry)
    2 = Écoulement non visible
    3 = Écoulement visible faible
    4 = Écoulement visible acceptable
    5 = Écoulement visible
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from hydromodpy.data_managers.common.io_helpers import (
    parse_chronicle_filename, read_locations, read_timeseries_csv, safe_file_token,
)
from hydromodpy.data_managers.contracts.location import StationLocation
from hydromodpy.data_managers.contracts.timeseries import PointRecord
from hydromodpy.data_managers.variables.intermittency.config import IntermittencySourceConfig


def load_custom(
    config: IntermittencySourceConfig,
    *,
    project_period: tuple[datetime, datetime] | None = None,
    internal_unit: str = "code",
) -> list[PointRecord]:
    """Load intermittency records from user CSV files."""

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

        # Clamp values to valid range [1, 5]
        df["value"] = df["value"].clip(lower=1, upper=5).astype(int)

        parsed = parse_chronicle_filename(chronicle_path.name)
        freq = parsed["freq"] if parsed else "irregular"

        records.append(
            PointRecord(
                station_id=loc.id, variable="flow_state", source="custom",
                unit=internal_unit, frequency=freq, data=df,
                date_start=df["datetime"].min().to_pydatetime(),
                date_end=df["datetime"].max().to_pydatetime(),
                location=loc,
                file_path=chronicle_path,
            )
        )

    print(f"  Custom: loaded {len(records)} station records")
    return records


def _find_location_file(data_dir: Path) -> Path:
    for ext in ("csv", "shp", "gpkg", "geojson"):
        candidate = data_dir / f"intermittency_custom_LOC.{ext}"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"No intermittency_custom_LOC.* in {data_dir}")


def _find_chronicle_file(data_dir: Path, station_id: str) -> Path | None:
    safe_id = safe_file_token(station_id)
    for pattern in (f"intermittency_custom_{safe_id}_*.csv", f"intermittency_custom_{station_id}_*.csv"):
        matches = sorted(data_dir.glob(pattern))
        if matches:
            return matches[0]
    exact = data_dir / f"intermittency_custom_{safe_id}.csv"
    return exact if exact.exists() else None
