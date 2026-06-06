from __future__ import annotations

from pathlib import Path

from hydromodpy.spatial.site_selection.config import SiteSelectionConfig
from tests.unit.site_selection._records import make_point_record


def make_record(station_id: str, *, x: float = 350000.0, y: float = 6810000.0):
    return make_point_record(station_id, x=x, y=y, n_values=2)


def make_wgs84_hubeau_record(station_id: str):
    return make_point_record(
        station_id,
        x=-1.696842126001275,
        y=48.315146335838115,
        crs="EPSG:4326",
        n_values=2,
        metadata={
            "x_l93": "352000.0",
            "y_l93": "6812000.0",
        },
    )


def make_config(tmp_path: Path) -> SiteSelectionConfig:
    return SiteSelectionConfig.model_validate(
        {
            "selection_id": "observed_demo",
            "output_root": tmp_path / "out",
            "strategy": {
                "principle": "observation_led",
                "profile": "gauged_downstream_station",
                "primary_observation_type": "flow_station",
                "candidate_mode": "station_outlets",
            },
            "territory": {
                "mode": "admin_regions",
                "country": "FR",
                "regions": ["Bretagne"],
            },
            "dem": {
                "source": "custom",
                "path": tmp_path / "dem.tif",
            },
            "outlets": {
                "candidate_mode": "station_outlets",
                "dem_snap_max_distance_m": 150,
            },
        }
    )
