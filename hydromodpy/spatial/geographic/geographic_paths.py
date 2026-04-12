"""Path container for geographic processing outputs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GeographicPaths:
    """Canonical set of output paths produced by `Geographic.processing()`."""

    stable_folder: str
    simulations_folder: str
    geographic_path: str
    correcflow_path: str
    watershed: str
    watershed_shp: str
    watershed_contour_shp: str
    watershed_box_shp: str
    box_buff: str
    watershed_box_buff_dem: str
    watershed_box_buff_fill: str
    watershed_box_buff_direc: str
    watershed_buff_dem: str
    watershed_buff_fill: str
    watershed_buff_direc: str
    watershed_dem: str
    watershed_fill: str
    watershed_direc: str
    watershed_contour_tif: str
    river_streams_tif: str
    river_streams_pruned_tif: str
    river_stream_order_strahler_tif: str
    river_stream_link_id_tif: str
    river_network_shp: str
    river_network_summary_json: str


def build_geographic_paths(
    out_dir_path: str | Path,
    *,
    stable_folder: str | Path | None = None,
) -> GeographicPaths:
    """Build all standard path outputs for one geographic run."""
    out_dir = Path(out_dir_path)
    if stable_folder is not None:
        stable = Path(stable_folder)
    else:
        from hydromodpy.core.workspace.path_registry import LEGACY_STABLE_DIR
        stable = out_dir / LEGACY_STABLE_DIR
    geographic_path = stable / "geographic"
    correcflow_path = stable / "demcorrecflow"

    return GeographicPaths(
        stable_folder=str(stable),
        simulations_folder=str(out_dir / ".solver_scratch"),
        geographic_path=str(geographic_path),
        correcflow_path=str(correcflow_path),
        watershed=str(geographic_path / "watershed.tif"),
        watershed_shp=str(geographic_path / "watershed.shp"),
        watershed_contour_shp=str(geographic_path / "watershed_contour.shp"),
        watershed_box_shp=str(geographic_path / "watershed_box.shp"),
        box_buff=str(geographic_path / "watershed_box_buff.shp"),
        watershed_box_buff_dem=str(geographic_path / "watershed_box_buff_dem.tif"),
        watershed_box_buff_fill=str(geographic_path / "watershed_box_buff_fill.tif"),
        watershed_box_buff_direc=str(geographic_path / "watershed_box_buff_direc.tif"),
        watershed_buff_dem=str(geographic_path / "watershed_buff_dem.tif"),
        watershed_buff_fill=str(geographic_path / "watershed_buff_fill.tif"),
        watershed_buff_direc=str(geographic_path / "watershed_buff_direc.tif"),
        watershed_dem=str(geographic_path / "watershed_dem.tif"),
        watershed_fill=str(geographic_path / "watershed_fill.tif"),
        watershed_direc=str(geographic_path / "watershed_direc.tif"),
        watershed_contour_tif=str(geographic_path / "watershed_contour.tif"),
        river_streams_tif=str(geographic_path / "river_streams.tif"),
        river_streams_pruned_tif=str(geographic_path / "river_streams_pruned.tif"),
        river_stream_order_strahler_tif=str(geographic_path / "river_stream_order_strahler.tif"),
        river_stream_link_id_tif=str(geographic_path / "river_stream_link_id.tif"),
        river_network_shp=str(geographic_path / "river_network.shp"),
        river_network_summary_json=str(geographic_path / "river_network_summary.json"),
    )
