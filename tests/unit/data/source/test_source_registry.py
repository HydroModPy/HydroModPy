"""Registry of data sources, keyed on a section and a source id.

A third-party source registers without a patch to HydroModPy. The foreign source
below arrives as a class defined outside the package, reached through a stub entry
point of the ``hydromodpy.data.source`` group. It answers under the joined name
``acme-weather_acme-radar``, the rule the solver backends follow.
"""

from __future__ import annotations

import inspect
import itertools
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
    Extent,
    FetchRequest,
    FetchResult,
    PayloadKind,
    PeriodNeed,
    Selector,
    extent_for,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]

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


def stub_entry_point(name: str, target: type) -> EntryPoint:
    """An entry point that loads *target* without a distribution on disk."""
    point = EntryPoint(name=name, value="tests.stub:Source", group=registry.ENTRY_POINT_GROUP)
    object.__setattr__(point, "load", lambda: target)
    return point


def serve_entry_points(monkeypatch, *points: EntryPoint) -> None:
    def fake_entry_points(*, group: str):
        assert group == registry.ENTRY_POINT_GROUP
        return tuple(points)

    monkeypatch.setattr(plugin_registry, "entry_points", fake_entry_points)


def radar_plugin() -> EntryPoint:
    return stub_entry_point("acme-weather_acme-radar", AcmeRadarSource)


def test_member_sets_partition_the_port():
    # A member in neither set would be asked of nobody.
    assert set(CLASS_SOURCE_MEMBERS) | set(INSTANCE_SOURCE_MEMBERS) == set(SOURCE_MEMBERS)
    assert not set(CLASS_SOURCE_MEMBERS) & set(INSTANCE_SOURCE_MEMBERS)
    assert INSTANCE_SOURCE_MEMBERS == ("variables", "hosts")


def test_builtin_paths():
    # 26 providers, plus `file` under 28 sections and `url` under 19: 73 in all.
    # The generic `file` and `url` sources are registered per section.
    assert len(registry._BUILTIN_PATHS) == 73
    shipped = registry.data_sources.names(shipped_only=True)
    assert len(shipped) == 73
    assert sum(key.endswith("_file") for key in shipped) == 28
    assert sum(key.endswith("_url") for key in shipped) == 19
    # Read the joined keys against the sections the loader dispatches on, never by cutting on "_".
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


def test_no_section_swallows_another():
    # Two joined keys must never collide, whatever a plugin is called.
    from hydromodpy.data.loading._dispatch import VARIABLE_SPECS

    for first, second in itertools.combinations(sorted(VARIABLE_SPECS), 2):
        assert not f"{second}_".startswith(f"{first}_"), (
            f"{second} would swallow the id of {first}, and two joined keys would read as one"
        )


def test_every_builtin_resolves():
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
def test_builtin_is_imported_lazily():
    # Declaring a path costs no import. Measured in a fresh interpreter, because purging
    # sys.modules here would leave a second class object behind for other tests.
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
    assert after, "the module was never imported at all"


def test_plugin_is_resolvable_not_shipped(isolated_registry, monkeypatch):
    serve_entry_points(monkeypatch, radar_plugin())

    assert "acme-weather_acme-radar" in registry.data_sources.names()
    assert "acme-weather_acme-radar" not in registry.data_sources.names(shipped_only=True)


def test_section_reaches_its_own_sources(isolated_registry):
    registered = registry.data_sources.register(AcmeRadarSource)

    assert registry.data_sources.get(ACME_SECTION, "acme-radar") is registered
    assert registry.data_sources.get("acme-weather_acme-radar") is registered
    assert registry.data_sources.names(ACME_SECTION) == ("acme-radar",)
    with pytest.raises(DataRequestError, match="serves"):
        registry.data_sources.get("hydrometry", "acme-radar")


def test_unregistered_source_is_refused(isolated_registry):
    with pytest.raises(DataRequestError, match="hydrography_sonar"):
        registry.data_sources.get("hydrography", "sonar")


