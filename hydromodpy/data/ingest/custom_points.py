"""Generic custom point loader for user-provided CSV files.

Replaces the per-variable custom.py boilerplate. Handles:
- Location file discovery ({variable}_custom_LOC.*)
- Chronicle file discovery ({variable}_custom_{id}_*.csv), or one chronicle the
  config names, read with the location file of its folder. A station with two
  chronicles in a folder is refused, since nothing tells which one to read.
- Unit resolution (strict or fallback)
- Constant expansion over project period
- Optional value clamping (intermittency)
- Optional multi-format dispatch (CSV dir / NetCDF / GeoTIFF)
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import pandas as pd

from hydromodpy.catchment.preprocess.geographic_tree import SHAPEFILE_SIDECARS
from hydromodpy.core.exceptions import DataSourceError
from hydromodpy.core.logging import get_logger
from hydromodpy.data.common.files import (
    parse_chronicle_filename,
    read_locations,
    read_timeseries_csv,
    safe_file_token,
)
from hydromodpy.data.common.units import convert_array
from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.timeseries import PointRecord

logger = get_logger(__name__)

# Map variable names to file prefixes (for naming convention compatibility).
_VAR_FILE_PREFIX = {
    "water_quality": "waterquality",
}

_CHRONICLE_TAIL = re.compile(r"(?:_(?:\d{8}_\d{8}_)?[A-Za-z0-9]+)?\.csv")
"""What may follow the station id in a chronicle name.

