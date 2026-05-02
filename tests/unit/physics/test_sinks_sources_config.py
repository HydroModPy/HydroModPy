from __future__ import annotations

import pytest

from hydromodpy.physics.base import SinkSource, normalize_sink_source_payload


def test_normalize_sink_source_payload_passes_through_instances() -> None:
    source = SinkSource(id="well", value=1.5, units="m3/s")

    result = normalize_sink_source_payload(source)

    assert result is source


def test_normalize_sink_source_payload_applies_defaults_and_unit_alias() -> None:
    result = normalize_sink_source_payload(
        {"value": 2.0, "unit": "m3/s"},
        default_id="well",
    )

    assert result.id == "well"
    assert result.value == pytest.approx(2.0)
    assert result.units == "m3/s"


def test_normalize_sink_source_payload_reports_location_for_non_mappings() -> None:
    with pytest.raises(TypeError, match="flow.sinks_sources must be a mapping payload"):
        normalize_sink_source_payload(
            3.0,
            location_prefix="flow.sinks_sources",
        )
