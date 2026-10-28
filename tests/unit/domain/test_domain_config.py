"""``[domain]``: the zone ids, the named supports, the depth model and the layering."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.spatial.domain.domain_config import DomainConfig

BANDS = {"kind": "generated_bands", "axis": "x", "breaks": [0.5], "labels": ["left", "right"]}
RINGS = {"kind": "generated_rings", "radii": [0.4, 0.7], "labels": ["inner", "middle", "outer"]}


def test_the_default_domain_is_a_constant_thickness_of_50_m_without_zones():
    cfg = DomainConfig()

    assert cfg.depth_model.kind == "constant_thickness"
    assert float(cfg.depth_model.thickness) == 50.0
    assert cfg.supports == {}
    assert cfg.zone_ids == []


def test_every_support_kind_is_accepted_side_by_side():
    supports = {"field_geology": {"kind": "geology"}, "halves": BANDS, "rings": RINGS, "zones": {"kind": "catchment_zones"}}  # fmt: skip

    cfg = DomainConfig.model_validate({"supports": supports})

    assert {key: support.kind for key, support in cfg.supports.items()} == {
        key: support["kind"] for key, support in supports.items()
    }


def test_a_zone_id_written_twice_is_kept_once():
    assert DomainConfig(zone_ids=["geology", "lithofacies", "geology"]).zone_ids == [
        "geology",
        "lithofacies",
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"supports": {"field_geology": {"provider": "geology"}}},
        {"depth_model": {"type": "constant_thickness", "thickness": "30 m"}},
        {"support_mode": "zones"},
        {"zone_ids": ["Geology"]},
        {"supports": {"Halves": BANDS}},
    ],
    ids=["provider_key", "type_key", "support_mode", "upper_case_zone_id", "upper_case_support_id"],
)
def test_a_retired_key_or_a_non_snake_case_id_is_refused(payload):
    with pytest.raises(ValidationError):
        DomainConfig.model_validate(payload)
