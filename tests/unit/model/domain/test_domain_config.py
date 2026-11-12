"""``[domain]``: the zone ids, the named supports, the depth model and the layering."""

from __future__ import annotations

from hydromodpy.model.domain.domain_config import DomainConfig


def test_the_default_domain_is_a_constant_thickness_of_50_m_without_zones():
    cfg = DomainConfig()

    assert (cfg.depth_model.kind, float(cfg.depth_model.thickness)) == ("constant_thickness", 50.0)
    assert (cfg.supports, cfg.zone_ids) == ({}, [])
    assert DomainConfig(zone_ids=["geology", "lithofacies", "geology"]).zone_ids == ["geology", "lithofacies"]  # fmt: skip
