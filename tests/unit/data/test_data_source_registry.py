"""What the data-source registry resolves, and what it refuses.

The exit gate of the phase is that a third-party source registers without a
patch to HydroModPy, so the foreign source below is built the way a foreign one
really arrives: a class defined outside the package, reached through a stub
entry point in the ``hydromodpy.data.source`` group, never imported by name. A
key has two parts since this phase, a ``section`` and a ``source_id``, so the
foreign source answers under a joined name, ``acme-weather_acme-radar``, exactly
the rule the solver backends follow.
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

ACME_SECTION = "acme-weather"


class AcmeRadarSource:
    """A source a third party ships, conforming and known to no in-tree module."""

    source_id: ClassVar[str] = "acme-radar"
    section: ClassVar[str] = ACME_SECTION
    payload_kind: ClassVar[PayloadKind] = "fields"
    extent_crs: ClassVar[str] = "EPSG:3035"
    selectors: ClassVar[tuple[Selector, ...]] = ("extent",)
    period_need: ClassVar[PeriodNeed] = "required"
    writes_out_dir: ClassVar[bool] = False

    def __init__(self) -> None:
        self.variables: tuple[str, ...] = ("radar_rainfall",)
        self.hosts: tuple[str, ...] = ("radar.acme.example",)

    def fetch(self, request: FetchRequest) -> FetchResult:
        return FetchResult(
            source_id=self.source_id,
            kind=self.payload_kind,
            variables=self.variables,
            extent=extent_for(self, request),
        )


class AcmeGaugeSource(AcmeRadarSource):
    """Another source of the same provider, under the same id and another section."""

    source_id: ClassVar[str] = "acme-gauge"
    section: ClassVar[str] = "acme-port"
    payload_kind: ClassVar[PayloadKind] = "points"


class MisnamedSource(AcmeRadarSource):
    """Declares one id while its entry point is published under another."""

    source_id: ClassVar[str] = "acme-radar"


class HalfSource:
    """Carries an id and nothing else the port asks of a class."""

    source_id: ClassVar[str] = "acme-radar"
    section: ClassVar[str] = ACME_SECTION


class IdlessSource:
    """Every class member but the one a registry is keyed on."""

    section: ClassVar[str] = ACME_SECTION
    payload_kind: ClassVar[PayloadKind] = "points"
    extent_crs: ClassVar[str] = "EPSG:4326"
    selectors: ClassVar[tuple[Selector, ...]] = ("extent",)
    period_need: ClassVar[PeriodNeed] = "refused"
    writes_out_dir: ClassVar[bool] = False

    def fetch(self, request: FetchRequest) -> FetchResult:  # pragma: no cover - never reached
        raise AssertionError("a class with no source_id must not be registrable")


class SectionlessSource(IdlessSource):
    """Every class member but the section this build keys on since this phase."""

    source_id: ClassVar[str] = "acme-doppler"
    section: ClassVar[str] = ""


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
    assert INSTANCE_SOURCE_MEMBERS == ("variables", "hosts")


def test_the_builtin_paths_are_the_seventy_three_sources_this_build_ships() -> None:
    """26 providers, plus ``file`` under 28 sections and ``url`` under 19: 73 in all.

    The single declaration of what is served. The generic ``file`` and ``url``
    sources of lot 4.3 are registered per section, so a section only reaches
    the ones its own registry names.
    """
    assert len(registry._BUILTIN_PATHS) == 73
    shipped = registry.data_sources.names(shipped_only=True)
    assert len(shipped) == 73
    assert sum(key.endswith("_file") for key in shipped) == 28
    assert sum(key.endswith("_url") for key in shipped) == 19
    # The ids any [data] section resolves, read the joined keys against the
    # sections the loader dispatches on, never by cutting on "_".
    from hydromodpy.data.loading._dispatch import VARIABLE_SPECS

    ids_by_section: dict[str, set[str]] = {}
    for key in shipped:
        for section in VARIABLE_SPECS:
            if key.startswith(f"{section}_"):
                ids_by_section.setdefault(section, set()).add(key[len(section) + 1 :])
    assert sum(len(ids) for ids in ids_by_section.values()) == 73
    assert ids_by_section["hydrography"] == {"bdtopage", "euhydro", "osm", "file", "url"}
    assert ids_by_section["water_quality"] == {"hubeau", "file"}
    assert ids_by_section["oceanic"] == {"shom", "constant", "file"}


def test_no_section_is_the_prefix_of_another_followed_by_an_underscore() -> None:
    """The one condition two joined keys can never collide on, whatever a plugin is called."""
    from hydromodpy.data.loading._dispatch import VARIABLE_SPECS

    sections = sorted(VARIABLE_SPECS)
    for first, second in __import__("itertools").combinations(sections, 2):
        assert not f"{second}_".startswith(f"{first}_"), (
            f"{second} would swallow the id of {first}, and two joined keys would read as one"
        )


def test_every_builtin_id_resolves_to_a_class_the_port_accepts() -> None:
    """Each class member is the class's own and not None, the rule ``register()`` applies.

    The classes of the providers that land in the same phase arrive with them;
    this resolves every declared path, so the test is red on a key whose class
    is not in the tree yet.
    """
    ids = registry.data_sources.names(shipped_only=True)
    assert ids, "a registry with no built-in serves nobody"
    for key in ids:
        source_cls = registry.data_sources.get(key)
        assert source_cls.section, key
        absent = [
            name
            for name in CLASS_SOURCE_MEMBERS
            if inspect.getattr_static(source_cls, name, None) is None
        ]
        assert absent == [], key


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
        "data_sources.get('hydrography', 'bdtopage');"
        "before = target in sys.modules;"
        "data_sources.get('hydrography', 'osm');"
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
        _entry_points_returning(_stub_entry_point("acme-weather_acme-radar", AcmeRadarSource)),
    )
    assert "acme-weather_acme-radar" in registry.data_sources.names()
    assert "acme-weather_acme-radar" not in registry.data_sources.names(shipped_only=True)


# --------------------------------------------------------------------------- #
# A source is keyed on its section and its id
# --------------------------------------------------------------------------- #


def test_a_section_reaches_its_own_sources_and_only_those(isolated_registry: object) -> None:
    """The key buys the confinement: no hydrometry section reaches a DEM source."""
    registered = registry.data_sources.register(AcmeRadarSource)
    assert registry.data_sources.get(ACME_SECTION, "acme-radar") is registered
    assert registry.data_sources.get("acme-weather_acme-radar") is registered
    assert registry.data_sources.names(ACME_SECTION) == ("acme-radar",)
    with pytest.raises(DataRequestError, match="serves"):
        registry.data_sources.get("hydrometry", "acme-radar")


def test_a_source_that_is_not_registered_anywhere_is_refused_by_name(
    isolated_registry: object,
) -> None:
    with pytest.raises(DataRequestError, match="hydrography_sonar"):
        registry.data_sources.get("hydrography", "sonar")


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
        _entry_points_returning(_stub_entry_point("acme-weather_acme-radar", AcmeRadarSource)),
    )

    assert registry.data_sources.load_plugins() == 1
    resolved = registry.data_sources.get("acme-weather", "acme-radar")
    assert resolved is AcmeRadarSource
    assert "acme-weather_acme-radar" in registry.data_sources.names()
    assert registry.data_sources.names("acme-weather") == ("acme-radar",)

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


def test_a_second_registration_of_one_key_is_refused_unless_it_replaces(
    isolated_registry: object,
) -> None:
    registry.data_sources.register(AcmeRadarSource)
    with pytest.raises(ValueError, match="already registered"):
        registry.data_sources.register(AcmeRadarSource)
    assert registry.data_sources.register(AcmeRadarSource, replace=True) is AcmeRadarSource


def test_substituting_the_class_behind_a_key_substitutes_what_a_caller_gets(
    isolated_registry: object,
) -> None:
    """G1 in one assertion: the key is the seam, the implementation is not."""

    class Substitute(AcmeRadarSource):
        source_id: ClassVar[str] = "bdtopage"
        section: ClassVar[str] = "hydrography"

    registry.data_sources.register(Substitute, replace=True)
    assert registry.data_sources.get("hydrography_bdtopage") is Substitute


# --------------------------------------------------------------------------- #
# What is refused
# --------------------------------------------------------------------------- #


def test_a_class_missing_a_port_member_is_refused_by_name(isolated_registry: object) -> None:
    with pytest.raises(TypeError, match="payload_kind"):
        registry.data_sources.register(HalfSource)
    assert HalfSource.source_id not in registry.data_sources.classes


def test_a_class_declaring_no_id_is_refused(isolated_registry: object) -> None:
    with pytest.raises(TypeError, match="source_id"):
        registry.data_sources.register(IdlessSource)


def test_a_class_declaring_no_section_is_refused(isolated_registry: object) -> None:
    """The section joined the id attributes this phase, and is checked the same."""
    with pytest.raises(TypeError, match="section"):
        registry.data_sources.register(SectionlessSource)


def test_the_instance_members_alone_do_not_make_a_class_unregistrable(
    isolated_registry: object,
) -> None:
    """``variables`` and ``hosts`` are the instance's, so demanding them here would refuse everyone."""
    assert not hasattr(AcmeRadarSource, "variables")
    assert not hasattr(AcmeRadarSource, "hosts")
    registry.data_sources.register(AcmeRadarSource)