def test_foreign_source_through_entry_points(isolated_registry, monkeypatch, tmp_path):
    serve_entry_points(monkeypatch, radar_plugin())

    assert registry.data_sources.load_plugins() == 1
    resolved = registry.data_sources.get("acme-weather", "acme-radar")
    assert resolved is AcmeRadarSource
    assert "acme-weather_acme-radar" in registry.data_sources.names()
    assert registry.data_sources.names("acme-weather") == ("acme-radar",)

    extent = Extent(xmin=-1.9, ymin=48.0, xmax=-1.5, ymax=48.3, crs="EPSG:4326")
    result = resolved().fetch(FetchRequest(out_dir=tmp_path, extent=extent, period=None))

    assert result.source_id == "acme-radar"
    assert result.extent is not None
    assert result.extent.crs == "EPSG:3035", "the port converted into what the source declares"


def test_register_returns_the_class(isolated_registry):
    assert registry.data_sources.register(AcmeRadarSource) is AcmeRadarSource


def test_second_registration(isolated_registry):
    registry.data_sources.register(AcmeRadarSource)

    with pytest.raises(ValueError, match="already registered"):
        registry.data_sources.register(AcmeRadarSource)
    assert registry.data_sources.register(AcmeRadarSource, replace=True) is AcmeRadarSource


def test_substituted_class(isolated_registry):
    class Substitute(AcmeRadarSource):
        source_id: ClassVar[str] = "bdtopage"
        section: ClassVar[str] = "hydrography"

    registry.data_sources.register(Substitute, replace=True)

    assert registry.data_sources.get("hydrography_bdtopage") is Substitute


REGISTRATION_REFUSALS = [
    pytest.param(HalfSource, "payload_kind", id="missing a port member"),
    pytest.param(IdlessSource, "source_id", id="no id"),
    pytest.param(SectionlessSource, "section", id="no section"),
]


@pytest.mark.parametrize(("source", "message"), REGISTRATION_REFUSALS)
def test_registration_refusals(isolated_registry, source, message):
    with pytest.raises(TypeError, match=message):
        registry.data_sources.register(source)

    assert "acme-radar" not in registry.data_sources.classes


def test_instance_members_are_not_required(isolated_registry):
    # `variables` and `hosts` belong to the instance, so demanding them would refuse everyone.
    assert not hasattr(AcmeRadarSource, "variables")
    assert not hasattr(AcmeRadarSource, "hosts")

    registry.data_sources.register(AcmeRadarSource)


def test_lookup_without_a_name():
    with pytest.raises(DataRequestError, match="no default") as excinfo:
        registry.data_sources.get()

    assert "hydrography_osm" in str(excinfo.value)


def test_unknown_id_names_what_is_served():
    with pytest.raises(DataRequestError) as excinfo:
        registry.data_sources.get("hydrography", "no-such-source")

    message = str(excinfo.value)
    assert "no-such-source" in message
    assert "hydrography_bdtopage" in message
    assert registry.ENTRY_POINT_GROUP in message


def broken_plugin() -> EntryPoint:
    point = EntryPoint(
        name="acme-weather_acme-broken",
        value="tests.missing:Source",
        group=registry.ENTRY_POINT_GROUP,
    )
    object.__setattr__(point, "load", lambda: (_ for _ in ()).throw(ImportError("no module")))
    return point


# (entry points served, plugins loaded, names the warning gives)
SKIPPED_PLUGINS = [
    pytest.param(
        [stub_entry_point("acme-weather_acme-doppler", MisnamedSource)],
        0,
        ["acme-doppler", "acme-radar"],
        id="name contradicts its class",
    ),
    pytest.param([broken_plugin(), radar_plugin()], 1, ["acme-broken"], id="import fails"),
    pytest.param(
        [stub_entry_point("acme-weather_acme-half", HalfSource), radar_plugin()],
        1,
        ["acme-half"],
        id="does not conform",
    ),
]


