"""Tests for the calibrable annotation of the configuration kernel."""

from __future__ import annotations

from hydromodpy.core.config_kit.calibrable import Calibrable


class TestExcludedBy:
    def test_excluded_by_defaults_to_empty(self):
        assert Calibrable(units="m3 s-1").excluded_by == ()

    def test_excluded_by_is_carried_in_the_record(self):
        calibrable = Calibrable(
            units="m", is_the_value_of_its_instance=True, excluded_by=("flow.param.Kv",)
        )
        assert calibrable.to_dict()["excluded_by"] == ["flow.param.Kv"]

    def test_a_default_unit_field_is_not_excluded(self):
        assert Calibrable(units="m", unit_field=None).excluded_by == ()