def test_a_source_has_no_default_so_a_lookup_without_a_name_is_a_request_fault() -> None:
    with pytest.raises(DataRequestError, match="no default") as excinfo:
        registry.data_sources.get()
    assert "hydrography_osm" in str(excinfo.value)


def test_an_unknown_id_is_a_request_fault_that_names_what_is_served() -> None:
    with pytest.raises(DataRequestError) as excinfo:
        registry.data_sources.get("hydrography", "no-such-source")
    message = str(excinfo.value)
    assert "no-such-source" in message
    assert "hydrography_bdtopage" in message
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
        _entry_points_returning(_stub_entry_point("acme-weather_acme-doppler", MisnamedSource)),
    )
    with caplog.at_level("WARNING"):
        assert registry.data_sources.load_plugins() == 0
    assert "acme-doppler" in caplog.text
    assert "acme-radar" in caplog.text
    assert "acme-weather_acme-doppler" not in registry.data_sources.names()


def test_a_plugin_cannot_take_a_key_this_build_describes(
    isolated_registry: object,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A [data.hydrography] section names bdtopage, and means the source shipped here."""

    class Impostor(AcmeRadarSource):
        source_id: ClassVar[str] = "bdtopage"
        section: ClassVar[str] = "hydrography"

    monkeypatch.setattr(
        plugin_registry,
        "entry_points",
        _entry_points_returning(_stub_entry_point("hydrography_bdtopage", Impostor)),
    )
    with caplog.at_level("WARNING"):
        assert registry.data_sources.load_plugins() == 0
    assert "hydrography_bdtopage" in caplog.text
    assert registry.data_sources.get("hydrography", "bdtopage").__module__.startswith("hydromodpy.")


def test_a_plugin_that_fails_to_load_is_skipped_and_the_others_are_not(
    isolated_registry: object,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    broken = EntryPoint(
        name="acme-weather_acme-broken",
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
        _entry_points_returning(
            broken, _stub_entry_point("acme-weather_acme-radar", AcmeRadarSource)
        ),
    )
    with caplog.at_level("WARNING"):
        assert registry.data_sources.load_plugins() == 1
    assert "acme-broken" in caplog.text
    assert "acme-weather_acme-radar" in registry.data_sources.names()


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
            _stub_entry_point("acme-weather_acme-half", HalfSource),
            _stub_entry_point("acme-weather_acme-radar", AcmeRadarSource),
        ),
    )
    with caplog.at_level("WARNING"):
        assert registry.data_sources.load_plugins() == 1
    assert "acme-half" in caplog.text
    assert "acme-weather_acme-radar" in registry.data_sources.names()


def test_the_group_is_scanned_once_unless_forced(
    isolated_registry: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def counting_entry_points(*, group: str):
        calls.append(group)
        return (_stub_entry_point("acme-weather_acme-radar", AcmeRadarSource),)

    monkeypatch.setattr(plugin_registry, "entry_points", counting_entry_points)
    assert registry.data_sources.load_plugins() == 1
    assert registry.data_sources.load_plugins() == 0
    assert len(calls) == 1
    assert registry.data_sources.load_plugins(force=True) == 1
    assert len(calls) == 2


def test_unregister_drops_the_declaration_too(isolated_registry: object) -> None:
    """Otherwise the next lookup lazy-loads the built-in straight back."""
    registry.data_sources.get("hydrography", "bdtopage")
    registry.data_sources.unregister("hydrography", "bdtopage")
    with pytest.raises(DataRequestError):
        registry.data_sources.get("hydrography", "bdtopage")


# --------------------------------------------------------------------------- #
# An installed source is named by its source id
# --------------------------------------------------------------------------- #


def test_an_installed_source_resolves_by_its_source_id_alone(
    isolated_registry: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        plugin_registry,
        "entry_points",
        _entry_points_returning(
            _stub_entry_point("acme-weather_acme-radar", AcmeRadarSource),
            _stub_entry_point("acme-port_acme-gauge", AcmeGaugeSource),
        ),
    )
    assert registry.installed_source_cls("acme-radar") is AcmeRadarSource
    assert registry.installed_source_cls("acme-gauge") is AcmeGaugeSource


def test_an_ambiguous_source_id_is_refused_naming_the_keys(
    isolated_registry: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two plugin sections serving one id: the id alone did not say which was meant."""

    class TwinSource(AcmeRadarSource):
        section: ClassVar[str] = "acme-wind"

    monkeypatch.setattr(
        plugin_registry,
        "entry_points",
        _entry_points_returning(
            _stub_entry_point("acme-weather_acme-radar", AcmeRadarSource),
            _stub_entry_point("acme-wind_acme-radar", TwinSource),
        ),
    )
    with pytest.raises(DataRequestError, match="acme-wind_acme-radar") as excinfo:
        registry.installed_source_cls("acme-radar")
    assert "acme-weather_acme-radar" in str(excinfo.value)


def test_an_installed_source_id_nothing_serves_is_refused_with_the_served_list(
    isolated_registry: object,
) -> None:
    with pytest.raises(DataRequestError) as excinfo:
        registry.installed_source_cls("acme-ghost")
    message = str(excinfo.value)
    assert "acme-ghost" in message
    assert registry.ENTRY_POINT_GROUP in message


def test_a_shipped_source_is_not_an_installed_one_even_once_imported(
    isolated_registry: object,
) -> None:
    """The registry resolves the built-in, and ``installed`` still does not reach it."""
    registry.data_sources.get("hydrography", "bdtopage")
    with pytest.raises(DataRequestError, match="No installed source"):
        registry.installed_source_cls("bdtopage")


def test_installed_source_cls_refuses_a_name_that_is_not_a_string(
    isolated_registry: object,
) -> None:
    with pytest.raises(DataRequestError, match="source id"):
        registry.installed_source_cls(42)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# build_from_section
# --------------------------------------------------------------------------- #


class _Section:
    """A duck-typed section, the shape the managers are handed."""

    def __init__(self, **fields: object) -> None:
        self.__dict__.update(fields)


def test_build_from_section_binds_the_fields_the_constructor_names(
    isolated_registry: object,
) -> None:
    built = registry.build_from_section(AcmeRadarSource, _Section(source="acme-radar", page_size=3))
    assert built.variables == ("radar_rainfall",)


def test_build_from_section_resolved_values_win_over_the_section(
    isolated_registry: object,
) -> None:
    """What the manager computes -- a measured point, a parsed date -- is the better value."""

    class BoundSource(AcmeRadarSource):
        def __init__(self, *, nearest_to: object = None) -> None:
            super().__init__()
            self.nearest_to = nearest_to

    section = _Section(source="acme-radar", nearest_to=(48.2, -1.8))
    plain = registry.build_from_section(BoundSource, section)
    assert plain.nearest_to == (48.2, -1.8)
    resolved = registry.build_from_section(BoundSource, section, nearest_to=(48.1, -1.7))
    assert resolved.nearest_to == (48.1, -1.7)


def test_build_from_section_passes_the_defaults_of_a_third_party_source(
    isolated_registry: object,
) -> None:
    """A closed model with no room for a plugin field still builds the plugin."""
    built = registry.build_from_section(AcmeRadarSource, _Section(source="acme-radar"))
    assert built.hosts == ("radar.acme.example",)


def test_build_from_section_refuses_a_positional_only_constructor(
    isolated_registry: object,
) -> None:
    class PickySource(AcmeRadarSource):
        def __init__(self, page_size: int, /) -> None:  # pragma: no cover - refused first
            super().__init__()
            del page_size

    with pytest.raises(DataRequestError, match="positional"):
        registry.build_from_section(PickySource, _Section(page_size=3))


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
    registry.data_sources.builtin_paths["broken_broken-builtin"] = (
        "hydromodpy.no_such_module:Whatever"
    )

    with pytest.raises(DataRequestError) as raised:
        registry.data_sources.get("broken", "broken-builtin")

    assert "broken_broken-builtin" in str(raised.value)
    assert "ModuleNotFoundError" in str(raised.value)
    assert isinstance(raised.value.__cause__, ModuleNotFoundError)


def test_a_declared_builtin_whose_class_is_missing_is_the_same_fault(
    isolated_registry: object,
) -> None:
    """A dotted path can be wrong in two ways, and both are one answer."""
    registry.data_sources.builtin_paths["hydrography_misnamed-builtin"] = (
        "hydromodpy.data.variables.hydrography.apis.osm:NotThere"
    )

    with pytest.raises(DataRequestError, match="misnamed-builtin"):
        registry.data_sources.get("hydrography_misnamed-builtin")


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
    assert registry.data_sources.get("hydrography", "bdtopage").source_id == "bdtopage"
    with pytest.raises(DataRequestError, match="acme-radar"):
        registry.data_sources.get(ACME_SECTION, "acme-radar")


# --------------------------------------------------------------------------- #
# The module surface
# --------------------------------------------------------------------------- #


def test_the_module_exposes_its_registry_and_none_of_the_retired_functions() -> None:
    """The registry is one object of the shared engine, read through ``data_sources``."""
    held = registry.data_sources

    assert isinstance(held, PluginRegistry)
    assert held.id_attributes == ("section", "source_id")
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
        "get_" + "serving",
    )
    assert [name for name in retired if hasattr(registry, name)] == []


def test_build_from_section_filters_resolved_parameters_not_in_constructor() -> None:
    """Extra resolved keys like date_start/date_end are dropped when not accepted."""
    from hydromodpy.data.common.clients.sim2_products import Sim2Precipitation
    from hydromodpy.data.variables.oceanic.config import OceanicSourceConfig
    from hydromodpy.data.variables.oceanic.constant import ConstantSeaLevel
    from hydromodpy.data.variables.precipitation.config import PrecipitationConfig

    cfg = PrecipitationConfig(sources=[{"source": "sim2"}])
    source = registry.build_from_section(
        Sim2Precipitation,
        cfg,
        date_start="2020-01-01",
        date_end="2020-12-31",
    )
    assert isinstance(source, Sim2Precipitation)

    oceanic_cfg = OceanicSourceConfig(source="constant", value=1.5)
    source_const = registry.build_from_section(
        ConstantSeaLevel,
        oceanic_cfg,
        date_start="2020-01-01",
        date_end="2020-12-31",
    )
    assert isinstance(source_const, ConstantSeaLevel)
    assert source_const.value == 1.5
