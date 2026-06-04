"""Pydantic-pint unit parsing on representative configuration fields."""

from __future__ import annotations

import math
from collections.abc import Callable

import pytest
from pydantic import BaseModel, ValidationError

from hydromodpy.core.units import LengthMeters
from hydromodpy.solver.modflow_nwt.nwt.nwt_config import ModflowProcessSpecificConfig
from hydromodpy.spatial.domain.depth_model_config import ConstantThicknessDepthModel
from hydromodpy.spatial.domain.spatial_support_config import GeneratedRingsSupportConfig
from hydromodpy.spatial.geographic.geographic_config import (
    OutletCatchDef,
    RiverNetworkConfig,
    TxtCatchDef,
)
from hydromodpy.spatial.geographic.synthetic.config import (
    RadialIslandTopography,
    SyntheticGridConfig,
)

pytestmark = pytest.mark.fast


class _DemoLength(BaseModel):
    length: LengthMeters


def _outlet(snap_dist: object) -> OutletCatchDef:
    return OutletCatchDef(
        catch_def="from_outlet_coord",
        x_outlet=0.0,
        y_outlet=0.0,
        snap_dist=snap_dist,
        buff_area=10.0,
    )


# ---------------------------------------------------------------------------
# Parse-success: a builder yields a model and the listed attributes must equal
# the expected metres values. Ids map 1:1 to the former per-field test names.
# ---------------------------------------------------------------------------

PARSE_SUCCESS: list[tuple[str, Callable[[], BaseModel], dict[str, float]]] = [
    (
        "TestThicknessLength::test_bare_number_is_metres",
        lambda: ConstantThicknessDepthModel(thickness=200.0),
        {"thickness": 200.0},
    ),
    (
        "TestThicknessLength::test_string_with_metres_unit",
        lambda: ConstantThicknessDepthModel(thickness="200 m"),
        {"thickness": 200.0},
    ),
    (
        "TestThicknessLength::test_string_with_kilometre_unit_converts",
        lambda: ConstantThicknessDepthModel(thickness="0.2 km"),
        {"thickness": 200.0},
    ),
    (
        "TestThicknessLength::test_string_with_centimetre_unit_converts",
        lambda: ConstantThicknessDepthModel(thickness="20000 cm"),
        {"thickness": 200.0},
    ),
    (
        "TestExtinctionDepthLength::test_default_is_one_metre",
        lambda: ModflowProcessSpecificConfig(),
        {"exdp": 1.0},
    ),
    (
        "TestExtinctionDepthLength::test_inline_centimetres",
        lambda: ModflowProcessSpecificConfig(exdp="50 cm"),
        {"exdp": 0.5},
    ),
    (
        "TestRiverNetworkMinStreamLength::test_zero_metres_accepted",
        lambda: RiverNetworkConfig(enabled=False),
        {"min_stream_length_m": 0.0},
    ),
    (
        "TestRiverNetworkMinStreamLength::test_inline_kilometres",
        lambda: RiverNetworkConfig(enabled=False, min_stream_length_m="0.5 km"),
        {"min_stream_length_m": 500.0},
    ),
    (
        "TestSyntheticGridLengths::test_explicit_metres_inputs",
        lambda: SyntheticGridConfig(length_x=100.0, length_y=100.0, nx=10, ny=10),
        {"length_x": 100.0, "length_y": 100.0},
    ),
    (
        "TestSyntheticGridLengths::test_inline_kilometre_conversion",
        lambda: SyntheticGridConfig(length_x="0.5 km", length_y="0.5 km", nx=10, ny=10),
        {"length_x": 500.0, "length_y": 500.0},
    ),
    (
        "TestOutletSnapDistance::test_bare_number_is_metres",
        lambda: _outlet(50),
        {"snap_dist": 50.0},
    ),
    (
        "TestOutletSnapDistance::test_inline_kilometres",
        lambda: _outlet("0.05 km"),
        {"snap_dist": 50.0},
    ),
    (
        "test_txt_catchdef_cell_size_uses_length_meters",
        lambda: TxtCatchDef(catch_def="txt", cell_size="0.025 km"),
        {"cell_size": 25.0},
    ),
    (
        "test_radial_island_center_uses_length_meters",
        lambda: RadialIslandTopography(
            kind="radial_island",
            base_elevation=-1.0,
            crest_elevation=10.0,
            island_radius="500 m",
            center_x="1 km",
            center_y=200,
        ),
        {"island_radius": 500.0, "center_x": 1000.0, "center_y": 200.0},
    ),
]


