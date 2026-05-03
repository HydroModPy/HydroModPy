"""Hub'Eau smart cache: shared cache+fetch logic for all Hub'Eau managers.

Extracts the duplicated pattern from hydrometry, piezometry, intermittency,
and water_quality managers into a single reusable function.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from hydromodpy.core.logging import get_logger
from hydromodpy.data.contracts.timeseries import PointRecord

if TYPE_CHECKING:
    from hydromodpy.data.base_manager_variable import BaseVariableManager

logger = get_logger(__name__)


def fetch_with_smart_cache(
    manager: BaseVariableManager,
    *,
    source_cfg,
    fetch_fn: Callable[..., list[PointRecord]],
    source_name: str = "hubeau",
) -> list[PointRecord]:
    """Fetch Hub'Eau data with smart cache (partial coverage + merge).

    This replaces the duplicated ``_fetch_hubeau`` method in each manager.

    Parameters
    ----------
    manager : BaseVariableManager
        The manager instance (provides catalog, project_period, etc.).
    source_cfg : source config object
        Must have ``station_ids``, ``force_refresh``, ``mask_path``.
    fetch_fn : callable(station_ids, date_start, date_end) -> list[PointRecord]
        Function that calls the Hub'Eau API for given stations and dates.
    source_name : str
        Source identifier for catalog registration (default "hubeau").
    """
    if manager.project_period is None:
        raise ValueError("project_period required for Hub'Eau.")

    # --- Try cache for explicitly requested station_ids ---
    if source_cfg.station_ids and not source_cfg.force_refresh:
        ready: list[PointRecord] = []
        missing_ids: list[str] = []
        to_persist: list[PointRecord] = []

        for sid in source_cfg.station_ids:
            if manager._is_empty_sentinel(source=source_name, station_id=sid):
                logger.debug("Hub'Eau no-data (cached): %s", sid)
                continue

            rec = manager._load_cached_api_record(
                source=source_name,
                station_id=sid,
            )
            if rec is not None:
                gaps = manager._compute_missing_periods(
                    rec.date_start,
                    rec.date_end,
                )
                if not gaps:
                    ready.append(rec)
                    logger.debug("Hub'Eau cache hit: %s", sid)
                else:
                    parts: list[PointRecord] = []
                    for gs, ge in gaps:
                        parts.extend(fetch_fn([sid], gs, ge))
                    if parts:
                        merged = manager._merge_into_record(rec, *parts)
                        ready.append(merged)
                        to_persist.append(merged)
                        logger.info(
                            "Hub'Eau cache merge: %s (+%d period(s))",
                            sid,
                            len(gaps),
                        )
                    else:
                        ready.append(rec)
            else:
                missing_ids.append(sid)

        if to_persist:
            manager._persist_api_records(to_persist, source_name)
        if not missing_ids:
            return manager._apply_mask(ready, source_cfg)

        records = fetch_fn(
            missing_ids,
            manager.project_period[0],
            manager.project_period[1],
        )
        manager._persist_api_records(records, source_name)

        fetched_ids = {r.station_id for r in records}
        empty_ids = [s for s in missing_ids if s not in fetched_ids]
        if empty_ids:
            manager._register_empty_api_stations(empty_ids, source_name)
        return manager._apply_mask(ready + records, source_cfg)

    # --- No cache for bbox-based discovery ---
    records = fetch_fn(
        source_cfg.station_ids,
        manager.project_period[0],
        manager.project_period[1],
    )
    manager._persist_api_records(records, source_name)
    return manager._apply_mask(records, source_cfg)
