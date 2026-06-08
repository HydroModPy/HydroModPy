"""Convert user-facing CSV files into the internal Parquet pivot format.

Two CSV flavours are supported:

- **Timeseries CSVs** (``<variable>_custom_<id>_<start>_<end>_<freq>.csv``)
  with columns ``datetime,value``.
- **Locations CSVs** (``<variable>_custom_LOC.csv``) with columns
  ``id,x,y,crs,unit``.

Validation is strict but emits all errors at once via
:class:`TimeSeriesValidationError` rather than stopping at the first one.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TypedDict

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.data.schemas import (
    StationCollectionSchema,
    TimeSeriesSchema,
    validate_abacus,
    validate_warn_only,
)

_WGS84_CRS_TOKENS = frozenset({"EPSG:4326", "epsg:4326", "WGS84", "WGS 84"})

TIMESERIES_COLUMNS = ("datetime", "value")
LOCATIONS_COLUMNS = ("id", "x", "y", "crs", "unit")

_ID_RE = re.compile(r"^[A-Za-z0-9_\-.]{1,64}$")


class TimeSeriesValidationError(DataContractViolation):
    """Raised when a CSV file fails validation.

    The ``errors`` attribute exposes the full list of issues; the
    exception message contains a concise human-readable summary.
    """

    def __init__(self, path: Path, errors: list[str]):
        self.path = path
        self.errors = errors
        joined = "\n  - ".join(errors)
        super().__init__(f"Validation failed for {path} ({len(errors)} issue(s)):\n  - {joined}")


@dataclass(frozen=True, slots=True)
class TimeSeriesArtifact:
    """In-memory representation of a validated timeseries CSV."""

    station_id: str
    records: list[tuple[datetime, float | None]]
    source_path: Path


class Station(TypedDict):
    """One row of a locations CSV after parsing (``x``/``y`` are numeric)."""

    id: str
    x: float
    y: float
    crs: str
    unit: str


@dataclass(frozen=True, slots=True)
class LocationsArtifact:
    """In-memory representation of a validated locations CSV."""

    stations: list[Station]
    crs: str
    unit: str
    source_path: Path
    errors: list[str] = field(default_factory=list)


def _read_rows(path: Path) -> list[dict[str, str]]:
    """Read a CSV skipping lines that start with ``#``."""
    with path.open("r", encoding="utf-8", newline="") as fh:
        cleaned = [line for line in fh if not line.lstrip().startswith("#")]
    reader = csv.DictReader(cleaned)
    return [{(k or ""): (v or "") for k, v in row.items()} for row in reader]


def _parse_datetime(value: str) -> datetime:
    value = value.strip()
    if not value:
        raise ValueError("empty datetime")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        raise ValueError(f"unparseable datetime: {value!r}") from None


def read_timeseries_csv(path: Path) -> TimeSeriesArtifact:
    """Read and validate a timeseries CSV. Raises on schema violations."""
    path = Path(path)
    rows = _read_rows(path)
    errors: list[str] = []

    if not rows:
        raise TimeSeriesValidationError(path, ["file is empty"])

    missing = [c for c in TIMESERIES_COLUMNS if c not in rows[0]]
    if missing:
        raise TimeSeriesValidationError(path, [f"missing columns: {missing!r}"])

    records: list[tuple[datetime, float | None]] = []
    for i, row in enumerate(rows, start=1):
        try:
            dt = _parse_datetime(row["datetime"])
        except ValueError as exc:
            errors.append(f"row {i}: {exc}")
            continue

        raw = row["value"].strip()
        if raw == "" or raw.lower() in ("nan", "null", "na"):
            val: float | None = None
        else:
            try:
                val = float(raw)
            except ValueError:
                errors.append(f"row {i}: non-numeric value {raw!r}")
                continue
        records.append((dt, val))

    if errors:
        raise TimeSeriesValidationError(path, errors)

    station_id = infer_station_id_from_filename(path)
    return TimeSeriesArtifact(
        station_id=station_id,
        records=records,
        source_path=path,
    )


def infer_station_id_from_filename(path: Path) -> str:
    """Derive a station identifier from a chronicle filename.

    ``P01.csv`` -> ``P01``. Raises if the stem is not a valid id.
    """
    stem = Path(path).stem
    if not _ID_RE.match(stem):
        raise TimeSeriesValidationError(
            Path(path),
            [f"filename stem {stem!r} is not a valid station id (1-64 alphanumerics)"],
        )
    return stem


