"""Common station management utilities and reporting for dropped stations."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from hydromodpy.core.config_kit.said import say
from hydromodpy.core.exceptions import DataSourceError
from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)


def report_dropped(
    variable: str,
    source: str,
    *,
    named: Sequence[str] | set[str] | None = None,
    dropped: Sequence[str] | set[str],
    kept: Sequence[Any],
    reason: str,
    product: str | None = None,
    window: tuple[Any, Any] | None = None,
    force_refresh_hint: bool = False,
    raise_on_empty: bool = True,
) -> None:
    """Report dropped stations via warning, and refuse with DataSourceError when all named are dropped."""
    dropped_list = sorted(set(dropped))
    if not dropped_list:
        return

    named_set = set(named or ())
    named_dropped = [sid for sid in dropped_list if sid in named_set]
    is_named = bool(named_set)

    details: list[str] = []
    if product:
        details.append(f"product={product}")
    if window:
        details.append(f"window={window[0]}..{window[1]}")
    if force_refresh_hint:
        details.append("try force_refresh=True")
    detail_str = f" ({', '.join(details)})" if details else ""

    if raise_on_empty and not kept and is_named:
        raise DataSourceError(
            f"{variable}: every named station of source '{source}' was dropped "
            f"({reason}){detail_str}: {named_dropped}. No station is left to load."
        )

    message = (
        f"{variable}: {len(dropped_list)} station(s) of source '{source}' "
        f"dropped ({reason}){detail_str}: {dropped_list}."
    )
    if not kept:
        message += " No station of the search lies inside: the variable is empty."
    if named_dropped:
        message += f" Named in station_ids and dropped all the same: {named_dropped}."

    logger.warning("%s", message)
    say(message, UserWarning, stacklevel=2)


__all__ = ["report_dropped"]
