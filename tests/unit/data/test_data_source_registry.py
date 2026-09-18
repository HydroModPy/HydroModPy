"""What the data-source registry resolves, and what it refuses.

The exit gate of the phase is that a third-party source registers without a
patch to HydroModPy, so the foreign source below is built the way a foreign one
really arrives: a class defined outside the package, reached through a stub
entry point in the ``hydromodpy.data.source`` group, never imported by name.
"""

from __future__ import annotations

from importlib.metadata import EntryPoint
from typing import ClassVar

import pytest

from hydromodpy.core.exceptions import DataRequestError
from hydromodpy.data.source import registry
from hydromodpy.data.source.port import (
    CLASS_SOURCE_MEMBERS,
    INSTANCE_SOURCE_MEMBERS,
    SOURCE_MEMBERS,
    FetchRequest,
    FetchResult,
    PayloadKind,
    PeriodNeed,
    Selector,
    extent_for,
    missing_class_members,
)


class AcmeRadarSource:
    """A source a third party ships, conforming and known to no in-tree module."""

    source_id: ClassVar[str] = "acme-radar"
    payload_kind: ClassVar[PayloadKind] = "fields"
    extent_crs: ClassVar[str] = "EPSG:3035"
    selectors: ClassVar[tuple[Selector, ...]] = ("extent",)
    period_need: ClassVar[PeriodNeed] = "required"
    hosts: ClassVar[tuple[str, ...]] = ("radar.acme.example",)
    writes_out_dir: ClassVar[bool] = False

    def __init__(self) -> None:
        self.variables: tuple[str, ...] = ("radar_rainfall",)

    def fetch(self, request: FetchRequest) -> FetchResult:
        return FetchResult(
            source_id=self.source_id,
            kind=self.payload_kind,
            variables=self.variables,
            extent=extent_for(self, request),
        )


class MisnamedSource(AcmeRadarSource):
    """Declares one id while its entry point is published under another."""

    source_id: ClassVar[str] = "acme-radar"


class HalfSource:
    """Carries an id and nothing else the port asks of a class."""

    source_id: ClassVar[str] = "acme-half"


class IdlessSource:
    """Every class member but the one a registry is keyed on."""

    payload_kind: ClassVar[PayloadKind] = "points"
    extent_crs: ClassVar[str] = "EPSG:4326"
    selectors: ClassVar[tuple[Selector, ...]] = ("extent",)
    period_need: ClassVar[PeriodNeed] = "refused"
    hosts: ClassVar[tuple[str, ...]] = ()
    writes_out_dir: ClassVar[bool] = False

    def fetch(self, request: FetchRequest) -> FetchResult:  # pragma: no cover - never reached
        raise AssertionError("a class with no source_id must not be registrable")


@pytest.fixture
def isolated_registry(monkeypatch: pytest.MonkeyPatch):
    """Give one test its own registry state, restored afterwards."""
    monkeypatch.setattr(registry, "_REGISTRY", dict(registry._REGISTRY))
    monkeypatch.setattr(registry, "_BUILTIN_PATHS", dict(registry._BUILTIN_PATHS))
    monkeypatch.setattr(registry, "_PLUGINS_LOADED", False)
    return registry


def _entry_points_returning(*points: EntryPoint):
    def fake_entry_points(*, group: str):
        assert group == registry.ENTRY_POINT_GROUP
        return tuple(points)

    return fake_entry_points


def _stub_entry_point(name: str, target: type) -> EntryPoint:
    """An entry point that loads *target* without a distribution on disk."""
    point = EntryPoint(name=name, value="tests.stub:Source", group=registry.ENTRY_POINT_GROUP)
    object.__setattr__(point, "load", lambda: target)
    return point


# --------------------------------------------------------------------------- #
# What this build declares
# --------------------------------------------------------------------------- #