def convert_timeseries_csv_to_parquet(
    src: str | Path,
    dest: str | Path,
) -> Path:
    """Convert a validated timeseries CSV into a Parquet file.

    The output respects the v2 Parquet write defaults (ZSTD-5, page index,
    row-group 50k) without crossing the layer boundary into ``results``.
    """
    import os
    import uuid as _uuid

    src = Path(src)
    dest = Path(dest)
    artifact = read_timeseries_csv(src)

    dest.parent.mkdir(parents=True, exist_ok=True)

    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq

    frame = pd.DataFrame(
        {
            "datetime": [record[0] for record in artifact.records],
            "value": [record[1] for record in artifact.records],
            "station_id": [artifact.station_id] * len(artifact.records),
        },
    )
    validation_view = frame[["datetime", "value"]].rename(columns={"datetime": "date"})
    validate_warn_only(
        validation_view,
        TimeSeriesSchema,
        schema_name=f"TimeSeriesSchema[{src.name}]",
    )
    schema = pa.schema(
        [
            pa.field("datetime", pa.timestamp("ms")),
            pa.field("value", pa.float64()),
            pa.field("station_id", pa.string()),
        ]
    )
    table = pa.Table.from_pandas(frame, schema=schema, preserve_index=False)
    tmp = dest.with_name(f"{dest.name}.tmp-{_uuid.uuid4().hex}")
    try:
        pq.write_table(
            table,
            tmp,
            compression="zstd",
            compression_level=5,
            row_group_size=50_000,
            use_dictionary=True,
            write_statistics=True,
            write_page_index=True,
            version="2.6",
        )
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise
    os.replace(tmp, dest)
    return dest


def convert_abacus_csv_to_parquet(
    src: str | Path,
    dest: str | Path,
    *,
    lake_id: str | None = None,
) -> Path:
    """Convert a lake stage-volume-area abacus CSV into a Parquet file.

    The CSV carries the abacus columns ``stage,volume,sarea`` and, optionally,
    a ``lake_id`` column. When ``lake_id`` is absent from the CSV it is
    injected from the ``lake_id`` argument (or the file stem as a last resort)
    so a single-lake CSV needs no boilerplate column. The table is validated
    against :data:`AbacusTableSchema` before being written with the same v2
    Parquet defaults as :func:`convert_timeseries_csv_to_parquet`.
    """
    import os
    import uuid as _uuid

    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq

    src = Path(src)
    dest = Path(dest)

    frame = pd.read_csv(src, comment="#")
    if "lake_id" not in frame.columns:
        frame.insert(0, "lake_id", lake_id if lake_id is not None else src.stem)
    frame["lake_id"] = frame["lake_id"].astype(str)

    validated = validate_abacus(frame, context=src.name)

    dest.parent.mkdir(parents=True, exist_ok=True)
    schema = pa.schema(
        [
            pa.field("lake_id", pa.string()),
            pa.field("stage", pa.float64()),
            pa.field("volume", pa.float64()),
            pa.field("sarea", pa.float64()),
        ]
    )
    table = pa.Table.from_pandas(
        validated[["lake_id", "stage", "volume", "sarea"]],
        schema=schema,
        preserve_index=False,
    )
    tmp = dest.with_name(f"{dest.name}.tmp-{_uuid.uuid4().hex}")
    try:
        pq.write_table(
            table,
            tmp,
            compression="zstd",
            compression_level=5,
            row_group_size=50_000,
            use_dictionary=True,
            write_statistics=True,
            write_page_index=True,
            version="2.6",
        )
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise
    os.replace(tmp, dest)
    return dest


