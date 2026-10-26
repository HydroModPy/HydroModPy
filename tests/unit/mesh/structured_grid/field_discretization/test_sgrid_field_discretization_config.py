"""Unit tests for FlowRechargeConfig fields tied to field discretization.

Covers: heterogeneous_source acceptance, spatial_mode, interpolation_method.
"""

from __future__ import annotations

import pytest

from hydromodpy.data.contracts.load_result import LoadResult

from ._test_sgrid_field_discretization_builders import _make_static_field_record

pytestmark = pytest.mark.fast


# ---------------------------------------------------------------------------
# 9. Integration: NWT adapter heterogeneous path
# ---------------------------------------------------------------------------


class TestFlowRechargeConfigHeterogeneousSource:
    def test_heterogeneous_source_field_accepted(self):
        """FlowRechargeConfig should accept and expose heterogeneous_source."""
        from hydromodpy.physics.flow.sinks_sources import FlowRechargeConfig

        lr = LoadResult(
            fields=[_make_static_field_record(2, 2, value=5.0)],
        )
        cfg = FlowRechargeConfig(
            values=0.0,
            heterogeneous_source=lr,
            first_clim="mean",
            units="m/s",
        )

        assert cfg.heterogeneous_source is lr
        assert cfg.heterogeneous_source.has_fields is True

    def test_heterogeneous_source_none_by_default(self):
        from hydromodpy.physics.flow.sinks_sources import FlowRechargeConfig

        cfg = FlowRechargeConfig(values=1.0e-8)
        assert cfg.heterogeneous_source is None


# ---------------------------------------------------------------------------
# 14. FlowRechargeConfig new fields
# ---------------------------------------------------------------------------


class TestFlowRechargeConfigNewFields:
    def test_spatial_mode_default(self):
        from hydromodpy.physics.flow.sinks_sources import FlowRechargeConfig

        cfg = FlowRechargeConfig(values=0.0)
        assert cfg.spatial_mode == "auto"

    def test_spatial_mode_homogeneous(self):
        from hydromodpy.physics.flow.sinks_sources import FlowRechargeConfig

        cfg = FlowRechargeConfig(values=0.0, spatial_mode="homogeneous")
        assert cfg.spatial_mode == "homogeneous"

    def test_spatial_mode_invalid_raises(self):
        from hydromodpy.physics.flow.sinks_sources import FlowRechargeConfig

        with pytest.raises(Exception):
            FlowRechargeConfig(values=0.0, spatial_mode="invalid")

    def test_interpolation_method_default(self):
        from hydromodpy.physics.flow.sinks_sources import FlowRechargeConfig

        cfg = FlowRechargeConfig(values=0.0)
        assert cfg.interpolation_method == "nearest"

    def test_interpolation_method_idw(self):
        from hydromodpy.physics.flow.sinks_sources import FlowRechargeConfig

        cfg = FlowRechargeConfig(values=0.0, interpolation_method="idw")
        assert cfg.interpolation_method == "idw"

    def test_interpolation_method_invalid_raises(self):
        from hydromodpy.physics.flow.sinks_sources import FlowRechargeConfig

        with pytest.raises(Exception):
            FlowRechargeConfig(values=0.0, interpolation_method="cubic")
