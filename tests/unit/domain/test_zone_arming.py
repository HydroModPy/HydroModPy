"""Arm the zone ids the runtime binders write, so a project need not declare them."""

from __future__ import annotations

import pytest

from hydromodpy.spatial.domain.domain import Domain
from hydromodpy.spatial.domain.domain_config import DomainConfig
from hydromodpy.spatial.domain.zone_arming import arm_runtime_zone_ids


def _domain(config: DomainConfig) -> Domain:
    domain = object.__new__(Domain)
    domain.config = config
    domain.zones = {}
    return domain


def test_the_binder_zone_ids_are_armed_on_an_empty_config():
    cfg = DomainConfig()

    arm_runtime_zone_ids(cfg)

    assert cfg.zone_ids == ["catchment", "geology"]


def test_geology_attaches_without_the_project_declaring_it():
    """The reason domain.zone_ids = ['geology'] used to be mandatory."""
    cfg = DomainConfig()
    arm_runtime_zone_ids(cfg)

    _domain(cfg).set_zone("geology", object())


def test_requested_support_ids_are_armed_too():
    cfg = DomainConfig()

    arm_runtime_zone_ids(cfg, ("field_geology",))

    assert cfg.zone_ids == ["catchment", "geology", "field_geology"]
    _domain(cfg).set_zone("field_geology", object())


def test_a_project_zonation_survives_and_stays_first():
    cfg = DomainConfig(zone_ids=["lithofacies"])

    arm_runtime_zone_ids(cfg)

    assert cfg.zone_ids == ["lithofacies", "catchment", "geology"]


def test_arming_twice_adds_nothing():
    cfg = DomainConfig(zone_ids=["geology"])

    arm_runtime_zone_ids(cfg, ("field_geology",))
    arm_runtime_zone_ids(cfg, ("field_geology",))

    assert cfg.zone_ids == ["geology", "catchment", "field_geology"]


def test_the_guard_still_refuses_an_undeclared_zone():
    cfg = DomainConfig()
    arm_runtime_zone_ids(cfg)

    with pytest.raises(ValueError, match="is not declared in domain.zone_ids"):
        _domain(cfg).set_zone("typo_zone", object())