def read_locations_csv(path: str | Path) -> LocationsArtifact:
    """Read and validate a locations CSV.

    Unlike :func:`read_timeseries_csv`, this function returns a *partial*
    artefact when validation fails, so callers (e.g. ``hmp data check``)
    can display every problem at once.
    """
    path = Path(path)
    rows = _read_rows(path)
    errors: list[str] = []

    if not rows:
        # Empty template (only comments + header) is legitimate - no stations yet.
        return LocationsArtifact(
            stations=[],
            crs="",
            unit="",
            source_path=path,
            errors=[],
        )

    missing = [c for c in LOCATIONS_COLUMNS if c not in rows[0]]
    if missing:
        return LocationsArtifact(
            stations=[],
            crs="",
            unit="",
            source_path=path,
            errors=[f"missing columns: {missing!r}"],
        )

    stations: list[Station] = []
    seen_ids: set[str] = set()
    crs_values: set[str] = set()
    unit_values: set[str] = set()

    for i, row in enumerate(rows, start=1):
        sid = row["id"].strip()
        if not sid:
            errors.append(f"row {i}: empty id")
            continue
        if not _ID_RE.match(sid):
            errors.append(f"row {i}: invalid id {sid!r}")
            continue
        if sid in seen_ids:
            errors.append(f"row {i}: duplicate id {sid!r}")
            continue
        seen_ids.add(sid)

        try:
            x = float(row["x"])
            y = float(row["y"])
        except ValueError:
            errors.append(f"row {i}: non-numeric x/y")
            continue

        crs = row["crs"].strip()
        unit = row["unit"].strip()
        if not crs:
            errors.append(f"row {i}: missing crs")
            continue
        crs_values.add(crs)
        unit_values.add(unit)

        stations.append({"id": sid, "x": x, "y": y, "crs": crs, "unit": unit})

    crs = crs_values.pop() if len(crs_values) == 1 else ""
    unit = unit_values.pop() if len(unit_values) == 1 else ""
    return LocationsArtifact(
        stations=stations,
        crs=crs,
        unit=unit,
        source_path=path,
        errors=errors,
    )


def convert_locations_csv_to_geoparquet(
    src: str | Path,
    dest: str | Path,
) -> Path:
    """Convert a locations CSV into an OGC GeoParquet 1.1 vector table.

    Uses :meth:`geopandas.GeoDataFrame.to_parquet` with the v2 contract
    (``schema_version=1.1.0``, WKB encoding, covering bbox) inline.
    """
    import os
    import uuid as _uuid

    src = Path(src)
    dest = Path(dest)
    artifact = read_locations_csv(src)
    if artifact.errors:
        raise TimeSeriesValidationError(src, artifact.errors)

    dest.parent.mkdir(parents=True, exist_ok=True)

    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import Point

    geoms = [Point(s["x"], s["y"]) for s in artifact.stations]
    gdf = gpd.GeoDataFrame(
        {
            "id": [s["id"] for s in artifact.stations],
            "unit": [s["unit"] for s in artifact.stations],
        },
        geometry=geoms,
        crs=artifact.crs,
    )

    if artifact.crs in _WGS84_CRS_TOKENS and artifact.stations:
        stations_view = pd.DataFrame(
            {
                "station_id": [str(s["id"]) for s in artifact.stations],
                "lat": [float(s["y"]) for s in artifact.stations],
                "lon": [float(s["x"]) for s in artifact.stations],
            }
        )
        validate_warn_only(
            stations_view,
            StationCollectionSchema,
            schema_name=f"StationCollectionSchema[{src.name}]",
        )
    tmp = dest.with_name(f"{dest.name}.tmp-{_uuid.uuid4().hex}")
    try:
        gdf.to_parquet(
            tmp,
            compression="zstd",
            compression_level=5,
            schema_version="1.1.0",
            geometry_encoding="WKB",
            write_covering_bbox=True,
            index=False,
        )
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise
    os.replace(tmp, dest)
    return dest


def iter_chronicle_files(data_dir: Path, prefix: str) -> Iterable[Path]:
    """Yield custom chronicle CSV paths in ``data_dir`` (flat).

    Matches ``<prefix>_custom_*.csv`` directly in the variable folder,
    excluding the ``_LOC`` location file, EXAMPLE templates shipped by
    ``hmp workspace init``, and files starting with ``_``.
    """
    from hydromodpy.data.common.io_helpers import is_scaffold_example

    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        return []
    loc_name = f"{prefix}_custom_LOC.csv"
    out: list[Path] = []
    for p in sorted(data_dir.glob(f"{prefix}_custom_*.csv")):
        if not p.is_file() or p.name.startswith("_"):
            continue
        if p.name == loc_name or is_scaffold_example(p):
            continue
        out.append(p)
    return out
