"""Convert user-facing CSV files into the internal Parquet pivot format.

Two CSV flavours are supported:

- **Timeseries CSVs** (``chronicles/<STATION_ID>.csv``) with columns
  ``datetime,value``.
- **Locations CSVs** (``example_locations.csv``) with columns
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

from hydromodpy.core.exceptions import DataContractViolation

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


@dataclass(frozen=True, slots=True)
class LocationsArtifact:
    """In-memory representation of a validated locations CSV."""

    stations: list[dict[str, object]]
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

    Returns the destination path. If pyarrow is not available, falls back
    to writing a canonical CSV with the same columns (for environments
    where Parquet is not installed). In both cases the caller sees a
    ``.parquet`` suffix, consistent with internal pivot semantics.
    """
    src = Path(src)
    dest = Path(dest)
    artifact = read_timeseries_csv(src)

    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        import pyarrow as pa  # type: ignore
        import pyarrow.parquet as pq  # type: ignore
    except ModuleNotFoundError:
        _write_timeseries_as_csv(artifact, dest)
        return dest

    table = pa.table(
        {
            "datetime": [r[0] for r in artifact.records],
            "value": [r[1] for r in artifact.records],
            "station_id": [artifact.station_id] * len(artifact.records),
        }
    )
    pq.write_table(table, dest, compression="zstd")
    return dest


def _write_timeseries_as_csv(
    artifact: TimeSeriesArtifact,
    dest: Path,
) -> None:
    """CSV fallback for environments lacking pyarrow/parquet."""
    with dest.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(("datetime", "value", "station_id"))
        for dt, val in artifact.records:
            writer.writerow((dt.isoformat(), "" if val is None else repr(val), artifact.station_id))


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
        # Empty template (only comments + header) is legitimate — no stations yet.
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

    stations: list[dict[str, object]] = []
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
    """Convert a locations CSV into a GeoParquet file.

    When ``geopandas`` is unavailable (e.g. minimal env), writes a
    canonical Parquet-compatible CSV as a fallback with the same columns.
    """
    src = Path(src)
    dest = Path(dest)
    artifact = read_locations_csv(src)
    if artifact.errors:
        raise TimeSeriesValidationError(src, artifact.errors)

    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        import geopandas as gpd  # type: ignore
        from shapely.geometry import Point  # type: ignore
    except ModuleNotFoundError:
        _write_locations_as_csv(artifact, dest)
        return dest

    geoms = [Point(s["x"], s["y"]) for s in artifact.stations]
    gdf = gpd.GeoDataFrame(
        {
            "id": [s["id"] for s in artifact.stations],
            "unit": [s["unit"] for s in artifact.stations],
        },
        geometry=geoms,
        crs=artifact.crs or None,
    )
    gdf.to_parquet(dest)
    return dest


def _write_locations_as_csv(
    artifact: LocationsArtifact,
    dest: Path,
) -> None:
    with dest.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(("id", "x", "y", "crs", "unit"))
        for s in artifact.stations:
            writer.writerow((s["id"], s["x"], s["y"], s["crs"], s["unit"]))


def iter_chronicle_files(custom_dir: Path) -> Iterable[Path]:
    """Yield chronicle CSV paths under ``<custom_dir>/chronicles/``.

    Files named ``EXAMPLE.csv`` or starting with ``_`` are skipped so
    the example template shipped by ``hmp init`` does not get ingested.
    """
    chronicles = Path(custom_dir) / "chronicles"
    if not chronicles.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(chronicles.iterdir()):
        if not p.is_file() or p.suffix.lower() != ".csv":
            continue
        if p.stem == "EXAMPLE" or p.name.startswith("_"):
            continue
        out.append(p)
    return out
