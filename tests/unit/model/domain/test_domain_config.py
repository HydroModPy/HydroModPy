"""``[domain]``: the zone ids, the named supports, the depth model and the layering."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.model.domain.domain_config import DomainConfig

BANDS = {"kind": "generated_bands", "axis": "x", "breaks": [0.5], "labels": ["left", "right"]}
RINGS = {"kind": "generated_rings", "radii": [0.4, 0.7], "labels": ["inner", "middle", "outer"]}


def test_the_default_domain_is_a_constant_thickness_of_50_m_without_zones():
    cfg = DomainConfig()

    assert (cfg.depth_model.kind, float(cfg.depth_model.thickness)) == ("constant_thickness", 50.0)
    assert (cfg.supports, cfg.zone_ids) == ({}, [])
    assert DomainConfig(zone_ids=["geology", "lithofacies", "geology"]).zone_ids == ["geology", "lithofacies"]  # fmt: skip


def test_every_support_kind_is_accepted_side_by_side():
    supports = {"field_geology": {"kind": "geology"}, "halves": BANDS, "rings": RINGS, "zones": {"kind": "catchment_zones"}}  # fmt: skip

    cfg = DomainConfig.model_validate({"supports": supports})

    assert {key: s.kind for key, s in cfg.supports.items()} == {key: s["kind"] for key, s in supports.items()}  # fmt: skip


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ({"supports": {"field_geology": {"provider": "geology"}}}, None),
        ({"depth_model": {"type": "constant_thickness", "thickness": "30 m"}}, None),
        ({"support_mode": "zones"}, None),
        ({"zone_ids": ["Geology"]}, None),
        ({"supports": {"Halves": BANDS}}, None),
        ({"depth_model": {"kind": "raster_substratum", "scale": 2.0}}, "scale"),
        ({"depth_model": {"kind": "constant_thickness", "thickness": -5.0}}, "thickness"),
        ({"depth_model": {"kind": "bedrock_map"}}, "kind"),
    ],
    ids=["provider_key", "type_key", "support_mode", "upper_case_zone_id", "upper_case_support_id",
         "scale_beside_an_elevation_raster", "negative_thickness", "unknown_depth_model_kind"],
)  # fmt: skip
def test_a_retired_key_a_non_snake_case_id_or_a_depth_model_its_kind_does_not_read_is_refused(payload, match):  # fmt: skip
    with pytest.raises(ValidationError, match=match):
        DomainConfig.model_validate(payload)
