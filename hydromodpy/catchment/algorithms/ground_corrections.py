"""The ground: the DEM plus the corrections the project declares, each bounded and logged.

The routing chain (lake carve, conditioning, D8) and the model top both
start from the ground, in both geographic entry points. Without a declared
correction the ground is the raw DEM path itself: no copy, no new file.

``[geographic.crossings]`` is the one correction: the embankments of roads,
railways and bridges lowered, along the channel, to the bed level read on both
sides.

The notch needs a channel to follow, so it runs after a first delineation: the
caller builds the ground without a channel (the raw DEM), delineates, hands the
channel it found back here, and delineates again on the notched ground.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import rasterio

from hydromodpy.catchment.algorithms.crossing_notch import NotchReport, notch_dem
from hydromodpy.catchment.algorithms.ground_inputs import lakes_from_config
from hydromodpy.core.io.raster_io import write_band
from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    import geopandas as gpd

logger = get_logger(__name__)

GROUND_FILENAME = "dem_ground.tif"
"""The ground with the crossings notched, written when ``crossings`` is enabled."""

CROSSINGS_REPORT_FILENAME = "dem_ground_crossings.json"
"""What the notch did, next to the corrected DEM."""

NOTCH_FOOTPRINT_FILENAME = "dem_ground_notch_footprint.tif"
"""The pixels the notch lowered (1) on the grid of the ground, next to it."""

# The channel raster of the first delineation, on the full DEM grid. Named in
# ``river_network.build_river_network_products``, which writes them; the
# products object only carries the clipped copies.
_STREAMS_FULL_NAME = "dem_streams_full.tif"
_STREAMS_PRUNED_FULL_NAME = "dem_streams_pruned_full.tif"


@dataclass(frozen=True)
class FirstPassChannel:
    """What the first delineation says about the channel, read by the notch."""

    streams_tif: str
    d8_tif: str
    acc_tif: str
    network_shp: str | None
    catchment_area_km2: float


def notch_enabled(config: object) -> bool:
    """Whether ``[geographic.crossings]`` is on."""
    return bool(getattr(getattr(config, "crossings", None), "enabled", False))


def ground_dem_path_from_config(config: object, setup: object) -> str:
    """Return the path of the final ground without building anything.

    The cache branch needs it and must not redo a correction. It is the raw DEM
    when nothing is declared, the notched file when the notch is on.
    """
    correcflow = Path(setup.paths.correcflow_path)
    if notch_enabled(config):
        return str(correcflow / GROUND_FILENAME)
    return str(setup.dem_path)


def ground_dem_from_config(
    config: object,
    setup: object,
    *,
    channel: FirstPassChannel | None = None,
) -> Path:
    """Build the ground and return its path.

    Without ``channel`` the ground is the raw DEM path. With the channel of a first delineation and the notch
    enabled, the crossings are notched into it and the report is written.
    """
    base = str(setup.dem_path)
    if channel is None or not notch_enabled(config):
        return Path(base)
    return _notched(config, setup, base=base, channel=channel)


def first_pass_channel(
    config: object,
    setup: object,
    *,
    flow: object,
    river_products: object,
    catchment_area_km2: float,
) -> FirstPassChannel:
    """Gather what the notch reads from the first delineation."""
    full_name = (
        _STREAMS_PRUNED_FULL_NAME
        if bool(config.river_network.prune_short_streams)
        else _STREAMS_FULL_NAME
    )
    return FirstPassChannel(
        streams_tif=str(Path(setup.paths.correcflow_path) / full_name),
        d8_tif=str(flow.direc),
        acc_tif=str(flow.acc),
        network_shp=getattr(river_products, "hydrographic_network_generated_shp", None),
        catchment_area_km2=float(catchment_area_km2),
    )


def notch_report_path(setup: object) -> Path:
    """Where the JSON report of the notch is written."""
    return Path(setup.paths.correcflow_path) / CROSSINGS_REPORT_FILENAME


def notch_footprint_path(setup: object) -> Path:
    """Where the mask of the pixels the notch lowered is written."""
    return Path(setup.paths.correcflow_path) / NOTCH_FOOTPRINT_FILENAME


def notch_lowered_pixels(setup: object) -> int:
    """How many pixels the last notch lowered, 0 when it did not run."""
    path = notch_report_path(setup)
    if not path.exists():
        return 0
    return int(json.loads(path.read_text(encoding="utf-8"))["pixels_lowered"])


def close_notch_report(setup: object, *, catchment_area_km2_after: float) -> NotchReport:
    """Add the catchment area after the second delineation, log the line, rewrite the JSON."""
    path = notch_report_path(setup)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["catchment_area_km2_after"] = float(catchment_area_km2_after)
    report = NotchReport(
        **{key: value for key, value in document.items() if key in NotchReport.__dataclass_fields__}
    )
    path.write_text(json.dumps(document, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    logger.info(report.info_line())
    return report


def _notched(
    config: object,
    setup: object,
    *,
    base: str,
    channel: FirstPassChannel,
) -> Path:
    """Notch the crossings into *base*, write the ground and its report."""
    notch = config.crossings
    path, crossings = _read_crossings(notch, setup)
    lakes = (
        lakes_from_config(config.enforce_lakes, setup)
        if bool(getattr(getattr(config, "enforce_lakes", None), "enabled", False))
        else []
    )
    network = _first_pass_network(channel)

    with rasterio.open(base) as src:
        dem = src.read(1).astype("float32")
        profile = src.profile.copy()
        transform = src.transform
        nodata = src.nodata
    streams = _read_int(channel.streams_tif) > 0
    d8 = _read_int(channel.d8_tif)
    with rasterio.open(channel.acc_tif) as src:
        acc = np.nan_to_num(src.read(1), nan=0.0)

    report = NotchReport(
        parameters={
            "kinds": list(notch.kinds),
            "notch_width_m": float(notch.notch_width),
            "bed_reach_m": float(notch.bed_reach),
            "max_depth_m": float(notch.max_depth),
            "snap_radius_m": float(notch.snap_radius),
            "path": str(path),
        },
        catchment_area_km2_before=channel.catchment_area_km2,
    )
    notched_dem, footprint = notch_dem(
        dem,
        nodata=nodata,
        transform=transform,
        streams=streams,
        d8=d8,
        acc=acc,
        crossings=crossings,
        network=network,
        kinds=list(notch.kinds),
        notch_width_m=float(notch.notch_width),
        bed_reach_m=float(notch.bed_reach),
        max_depth_m=float(notch.max_depth),
        snap_radius_m=float(notch.snap_radius),
        report=report,
        lakes=lakes,
    )
    return _write_ground(setup, notched_dem, footprint, profile=profile, report=report)


def _read_crossings(notch: object, setup: object) -> tuple[Path, gpd.GeoDataFrame]:
    """Read the crossings file of *notch*, in the project CRS when the setup names one."""
    import geopandas as gpd

    if notch.path is None:
        raise ValueError(
            "geographic.crossings is enabled without a path, and no "
            "[[data.crossings.sources]] filled one in. Set geographic.crossings.path, or "
            "declare a crossings source."
        )
    path = Path(notch.path)
    if not path.exists():
        raise FileNotFoundError(f"geographic.crossings.path points to nothing: {path}")
    crossings = gpd.read_file(path)
    if crossings.crs is None:
        raise ValueError(
            f"geographic.crossings.path {path} carries no CRS, so its geometries cannot "
            "be placed on the DEM. Save it with a CRS."
        )
    crs_project = getattr(setup, "crs_project", None)
    if crs_project is not None:
        crossings = crossings.to_crs(crs_project)
    return path, crossings


def _first_pass_network(channel: FirstPassChannel) -> gpd.GeoDataFrame | None:
    """The channel vector of the first delineation, ``None`` when none was written."""
    import geopandas as gpd

    shp = channel.network_shp
    return gpd.read_file(shp) if shp is not None and Path(shp).exists() else None


def _write_ground(
    setup: object,
    notched_dem: np.ndarray,
    footprint: np.ndarray,
    *,
    profile: dict,
    report: NotchReport,
) -> Path:
    """Write the notched ground, its footprint and the JSON report, return the ground path."""
    out_path = Path(setup.paths.correcflow_path) / GROUND_FILENAME
    profile.pop("blockxsize", None)
    profile.pop("blockysize", None)
    profile.update(compress="lzw", tiled=False)
    write_band(out_path, notched_dem.astype("float32"), profile, dtype="float32")
    write_band(
        notch_footprint_path(setup), footprint.astype("uint8"), profile, dtype="uint8", nodata=None
    )
    notch_report_path(setup).write_text(
        json.dumps(report.to_document(), indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    return out_path


def _read_int(path: str) -> np.ndarray:
    with rasterio.open(path) as src:
        return np.nan_to_num(src.read(1), nan=0.0).astype(int)
