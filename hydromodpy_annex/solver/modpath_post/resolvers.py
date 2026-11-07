"""Small readers shared by the MODPATH post-processing of the annex."""

from __future__ import annotations

from typing import Any


def budget_holds(cbb: Any, text: str) -> bool:
    """Return True when the cell budget file holds the term ``text``."""
    return any(text == name.decode().strip() for name in cbb.get_unique_record_names())


def crs_for_write_from_proj(crs: object | None) -> tuple[object | None, int | None]:
    """Normalize a CRS proj definition into ``(crs_for_write, epsg)``."""
    if isinstance(crs, (int, float)):
        epsg: int | None = int(crs)
    elif isinstance(crs, str) and crs[:4].upper() == "EPSG":
        epsg = int(crs.split(":")[-1])
    else:
        epsg = None
    crs_for_write = crs if crs is not None else (f"EPSG:{epsg}" if epsg is not None else None)
    return crs_for_write, epsg
