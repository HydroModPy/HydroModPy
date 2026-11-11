"""Shared base for the station and grid variables.

Private to the ``hydromodpy.data`` package: provides the constructor, the
source resolution, and the spatial helpers that both families share.
``StationVariable`` and ``GridVariable`` both inherit from
:class:`VariableBase`, and the lake variables inherit
:class:`SourceTable` through :class:`FileVariable`.

A variable resolves the source a section names on the source registry, within
its own section: ``data_sources.get(self.VARIABLE_NAME, cfg.source)``, built
with :func:`~hydromodpy.data.source.registry.build_from_section`. ``file`` is
always the user's own files, read by ``load_file`` where they lie, and ``url``
fills the data cache from its URL, then reads the cached file the same way.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, ClassVar

from hydromodpy.core.exceptions import DataProductError, DataSourceError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.provenance.sidecars import CacheIndex
from hydromodpy.data.source.port import FetchRequest, FetchResult, fetch_within
from hydromodpy.data.source.registry import build_from_section, data_sources

logger = get_logger(__name__)

FILE_SOURCE = "file"
"""The ``source =`` value that names the user's own files."""

URL_SOURCE = "url"
"""The ``source =`` value that fills the data cache from one URL."""


@dataclass(frozen=True)
class SourceWithinBounds:
    """The source a variable serves, under the :class:`Bounds` of its call.

    The base of the variable families hands its fetchers this wrapper instead of
    the bare source, so that every request they build that carries no bounds of
    its own rides on the bounds of the call, and every fetch goes through
    :func:`~hydromodpy.data.source.port.fetch_within`, which refuses the hosts
    the source declares before anything connects. The hydrography network
    seam reads ``bounds`` off the source it is handed, the only object the
    caller of that seam passes down. Every other attribute reads through to
    the wrapped source.
    """

    source: Any
    bounds: Bounds

    def __getattr__(self, name: str) -> Any:
        return getattr(self.source, name)

    def fetch(self, request: Any) -> FetchResult:
        if request.bounds == Bounds():
            request = replace(request, bounds=self.bounds)
        return fetch_within(self.source, request)


def source_within_bounds(source: Any, bounds: Bounds) -> SourceWithinBounds:
    """The source a call hands its fetchers, under the given bounds."""
    return SourceWithinBounds(source=source, bounds=bounds)


class SourceTable:
    """Dispatch a source config to ``load_file``, the ``url`` cache, or its port."""

    VARIABLE_NAME: ClassVar[str] = ""

    # The bounds of the call this variable serves: the hosts it may reach and the
    # roots it may use. The construction path that knows them (the runtime
    # loader, or the request engine) sets them; left alone, the default allows
    # every host, which is the behaviour of a machine call.
    bounds: Bounds = Bounds()

    def _fetch_from_source(self, source_cfg: Any) -> Any:
        """Serve the user's file entry, the ``url`` cache, or the registered source.

        The user's own entries never reach a provider: ``file`` is read by
        ``load_file``, and ``url`` fills the data cache from its URL then reads
        the cached file exactly as ``load_file`` reads a user file. A URL only
        fills the cache; the run reads the file.
        """
        source_kind = str(getattr(source_cfg, "source", ""))
        if source_kind == FILE_SOURCE:
            return self.load_file(source_cfg)
        if source_kind == URL_SOURCE:
            return self._load_url_source(source_cfg)
        source = self._build_configured_source(source_cfg)
        return self._fetch_listed_source(self._within_bounds(source), source_cfg)

    def _load_url_source(self, source_cfg: Any) -> Any:
        """Fill the data cache from the URL the entry names, then read the file."""
        source_cls = data_sources.get(self.VARIABLE_NAME, URL_SOURCE)
        data_dir = getattr(self, "data_dir", None)
        with TemporaryDirectory(prefix="hmp-url-") as scratch:
            # Without a data folder the file lands in a scratch that goes with
            # the call, and its sidecar is a row of an index of that scratch.
            if data_dir is not None:
                out_dir, index = Path(data_dir), getattr(self, "index", None)
            else:
                out_dir, index = Path(scratch), CacheIndex(scratch)
            source = build_from_section(source_cls, source_cfg, index=index)
            result = fetch_within(source, FetchRequest(out_dir=out_dir, bounds=self.bounds))
            # The file is read before the scratch, if any, goes.
            loaded_files = [
                self.load_file(
                    source_cfg.model_copy(update={"source": FILE_SOURCE, "path": Path(record.path)})
                )
                for record in result.files
            ]
        if len(loaded_files) == 1 and not isinstance(loaded_files[0], list):
            return loaded_files[0]
        records: list[Any] = []
        for loaded in loaded_files:
            records.extend(loaded if isinstance(loaded, list) else [loaded])
        return records

    def _within_bounds(self, source: Any) -> SourceWithinBounds:
        """The source this variable hands its fetchers, under its own bounds.

        Every request the variable families build flows through the ``fetch``
        of that wrapper, which stamps the bounds of the call on a request that
        carries none of its own and refuses, through :func:`fetch_within`, the
        hosts the source declares before anything connects.
        """
        return source_within_bounds(source, self.bounds)

    def _build_configured_source(self, source_cfg: Any) -> Any:
        """The source the section names, built from that section.

        A name this section does not serve is refused here with the registry's
        own message, which lists what it does serve, so a source id that
        belongs to another variable never builds.
        """
        source_cls = data_sources.get(self.VARIABLE_NAME, str(source_cfg.source))
        return build_from_section(
            source_cls, source_cfg, **self._resolved_source_values(source_cfg)
        )

    def _resolved_source_values(self, source_cfg: Any) -> dict[str, Any]:
        """What only the variable can compute, handed to the source constructor.

        A family overrides this: the station family resolves the point a
        nearest-station search starts from, the field family hands the dates
        the section writes as datetimes. Each key a constructor does not name
        is dropped by ``build_from_section``, so a source asks for what it
        reads.
        """
        del source_cfg
        return {}

    def load_file(self, source_cfg: Any) -> Any:
        """Load the user's own files for one source config."""
        raise NotImplementedError

    def _fetch_listed_source(self, source: Any, source_cfg: Any) -> Any:
        """Call one source the way this variable family does."""
        raise NotImplementedError


