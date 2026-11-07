"""The zone codes a domain gets from the geographic outputs, and why it gets none."""

from types import SimpleNamespace

import numpy as np
import pytest
from shapely.geometry import box

from hydromodpy.model.domain.structure_binders import (
    apply_catchment_zones_to_domain,
    apply_geology_to_domain,
    build_catchment_zone_field_from_geographic,
)
from hydromodpy.spatial.geographic.core.catchment_zones import CatchmentZoneCode
from tests._helpers.geographic_cases import write_features
from tests._helpers.geotiffs import write_geotiff


class _Domain:
    def __init__(self) -> None:
        self.zones: dict[str, object] = {}
        self.set_zone = self.zones.__setitem__


def _outputs(tmp_path, **missing) -> SimpleNamespace:
    """The polygons and the box DEM of a 10 x 10 domain around a 4 x 4 catchment."""
    folder = tmp_path / "geographic"
    files = {
        "watershed_shp": write_features(folder / "watershed.shp", [box(3, 3, 7, 7)]),
        "watershed_buff": write_features(folder / "watershed_buff.shp", [box(2, 2, 8, 8)]),
        "box_buff": write_features(folder / "watershed_box_buff.shp", [box(0, 0, 10, 10)]),
        "watershed_box_buff_dem": write_geotiff(folder / "box.tif", np.ones((10, 10))),
    }
    for name, how in missing.items():
        if how == "unset":
            files[name] = None
        else:
            for sidecar in files[name].parent.glob(f"{files[name].stem}.*"):
                sidecar.unlink()
    files.pop("watershed_buff")
    return SimpleNamespace(**{k: None if v is None else str(v) for k, v in files.items()})


@pytest.mark.parametrize(
    ("missing", "note"),
    [
        ({"watershed_shp": "unset"}, "watershed shapefile path is missing"),
        ({"watershed_box_buff_dem": "unset"}, "reference raster path is missing"),
        ({"watershed_box_buff_dem": "deleted"}, "reference raster not found"),
        ({"box_buff": "unset"}, "buffered domain shapefile path is missing"),
        ({"watershed_shp": "deleted"}, "catchment shapefile not found"),
        ({"watershed_buff": "deleted"}, "buffered catchment shapefile not found"),
        ({"box_buff": "deleted"}, "buffered domain shapefile not found"),
    ],
)
def test_a_missing_output_leaves_the_domain_without_zones_and_says_which(
    tmp_path, missing, note
) -> None:
    geographic = _outputs(tmp_path, **missing)
    domain = _Domain()
    field, codes, said = build_catchment_zone_field_from_geographic(geographic=geographic)
    apply_catchment_zones_to_domain(domain=domain, geographic=geographic)
    assert (field, codes) == (None, None)
    assert said.startswith(note)
    assert domain.zones == {}


def test_the_zones_nest_the_core_in_the_buffer_ring_in_the_domain(tmp_path) -> None:
    domain = _Domain()
    apply_catchment_zones_to_domain(domain=domain, geographic=_outputs(tmp_path))
    codes = np.asarray(domain.zones["catchment"].encoded_codes)
    zones = ("CATCHMENT_CORE", "BUFFER_RING", "DOMAIN_OUTSIDE_BUFFER")
    counts = [np.count_nonzero(codes == int(CatchmentZoneCode[zone])) for zone in zones]
    assert min(counts) > 0
    assert sum(counts) == codes.size


def test_a_uniform_domain_is_one_zone_and_a_missing_payload_is_said(tmp_path) -> None:
    geographic = _outputs(tmp_path)
    geographic.zone_kind = "uniform"
    field, codes, note = build_catchment_zone_field_from_geographic(geographic=geographic)
    assert note is None
    assert set(np.unique(field.encoded_codes).tolist()) == {int(CatchmentZoneCode.UNIFORM)}
    assert field.encoded_to_zone == {int(CatchmentZoneCode.UNIFORM): "uniform"}
    _, _, missing = build_catchment_zone_field_from_geographic(geographic=None)
    assert missing == "geographic payload is missing"


def test_a_domain_without_zones_or_without_geology_is_left_alone(tmp_path) -> None:
    apply_catchment_zones_to_domain(domain=object(), geographic=_outputs(tmp_path))
    domain = _Domain()
    apply_geology_to_domain(domain=domain, geology=None)
    apply_geology_to_domain(domain=domain, geology="field", zone_id="rock")
    assert domain.zones == {"rock": "field"}
