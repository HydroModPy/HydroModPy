"""The regional flow stack: the method a config names and a stack read back from disk."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.catchment.algorithms.flow_products import (
    TerrainRequest,
    build_regional_flow_products,
    conditioning_method,
    corrected_dem_name,
    rankable_accumulation,
)
from hydromodpy.catchment.preprocess.capped_breach_config import (
    CappedBreachConfig,
    capped_breach_of,
)
from hydromodpy.catchment.terrain.port import CappedBreach
from hydromodpy.catchment.terrain.undrained import UndrainedCells
from tests._helpers.geotiffs import write_geotiff
from tests._helpers.terrain_doubles import fake_accumulation, fake_flow_products

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


def test_an_accumulation_that_can_already_rank_the_window_is_kept(tmp_path) -> None:
    raw = fake_accumulation(transform="none")
    missing = fake_accumulation(acc=tmp_path / "gone.tif")
    small = fake_accumulation(acc=write_geotiff(tmp_path / "acc.tif", np.log(np.ones((3, 3)))))
    for accumulation in (raw, missing, small):
        kept = rankable_accumulation(
            object(), accumulation, [(1.0, 1.0)], snap_distance_m=10.0, out=tmp_path / "x.tif"
        )
        assert kept is accumulation


def _terrain_request(**overrides) -> TerrainRequest:
    facts = {
        "dem": Path("dem.tif"),
        "dem_sha256": "a" * 64,
        "state": "raw",
        "method": "fill",
        "capped_breach": None,
        "crs_project": "EPSG:2154",
        "engine": {"engine_id": "whitebox_workflows", "engine_version": "1.0"},
        "notched": False,
        "out_dir": Path("out"),
    }
    facts.update(overrides)
    return TerrainRequest(**facts)


def test_a_terrain_request_names_every_key_fact() -> None:
    processing = _terrain_request().processing()

    assert processing["state"] == "raw"
    assert processing["method"] == "fill"
    assert processing["crs_project"] == "EPSG:2154"
    assert processing["accumulation"] == {"units": "cells", "transform": "ln"}
    assert processing["pointer_convention"] == "d8_wbt"
    assert "capped_breach" not in processing


def test_a_capped_breach_enters_the_request_processing() -> None:
    processing = _terrain_request(method="capped_breach", capped_breach=LIMITS).processing()

    assert processing["capped_breach"] == {"max_depth_m": 1.0, "max_distance_m": 50.0}


def test_a_provided_dem_is_routed_without_a_conditioning_pass(tmp_path) -> None:
    rows, cols = np.mgrid[0:12, 0:12]
    dem = write_geotiff(tmp_path / "dem.tif", (50.0 - rows - 0.5 * cols).astype("float32"))

    products = build_regional_flow_products(
        dem_path=dem,
        dem_out_dir_path=tmp_path / "flow",
        dem_correc_type="provided",
        crs_project="EPSG:2154",
        engine_id="numpy_d8",
    )

    assert Path(products.correc) == Path(dem)
    assert products.accumulation.directions.conditioned_dem.method == "provided"
    assert isinstance(products.undrained, UndrainedCells)


def test_flow_products_leave_the_undrained_count_to_none_until_it_is_measured() -> None:
    products = fake_flow_products()
    assert products.undrained is None
