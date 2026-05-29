"""Cleanup helpers for generated site-selection intermediates."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from hydromodpy.core.logging import get_logger
from hydromodpy.spatial.site_selection.hydrology.delineation import DelineatedCatchment
from hydromodpy.spatial.site_selection.hydrology.flow_products import SiteSelectionFlowProducts

logger = get_logger(__name__)


def cleanup_site_selection_intermediate_rasters(
    *,
    output_root: str | Path,
    catchments: Iterable[DelineatedCatchment],
    flow_products: SiteSelectionFlowProducts | None = None,
) -> tuple[Path, ...]:
    """Remove reproducible GeoTIFF intermediates under a site-selection output root."""

    root = Path(output_root).expanduser().resolve()
    targets = _cleanup_targets(root=root, catchments=catchments, flow_products=flow_products)
    removed: list[Path] = []
    seen: set[Path] = set()
    for target in targets:
        resolved = Path(target).expanduser().resolve(strict=False)
        if resolved in seen or not _is_within(resolved, root) or not resolved.is_file():
            continue
        seen.add(resolved)
        try:
            resolved.unlink()
        except OSError as exc:
            logger.warning("Could not remove site-selection intermediate raster %s: %s", resolved, exc)
            continue
        removed.append(resolved)
        _remove_empty_parents(resolved.parent, stop=root)
    return tuple(removed)


def _cleanup_targets(
    *,
    root: Path,
    catchments: Iterable[DelineatedCatchment],
    flow_products: SiteSelectionFlowProducts | None,
) -> list[Path]:
    targets: list[Path] = []
    if flow_products is not None:
        products = flow_products.products
        targets.extend(Path(path) for path in (products.correc, products.direc, products.acc))

    flow_dir = root / "flow_products"
    if flow_dir.is_dir():
        targets.extend(flow_dir.glob("*.tif"))

    for catchment in catchments:
        if catchment.watershed_tif:
            targets.append(Path(catchment.watershed_tif))
    return targets


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _remove_empty_parents(path: Path, *, stop: Path) -> None:
    current = path
    while _is_within(current, stop) and current != stop:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


__all__ = ["cleanup_site_selection_intermediate_rasters"]
