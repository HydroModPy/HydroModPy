"""Measure how far the computed flow paths stray from the mapped stream network.

Seed the D8 pointer on every mapped cell of the catchment and follow it down: the
cells reached form the downstream closure of the network. ``alpha`` is the share
of that closure the mapped network already covers, so ``1.0`` means the computed
paths never leave the map, and ``0.5`` means each mapped cell generates one cell
of spurious trace, the signature of a systematic one-pixel shift.

This is not a quality mark on the network, which is an input taken as given. It
measures the disagreement between the DEM and that network, so it says whether
the DEM needs the stream burn of
:mod:`~hydromodpy.spatial.geographic.core.stream_enforcement`, and whether the
depth used was enough. It runs on any project that declares a network, with or
without burning, and needs no calibration.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import rasterize

from hydromodpy.core.logging import get_logger
from hydromodpy.spatial.geographic.core.d8 import WBT_D8_OFFSETS
from hydromodpy.spatial.geographic.core.stream_enforcement import streams_from_config

logger = get_logger(__name__)

# Below this agreement the mapped network and the DEM disagree enough that any
# length measured along the computed flow paths reports that disagreement.
_ALPHA_WARNING_THRESHOLD = 0.90


@dataclass(frozen=True)
class NetworkDemAgreement:
    """Agreement between one D8 pointer raster and the mapped stream network."""

    n_network_cells: int
    n_closure_cells: int
    alpha: float
    burned: bool


def measure_network_dem_agreement(
    *,
    d8_pointer_path: str | Path,
    watershed_shp: str | Path,
    stream_lines: list,
    burned: bool = False,
) -> NetworkDemAgreement:
    """Measure the agreement between one D8 pointer raster and a mapped network."""
    import geopandas as gpd

    with rasterio.open(str(d8_pointer_path)) as src:
        codes = src.read(1)
        transform = src.transform
        shape = codes.shape

    lines = [g for g in stream_lines if g is not None and not g.is_empty]
    if not lines:
        raise ValueError("measure_network_dem_agreement: no stream geometry to measure.")
    network = rasterize(
        ((g, 1) for g in lines),
        out_shape=shape,
        transform=transform,
        fill=0,
        all_touched=True,
        dtype="uint8",
    ).astype(bool)

    catchment = gpd.read_file(str(watershed_shp))
    core = rasterize(
        ((g, 1) for g in catchment.geometry if g is not None and not g.is_empty),
        out_shape=shape,
        transform=transform,
        fill=0,
        all_touched=False,
        dtype="uint8",
    ).astype(bool)

    seeds = np.flatnonzero((network & core).ravel())
    if seeds.size == 0:
        raise ValueError(
            "measure_network_dem_agreement: the mapped network and the catchment "
            "polygon do not share a single cell; check their CRS and extents."
        )
    closure = _downstream_closure(_d8_receivers(codes), seeds)
    n_closure = int(np.count_nonzero(closure.reshape(shape) & core))

    return NetworkDemAgreement(
        n_network_cells=int(seeds.size),
        n_closure_cells=n_closure,
        alpha=float(seeds.size) / float(n_closure) if n_closure else float("nan"),
        burned=bool(burned),
    )


def report_network_dem_agreement(
    config: object,
    setup: object,
    *,
    d8_pointer_path: str | Path,
) -> NetworkDemAgreement | None:
    """Measure, log and journal the DEM/network agreement when a network is declared.

    Runs whether or not burning is enabled: on a project that declares a network
    without burning it, this is the number that says whether burning is needed.
    Returns ``None`` when no network is declared.
    """
    enforce = getattr(config, "enforce_streams", None)
    if enforce is None or getattr(enforce, "stream_geometry_path", None) is None:
        return None

    burned = bool(getattr(enforce, "enabled", False))
    agreement = measure_network_dem_agreement(
        d8_pointer_path=d8_pointer_path,
        watershed_shp=setup.paths.watershed_shp,
        stream_lines=streams_from_config(enforce, setup),
        burned=burned,
    )
    summary_path = Path(setup.paths.geographic_path) / "stream_dem_agreement.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(asdict(agreement), indent=1), encoding="utf-8")

    logger.info(
        "Stream/DEM agreement: %d mapped cells generate a downstream closure of %d "
        "(alpha %.3f, burning %s).",
        agreement.n_network_cells,
        agreement.n_closure_cells,
        agreement.alpha,
        "on" if burned else "off",
    )
    if agreement.alpha < _ALPHA_WARNING_THRESHOLD:
        logger.warning(
            "Stream/DEM agreement is low (alpha %.3f): following D8 from the mapped "
            "network leaves it almost at once, so any length measured along those "
            "paths reports a DEM-versus-map disagreement rather than hydrogeology. %s",
            agreement.alpha,
            (
                "Increase geographic.enforce_streams.depth_m."
                if burned
                else "Enable geographic.enforce_streams."
            ),
        )
    return agreement


def _d8_receivers(codes: np.ndarray) -> np.ndarray:
    """Flat receiver index per cell, ``-1`` at a pit, a nodata code or the raster edge."""
    nrow, ncol = codes.shape
    receivers = np.full(nrow * ncol, -1, dtype=np.int64)
    rows, cols = np.meshgrid(np.arange(nrow), np.arange(ncol), indexing="ij")
    pointer = np.asarray(codes)
    for code, (drow, dcol) in WBT_D8_OFFSETS.items():
        hit = pointer == code
        if not hit.any():
            continue
        target_row = rows[hit] + drow
        target_col = cols[hit] + dcol
        inside = (target_row >= 0) & (target_row < nrow) & (target_col >= 0) & (target_col < ncol)
        source = np.flatnonzero(hit.ravel())
        receivers[source[inside]] = target_row[inside] * ncol + target_col[inside]
    return receivers


def _downstream_closure(receivers: np.ndarray, seeds: np.ndarray) -> np.ndarray:
    """Flat boolean mask of the cells reached by following D8 from ``seeds``."""
    reached = np.zeros(receivers.size, dtype=bool)
    reached[seeds] = True
    frontier = np.asarray(seeds, dtype=np.int64)
    while frontier.size:
        nxt = receivers[frontier]
        nxt = nxt[nxt >= 0]
        nxt = np.unique(nxt[~reached[nxt]])
        reached[nxt] = True
        frontier = nxt
    return reached
