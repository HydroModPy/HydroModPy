"""The regional flow stack: the method a config names and a stack read back from disk."""

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.catchment.algorithms.flow_products import (
    build_regional_flow_products,
    conditioning_method,
    corrected_dem_name,
    flow_products_from_paths,
    rankable_accumulation,
)
from hydromodpy.catchment.preprocess.capped_breach_config import (
    CappedBreachConfig,
    capped_breach_of,
)
from hydromodpy.catchment.terrain.port import CappedBreach
from tests._helpers.geotiffs import write_geotiff
from tests._helpers.terrain_doubles import fake_accumulation

LIMITS = CappedBreach(max_depth_m=1.0, max_distance_m=50.0)


@pytest.mark.parametrize(
    ("method", "limits", "expected"),
    [("fill", None, "fill"), ("breach", None, "breach"), ("capped_breach", LIMITS, LIMITS)],
)
def test_each_correction_names_one_method_of_the_port(method, limits, expected) -> None:
    assert conditioning_method(method, limits) == expected
    assert corrected_dem_name(method).endswith(".tif")


@pytest.mark.parametrize(
    ("method", "limits", "reason"),
    [
        ("carve", None, "Unknown dem_correc_type"),
        ("capped_breach", None, "needs its limits"),
        ("fill", LIMITS, "which has none"),
    ],
)
def test_a_correction_and_limits_that_do_not_go_together_are_refused(method, limits, reason):
    with pytest.raises(ValueError, match=reason):
        conditioning_method(method, limits)
    if method == "carve":
        with pytest.raises(ValueError, match=reason):
            corrected_dem_name(method)


def test_a_capped_breach_without_its_section_takes_the_documented_defaults() -> None:
    defaults = CappedBreachConfig()
    assert capped_breach_of(SimpleNamespace(dem_correc_type="fill")) is None
    assert capped_breach_of(SimpleNamespace(dem_correc_type="capped_breach")) == CappedBreach(
        max_depth_m=float(defaults.max_depth), max_distance_m=float(defaults.max_distance)
    )


def test_a_stack_read_back_from_disk_describes_the_stack_that_was_written(tmp_path) -> None:
    rows, cols = np.mgrid[0:12, 0:12]
    dem = write_geotiff(tmp_path / "dem.tif", (50.0 - rows - 0.5 * cols).astype("float32"))
    written = build_regional_flow_products(
        dem_init_path=dem,
        dem_out_dir_path=tmp_path / "flow",
        dem_correc_type="fill",
        crs_project="EPSG:2154",
        engine_id="numpy_d8",
    )
    read = flow_products_from_paths(dem_out_dir_path=tmp_path / "flow", dem_correc_type="fill")
    assert (read.correc, read.direc, read.acc) == (written.correc, written.direc, written.acc)
    assert read.accumulation.transform == written.accumulation.transform
    assert read.accumulation.directions.conditioned_dem.method == "fill"


def test_an_accumulation_that_can_already_rank_the_window_is_kept(tmp_path) -> None:
    raw = fake_accumulation(transform="none")
    missing = fake_accumulation(acc=tmp_path / "gone.tif")
    small = fake_accumulation(acc=write_geotiff(tmp_path / "acc.tif", np.log(np.ones((3, 3)))))
    for accumulation in (raw, missing, small):
        kept = rankable_accumulation(
            object(), accumulation, [(1.0, 1.0)], snap_distance_m=10.0, out=tmp_path / "x.tif"
        )
        assert kept is accumulation