def point_records_of(result: FetchResult) -> list[PointRecord]:
    """The point records a station variable holds, refusing any other payload.

    An empty list is an answer -- a box over the sea holds no gauging station --
    and the cache is what records it, so the caller decides what it means.
    """
    if result.kind != "points":
        raise DataProductError(
            f"Source {result.source_id!r} answered a station variable with a "
            f"{result.kind!r} payload. A station variable holds point records, and the "
            "sources registered under its section serve exactly that."
        )
    return list(result.points)


class VariableBase(SourceTable, ABC):
    """Shared state and spatial helpers for the station and grid variables.

    ``index`` is the :class:`CacheIndex` of the data folder, read once by the
    store and shared by every variable it builds. A variable built with
    ``index=None`` reads and writes no cache.
    """

    INTERNAL_UNIT: ClassVar[str] = ""

    def __init__(
        self,
        *,
        config: Any,
        index: CacheIndex | None,
        project_extent: tuple | None = None,
        project_period: tuple[datetime, datetime] | None = None,
        data_dir: Path | None = None,
        bounds: Bounds | None = None,
    ) -> None:
        self.config = config
        self.index = index
        self.project_extent = project_extent
        self.project_period = project_period
        self.data_dir = Path(data_dir) if data_dir else None
        # The bounds of the call this variable serves, or the all-allowing
        # default of a machine call: every request it builds carries them.
        self.bounds = bounds if bounds is not None else Bounds()

    def _config_period(self) -> tuple[datetime, datetime] | None:
        start = getattr(self.config, "date_start", None)
        end = getattr(self.config, "date_end", None)
        if not (start and end):
            return None
        return datetime.fromisoformat(str(start)), datetime.fromisoformat(str(end))

    # ------------------------------------------------------------------
    # Bbox resolution and spatial mask
    # ------------------------------------------------------------------

    def _resolve_bbox(self, source_cfg) -> tuple | None:
        """Resolve bbox from mask geometry or fall back to project extent."""
        if source_cfg.mask_path:
            from hydromodpy.data.common.geometry import geometry_to_bbox

            geom = self._load_mask_geometry(source_cfg.mask_path)
            return geometry_to_bbox(geom)
        if source_cfg.extent and self.project_extent:
            return self.project_extent
        return None

    @abstractmethod
    def _load_mask_geometry(self, mask_path: Path):
        """Load a mask geometry. Each variable reprojects to WGS84."""
        ...

    def _apply_mask(
        self,
        records: list[PointRecord],
        source_cfg,
    ) -> list[PointRecord]:
        """Filter records by spatial mask (WGS84).

        Dropping a station outside the mask is the intended behavior, never a
        silent one: the warning names each station dropped. When every station
        lies outside and the user listed them (in ``station_ids``, or in the
        files of a ``custom`` source), the variable the user asked for cannot be
        obtained, and is refused. Stations found by a search over the extent of
        the mask are only candidates: when none of them lies inside, the warning
        says so and the variable is empty, as when the search finds no station.
        """
        if not source_cfg.mask_path:
            return records
        from hydromodpy.data.common.geometry import filter_locations_by_geometry
        from hydromodpy.data.common.source_extent import mask_geometry_wgs84

        geom = mask_geometry_wgs84(source_cfg.mask_path)
        locs_to_check = [r.location for r in records if r.location is not None]
        inside = filter_locations_by_geometry(locs_to_check, geom)
        valid_ids = {loc.id for loc in inside}
        kept = [r for r in records if r.location is None or r.station_id in valid_ids]
        dropped = sorted(
            {
                r.station_id
                for r in records
                if r.location is not None and r.station_id not in valid_ids
            }
        )
        if not dropped:
            return kept
        named = set(getattr(source_cfg, "station_ids", None) or ())
        named_dropped = [sid for sid in dropped if sid in named]
        mask = Path(str(source_cfg.mask_path)).name
        listed = bool(named) or str(getattr(source_cfg, "source", "")) == FILE_SOURCE
        if not kept and listed:
            raise DataSourceError(
                f"{self.VARIABLE_NAME}: every station of source "
                f"'{source_cfg.source}' lies outside the mask {mask}: {dropped}. "
                "No station is left to load."
            )
        message = (
            f"{self.VARIABLE_NAME}: {len(dropped)} station(s) of source "
            f"'{source_cfg.source}' outside the mask {mask} dropped: {dropped}."
        )
        if not kept:
            message += " No station of the search lies inside: the variable is empty."
        if named_dropped:
            message += f" Named in station_ids and dropped all the same: {named_dropped}."
        logger.warning("%s", message)
        return kept