Nothing, a frequency (``_D``), or two dates and a frequency
(``_20000101_20021231_M``). ``NANCON_REA_19900101_20201231_D.csv`` is thus no
chronicle of station ``NANCON``.
"""


def load_file_points(
    *,
    path: Path,
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
    """Load point records from a folder of chronicle CSVs, or from one chronicle CSV.

    Parameters
    ----------
    path : Path
        Folder holding the location file and the chronicle CSVs, or one
        chronicle CSV. A chronicle is read with the location file of its
        folder, for the one station the source reads.
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
    source_unit_override : str or None
        Unit of the values for a station whose LOC row has none. A LOC unit
        that differs from it is refused, not chosen between.
    """
    path = Path(path)
    named_file = path.is_file()
    if named_file and path.suffix.lower() != ".csv":
        raise DataSourceError(
            f"{variable_name}: {path.name} is no chronicle. A station source reads a "
            "folder of chronicles or one .csv chronicle."
        )
    if not named_file and not path.is_dir():
        raise FileNotFoundError(f"Custom data path not found: {path}")
    data_dir = path.parent if named_file else path

    loc_file = _find_location_file(data_dir, variable_name)
    locations = read_locations(
        loc_file,
        col_id=col_id,
        col_x=col_x,
        col_y=col_y,
        col_crs=col_crs,
        default_crs=default_crs,
    )
    known_ids = [loc.id for loc in locations]

    if station_ids:
        requested = set(station_ids)
        available = {loc.id for loc in locations}
        missing = sorted(requested - available)
        if missing:
            # A silent drop leaves an empty observed series, and a calibration
            # scored against nothing still reports a number.
            known = sorted(available)
            shown = ", ".join(known[:10]) + (", ..." if len(known) > 10 else "")
            raise DataSourceError(
                f"{variable_name}: station_ids declares {missing}, absent from "
                f"{loc_file.name}. Known ids: {shown or '(none)'}."
            )
        locations = [loc for loc in locations if loc.id in requested]
    if named_file:
        locations = [_station_of_file(path, locations, variable_name)]

    logger.debug("Custom: %d stations from %s", len(locations), loc_file.name)
    location_files = _location_parts(loc_file)

    var_label = record_variable or variable_name
    records: list[PointRecord] = []

    for loc in locations:
        chronicle_path = (
            path if named_file else _find_chronicle_file(data_dir, variable_name, loc.id, known_ids)
        )
        if chronicle_path is None:
            logger.warning("No chronicle for station %s", loc.id)
            continue

        df = read_timeseries_csv(
            chronicle_path,
            col_datetime=col_datetime,
            col_value=col_value,
        )
        if df.empty:
            continue

        # Unit conversion
        if clamp_values is None:
            source_unit = _resolve_station_unit(
                loc, default_unit=source_unit_override or default_unit
            )
            declared = str(loc.metadata.get("unit") or "").strip()
            if source_unit_override and declared and declared != source_unit_override:
                raise ValueError(
                    f"Station {loc.id!r} has unit {declared!r} in its LOC file and "
                    f"source_unit = {source_unit_override!r} in the config. Drop one of "
                    "them, or make them agree."
                )
            df["value"] = convert_array(df["value"], source_unit, internal_unit)
        else:
            source_unit = source_unit_override or internal_unit

        # Value clamping
        if clamp_values is not None:
            df["value"] = (
                df["value"]
                .clip(
                    lower=clamp_values[0],
                    upper=clamp_values[1],
                )
                .astype(int)
            )

        # Constant expansion
        is_constant = len(df) == 1
        if is_constant and expand_constants and project_period is not None:
            dates = pd.date_range(
                start=project_period[0],
                end=project_period[1],
                freq="D",
            )
            df = pd.DataFrame({"datetime": dates, "value": df.iloc[0]["value"]})

        parsed = parse_chronicle_filename(chronicle_path.name)
        freq = parsed["freq"] if parsed else default_frequency

        records.append(
            PointRecord(
                station_id=loc.id,
                variable=var_label,
                source="file",
                unit=internal_unit,
                frequency=freq,
                data=df,
                date_start=df["datetime"].min().to_pydatetime(),
                date_end=df["datetime"].max().to_pydatetime(),
                location=loc,
                is_constant=is_constant,
                file_path=chronicle_path,
                source_unit=source_unit,
                location_files=location_files,
            )
        )

    logger.debug("Custom: loaded %d station records", len(records))
    return records


def load_file_multiformat(
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
    grid_crs: str | None = None,
    grid_nodata: float | int | str | None = None,
) -> list:
    """Load custom data: CSV directory, NetCDF, or GeoTIFF.

    Returns list[PointRecord] for CSV, list[FieldRecord] for .nc/.tif.
    """
    path = Path(path)
    if path.is_dir() or path.suffix.lower() == ".csv":
        return load_file_points(
            path=path,
            variable_name=variable_name,
            internal_unit=internal_unit,
            project_period=project_period,
            col_id=col_id,
            col_x=col_x,
            col_y=col_y,
            col_crs=col_crs,
            default_crs=default_crs,
            col_datetime=col_datetime,
            col_value=col_value,
            station_ids=station_ids,
            default_unit=default_unit,
            record_variable=record_variable,
            expand_constants=expand_constants,
        )
    elif path.suffix == ".nc":
        from hydromodpy.data.ingest.custom_grids import load_custom_nc

        return load_custom_nc(
            path,
            variable=variable_name,
            unit=internal_unit,
            source_unit=source_unit,
            crs=grid_crs,
            nodata=grid_nodata,
            project_period=project_period,
        )
    elif path.suffix in (".tif", ".tiff"):
        from hydromodpy.data.ingest.custom_grids import load_custom_tif

        return load_custom_tif(
            path,
            variable=variable_name,
            unit=internal_unit,
            source_unit=source_unit,
        )
    else:
        raise ValueError(
            f"Unsupported custom format: {path.suffix}. Use a folder of chronicles, one "
            ".csv chronicle, a .nc or a .tif."
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
        logger.warning(
            "Station %s has no unit in its LOC file; its values are taken as %s and "
            "not converted. Add a 'unit' column to say otherwise.",
            loc.id,
            default_unit,
        )
        return default_unit
    raise ValueError(f"No unit for station {loc.id!r}. Add a 'unit' column in the LOC file.")


def _file_prefixes(variable_name: str) -> list[str]:
    """Return possible file prefixes for a variable (canonical + alias)."""
    alias = _VAR_FILE_PREFIX.get(variable_name)
    if alias and alias != variable_name:
        return [variable_name, alias]
    return [variable_name]


def _location_parts(loc_file: Path) -> tuple[Path, ...]:
    """Return the files a location file is read from: a shapefile brings its parts."""
    if loc_file.suffix != ".shp":
        return (loc_file,)
    parts = (loc_file.with_suffix(ext) for ext in SHAPEFILE_SIDECARS)
    return tuple(path for path in parts if path.is_file())


def _find_location_file(data_dir: Path, variable_name: str) -> Path:
    for prefix in _file_prefixes(variable_name):
        for kind in ("file", "custom"):
            for ext in ("csv", "shp", "gpkg", "geojson"):
                candidate = data_dir / f"{prefix}_{kind}_LOC.{ext}"
                if candidate.exists():
                    return candidate
    raise FileNotFoundError(
        f"No {variable_name}_file_LOC.* (or {variable_name}_custom_LOC.*) in {data_dir}"
    )


def location_files_beside(chronicle: Path, variable_name: str) -> tuple[Path, ...]:
    """Return the location file a named chronicle is read with, and its parts.

    Empty for a path that is no .csv file, or whose folder holds no location
    file of the variable.
    """
    chronicle = Path(chronicle)
    if not chronicle.is_file() or chronicle.suffix.lower() != ".csv":
        return ()
    try:
        loc_file = _find_location_file(chronicle.parent, variable_name)
    except FileNotFoundError:
        return ()
    return _location_parts(loc_file)


def _station_of_file(
    chronicle: Path, locations: list[StationLocation], variable_name: str
) -> StationLocation:
    """Return the one station a named chronicle belongs to."""
    if len(locations) != 1:
        ids = ", ".join(loc.id for loc in locations[:10]) or "none"
        raise DataSourceError(
            f"{variable_name}: {chronicle.name} is the chronicle of one station, and the "
            f"source reads {len(locations)} ({ids}). Name its station in station_ids, or "
            "in [site] gauge."
        )
    (loc,) = locations
    parsed = parse_chronicle_filename(chronicle.name)
    if parsed is not None and parsed["id"] not in {loc.id, safe_file_token(loc.id)}:
        raise DataSourceError(
            f"{variable_name}: {chronicle.name} is named for station {parsed['id']}, and "
            f"the source reads station {loc.id}. Point the path at the chronicle of "
            f"{loc.id}, or set station_ids to {parsed['id']}."
        )
    return loc


def _chronicle_heads(variable_name: str, station_id: str) -> list[str]:
    """Return the name starts a chronicle of the station may have."""
    tokens = dict.fromkeys((safe_file_token(station_id), station_id))
    return [
        f"{prefix}_{kind}_{token}"
        for prefix in _file_prefixes(variable_name)
        for kind in ("file", "custom")
        for token in tokens
    ]


def _is_chronicle_of(name: str, heads: Sequence[str]) -> bool:
    return any(
        name.startswith(head) and _CHRONICLE_TAIL.fullmatch(name[len(head) :]) is not None
        for head in heads
    )


def _find_chronicle_file(
    data_dir: Path,
    variable_name: str,
    station_id: str,
    known_ids: Sequence[str] = (),
) -> Path | None:
    """Return the one chronicle of a station in a folder, None when it has none.

    A file that also reads as the chronicle of a longer id of *known_ids*
    (``NANCON_REA`` beside ``NANCON``) belongs to that station. Two chronicles
    for one station are refused rather than picked by name order.
    """
    heads = _chronicle_heads(variable_name, station_id)
    longer = [
        _chronicle_heads(variable_name, other)
        for other in known_ids
        if other != station_id
        and safe_file_token(other).startswith(f"{safe_file_token(station_id)}_")
    ]
    found = sorted(
        candidate
        for candidate in data_dir.glob("*.csv")
        if _is_chronicle_of(candidate.name, heads)
        and not any(_is_chronicle_of(candidate.name, other) for other in longer)
    )
    if len(found) > 1:
        names = ", ".join(candidate.name for candidate in found)
        raise DataSourceError(
            f"{variable_name}: station {station_id} has {len(found)} chronicles in "
            f"{data_dir}: {names}. Nothing tells which one to read. Point the path of "
            f'the source at the one to read, as path = "workspace:{found[0].name}" in '
            "a workspace."
        )
    return found[0] if found else None
