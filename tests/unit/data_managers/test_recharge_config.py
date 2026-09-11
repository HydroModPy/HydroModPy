"""Tests for RechargeSourceConfig validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.data.variables.recharge.config import RechargeSourceConfig


@pytest.mark.fast
class TestRechargeSourceConfigValidation:
    @pytest.mark.parametrize(
        ("source", "match"),
        [
            ("custom", "path"),
            ("synthetic", "values"),
        ],
        ids=["custom_requires_path", "synthetic_requires_values"],
    )
    def test_requires_field(self, source, match):
        with pytest.raises(ValueError, match=match):
            RechargeSourceConfig(source=source)

    def test_custom_with_path_ok(self, tmp_path):
        cfg = RechargeSourceConfig(source="custom", path=tmp_path)
        assert cfg.source == "custom"
        assert cfg.path == tmp_path

    def test_custom_with_source_unit_ok(self, tmp_path):
        cfg = RechargeSourceConfig(source="custom", path=tmp_path, source_unit="m/day")
        assert cfg.source_unit == "m/day"

    def test_sim2_without_path_ok(self):
        cfg = RechargeSourceConfig(source="sim2")
        assert cfg.source == "sim2"
        assert cfg.path is None

    def test_synthetic_with_values_ok(self):
        cfg = RechargeSourceConfig(source="synthetic", values=[1.5, 2.0])
        assert cfg.source == "synthetic"
        assert cfg.values == [1.5, 2.0]

    def test_synthetic_with_amplitude(self):
        """Amplitude and period_days drive the seasonal synthetic recharge signal."""
        cfg = RechargeSourceConfig(
            source="synthetic",
            values=[1.0],
            amplitude=0.5,
            period_days=365,
        )
        assert cfg.amplitude == 0.5
        assert cfg.period_days == 365

    def test_invalid_source_rejected(self):
        with pytest.raises(Exception):
            RechargeSourceConfig(source="unknown_provider")

    def test_literal_sources(self):
        """The allowed sources are exactly custom, sim2, synthetic."""
        # Verify each valid source is accepted (sim2 needs no extras,
        # custom needs path, synthetic needs values).
        RechargeSourceConfig(source="sim2")
        RechargeSourceConfig(source="custom", path=Path("/tmp"))
        RechargeSourceConfig(source="synthetic", values=[1.0])

        # Anything else is rejected
        for bad in ("nasa", "ERA5", ""):
            with pytest.raises(Exception):
                RechargeSourceConfig(source=bad)
