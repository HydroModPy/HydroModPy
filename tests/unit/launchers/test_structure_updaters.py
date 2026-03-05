"""Unit tests for structural binders applied after data loading."""

from types import SimpleNamespace

from hydromodpy.domain.structure_binders import apply_geology_to_domain
from hydromodpy.process.flow.structure_binders import apply_oceanic_to_flow


class _DummyDomain:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def set_zone(self, zone_id: str, zone_obj: object) -> None:
        self.calls.append((zone_id, zone_obj))


def test_apply_geology_to_domain_sets_declared_zone() -> None:
    domain = _DummyDomain()
    geology = object()

    apply_geology_to_domain(domain=domain, geology=geology)

    assert domain.calls == [("geology", geology)]


def test_apply_geology_to_domain_is_noop_without_geology() -> None:
    domain = _DummyDomain()

    apply_geology_to_domain(domain=domain, geology=None)

    assert domain.calls == []


def test_apply_oceanic_to_flow_updates_ocean_boundary_value() -> None:
    flow = SimpleNamespace(boundary_conditions={"ocean": SimpleNamespace(value=None)})
    oceanic = SimpleNamespace(MSL=7.5)

    apply_oceanic_to_flow(flow=flow, oceanic=oceanic)

    assert flow.boundary_conditions["ocean"].value == 7.5


def test_apply_oceanic_to_flow_is_noop_without_ocean_boundary() -> None:
    flow = SimpleNamespace(boundary_conditions={})
    oceanic = SimpleNamespace(MSL=3.0)

    apply_oceanic_to_flow(flow=flow, oceanic=oceanic)

    assert flow.boundary_conditions == {}
