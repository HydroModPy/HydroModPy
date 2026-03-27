"""Generic custom point loader for user-provided CSV files.

Replaces the per-variable custom.py boilerplate. Handles:
- Location file discovery ({variable}_custom_LOC.*)
- Chronicle file discovery ({variable}_custom_{id}_*.csv)
- Unit resolution (strict or fallback)
- Constant expansion over project period
- Optional value clamping (intermittency)
- Optional multi-format dispatch (CSV dir / NetCDF / GeoTIFF)
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from hydromodpy.data.common.io_helpers import (
    parse_chronicle_filename,
    read_locations,
    read_timeseries_csv,
    safe_file_token,
)
from hydromodpy.data.common.unit_helpers import convert_array
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.core.tools.log_manager import get_logger

logger = get_logger(__name__)

# Map variable names to file prefixes (for naming convention compatibility).
_VAR_FILE_PREFIX = {
    "water_quality": "waterquality",
}


def load_custom_points(
    *,
    data_dir: Path,
    variable_name: str,
    internal_unit: str,
    project_period: tuple[datetime, datetime] | None = None,
    col_id: str = "id",
    col_x: str = "x",
    col_y: str = "y",
    col_crs: str = "crs",
    default_crs: str = "EPSG:4326",
    col_datetime: str = "datetime",
    col_value: str = "value",
    station_ids: list[str] | None = None,
    default_unit: str | None = None,
    record_variable: str | None = None,
    clamp_values: tuple[int, int] | None = None,
    default_frequency: str = "D",
    expand_constants: bool = True,
    source_unit_override: str | None = None,
) -> list[PointRecord]:
    """Load point records from a CSV directory.

    Parameters
    ----------
    data_dir : Path
        Directory containing LOC file and chronicle CSVs.
    variable_name : str
        Variable name for file discovery (e.g. "hydrometry").
    internal_unit : str
        Target unit for loaded data (e.g. "m3/s").
    default_unit : str or None
        If None, unit column in LOC is required (raises on missing).
        If set, used as fallback when LOC unit is missing.
    record_variable : str or None
        Override the ``variable`` field in PointRecord.
        If None, uses *variable_name*.
    clamp_values : tuple or None
        If set, clamp values to (min, max) range.
    default_frequency : str
        Frequency if not parseable from filename.
    expand_constants : bool
        Expand single-row CSVs to daily series over project_period.
    """
    if not data_dir.is_dir():
        raise FileNotFoundError(f"Custom data directory not found: {data_dir}")

    loc_file = _find_location_file(data_dir, variable_name)
    locations = read_locations(
        loc_file, col_id=col_id, col_x=col_x,
        col_y=col_y, col_crs=col_crs, default_crs=default_crs,
    )

    if station_ids:
        requested = set(station_ids)
        locations = [loc for loc in locations if loc.id in requested]

    logger.info("Custom: %d stations from %s", len(locations), loc_file.name)

    var_label = record_variable or variable_name
    records: list[PointRecord] = []

    for loc in locations:
        chronicle_path = _find_chronicle_file(data_dir, variable_name, loc.id)
        if chronicle_path is None:
            logger.warning("No chronicle for station %s", loc.id)
            continue

        df = read_timeseries_csv(
            chronicle_path, col_datetime=col_datetime, col_value=col_value,
        )
        if df.empty:
            continue

        # Unit conversion
        if clamp_values is None:
            source_unit = _resolve_station_unit(loc, default_unit=default_unit)
            df["value"] = convert_array(df["value"], source_unit, internal_unit)
        else:
            source_unit = source_unit_override or internal_unit

        # Value clamping
        if clamp_values is not None:
            df["value"] = df["value"].clip(
                lower=clamp_values[0], upper=clamp_values[1],
            ).astype(int)

        # Constant expansion
        is_constant = len(df) == 1
        if is_constant and expand_constants and project_period is not None:
            dates = pd.date_range(
                start=project_period[0], end=project_period[1], freq="D",
            )
            df = pd.DataFrame({"datetime": dates, "value": df.iloc[0]["value"]})

        parsed = parse_chronicle_filename(chronicle_path.name)
        freq = parsed["freq"] if parsed else default_frequency

        records.append(
            PointRecord(
                station_id=loc.id,
                variable=var_label,
                source="custom",
                unit=internal_unit,
                frequency=freq,
                data=df,
                date_start=df["datetime"].min().to_pydatetime(),
                date_end=df["datetime"].max().to_pydatetime(),
                location=loc,
                is_constant=is_constant,
                file_path=chronicle_path,
                source_unit=source_unit,
            )
        )

    logger.info("Custom: loaded %d station records", len(records))
    return records


def load_custom_multiformat(
    path: Path,
    *,
    variable_name: str,
    internal_unit: str,
    project_period: tuple[datetime, datetime] | None = None,
    col_id: str = "id",
    col_x: str = "x",
    col_y: str = "y",
    col_crs: str = "crs",
    default_crs: str = "EPSG:4326",
    col_datetime: str = "datetime",
    col_value: str = "value",
    station_ids: list[str] | None = None,
    default_unit: str | None = None,
    record_variable: str | None = None,
    expand_constants: bool = True,
    source_unit: str | None = None,
) -> list:
    """Load custom data: CSV directory, NetCDF, or GeoTIFF.

    Returns list[PointRecord] for CSV, list[FieldRecord] for .nc/.tif.
    """
    path = Path(path)
    if path.is_dir():
        return load_custom_points(
            data_dir=path,
            variable_name=variable_name,
            internal_unit=internal_unit,
            project_period=project_period,
            col_id=col_id, col_x=col_x, col_y=col_y,
            col_crs=col_crs, default_crs=default_crs,
            col_datetime=col_datetime, col_value=col_value,
            station_ids=station_ids,
            default_unit=default_unit,
            record_variable=record_variable,
            expand_constants=expand_constants,
        )
    elif path.suffix == ".nc":
        from hydromodpy.data.common.custom_grid_loader import load_custom_nc
        return load_custom_nc(
            path, variable=variable_name, unit=internal_unit,
            source_unit=source_unit,
            project_period=project_period,
        )
    elif path.suffix in (".tif", ".tiff"):
        from hydromodpy.data.common.custom_grid_loader import load_custom_tif
        return load_custom_tif(
            path, variable=variable_name, unit=internal_unit,
            source_unit=source_unit,
        )
    else:
        raise ValueError(
            f"Unsupported custom format: {path.suffix}. "
            f"Use a directory (CSV), .nc, or .tif."
        )


# ------------------------------------------------------------------
# Private helpers
# ------------------------------------------------------------------

def _resolve_station_unit(loc, *, default_unit: str | None = None) -> str:
    """Return the source unit from LOC metadata.

    If *default_unit* is None, raises on missing unit.
    Otherwise falls back to *default_unit*.
    """
    unit = loc.metadata.get("unit")
    if unit is not None and str(unit).strip():
        return str(unit).strip()
    if default_unit is not None:
        return default_unit
    raise ValueError(
        f"No unit for station {loc.id!r}. "
        f"Add a 'unit' column in the LOC file."
    )


def _file_prefixes(variable_name: str) -> list[str]:
    """Return possible file prefixes for a variable (canonical + alias)."""
    alias = _VAR_FILE_PREFIX.get(variable_name)
    if alias and alias != variable_name:
        return [variable_name, alias]
    return [variable_name]


def _find_location_file(data_dir: Path, variable_name: str) -> Path:
    for prefix in _file_prefixes(variable_name):
        for ext in ("csv", "shp", "gpkg", "geojson"):
            candidate = data_dir / f"{prefix}_custom_LOC.{ext}"
            if candidate.exists():
                return candidate
    raise FileNotFoundError(f"No {variable_name}_custom_LOC.* in {data_dir}")


def _find_chronicle_file(
    data_dir: Path, variable_name: str, station_id: str,
) -> Path | None:
    safe_id = safe_file_token(station_id)
    for prefix in _file_prefixes(variable_name):
        for pattern in (
            f"{prefix}_custom_{safe_id}_*.csv",
            f"{prefix}_custom_{station_id}_*.csv",
        ):
            matches = sorted(data_dir.glob(pattern))
            if matches:
                return matches[0]
        exact = data_dir / f"{prefix}_custom_{safe_id}.csv"
        if exact.exists():
            return exact
    return None