@pytest.mark.parametrize(("points", "loaded", "logged"), SKIPPED_PLUGINS)
def test_bad_plugin_is_skipped(isolated_registry, monkeypatch, caplog, points, loaded, logged):
    serve_entry_points(monkeypatch, *points)

    with caplog.at_level("WARNING"):
        assert registry.data_sources.load_plugins() == loaded

    for name in logged:
        assert name in caplog.text
    names = registry.data_sources.names()
    assert "acme-weather_acme-doppler" not in names
    assert ("acme-weather_acme-radar" in names) == (loaded == 1)


def test_plugin_cannot_take_a_shipped_key(isolated_registry, monkeypatch, caplog):
    class Impostor(AcmeRadarSource):
        source_id: ClassVar[str] = "bdtopage"
        section: ClassVar[str] = "hydrography"

    serve_entry_points(monkeypatch, stub_entry_point("hydrography_bdtopage", Impostor))

    with caplog.at_level("WARNING"):
        assert registry.data_sources.load_plugins() == 0

    assert "hydrography_bdtopage" in caplog.text
    assert registry.data_sources.get("hydrography", "bdtopage").__module__.startswith("hydromodpy.")


def test_group_is_scanned_once(isolated_registry, monkeypatch):
    calls: list[str] = []

    def counting_entry_points(*, group: str):
        calls.append(group)
        return (radar_plugin(),)

    monkeypatch.setattr(plugin_registry, "entry_points", counting_entry_points)

    assert registry.data_sources.load_plugins() == 1
    assert registry.data_sources.load_plugins() == 0
    assert len(calls) == 1
    assert registry.data_sources.load_plugins(force=True) == 1
    assert len(calls) == 2


def test_unregister(isolated_registry):
    # Otherwise the next lookup lazy-loads the built-in straight back.
    registry.data_sources.get("hydrography", "bdtopage")
    registry.data_sources.unregister("hydrography", "bdtopage")

    with pytest.raises(DataRequestError):
        registry.data_sources.get("hydrography", "bdtopage")


def test_installed_source_by_id(isolated_registry, monkeypatch):
    serve_entry_points(
        monkeypatch, radar_plugin(), stub_entry_point("acme-port_acme-gauge", AcmeGaugeSource)
    )

    assert registry.installed_source_cls("acme-radar") is AcmeRadarSource
    assert registry.installed_source_cls("acme-gauge") is AcmeGaugeSource


def test_ambiguous_installed_id(isolated_registry, monkeypatch):
    class TwinSource(AcmeRadarSource):
        section: ClassVar[str] = "acme-wind"

    serve_entry_points(
        monkeypatch, radar_plugin(), stub_entry_point("acme-wind_acme-radar", TwinSource)
    )

    with pytest.raises(DataRequestError, match="acme-wind_acme-radar") as excinfo:
        registry.installed_source_cls("acme-radar")

    assert "acme-weather_acme-radar" in str(excinfo.value)


def test_unserved_installed_id(isolated_registry):
    with pytest.raises(DataRequestError) as excinfo:
        registry.installed_source_cls("acme-ghost")

    message = str(excinfo.value)
    assert "acme-ghost" in message
    assert registry.ENTRY_POINT_GROUP in message


def test_shipped_is_not_installed(isolated_registry):
    registry.data_sources.get("hydrography", "bdtopage")

    with pytest.raises(DataRequestError, match="No installed source"):
        registry.installed_source_cls("bdtopage")


def test_installed_id_must_be_a_string(isolated_registry):
    with pytest.raises(DataRequestError, match="source id"):
        registry.installed_source_cls(42)  # type: ignore[arg-type]


class Section:
    """A duck-typed config section, as the loaders hand it."""

    def __init__(self, **fields: object) -> None:
        self.__dict__.update(fields)


def test_build_binds_constructor_fields(isolated_registry):
    built = registry.build_from_section(AcmeRadarSource, Section(source="acme-radar", page_size=3))

    assert built.variables == ("radar_rainfall",)