def test_the_two_member_sets_partition_the_port() -> None:
    """A member in neither set would be asked of nobody."""
    assert set(CLASS_SOURCE_MEMBERS) | set(INSTANCE_SOURCE_MEMBERS) == set(SOURCE_MEMBERS)
    assert not set(CLASS_SOURCE_MEMBERS) & set(INSTANCE_SOURCE_MEMBERS)
    assert INSTANCE_SOURCE_MEMBERS == ("variables",)


def test_every_builtin_id_resolves_to_a_class_the_port_accepts() -> None:
    ids = registry.builtin_source_ids()
    assert ids, "a registry with no built-in serves nobody"
    for source_id in ids:
        source_cls = registry.get(source_id)
        assert source_cls.source_id == source_id
        assert missing_class_members(source_cls) == ()


def test_a_builtin_is_not_imported_until_it_is_asked_for(
    isolated_registry: object,
) -> None:
    """The declaration is a dotted path, so declaring costs no import."""
    import sys

    module = "hydromodpy.data.source.ign_dem"
    for name in [key for key in sys.modules if key == module]:
        del sys.modules[name]
    registry._REGISTRY.pop("ign-bdalti", None)

    registry.get("bdtopage")
    assert module not in sys.modules

    registry.get("ign-bdalti")
    assert module in sys.modules