@pytest.mark.parametrize(
    ("build", "expected"),
    [pytest.param(build, expected, id=name) for name, build, expected in PARSE_SUCCESS],
)
def test_length_field_parses(build: Callable[[], BaseModel], expected: dict[str, float]) -> None:
    cfg = build()
    for attr, value in expected.items():
        assert math.isclose(getattr(cfg, attr), value)


# ---------------------------------------------------------------------------
# Parse-reject: a builder must raise. Each row keeps its own expected error.
# ---------------------------------------------------------------------------

PARSE_REJECT: list[tuple[str, Callable[[], object], type[Exception]]] = [
    (
        "TestThicknessLength::test_incompatible_unit_rejected",
        lambda: ConstantThicknessDepthModel(thickness="10 kg"),
        ValidationError,
    ),
    (
        "TestThicknessLength::test_non_positive_rejected",
        lambda: ConstantThicknessDepthModel(thickness=0.0),
        ValidationError,
    ),
    (
        "TestExtinctionDepthLength::test_incompatible_unit_rejected",
        lambda: ModflowProcessSpecificConfig(exdp="5 hour"),
        ValidationError,
    ),
    (
        "TestRiverNetworkMinStreamLength::test_negative_rejected",
        lambda: RiverNetworkConfig(enabled=False, min_stream_length_m="-1 m"),
        ValidationError,
    ),
    (
        "TestSyntheticGridLengths::test_incompatible_unit_rejected",
        lambda: SyntheticGridConfig(length_x="5 hour", length_y="1 m", nx=10, ny=1),
        ValidationError,
    ),
    (
        "test_length_meters_directly_rejects_dimensional_mismatch",
        lambda: _DemoLength(length="5 kg"),
        ValidationError,
    ),
]


@pytest.mark.parametrize(
    ("build", "error"),
    [pytest.param(build, error, id=name) for name, build, error in PARSE_REJECT],
)
def test_length_field_rejects(build: Callable[[], object], error: type[Exception]) -> None:
    with pytest.raises(error):
        build()


# ---------------------------------------------------------------------------
# Spot-checks of field wiring kept as stand-alone cases.
# ---------------------------------------------------------------------------


def test_parse_length_to_m_helper_removed() -> None:
    """The legacy parse_length_to_m export is gone."""
    import hydromodpy.core.units as units_pkg

    assert not hasattr(units_pkg, "parse_length_to_m")


def test_length_meters_directly_accepts_pint_strings() -> None:
    assert math.isclose(_DemoLength(length="100 m").length, 100.0)
    assert math.isclose(_DemoLength(length="1 km").length, 1000.0)
    assert math.isclose(_DemoLength(length="200 cm").length, 2.0)


def test_rings_center_uses_length_meters() -> None:
    """domain.supports.generated_rings.center_x/center_y use LengthMeters."""
    cfg = GeneratedRingsSupportConfig(
        kind="generated_rings",
        coordinate_mode="absolute",
        radii=["50 m", "200 m"],
        labels=["inner", "mid", "outer"],
        center_x="1 km",
        center_y=100,
    )
    assert math.isclose(cfg.center_x, 1000.0)
    assert math.isclose(cfg.center_y, 100.0)
    assert cfg.radii == [50.0, 200.0]
