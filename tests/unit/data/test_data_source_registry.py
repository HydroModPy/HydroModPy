"""What the data-source registry resolves, and what it refuses.

The exit gate of the phase is that a third-party source registers without a
patch to HydroModPy, so the foreign source below is built the way a foreign one
really arrives: a class defined outside the package, reached through a stub
entry point in the ``hydromodpy.data.source`` group, never imported by name.
"""

from __future__ import annotations

import inspect
import json
import pathlib
import subprocess
import sys
from importlib.metadata import EntryPoint
from typing import ClassVar

import pytest

import hydromodpy.core.plugin_registry as plugin_registry
from hydromodpy.core.exceptions import DataRequestError
from hydromodpy.core.plugin_registry import PluginRegistry
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
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


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
    """Each class member is the class's own and not None, the rule ``register()`` applies."""
    ids = registry.data_sources.names(shipped_only=True)
    assert ids, "a registry with no built-in serves nobody"
    for source_id in ids:
        source_cls = registry.data_sources.get(source_id)
        assert source_cls.source_id == source_id
        absent = [
            name
            for name in CLASS_SOURCE_MEMBERS
            if inspect.getattr_static(source_cls, name, None) is None
        ]
        assert absent == [], source_id


@pytest.mark.allow_subprocess
def test_a_builtin_is_not_imported_until_it_is_asked_for() -> None:
    """The declaration is a dotted path, so declaring costs no import.

    Measured in a fresh interpreter, and deliberately not by deleting the
    module from ``sys.modules`` here: the adversarial gate of this phase showed
    that a purge no fixture restores leaves a second, distinct class object
    behind, and two integration tests then monkeypatch the wrong one and pass
    for the wrong reason.
    """
    script = (
        "import json, sys;"
        "from hydromodpy.data.source.registry import data_sources;"
        "target = 'hydromodpy.data.variables.hydrography.apis.osm';"
        "data_sources.get('bdtopage');"
        "before = target in sys.modules;"
        "data_sources.get('osm');"
        "after = target in sys.modules;"
        "print(json.dumps([before, after]))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    )
    before, after = json.loads(completed.stdout.strip().splitlines()[-1])
    assert not before, "resolving one source imported another one's module"
    assert after, "anti-vacuity: the module was never imported at all"


def test_the_described_set_and_the_resolvable_set_are_different_questions(
    isolated_registry: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plugin is resolvable and not describable, and the two answers say so."""
    monkeypatch.setattr(
        plugin_registry,
        "entry_points",
        _entry_points_returning(_stub_entry_point("acme-radar", AcmeRadarSource)),
    )
    assert "acme-radar" in registry.data_sources.names()
    assert "acme-radar" not in registry.data_sources.names(shipped_only=True)


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
        plugin_registry,
        "entry_points",
        _entry_points_returning(_stub_entry_point("acme-radar", AcmeRadarSource)),
    )

    assert registry.data_sources.load_plugins() == 1
    resolved = registry.data_sources.get("acme-radar")
    assert resolved is AcmeRadarSource
    assert "acme-radar" in registry.data_sources.names()

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
    assert registry.data_sources.register(AcmeRadarSource) is AcmeRadarSource


def test_a_second_registration_of_one_id_is_refused_unless_it_replaces(
    isolated_registry: object,
) -> None:
    registry.data_sources.register(AcmeRadarSource)
    with pytest.raises(ValueError, match="already registered"):
        registry.data_sources.register(AcmeRadarSource)
    assert registry.data_sources.register(AcmeRadarSource, replace=True) is AcmeRadarSource


def test_substituting_the_class_behind_an_id_substitutes_what_a_caller_gets(
    isolated_registry: object,
) -> None:
    """G1 in one assertion: the id is the seam, the implementation is not."""

    class Substitute(AcmeRadarSource):
        source_id: ClassVar[str] = "bdtopage"

    registry.data_sources.register(Substitute, replace=True)
    assert registry.data_sources.get("bdtopage") is Substitute


# --------------------------------------------------------------------------- #
# What is refused
# --------------------------------------------------------------------------- #


def test_a_class_missing_a_port_member_is_refused_by_name(isolated_registry: object) -> None:
    with pytest.raises(TypeError, match="payload_kind"):
        registry.data_sources.register(HalfSource)
    assert "acme-half" not in registry.data_sources.classes


def test_a_class_declaring_no_id_is_refused(isolated_registry: object) -> None:
    with pytest.raises(TypeError, match="source_id"):
        registry.data_sources.register(IdlessSource)


def test_variables_alone_does_not_make_a_class_unregistrable(isolated_registry: object) -> None:
    """``variables`` is the instance's, so demanding it here would refuse everyone."""
    assert not hasattr(AcmeRadarSource, "variables")
    registry.data_sources.register(AcmeRadarSource)


def test_a_source_has_no_default_so_a_lookup_without_a_name_is_a_request_fault() -> None:
    with pytest.raises(DataRequestError, match="no default") as excinfo:
        registry.data_sources.get()
    assert "bdtopage" in str(excinfo.value)


def test_an_unknown_id_is_a_request_fault_that_names_what_is_served() -> None:
    with pytest.raises(DataRequestError) as excinfo:
        registry.data_sources.get("no-such-source")
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
        plugin_registry,
        "entry_points",
        _entry_points_returning(_stub_entry_point("acme-doppler", MisnamedSource)),
    )
    with caplog.at_level("WARNING"):
        assert registry.data_sources.load_plugins() == 0
    assert "acme-doppler" in caplog.text
    assert "acme-radar" in caplog.text
    assert "acme-doppler" not in registry.data_sources.names()


def test_a_plugin_cannot_take_a_name_this_build_describes(
    isolated_registry: object,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A [data.hydrography] section names bdtopage, and means the source shipped here."""

    class Impostor(AcmeRadarSource):
        source_id: ClassVar[str] = "bdtopage"

    monkeypatch.setattr(
        plugin_registry,
        "entry_points",
        _entry_points_returning(_stub_entry_point("bdtopage", Impostor)),
    )
    with caplog.at_level("WARNING"):
        assert registry.data_sources.load_plugins() == 0
    assert "bdtopage" in caplog.text
    assert registry.data_sources.get("bdtopage").__module__.startswith("hydromodpy.")


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
        plugin_registry,
        "entry_points",
        _entry_points_returning(broken, _stub_entry_point("acme-radar", AcmeRadarSource)),
    )
    with caplog.at_level("WARNING"):
        assert registry.data_sources.load_plugins() == 1
    assert "acme-broken" in caplog.text
    assert "acme-radar" in registry.data_sources.names()


def test_a_non_conforming_plugin_is_skipped_rather_than_raised(
    isolated_registry: object,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """One broken plugin must not take down a host asking for another source."""
    monkeypatch.setattr(
        plugin_registry,
        "entry_points",
        _entry_points_returning(
            _stub_entry_point("acme-half", HalfSource),
            _stub_entry_point("acme-radar", AcmeRadarSource),
        ),
    )
    with caplog.at_level("WARNING"):
        assert registry.data_sources.load_plugins() == 1
    assert "acme-half" in caplog.text
    assert "acme-radar" in registry.data_sources.names()


def test_the_group_is_scanned_once_unless_forced(
    isolated_registry: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def counting_entry_points(*, group: str):
        calls.append(group)
        return (_stub_entry_point("acme-radar", AcmeRadarSource),)

    monkeypatch.setattr(plugin_registry, "entry_points", counting_entry_points)
    assert registry.data_sources.load_plugins() == 1
    assert registry.data_sources.load_plugins() == 0
    assert len(calls) == 1
    assert registry.data_sources.load_plugins(force=True) == 1
    assert len(calls) == 2


def test_unregister_drops_the_declaration_too(isolated_registry: object) -> None:
    """Otherwise the next lookup lazy-loads the built-in straight back."""
    registry.data_sources.get("bdtopage")
    registry.data_sources.unregister("bdtopage")
    with pytest.raises(DataRequestError):
        registry.data_sources.get("bdtopage")


# --------------------------------------------------------------------------- #
# What a broken installation does, which is not raise whatever it likes
# --------------------------------------------------------------------------- #


def test_a_declared_builtin_that_cannot_be_imported_is_a_request_fault(
    isolated_registry: object,
) -> None:
    """Found by the adversarial gate of F5e-3, and it is the diff that opened it.

    Resolving a name is reached from a **configuration validator** since the
    source field stopped being a ``Literal``, so an adapter that fails at import
    used to leave as a ``ModuleNotFoundError`` -- past pydantic, past the config
    command's error handling, onto the exit code that means "this is a bug in
    HydroModPy". An id this build declares and cannot load is an id this
    installation does not serve, and it leaves as that.
    """
    registry.data_sources.builtin_paths["broken-builtin"] = "hydromodpy.no_such_module:Whatever"

    with pytest.raises(DataRequestError) as raised:
        registry.data_sources.get("broken-builtin")

    assert "broken-builtin" in str(raised.value)
    assert "ModuleNotFoundError" in str(raised.value)
    assert isinstance(raised.value.__cause__, ModuleNotFoundError)


def test_a_declared_builtin_whose_class_is_missing_is_the_same_fault(
    isolated_registry: object,
) -> None:
    """A dotted path can be wrong in two ways, and both are one answer."""
    registry.data_sources.builtin_paths["misnamed-builtin"] = (
        "hydromodpy.data.variables.hydrography.apis.osm:NotThere"
    )

    with pytest.raises(DataRequestError, match="misnamed-builtin"):
        registry.data_sources.get("misnamed-builtin")


def test_an_unscannable_entry_point_group_leaves_the_builtins_resolvable(
    isolated_registry: object,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The per-plugin policy, one level up: a broken distribution is not a crash.

    ``entry_points()`` reads every distribution's metadata, so one unreadable
    ``.dist-info`` in the environment takes the whole scan down -- for a caller
    that named a built-in and no plugin at all.
    """

    def _unreadable(*, group: str):
        raise RuntimeError("corrupt importlib.metadata cache")

    monkeypatch.setattr(plugin_registry, "entry_points", _unreadable)

    with caplog.at_level("WARNING"):
        assert registry.data_sources.load_plugins() == 0

    assert registry.ENTRY_POINT_GROUP in caplog.text
    assert registry.data_sources.get("bdtopage").source_id == "bdtopage"
    with pytest.raises(DataRequestError, match="acme-radar"):
        registry.data_sources.get("acme-radar")


def test_the_module_exposes_its_registry_and_none_of_the_retired_functions() -> None:
    """The registry is one object of the shared engine, read through ``data_sources``."""
    held = registry.data_sources

    assert isinstance(held, PluginRegistry)
    assert held.id_attributes == ("source_id",)
    assert held.group == registry.ENTRY_POINT_GROUP
    assert held.default_id is None
    assert held.names(shipped_only=True) == tuple(sorted(registry._BUILTIN_PATHS))
    retired = (
        "get",
        "create",
        "register",
        "unregister",
        "load_plugins",
        "is_registered",
        "resolve_id",
        "list_source_ids",
        "builtin_source_ids",
    )
    assert [name for name in retired if hasattr(registry, name)] == []
