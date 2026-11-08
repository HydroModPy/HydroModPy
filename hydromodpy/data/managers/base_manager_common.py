"""Shared base for variable and field data managers.

Private to the ``hydromodpy.data`` package: provides the constructor, the
source resolution, and the spatial helpers that both manager families share.
``BaseVariableManager`` and ``BaseFieldManager`` both inherit from
:class:`BaseManagerCommon`, and the lake variables inherit
:class:`SourceTable` through :class:`BaseFileManager`.

A manager resolves the source a section names on the source registry, within
its own section: ``data_sources.get(self.VARIABLE_NAME, cfg.source)``, built
with :func:`~hydromodpy.data.source.registry.build_from_section`. ``custom`` is
always the user's own files, loaded by ``load_custom``, and stays outside the
registry until the lot that makes it a source.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

from hydromodpy.core.exceptions import DataProductError, DataSourceError
from hydromodpy.core.logging import get_logger
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.source.port import FetchResult
from hydromodpy.data.source.registry import build_from_section, data_sources

logger = get_logger(__name__)

CUSTOM_SOURCE = "custom"
"""The ``source =`` value that names the user's own files."""


class SourceTable:
    """Dispatch a source config to ``load_custom`` or to the port it registers on."""

    VARIABLE_NAME: ClassVar[str] = ""

    def _fetch_from_source(self, source_cfg: Any) -> Any:
        if source_cfg.source == CUSTOM_SOURCE:
            return self.load_custom(source_cfg)
        source = self._build_configured_source(source_cfg)
        return self._fetch_listed_source(source, source_cfg)

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
        """What only the manager can compute, handed to the source constructor.

        A family overrides this: the station family resolves the point a
        nearest-station search starts from, the field family hands the dates
        the section writes as datetimes. Each key a constructor does not name
        is dropped by ``build_from_section``, so a source asks for what it
        reads.
        """
        del source_cfg
        return {}

    def load_custom(self, source_cfg: Any) -> Any:
        """Load the user's own files for one source config."""
        raise NotImplementedError

    def _fetch_listed_source(self, source: Any, source_cfg: Any) -> Any:
        """Call one source the way this manager family does."""
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


class BaseManagerCommon(SourceTable, ABC):
    """Shared state and spatial helpers for data managers."""

    INTERNAL_UNIT: ClassVar[str] = ""

    def __init__(
        self,
        *,
        config: Any,
        catalog: Any,
        project_extent: tuple | None = None,
        project_period: tuple[datetime, datetime] | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self.config = config
        self.catalog = catalog
        self.project_extent = project_extent
        self.project_period = project_period
        self.data_dir = Path(data_dir) if data_dir else None

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
            from hydromodpy.data.common.geo_helpers import geometry_to_bbox

            geom = self._load_mask_geometry(source_cfg.mask_path)
            return geometry_to_bbox(geom)
        if source_cfg.extent and self.project_extent:
            return self.project_extent
        return None

    @abstractmethod
    def _load_mask_geometry(self, mask_path: Path):
        """Load a mask geometry. Variable managers reproject to WGS84."""
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
        from hydromodpy.data.common.geo_helpers import filter_locations_by_geometry
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
        listed = bool(named) or str(getattr(source_cfg, "source", "")) == "custom"
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
