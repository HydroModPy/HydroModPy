"""Shared base for variable and field data managers.

Private to the ``hydromodpy.data`` package: provides the constructor, the
source table, and the spatial helpers that both manager families share.
``BaseVariableManager`` and ``BaseFieldManager`` both inherit from
:class:`BaseManagerCommon`.

A manager reaches its providers through ``SOURCES``: each value a user may
write in ``source =``, except ``custom``, maps to the function that fetches it.
``custom`` is always the user's own files, loaded by ``load_custom``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

from hydromodpy.core.exceptions import DataSourceError
from hydromodpy.core.logging import get_logger
from hydromodpy.data.contracts.timeseries import PointRecord

logger = get_logger(__name__)

CUSTOM_SOURCE = "custom"
"""The ``source =`` value that names the user's own files."""


@dataclass(frozen=True, slots=True)
class SourceContext:
    """What a manager knows beyond the source config and its extent.

    Handed to every function of a ``SOURCES`` table, which reads only what it
    needs: the SHOM tide gauges keep their cache in ``data_dir`` and fall back on
    ``config_period``, a nearest-station search starts from ``nearest_to``.
    """

    project_extent: tuple | None
    data_dir: Path | None
    config_period: tuple[datetime, datetime] | None
    """The ``date_start`` and ``date_end`` of the ``[data.<name>]`` section, when both are set."""
    nearest_to: tuple[float, float] | None = None
    """Where a nearest-station search starts, when the source config asks for one."""


class SourceTable:
    """Dispatch a source config to ``load_custom`` or to its ``SOURCES`` entry."""

    VARIABLE_NAME: ClassVar[str] = ""
    SOURCES: ClassVar[Mapping[str, Callable[..., Any]]] = {}

    def _fetch_from_source(self, source_cfg: Any) -> Any:
        if source_cfg.source == CUSTOM_SOURCE:
            return self.load_custom(source_cfg)
        return self._fetch_listed_source(self._listed_source(source_cfg.source), source_cfg)

    def _listed_source(self, name: str) -> Callable[..., Any]:
        try:
            return self.SOURCES[name]
        except KeyError:
            raise ValueError(f"Unknown {self.VARIABLE_NAME} source: {name}") from None

    def load_custom(self, source_cfg: Any) -> Any:
        """Load the user's own files for one source config."""
        raise NotImplementedError

    def _fetch_listed_source(self, fetch: Callable[..., Any], source_cfg: Any) -> Any:
        """Call one ``SOURCES`` function the way this manager family calls them."""
        raise NotImplementedError


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
    ):
        self.config = config
        self.catalog = catalog
        self.project_extent = project_extent
        self.project_period = project_period
        self.data_dir = Path(data_dir) if data_dir else None

    def _source_context(self, source_cfg: Any) -> SourceContext:
        return SourceContext(
            project_extent=self.project_extent,
            data_dir=self.data_dir,
            config_period=self._config_period(),
        )

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

        Dropping a station outside the mask is the intended behaviour, never a
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
