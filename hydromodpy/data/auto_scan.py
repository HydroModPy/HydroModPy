"""Auto-scan the drag-and-drop ``<variable>_custom/`` folders.

Called at the start of every ``hmp run`` and from ``hmp data check`` /
``hmp data list``. Detects new or modified user files (mtime > last
indexed timestamp), validates them via the adapters, normalises to the
internal pivot format, and registers the result in ``data/cache.duckdb``
with ``provider="custom"``.

The module is idempotent: re-scanning an unchanged workspace is a no-op.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from hydromodpy.core.tools.log_manager import get_logger
from hydromodpy.data.adapters import (
    TimeSeriesValidationError,
    convert_asc_to_geotiff,
    convert_timeseries_csv_to_parquet,
    convert_vector_to_geoparquet,
    read_locations_csv,
)
from hydromodpy.data.adapters.csv_to_parquet import iter_chronicle_files
from hydromodpy.data.scaffold import VARIABLES, VariableSpec

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Artifact:
    """Outcome of scanning one source file."""

    variable: str
    provider: str
    station_id: Optional[str]
    source_path: Path
    pivot_path: Path
    format: str
    size_bytes: int
    indexed_at: datetime


@dataclass(frozen=True, slots=True)
class ScanReport:
    """Aggregate result of a scan across the workspace."""

    added: list[Artifact] = field(default_factory=list)
    updated: list[Artifact] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    errors: list[tuple[Path, str]] = field(default_factory=list)

    @property
    def n_changed(self) -> int:
        return len(self.added) + len(self.updated)

    def format_summary(self) -> str:
        lines = [
            f"Added   : {len(self.added):3d}",
            f"Updated : {len(self.updated):3d}",
            f"Skipped : {len(self.skipped):3d}",
            f"Errors  : {len(self.errors):3d}",
        ]
        for path, msg in self.errors:
            lines.append(f"  ! {path}: {msg}")
        return "\n".join(lines)


def _workspace_blobs_dir(workspace: Path) -> Path:
    blobs = Path(workspace) / "data" / "blobs"
    blobs.mkdir(parents=True, exist_ok=True)
    return blobs


def _last_indexed_mtime(catalog, variable: str, source_path: Path) -> float | None:
    """Return the stored ``file_mtime`` for a given source path, or None."""
    conn = getattr(catalog, "_conn", None)
    if conn is None:
        return None
    row = conn.execute(
        "SELECT file_mtime FROM entries WHERE variable = ? AND source = 'custom' "
        "AND file_path = ?",
        [variable, str(source_path)],
    ).fetchone()
    if row is None:
        return None
    return row[0]


def _is_fresh(source_path: Path, stored_mtime: float | None) -> bool:
    """True when the source has not changed since the last index."""
    if stored_mtime is None:
        return False
    try:
        current = source_path.stat().st_mtime
    except OSError:
        return False
    return abs(current - stored_mtime) < 1e-6


def _custom_dir(workspace: Path, spec: VariableSpec) -> Path:
    return Path(workspace) / f"{spec.name}_custom"


def _scan_timeseries_variable(
    workspace: Path,
    spec: VariableSpec,
    catalog,
    report: ScanReport,
    *,
    blobs_dir: Path,
    now: datetime,
) -> None:
    custom_dir = _custom_dir(workspace, spec)
    if not custom_dir.is_dir():
        return

    loc_csv = custom_dir / "example_locations.csv"
    locations_by_id: dict[str, dict] = {}
    if loc_csv.exists():
        loc_artifact = read_locations_csv(loc_csv)
        if loc_artifact.errors:
            for err in loc_artifact.errors:
                report.errors.append((loc_csv, err))
        for station in loc_artifact.stations:
            locations_by_id[str(station["id"])] = station

    for src in iter_chronicle_files(custom_dir):
        stored_mtime = _last_indexed_mtime(catalog, spec.name, src)
        if _is_fresh(src, stored_mtime):
            report.skipped.append(src)
            continue

        try:
            dest = (
                blobs_dir / spec.name / "custom" / f"{src.stem}.parquet"
            )
            convert_timeseries_csv_to_parquet(src, dest)
        except TimeSeriesValidationError as exc:
            report.errors.append((src, str(exc)))
            continue
        except Exception as exc:  # pragma: no cover - defensive
            report.errors.append((src, f"{type(exc).__name__}: {exc}"))
            continue

        station_id = src.stem
        station = locations_by_id.get(station_id, {})
        crs = str(station.get("crs") or "")
        unit = str(station.get("unit") or spec.unit)
        bbox = None
        if "x" in station and "y" in station:
            x, y = float(station["x"]), float(station["y"])
            bbox = (x, y, x, y)

        entry_id = catalog.register(
            variable=spec.name,
            source="custom",
            station_id=station_id,
            file_path=str(src),
            bbox=bbox,
            crs=crs or None,
            unit=unit,
            is_custom=True,
            fetch_metadata={
                "pivot_path": str(dest),
                "pivot_format": spec.pivot,
                "indexed_at": now.isoformat(),
                "source_file_stem": src.stem,
            },
        )
        artifact = Artifact(
            variable=spec.name,
            provider="custom",
            station_id=station_id,
            source_path=src,
            pivot_path=dest,
            format=spec.pivot,
            size_bytes=dest.stat().st_size if dest.exists() else 0,
            indexed_at=now,
        )
        if stored_mtime is None or entry_id == -1:
            report.added.append(artifact)
        else:
            report.updated.append(artifact)


def _iter_files(custom_dir: Path, suffixes: frozenset[str]) -> list[Path]:
    if not custom_dir.is_dir():
        return []
    out = []
    for p in sorted(custom_dir.iterdir()):
        if not p.is_file():
            continue
        if p.suffix.lower() not in suffixes:
            continue
        if p.name.startswith("_") or p.stem == "EXAMPLE":
            continue
        out.append(p)
    return out


_RASTER_SUFFIXES = frozenset({".asc", ".tif", ".tiff"})
_VECTOR_SUFFIXES = frozenset({".shp", ".geojson", ".json", ".gpkg", ".parquet"})


def _scan_raster_variable(
    workspace: Path,
    spec: VariableSpec,
    catalog,
    report: ScanReport,
    *,
    blobs_dir: Path,
    now: datetime,
) -> None:
    custom_dir = _custom_dir(workspace, spec)
    for src in _iter_files(custom_dir, _RASTER_SUFFIXES):
        stored_mtime = _last_indexed_mtime(catalog, spec.name, src)
        if _is_fresh(src, stored_mtime):
            report.skipped.append(src)
            continue

        dest = blobs_dir / spec.name / "custom" / f"{src.stem}.tif"
        try:
            convert_asc_to_geotiff(src, dest)
        except Exception as exc:
            report.errors.append((src, f"{type(exc).__name__}: {exc}"))
            continue

        entry_id = catalog.register(
            variable=spec.name,
            source="custom",
            file_path=str(src),
            unit=spec.unit,
            is_custom=True,
            fetch_metadata={
                "pivot_path": str(dest),
                "pivot_format": spec.pivot,
                "indexed_at": now.isoformat(),
            },
        )
        artifact = Artifact(
            variable=spec.name, provider="custom", station_id=None,
            source_path=src, pivot_path=dest, format=spec.pivot,
            size_bytes=dest.stat().st_size if dest.exists() else 0,
            indexed_at=now,
        )
        if stored_mtime is None or entry_id == -1:
            report.added.append(artifact)
        else:
            report.updated.append(artifact)


def _scan_vector_variable(
    workspace: Path,
    spec: VariableSpec,
    catalog,
    report: ScanReport,
    *,
    blobs_dir: Path,
    now: datetime,
) -> None:
    custom_dir = _custom_dir(workspace, spec)
    for src in _iter_files(custom_dir, _VECTOR_SUFFIXES):
        stored_mtime = _last_indexed_mtime(catalog, spec.name, src)
        if _is_fresh(src, stored_mtime):
            report.skipped.append(src)
            continue

        dest = blobs_dir / spec.name / "custom" / f"{src.stem}.parquet"
        try:
            convert_vector_to_geoparquet(src, dest)
        except Exception as exc:
            report.errors.append((src, f"{type(exc).__name__}: {exc}"))
            continue

        entry_id = catalog.register(
            variable=spec.name,
            source="custom",
            file_path=str(src),
            unit=spec.unit,
            is_custom=True,
            fetch_metadata={
                "pivot_path": str(dest),
                "pivot_format": spec.pivot,
                "indexed_at": now.isoformat(),
            },
        )
        artifact = Artifact(
            variable=spec.name, provider="custom", station_id=None,
            source_path=src, pivot_path=dest, format=spec.pivot,
            size_bytes=dest.stat().st_size if dest.exists() else 0,
            indexed_at=now,
        )
        if stored_mtime is None or entry_id == -1:
            report.added.append(artifact)
        else:
            report.updated.append(artifact)


_SCANNERS = {
    "timeseries": _scan_timeseries_variable,
    "raster": _scan_raster_variable,
    "vector": _scan_vector_variable,
}


def _open_catalog(workspace: Path):
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

    db_path = Path(workspace) / "data" / "cache.duckdb"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return DataCatalogDuckDB(db_path)


def scan_custom(
    workspace_path: str | Path,
    *,
    catalog=None,
    now: datetime | None = None,
) -> ScanReport:
    """Scan all ``<variable>_custom/`` folders in ``workspace_path``.

    Returns a :class:`ScanReport` listing what was added, updated,
    skipped, or errored. If ``catalog`` is omitted, the function opens
    ``<workspace>/data/cache.duckdb`` and closes it after scanning.
    """
    workspace = Path(workspace_path).expanduser().resolve()
    if not workspace.is_dir():
        raise FileNotFoundError(f"Workspace not found: {workspace}")

    owned = catalog is None
    if owned:
        catalog = _open_catalog(workspace)

    report = ScanReport()
    blobs_dir = _workspace_blobs_dir(workspace)
    stamp = now or datetime.now(tz=timezone.utc)

    try:
        for spec in VARIABLES:
            scanner = _SCANNERS.get(spec.kind)
            if scanner is None:
                continue
            scanner(
                workspace, spec, catalog, report,
                blobs_dir=blobs_dir, now=stamp,
            )
    finally:
        if owned:
            catalog.close()

    if report.n_changed:
        logger.info(
            "auto_scan: %d added, %d updated, %d skipped, %d errors",
            len(report.added), len(report.updated),
            len(report.skipped), len(report.errors),
        )
    return report


def check_custom(
    workspace_path: str | Path, *, variable: str | None = None,
) -> list[tuple[Path, str]]:
    """Dry-run validation of the drag-and-drop folders.

    Returns a list of ``(path, message)`` issues without writing to the
    cache. When ``variable`` is given, only that subfolder is checked.
    """
    workspace = Path(workspace_path).expanduser().resolve()
    issues: list[tuple[Path, str]] = []

    for spec in VARIABLES:
        if variable and spec.name != variable:
            continue
        custom_dir = _custom_dir(workspace, spec)
        if not custom_dir.is_dir():
            continue

        if spec.kind == "timeseries":
            loc = custom_dir / "example_locations.csv"
            if loc.exists():
                artefact = read_locations_csv(loc)
                for err in artefact.errors:
                    issues.append((loc, err))
            for src in iter_chronicle_files(custom_dir):
                try:
                    convert_timeseries_csv_to_parquet(src, custom_dir / "_check.tmp")
                except TimeSeriesValidationError as exc:
                    for err in exc.errors:
                        issues.append((src, err))
                finally:
                    tmp = custom_dir / "_check.tmp"
                    if tmp.exists():
                        tmp.unlink(missing_ok=True)
        elif spec.kind in ("raster", "vector"):
            suffixes = _RASTER_SUFFIXES if spec.kind == "raster" else _VECTOR_SUFFIXES
            for src in _iter_files(custom_dir, suffixes):
                if not src.exists():
                    issues.append((src, "file disappeared during check"))
    return issues
