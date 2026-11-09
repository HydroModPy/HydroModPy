"""Abstract base class for station/point variable managers."""

from __future__ import annotations

import json
import warnings
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, ClassVar

import pandas as pd

from hydromodpy.core.exceptions import MissingForcingError
from hydromodpy.core.logging import get_logger
from hydromodpy.data.common.io_helpers import safe_file_token
from hydromodpy.data.common.source_extent import STATION_EXTENT_CRS
from hydromodpy.data.contracts.completeness import compute_completeness
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.managers.base_manager_common import BaseManagerCommon, point_records_of
from hydromodpy.data.provenance.sidecars import (
    load_sidecar,
    sidecar_path_for,
    unlink_with_sidecar,
)
from hydromodpy.data.registry.cache_queries import PRODUCT_VERSION_KEY
from hydromodpy.data.registry.cache_store import reject_frozen_download
from hydromodpy.data.registry.constants import (
    SENTINEL_CUSTOM,
    SENTINEL_EMPTY,
)
from hydromodpy.data.source.port import Extent, FetchRequest, Period

logger = get_logger(__name__)


# Map VARIABLE_NAME to file prefix used in naming convention.
_VAR_FILE_PREFIX = {
    "hydrometry": "hydrometry",
    "intermittency": "intermittency",
    "piezometry": "piezometry",
    "water_quality": "waterquality",
}


_ASKED_WINDOW_KEY = "asked_window"
"""``fetch_metadata`` key of the period a station chronicle was asked for."""


def _fetch_metadata_of(
    window: tuple[datetime, datetime] | None, product: str | None
) -> dict | None:
    """The ``fetch_metadata`` of a station entry: its asked window and its product.

    The two fields are written only when known, so an entry of a section that
    carries no product keeps the bytes it always had, and a product answers
    nothing for a request made under another one.
    """
    metadata: dict[str, object] = {}
    if window is not None:
        metadata[_ASKED_WINDOW_KEY] = [window[0].isoformat(), window[1].isoformat()]
    if product is not None:
        metadata[PRODUCT_VERSION_KEY] = product
    return metadata or None


def _hull(
    first: tuple[datetime, datetime], second: tuple[datetime, datetime] | None
) -> tuple[datetime, datetime]:
    """Return the smallest period holding ``first`` and ``second``."""
    if second is None:
        return first
    return (min(first[0], second[0]), max(first[1], second[1]))


def _chronicle_sidecar(path: Path) -> dict[str, str | None]:
    """The chronicle fields of the sidecar next to ``path``; empty when there is none."""
    if not sidecar_path_for(path).is_file():
        return {}
    try:
        sidecar = load_sidecar(path)
    except (OSError, ValueError) as exc:
        logger.debug("Unreadable sidecar next to %s: %s", path, exc)
        return {}
    return {
        "unit": sidecar.unit,
        "source_unit": sidecar.source_unit,
        "frequency": sidecar.frequency,
    }


