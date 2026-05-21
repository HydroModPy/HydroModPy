"""Pydantic-pint unit parsing on representative configuration fields."""

from __future__ import annotations

import math

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


# ---------------------------------------------------------------------------
# Representative fields converted to pint-backed LengthMeters
# ---------------------------------------------------------------------------


class TestThicknessLength:
    """domain.depth_model.constant_thickness.thickness uses LengthMeters."""

    def test_bare_number_is_metres(self) -> None:
        cfg = ConstantThicknessDepthModel(thickness=200.0)
        assert math.isclose(cfg.thickness, 200.0)

    def test_string_with_metres_unit(self) -> None:
        cfg = ConstantThicknessDepthModel(thickness="200 m")
        assert math.isclose(cfg.thickness, 200.0)

    def test_string_with_kilometre_unit_converts(self) -> None:
        cfg = ConstantThicknessDepthModel(thickness="0.2 km")
        assert math.isclose(cfg.thickness, 200.0)

    def test_string_with_centimetre_unit_converts(self) -> None:
        cfg = ConstantThicknessDepthModel(thickness="20000 cm")
        assert math.isclose(cfg.thickness, 200.0)

    def test_incompatible_unit_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ConstantThicknessDepthModel(thickness="10 kg")

    def test_non_positive_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ConstantThicknessDepthModel(thickness=0.0)


class TestExtinctionDepthLength:
    """modflownwt.process_specific.exdp uses LengthMeters."""

    def test_default_is_one_metre(self) -> None:
        cfg = ModflowProcessSpecificConfig()
        assert math.isclose(cfg.exdp, 1.0)

    def test_inline_centimetres(self) -> None:
        cfg = ModflowProcessSpecificConfig(exdp="50 cm")
        assert math.isclose(cfg.exdp, 0.5)

    def test_incompatible_unit_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ModflowProcessSpecificConfig(exdp="5 hour")


class TestRiverNetworkMinStreamLength:
    """geographic.river_network.min_stream_length_m uses LengthMeters."""

    def test_zero_metres_accepted(self) -> None:
        cfg = RiverNetworkConfig(enabled=False)
        assert math.isclose(cfg.min_stream_length_m, 0.0)

    def test_inline_kilometres(self) -> None:
        cfg = RiverNetworkConfig(enabled=False, min_stream_length_m="0.5 km")
        assert math.isclose(cfg.min_stream_length_m, 500.0)

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RiverNetworkConfig(enabled=False, min_stream_length_m="-1 m")


class TestSyntheticGridLengths:
    """synthetic_geographic.grid.length_x/length_y use LengthMeters."""

    def test_explicit_metres_inputs(self) -> None:
        cfg = SyntheticGridConfig(length_x=100.0, length_y=100.0, nx=10, ny=10)
        assert math.isclose(cfg.length_x, 100.0)
        assert math.isclose(cfg.length_y, 100.0)

    def test_inline_kilometre_conversion(self) -> None:
        cfg = SyntheticGridConfig(length_x="0.5 km", length_y="0.5 km", nx=10, ny=10)
        assert math.isclose(cfg.length_x, 500.0)
        assert math.isclose(cfg.length_y, 500.0)

    def test_incompatible_unit_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SyntheticGridConfig(length_x="5 hour", length_y="1 m", nx=10, ny=1)


class TestOutletSnapDistance:
    """geographic.catch_def.snap_dist uses LengthMeters."""

    def test_bare_number_is_metres(self) -> None:
        cfg = OutletCatchDef(
            catch_def="from_outlet_coord",
            x_outlet=0.0,
            y_outlet=0.0,
            snap_dist=50,
            buff_area=10.0,
        )
        assert math.isclose(cfg.snap_dist, 50.0)

    def test_inline_kilometres(self) -> None:
        cfg = OutletCatchDef(
            catch_def="from_outlet_coord",
            x_outlet=0.0,
            y_outlet=0.0,
            snap_dist="0.05 km",
            buff_area=10.0,
        )
        assert math.isclose(cfg.snap_dist, 50.0)


# ---------------------------------------------------------------------------
# parse_length_to_m has been removed from the public API
# ---------------------------------------------------------------------------


def test_parse_length_to_m_helper_removed() -> None:
    """The legacy parse_length_to_m export is gone."""
    import hydromodpy.core.units as units_pkg

    assert not hasattr(units_pkg, "parse_length_to_m")


# ---------------------------------------------------------------------------
# Stand-alone LengthMeters used directly
# ---------------------------------------------------------------------------


class _DemoLength(BaseModel):
    length: LengthMeters


def test_length_meters_directly_accepts_pint_strings() -> None:
    assert math.isclose(_DemoLength(length="100 m").length, 100.0)
    assert math.isclose(_DemoLength(length="1 km").length, 1000.0)
    assert math.isclose(_DemoLength(length="200 cm").length, 2.0)


def test_length_meters_directly_rejects_dimensional_mismatch() -> None:
    with pytest.raises(ValidationError):
        _DemoLength(length="5 kg")


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


def test_txt_catchdef_cell_size_uses_length_meters() -> None:
    """geographic.catch_def(txt).cell_size uses LengthMeters."""
    cfg = TxtCatchDef(catch_def="txt", cell_size="0.025 km")
    assert math.isclose(cfg.cell_size, 25.0)


def test_radial_island_center_uses_length_meters() -> None:
    cfg = RadialIslandTopography(
        kind="radial_island",
        base_elevation=-1.0,
        crest_elevation=10.0,
        island_radius="500 m",
        center_x="1 km",
        center_y=200,
    )
    assert math.isclose(cfg.island_radius, 500.0)
    assert math.isclose(cfg.center_x, 1000.0)
    assert math.isclose(cfg.center_y, 200.0)