def test_build_resolved_values_win(isolated_registry):
    # What the loader computes (a measured point, a parsed date) is the better value.
    class BoundSource(AcmeRadarSource):
        def __init__(self, *, nearest_to: object = None) -> None:
            super().__init__()
            self.nearest_to = nearest_to

    section = Section(source="acme-radar", nearest_to=(48.2, -1.8))

    plain = registry.build_from_section(BoundSource, section)
    resolved = registry.build_from_section(BoundSource, section, nearest_to=(48.1, -1.7))

    assert plain.nearest_to == (48.2, -1.8)
    assert resolved.nearest_to == (48.1, -1.7)


def test_build_third_party_defaults(isolated_registry):
    # A closed config model with no room for a plugin field still builds the plugin.
    built = registry.build_from_section(AcmeRadarSource, Section(source="acme-radar"))

    assert built.hosts == ("radar.acme.example",)


def test_build_refuses_positional_only(isolated_registry):
    class PickySource(AcmeRadarSource):
        def __init__(self, page_size: int, /) -> None:  # pragma: no cover - refused first
            super().__init__()
            del page_size

    with pytest.raises(DataRequestError, match="positional"):
        registry.build_from_section(PickySource, Section(page_size=3))


def test_unimportable_builtin_is_unserved(isolated_registry):
    # A config validator resolves names, so an adapter that fails at import must leave as
    # a DataRequestError and not as a bare ModuleNotFoundError.
    registry.data_sources.builtin_paths["broken_broken-builtin"] = (
        "hydromodpy.no_such_module:Whatever"
    )

    with pytest.raises(DataRequestError) as raised:
        registry.data_sources.get("broken", "broken-builtin")

    assert "broken_broken-builtin" in str(raised.value)
    assert "ModuleNotFoundError" in str(raised.value)
    assert isinstance(raised.value.__cause__, ModuleNotFoundError)


def test_builtin_with_a_missing_class(isolated_registry):
    registry.data_sources.builtin_paths["hydrography_misnamed-builtin"] = (
        "hydromodpy.data.variables.hydrography.apis.osm:NotThere"
    )

    with pytest.raises(DataRequestError, match="misnamed-builtin"):
        registry.data_sources.get("hydrography_misnamed-builtin")


def test_unscannable_entry_points(isolated_registry, monkeypatch, caplog):
    # entry_points() reads every distribution, so one unreadable one fails the whole scan.
    # A caller that named a built-in must not feel it.
    def unreadable(*, group: str):
        raise RuntimeError("corrupt importlib.metadata cache")

    monkeypatch.setattr(plugin_registry, "entry_points", unreadable)

    with caplog.at_level("WARNING"):
        assert registry.data_sources.load_plugins() == 0

    assert registry.ENTRY_POINT_GROUP in caplog.text
    assert registry.data_sources.get("hydrography", "bdtopage").source_id == "bdtopage"
    with pytest.raises(DataRequestError, match="acme-radar"):
        registry.data_sources.get(ACME_SECTION, "acme-radar")


def test_module_surface():
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


def test_build_drops_unaccepted_parameters():
    # date_start and date_end are dropped when the source does not accept them.
    from hydromodpy.data.common.clients.sim2_products import Sim2Precipitation
    from hydromodpy.data.variables.forcing_series import PrecipitationConfig
    from hydromodpy.data.variables.oceanic.config import OceanicSourceConfig
    from hydromodpy.data.variables.oceanic.constant import ConstantSeaLevel

    dates = {"date_start": "2020-01-01", "date_end": "2020-12-31"}

    rain = registry.build_from_section(
        Sim2Precipitation, PrecipitationConfig(sources=[{"source": "sim2"}]), **dates
    )
    sea = registry.build_from_section(
        ConstantSeaLevel, OceanicSourceConfig(source="constant", value=1.5), **dates
    )

    assert isinstance(rain, Sim2Precipitation)
    assert isinstance(sea, ConstantSeaLevel)
    assert sea.value == 1.5