class BaseVariableManager(BaseManagerCommon):
    """Base orchestrator inherited by each station-based variable manager.

    Subclasses set ``VARIABLE_NAME`` and ``INTERNAL_UNIT``; the source a section
    names is a class of the data-source port, and this family translates its
    call into one :class:`~hydromodpy.data.source.port.FetchRequest`: the
    stations when the list is not empty, else the extent as a WGS84 box, with
    the window the station cache asks for. The station cache alone decides
    which stations and which periods the source is asked for, and the request
    is rebuilt for each of its calls.
    """

    RECORD_VARIABLE: ClassVar[str | None] = None
    """The name of each record a custom file yields; the variable name when unset."""

    def load(self) -> LoadResult:
        """Load data from all configured sources.

        Returns a LoadResult (points only for station-based variables).
        """
        results: list[PointRecord] = []
        for source_cfg in self.config.sources:
            records = self._fetch_from_source(source_cfg)
            if isinstance(records, list):
                results.extend(records)
            else:
                results.append(records)
        self._warn_stations_outside_extent(results)
        self._register_records(results)
        return LoadResult(points=results)

    def _warn_stations_outside_extent(self, records: list[PointRecord]) -> None:
        """Warn if any loaded station falls outside project_extent, read in WGS84."""
        if self.project_extent is None:
            return
        from shapely.geometry import box

        from hydromodpy.data.common.geo_helpers import filter_locations_by_geometry
        from hydromodpy.data.common.source_extent import STATION_EXTENT_CRS

        located = [r.location for r in records if r.location is not None]
        inside = filter_locations_by_geometry(
            located, box(*self.project_extent), geometry_crs=STATION_EXTENT_CRS
        )
        inside_ids = {location.id for location in inside}
        outside = [
            r.station_id
            for r in records
            if r.location is not None and r.location.id not in inside_ids
        ]
        if outside:
            warnings.warn(
                f"{self.VARIABLE_NAME}: {len(outside)} station(s) outside "
                f"project_extent {self.project_extent}: {outside}",
                stacklevel=2,
            )

    def load_file(self, source_cfg: Any) -> list[PointRecord]:
        """Load a folder of station chronicles and their locations."""
        from hydromodpy.data.ingest.custom_points import load_file_points

        records = load_file_points(
            data_dir=Path(source_cfg.path),
            variable_name=self.VARIABLE_NAME,
            internal_unit=self.INTERNAL_UNIT,
            project_period=self.project_period,
            col_id=source_cfg.col_id,
            col_x=source_cfg.col_x,
            col_y=source_cfg.col_y,
            col_crs=source_cfg.col_crs,
            default_crs=source_cfg.default_crs,
            col_datetime=source_cfg.col_datetime,
            col_value=source_cfg.col_value,
            station_ids=source_cfg.station_ids,
            default_unit=None,
            record_variable=self.RECORD_VARIABLE or self.VARIABLE_NAME,
            source_unit_override=source_cfg.source_unit,
        )
        return self._apply_mask(records, source_cfg)

    @staticmethod
    def _product_of(source_cfg: Any) -> str | None:
        """Return the provider product the source asks for, when it names one."""
        return getattr(source_cfg, "product", None)

    def _resolved_source_values(self, source_cfg: Any) -> dict[str, Any]:
        """The point a nearest-station search starts from, when the config asks for one."""
        if not getattr(source_cfg, "nearest", False):
            return {}
        nearest_to = self._resolve_nearest_to(source_cfg)
        return {} if nearest_to is None else {"nearest_to": nearest_to}

    def _fetch_listed_source(self, source: Any, source_cfg: Any) -> list[PointRecord]:
        bbox = self._resolve_bbox(source_cfg)

        # No cache folder means no side file worth keeping: a scratch owned by
        # this call is the out_dir, and goes when the call does, which is what
        # an empty data_dir has always meant for the station families.
        with TemporaryDirectory(prefix="hmp-stations-") as scratch:
            out_dir = self.data_dir if self.data_dir is not None else Path(scratch)

            def _fetch_for(station_ids, start, end) -> list[PointRecord]:
                request = self._station_request(
                    source_cfg,
                    out_dir=out_dir,
                    station_ids=station_ids,
                    bbox=bbox,
                    start=start,
                    end=end,
                )
                return point_records_of(source.fetch(request))

            return self._fetch_with_station_cache(
                source_cfg, _fetch_for, source_name=source_cfg.source
            )

    def _station_request(
        self,
        source_cfg: Any,
        *,
        out_dir: Path,
        station_ids: list[str] | None,
        bbox: tuple | None,
        start: datetime | None,
        end: datetime | None,
    ) -> FetchRequest:
        """The question a station source is asked: stations it names, or a box.

        One selector, never the two, on the rule the source itself enforces. A
        source that selects by station ids is handed them alone, and a source
        asked to discover is handed the box the mask or the project extent
        resolves to, as an :class:`Extent` in WGS84, the frame every station
        provider of this tree is asked in.
        """
        del source_cfg
        period = Period(start=start, end=end) if start is not None and end is not None else None
        station_ids = list(station_ids or ())
        if station_ids:
            return FetchRequest(out_dir=out_dir, station_ids=tuple(station_ids), period=period)
        extent = None
        if bbox is None:
            bbox = self.project_extent
        if bbox is not None:
            extent = Extent(*bbox, crs=STATION_EXTENT_CRS)
        return FetchRequest(out_dir=out_dir, extent=extent, period=period)

    # ------------------------------------------------------------------
    # Bbox resolution and spatial mask (station APIs expect WGS84)
    # ------------------------------------------------------------------

    def _load_mask_geometry(self, mask_path: Path):
        """Station APIs expect WGS84, so reproject to lon/lat."""
        from hydromodpy.data.common.source_extent import mask_geometry_wgs84

        return mask_geometry_wgs84(mask_path)

    def _apply_mask(
        self,
        records: list[PointRecord],
        source_cfg,
    ) -> list[PointRecord]:
        """Filter records by spatial mask (reprojected to WGS84).

        A station named in ``station_ids``, or asked for with ``nearest=True``,
        is kept even when it lies outside the watershed mask (typical for
        piezometers). The mask still bounds API discovery through
        ``_resolve_bbox``; it only stops stripping what was asked for.
        """
        named = bool(getattr(source_cfg, "station_ids", None))
        if source_cfg.mask_path and (named or getattr(source_cfg, "nearest", False)):
            return records
        return super()._apply_mask(records, source_cfg)

    def _resolve_nearest_to(self, source_cfg) -> tuple[float, float] | None:
        """Compute centroid of the project extent for nearest-station search."""
        bbox = self._resolve_bbox(source_cfg)
        if bbox is None and self.project_extent is not None:
            bbox = self.project_extent
        if bbox is None:
            return None
        xmin, ymin, xmax, ymax = bbox
        return ((xmin + xmax) / 2, (ymin + ymax) / 2)

    # ------------------------------------------------------------------
    # Station cache: partial coverage detection + merge
    # ------------------------------------------------------------------

    def _fetch_with_station_cache(
        self,
        source_cfg: Any,
        fetch_fn: Callable[[list[str] | None, datetime, datetime], list[PointRecord]],
        *,
        source_name: str,
    ) -> list[PointRecord]:
        """Fetch station records, downloading only what the cache lacks.

        ``fetch_fn(station_ids, start, end)`` calls the provider; ``None`` as
        station ids asks it to discover stations in the extent. Stations named
        in the config are read from the cache, completed for the periods it
        misses, and a station known to have no data is not asked again.
        Discovery by extent is never cached.
        """
        if self.project_period is None:
            raise MissingForcingError(
                f"project_period required to fetch {self.VARIABLE_NAME} stations: "
                f"declare date_start and date_end in [data.{self.VARIABLE_NAME}], "
                "or a window in [simulation.time]."
            )

        station_ids = list(source_cfg.station_ids or [])
        max_stations = getattr(source_cfg, "max_stations", None)
        if station_ids and max_stations is not None:
            station_ids = station_ids[:max_stations]
        product = self._product_of(source_cfg)

        if not station_ids or source_cfg.force_refresh:
            reject_frozen_download(
                variable=self.VARIABLE_NAME,
                source=source_name,
                station_id=None,
                detail=(
                    "is asked for by extent or with force_refresh, which the cache cannot "
                    "answer. Name the stations in station_ids and drop force_refresh"
                ),
            )
            records = fetch_fn(station_ids or None, *self.project_period)
            self._persist_api_records(
                records, source_name, window=self.project_period, product=product
            )
            return self._apply_mask(records, source_cfg)

        ready: list[PointRecord] = []
        missing_ids: list[str] = []
        to_persist: list[tuple[PointRecord, tuple[datetime, datetime]]] = []
        for sid in station_ids:
            if self._is_empty_sentinel(source=source_name, station_id=sid, product=product):
                logger.debug("%s station without data (cached): %s", source_name, sid)
                continue
            rec = self._load_cached_api_record(source=source_name, station_id=sid, product=product)
            if rec is None:
                missing_ids.append(sid)
                continue
            # A station answers for the window it was asked for, which can be
            # wider than its data: an ONDE campaign never starts on 1 January.
            asked = self._cached_window(source=source_name, station_id=sid, product=product)
            covered = _hull((rec.date_start, rec.date_end), asked)
            gaps = self._compute_missing_periods(*covered)
            if not gaps:
                ready.append(rec)
                logger.debug("%s cache hit: %s", source_name, sid)
                continue
            parts: list[PointRecord] = []
            reject_frozen_download(
                variable=self.VARIABLE_NAME,
                source=source_name,
                station_id=sid,
                detail=(
                    f"is cached from {covered[0]:%Y-%m-%d} to {covered[1]:%Y-%m-%d} and "
                    f"the run asks for {self.project_period[0]:%Y-%m-%d} to "
                    f"{self.project_period[1]:%Y-%m-%d}"
                    + (
                        ""
                        if asked is not None
                        else ". The cache does not record the window it was asked for: "
                        "run once without --frozen to record it"
                    )
                ),
            )
            for gap_start, gap_end in gaps:
                parts.extend(fetch_fn([sid], gap_start, gap_end))
            window = _hull(covered, self.project_period)
            if parts:
                merged = self._merge_into_record(rec, *parts)
                ready.append(merged)
                to_persist.append((merged, window))
                logger.debug("%s cache merge: %s (+%d period(s))", source_name, sid, len(gaps))
            else:
                # Nothing upstream for the gap: record that it was asked, so
                # the next run (and a frozen replay) does not ask again.
                ready.append(rec)
                self._record_window(rec, source_name, window, product=product)

        for merged, window in to_persist:
            self._persist_api_records([merged], source_name, window=window, product=product)
        if not missing_ids:
            return self._apply_mask(ready, source_cfg)

        records = fetch_fn(missing_ids, *self.project_period)
        self._persist_api_records(records, source_name, window=self.project_period, product=product)
        fetched_ids = {r.station_id for r in records}
        empty_ids = [sid for sid in missing_ids if sid not in fetched_ids]
        if empty_ids:
            self._register_empty_api_stations(empty_ids, source_name, product=product)
        return self._apply_mask(ready + records, source_cfg)

    def _compute_missing_periods(
        self,
        cached_start: datetime,
        cached_end: datetime,
    ) -> list[tuple[datetime, datetime]]:
        """Return date ranges from project_period not covered by the cache.

        Returns an empty list if the cache fully covers the requested period.
        """
        if self.project_period is None:
            return []
        req_start, req_end = self.project_period
        missing: list[tuple[datetime, datetime]] = []
        if req_start < cached_start:
            missing.append((req_start, cached_start - timedelta(days=1)))
        if req_end > cached_end:
            missing.append((cached_end + timedelta(days=1), req_end))
        return missing

    def _merge_into_record(
        self,
        base: PointRecord,
        *others: PointRecord,
    ) -> PointRecord:
        """Merge multiple PointRecords for the same station.

        Concatenates data, deduplicates by datetime, and sorts.
        Returns a single PointRecord covering the full period.
        """
        dfs = [base.data] + [r.data for r in others]
        merged = (
            pd.concat(dfs, ignore_index=True)
            .drop_duplicates(subset="datetime")
            .sort_values("datetime")
            .reset_index(drop=True)
        )
        return PointRecord(
            station_id=base.station_id,
            variable=base.variable,
            source=base.source,
            unit=base.unit,
            frequency=base.frequency,
            data=merged,
            date_start=merged["datetime"].min().to_pydatetime(),
            date_end=merged["datetime"].max().to_pydatetime(),
            location=base.location or (others[0].location if others else None),
            source_unit=base.source_unit or (others[0].source_unit if others else None),
        )

    # ------------------------------------------------------------------
    # Persistence: save API results as CSV and register in catalog
    # ------------------------------------------------------------------

    def _persist_api_records(
        self,
        records: list[PointRecord],
        source: str,
        *,
        window: tuple[datetime, datetime] | None = None,
        product: str | None = None,
    ) -> None:
        """Save API records as CSV files in data_dir and register in catalog.

        If a previous CSV exists for the same station (different period),
        the old file is deleted before saving the new one. ``window`` is the
        period the provider was asked for (default: the project period). It
        is recorded with each entry, so a station whose data stops short of
        it is not asked again for the days it does not have. ``product`` keys
        the entry the same way: the chronicle of one product never answers a
        request for another one.
        """
        if self.data_dir is None or not records:
            return
        self.data_dir.mkdir(parents=True, exist_ok=True)
        prefix = _VAR_FILE_PREFIX.get(self.VARIABLE_NAME, self.VARIABLE_NAME)

        for r in records:
            # Delete old CSV if it exists with a different filename
            self._cleanup_old_api_file(source, r.station_id, product=product)

            # Save chronicle CSV
            safe_id = safe_file_token(r.station_id)
            start_str = r.date_start.strftime("%Y%m%d")
            end_str = r.date_end.strftime("%Y%m%d")
            filename = f"{prefix}_{source}_{safe_id}_{start_str}_{end_str}_{r.frequency}.csv"
            filepath = self.data_dir / filename
            r.data.to_csv(filepath, index=False)
            # The seal records this file as the input of the run that read it.
            r.file_path = filepath

            # Update LOC file with station location
            if r.location:
                self._upsert_api_loc(r.location, source)

            asked = _hull((r.date_start, r.date_end), window or self.project_period)
            self._register_one(r, filepath, window=asked, product=product)

    def _record_window(
        self,
        record: PointRecord,
        source: str,
        window: tuple[datetime, datetime],
        product: str | None = None,
    ) -> None:
        """Record ``window`` as asked for the cached ``record``, leaving its file as it is."""
        if self.catalog is None:
            return
        entry = self.catalog.find_cached(
            variable=self.VARIABLE_NAME,
            source=source,
            station_id=record.station_id,
            product_version=product,
        )
        if entry is None or entry.file_path in (SENTINEL_CUSTOM, SENTINEL_EMPTY):
            return
        self._register_one(
            record, self._resolve_catalog_path(entry.file_path), window=window, product=product
        )

    def _cached_window(
        self, *, source: str, station_id: str, product: str | None = None
    ) -> tuple[datetime, datetime] | None:
        """Return the window a cached station was asked for, or None when not recorded."""
        if self.catalog is None:
            return None
        entry = self.catalog.find_cached(
            variable=self.VARIABLE_NAME,
            source=source,
            station_id=station_id,
            product_version=product,
        )
        recorded = getattr(entry, "fetch_metadata", None)
        if isinstance(recorded, str):
            try:
                recorded = json.loads(recorded)
            except ValueError:
                return None
        if not isinstance(recorded, dict):
            return None
        window = recorded.get(_ASKED_WINDOW_KEY)
        if not isinstance(window, list) or len(window) != 2:
            return None
        try:
            return (datetime.fromisoformat(window[0]), datetime.fromisoformat(window[1]))
        except (TypeError, ValueError):
            return None

    def _cleanup_old_api_file(
        self, source: str, station_id: str, product: str | None = None
    ) -> None:
        """Delete old API CSV if a previous download exists for this station.

        The lookup rides on the product: a CSV written for another product
        stays on disk, its entry answers nothing and is replaced at the end
        of the fetch.
        """
        if self.catalog is None:
            return
        entry = self.catalog.find_cached(
            variable=self.VARIABLE_NAME,
            source=source,
            station_id=station_id,
            product_version=product,
        )
        if entry is None or entry.file_path in (SENTINEL_CUSTOM, SENTINEL_EMPTY):
            return
        unlink_with_sidecar(self._resolve_catalog_path(entry.file_path))

    def _resolve_catalog_path(self, file_path: str) -> Path:
        """Resolve a catalog file_path the way the catalog stored it."""
        return self.catalog.resolve_path(file_path, variable=self.VARIABLE_NAME)

    def _register_empty_api_stations(
        self,
        station_ids: list[str],
        source: str,
        product: str | None = None,
    ) -> None:
        """Register stations that returned no data from the API.

        Creates a catalog entry with file_path=SENTINEL_EMPTY so that subsequent
        runs don't re-fetch stations known to have no data.
        Use force_refresh=True to bypass this sentinel.
        """
        if self.catalog is None:
            return
        for sid in station_ids:
            window = self.project_period
            self.catalog.register(
                variable=self.VARIABLE_NAME,
                source=source,
                station_id=sid,
                file_path=SENTINEL_EMPTY,
                is_custom=False,
                fetch_metadata=_fetch_metadata_of(window, product),
            )

    def _is_empty_sentinel(self, source: str, station_id: str, product: str | None = None) -> bool:
        """True when the cache keeps a no-data sentinel for this station.

        The lookup rides on the product the same way: a sentinel written for
        one product never answers a request made under another one.
        """
        if self.catalog is None:
            return False
        entry = self.catalog.find_cached(
            variable=self.VARIABLE_NAME,
            source=source,
            station_id=station_id,
            product_version=product,
        )
        if entry is None or entry.file_path != SENTINEL_EMPTY:
            return False
        # The sentinel answers for the window it was asked for. Another window
        # may hold data, so it is asked again. A sentinel with no recorded
        # window comes from an older cache and keeps answering for any window.
        asked = self._cached_window(source=source, station_id=station_id, product=product)
        if asked is None or self.project_period is None:
            return True
        return asked[0] <= self.project_period[0] and self.project_period[1] <= asked[1]

    def _upsert_api_loc(self, loc: StationLocation, source: str) -> None:
        """Add or update a station in the API LOC file."""
        if self.data_dir is None:
            return
        prefix = _VAR_FILE_PREFIX.get(self.VARIABLE_NAME, self.VARIABLE_NAME)
        loc_path = self.data_dir / f"{prefix}_{source}_LOC.csv"

        existing: dict[str, dict] = {}
        if loc_path.exists():
            df = pd.read_csv(loc_path)
            for _, row in df.iterrows():
                existing[str(row["id"])] = row.to_dict()

        # Flatten metadata for CSV columns
        row_data = {"id": loc.id, "x": loc.x, "y": loc.y, "crs": loc.crs}
        for k, v in loc.metadata.items():
            if v is not None:
                row_data[k] = v
        existing[loc.id] = row_data

        out = pd.DataFrame(existing.values())
        out.to_csv(loc_path, index=False)

    # ------------------------------------------------------------------
    # Catalog registration
    # ------------------------------------------------------------------

    def _register_records(self, records: list[PointRecord]) -> None:
        """Register all records in the catalog (metadata only)."""
        if self.catalog is None:
            return
        for r in records:
            # API records are already registered in _persist_api_records.
            if r.source not in ("file", "custom"):
                continue
            fp = r.file_path if r.file_path is not None else Path(SENTINEL_CUSTOM)
            self._register_one(r, file_path=fp)

    def _register_one(
        self,
        r: PointRecord,
        file_path: Path,
        *,
        window: tuple[datetime, datetime] | None = None,
        product: str | None = None,
    ) -> None:
        """Register a single record in the catalog, with window and product asked."""
        if self.catalog is None:
            return
        bbox = None
        crs = None
        if r.location:
            bbox = (r.location.x, r.location.y, r.location.x, r.location.y)
            crs = r.location.crs
        self.catalog.register(
            variable=self.VARIABLE_NAME,
            source=r.source,
            station_id=r.station_id,
            file_path=str(file_path),
            date_start=r.date_start,
            date_end=r.date_end,
            unit=r.unit,
            source_unit=r.source_unit,
            frequency=r.frequency,
            bbox=bbox,
            crs=crs,
            is_custom=(r.source in ("file", "custom")),
            fetch_metadata=_fetch_metadata_of(window, product),
        )

    # ------------------------------------------------------------------
    # Cache lookup for API data
    # ------------------------------------------------------------------

    def _load_cached_api_record(
        self,
        *,
        source: str,
        station_id: str,
        product: str | None = None,
    ) -> PointRecord | None:
        """Try to load a single station from cached CSV via the catalog.

        Does NOT filter by date - returns whatever is cached. The caller
        uses _compute_missing_periods() to detect partial coverage. The
        lookup rides on the product: a chronicle cached under one product
        never answers a request made under another one, so the product
        change re-downloads the station once.
        """
        if self.catalog is None or self.data_dir is None:
            return None
        entry = self.catalog.find_cached(
            variable=self.VARIABLE_NAME,
            source=source,
            station_id=station_id,
            product_version=product,
        )
        if entry is None:
            return None

        filepath = self._resolve_catalog_path(entry.file_path)
        if not filepath.exists():
            # File deleted externally - clean up stale entry
            self.catalog.invalidate(
                variable=self.VARIABLE_NAME,
                source=source,
                station_id=station_id,
            )
            return None

        # Check if file was modified externally (mtime mismatch)
        if entry.file_mtime is not None:
            current_mtime = filepath.stat().st_mtime
            if abs(current_mtime - entry.file_mtime) > 1.0:
                # File modified externally - invalidate and re-fetch
                self.catalog.invalidate(
                    variable=self.VARIABLE_NAME,
                    source=source,
                    station_id=station_id,
                )
                return None

        from hydromodpy.data.common.io_helpers import read_timeseries_csv

        df = read_timeseries_csv(filepath)
        if df.empty:
            return None

        # Reconstruct location from LOC file if available
        location = self._load_cached_location(source, station_id)
        # The sidecar speaks for the file; the index row fills what it lacks.
        sidecar = _chronicle_sidecar(filepath)

        return PointRecord(
            station_id=station_id,
            variable=self.RECORD_VARIABLE or self.VARIABLE_NAME,
            source=source,
            unit=sidecar.get("unit") or entry.unit or "",
            frequency=sidecar.get("frequency") or entry.frequency or "D",
            data=df,
            date_start=df["datetime"].min().to_pydatetime(),
            date_end=df["datetime"].max().to_pydatetime(),
            location=location,
            file_path=filepath,
            source_unit=sidecar.get("source_unit") or entry.source_unit,
        )

    def _load_cached_location(
        self,
        source: str,
        station_id: str,
    ) -> StationLocation | None:
        """Load a station's location from the API LOC file."""
        if self.data_dir is None:
            return None
        prefix = _VAR_FILE_PREFIX.get(self.VARIABLE_NAME, self.VARIABLE_NAME)
        loc_path = self.data_dir / f"{prefix}_{source}_LOC.csv"
        if not loc_path.exists():
            return None
        df = pd.read_csv(loc_path)
        row = df[df["id"].astype(str) == str(station_id)]
        if row.empty:
            return None
        r = row.iloc[0]
        extra = {k: v for k, v in r.items() if k not in ("id", "x", "y", "crs") and pd.notna(v)}
        return StationLocation(
            id=str(r["id"]),
            x=float(r["x"]),
            y=float(r["y"]),
            crs=str(r.get("crs", "EPSG:4326")),
            metadata=extra,
        )

    # ------------------------------------------------------------------
    # Reporting and export
    # ------------------------------------------------------------------

    def get_completeness_report(self, records: LoadResult | list[PointRecord]) -> pd.DataFrame:
        """Compute per-station completeness stats."""
        if isinstance(records, LoadResult):
            records = records.points

        start = self.project_period[0] if self.project_period else None
        end = self.project_period[1] if self.project_period else None

        rows = []
        for rec in records:
            stats = compute_completeness(
                rec.data,
                station_id=rec.station_id,
                start_date=start or rec.date_start,
                end_date=end or rec.date_end,
            )
            stats["variable"] = rec.variable
            stats["source"] = rec.source
            stats["is_constant"] = rec.is_constant
            rows.append(stats)

        return pd.DataFrame(rows)

    def export(
        self,
        records: LoadResult | list[PointRecord],
        output_dir: str | Path,
    ) -> dict[str, Path]:
        """Export records to CSV (chronicles + metadata + table of contents)."""
        if isinstance(records, LoadResult):
            records = records.points
        from hydromodpy.data.common.export import export_records

        return export_records(
            records,
            output_dir,
            variable_name=self.VARIABLE_NAME,
            prefix=self.VARIABLE_NAME,
        )