def test_the_described_set_and_the_resolvable_set_are_different_questions(
    isolated_registry: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plugin is resolvable and not describable, and the two answers say so."""
    monkeypatch.setattr(
        registry,
        "entry_points",
        _entry_points_returning(_stub_entry_point("acme-radar", AcmeRadarSource)),
    )
    assert "acme-radar" in registry.list_source_ids()
    assert "acme-radar" not in registry.builtin_source_ids()


# --------------------------------------------------------------------------- #
# A third party registers, in process and through the group
# --------------------------------------------------------------------------- #


def test_a_foreign_source_is_reached_through_the_entry_point_group(
    isolated_registry: object,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """The exit gate: registered, resolved and served, with no in-tree edit."""
    monkeypatch.setattr(
        registry,
        "entry_points",
        _entry_points_returning(_stub_entry_point("acme-radar", AcmeRadarSource)),
    )

    assert registry.load_plugins() == 1
    resolved = registry.get("acme-radar")
    assert resolved is AcmeRadarSource
    assert registry.is_registered("acme-radar")

    from hydromodpy.data.source.port import Extent

    result = resolved().fetch(
        FetchRequest(
            out_dir=tmp_path,
            extent=Extent(xmin=-1.9, ymin=48.0, xmax=-1.5, ymax=48.3, crs="EPSG:4326"),
            period=None,
        )
    )
    assert result.source_id == "acme-radar"
    assert result.extent is not None
    assert result.extent.crs == "EPSG:3035", "the port converted into what the source declares"


def test_register_returns_the_class_so_it_can_decorate(isolated_registry: object) -> None:
    assert registry.register(AcmeRadarSource) is AcmeRadarSource


def test_a_second_registration_of_one_id_is_refused_unless_it_replaces(
    isolated_registry: object,
) -> None:
    registry.register(AcmeRadarSource)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(AcmeRadarSource)
    assert registry.register(AcmeRadarSource, replace=True) is AcmeRadarSource


def test_substituting_the_class_behind_an_id_substitutes_what_a_caller_gets(
    isolated_registry: object,
) -> None:
    """G1 in one assertion: the id is the seam, the implementation is not."""

    class Substitute(AcmeRadarSource):
        source_id: ClassVar[str] = "bdtopage"

    registry.register(Substitute, replace=True)
    assert registry.get("bdtopage") is Substitute


# --------------------------------------------------------------------------- #
# What is refused
# --------------------------------------------------------------------------- #


def test_a_class_missing_a_port_member_is_refused_by_name(isolated_registry: object) -> None:
    with pytest.raises(TypeError, match="payload_kind"):
        registry.register(HalfSource)
    assert "acme-half" not in registry._REGISTRY


def test_a_class_declaring_no_id_is_refused(isolated_registry: object) -> None:
    with pytest.raises(TypeError, match="source_id"):
        registry.register(IdlessSource)


def test_variables_alone_does_not_make_a_class_unregistrable(isolated_registry: object) -> None:
    """``variables`` is the instance's, so demanding it here would refuse everyone."""
    assert not hasattr(AcmeRadarSource, "variables")
    registry.register(AcmeRadarSource)


def test_an_unknown_id_is_a_request_fault_that_names_what_is_served() -> None:
    with pytest.raises(DataRequestError) as excinfo:
        registry.get("no-such-source")
    message = str(excinfo.value)
    assert "no-such-source" in message
    assert "bdtopage" in message
    assert registry.ENTRY_POINT_GROUP in message


def test_a_plugin_name_that_contradicts_the_class_is_refused(
    isolated_registry: object,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """D21's lesson, on this group: the name and the class cannot diverge."""
    monkeypatch.setattr(
        registry,
        "entry_points",
        _entry_points_returning(_stub_entry_point("acme-doppler", MisnamedSource)),
    )
    with caplog.at_level("WARNING"):
        assert registry.load_plugins() == 0
    assert "acme-doppler" in caplog.text
    assert "acme-radar" in caplog.text
    assert not registry.is_registered("acme-doppler")


def test_a_plugin_cannot_take_a_name_this_build_describes(
    isolated_registry: object,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The published description of data-fetch names bdtopage and its shape."""

    class Impostor(AcmeRadarSource):
        source_id: ClassVar[str] = "bdtopage"

    monkeypatch.setattr(
        registry,
        "entry_points",
        _entry_points_returning(_stub_entry_point("bdtopage", Impostor)),
    )
    with caplog.at_level("WARNING"):
        assert registry.load_plugins() == 0
    assert "bdtopage" in caplog.text
    assert registry.get("bdtopage").__module__.startswith("hydromodpy.")


def test_a_plugin_that_fails_to_load_is_skipped_and_the_others_are_not(
    isolated_registry: object,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    broken = EntryPoint(
        name="acme-broken",
        value="tests.missing:Source",
        group=registry.ENTRY_POINT_GROUP,
    )
    object.__setattr__(
        broken,
        "load",
        lambda: (_ for _ in ()).throw(ImportError("no module named acme")),
    )
    monkeypatch.setattr(
        registry,
        "entry_points",
        _entry_points_returning(broken, _stub_entry_point("acme-radar", AcmeRadarSource)),
    )
    with caplog.at_level("WARNING"):
        assert registry.load_plugins() == 1
    assert "acme-broken" in caplog.text
    assert registry.is_registered("acme-radar")


def test_a_non_conforming_plugin_is_skipped_rather_than_raised(
    isolated_registry: object,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """One broken plugin must not take down a host asking for another source."""
    monkeypatch.setattr(
        registry,
        "entry_points",
        _entry_points_returning(
            _stub_entry_point("acme-half", HalfSource),
            _stub_entry_point("acme-radar", AcmeRadarSource),
        ),
    )
    with caplog.at_level("WARNING"):
        assert registry.load_plugins() == 1
    assert "acme-half" in caplog.text
    assert registry.is_registered("acme-radar")


def test_the_group_is_scanned_once_unless_forced(
    isolated_registry: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def counting_entry_points(*, group: str):
        calls.append(group)
        return (_stub_entry_point("acme-radar", AcmeRadarSource),)

    monkeypatch.setattr(registry, "entry_points", counting_entry_points)
    assert registry.load_plugins() == 1
    assert registry.load_plugins() == 0
    assert len(calls) == 1
    assert registry.load_plugins(force=True) == 1
    assert len(calls) == 2


def test_unregister_drops_the_declaration_too(isolated_registry: object) -> None:
    """Otherwise the next lookup lazy-loads the built-in straight back."""
    registry.get("bdtopage")
    registry.unregister("bdtopage")
    with pytest.raises(DataRequestError):
        registry.get("bdtopage")
