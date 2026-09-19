"""A terrain engine is resolved by name, including one this repository never names.

This is the canonical test of G1 written down: "replace WhiteboxTools without
touching the callers". Before the registry it could not be written at all, because
three production sites imported ``WhiteboxTerrainEngine`` and constructed it.

The last test of this file is the one that matters. It installs an engine through
the entry-point group, from a class defined right here and named nowhere in
``hydromodpy/``, and runs the whole ``terrain-delineate`` resolution against it.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import ClassVar

import pytest

from hydromodpy.core.exceptions import ConfigValidationError, TerrainRequestError
from hydromodpy.spatial.terrain import registry

pytestmark = pytest.mark.fast


class _ConformingEngine:
    """An engine that satisfies the port and takes no constructor option."""

    engine_id: ClassVar[str] = "test-conforming"
    engine_version: ClassVar[str] = "0.1.0"

    def engine_digest(self) -> str:
        return hashlib.sha256(self.engine_id.encode("utf-8")).hexdigest()

    def condition_dem(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def drainage_directions(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def flow_accumulation(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def stream_network(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError

    def delineate(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError


class _EngineTakingABackend(_ConformingEngine):
    """An engine that names ``backend``, the way the Whitebox one does."""

    engine_id: ClassVar[str] = "test-with-backend"

    def __init__(self, backend: object = None) -> None:
        self.backend = backend


class _EngineMissingAMember(_ConformingEngine):
    """Conforming but for ``delineate``, which the chain always calls.

    Declared and bound to ``None`` rather than absent, because that is the case
    ``hasattr`` lets through: the port says so about its own presence check, and
    a registry that only asked it would build this class and die on the first
    delineation.
    """

    engine_id: ClassVar[str] = "test-incomplete"
    delineate = None  # type: ignore[assignment]


class _EngineWithoutAnId:
    engine_version: ClassVar[str] = "0.1.0"


@pytest.fixture
def clean_registry(monkeypatch: pytest.MonkeyPatch):
    """Isolate the module-level registry state for one test."""
    monkeypatch.setattr(registry, "_REGISTRY", dict(registry._REGISTRY))
    monkeypatch.setattr(registry, "_BUILTIN_PATHS", dict(registry._BUILTIN_PATHS))
    monkeypatch.setattr(registry, "_PLUGINS_LOADED", True)
    return registry


# ---------------------------------------------------------------------------
# What this build declares
# ---------------------------------------------------------------------------


def test_the_build_declares_the_two_engines_it_ships() -> None:
    assert registry.builtin_engine_ids() == ("numpy_d8", "whitebox_workflows")


def test_the_default_is_the_engine_every_committed_number_came_from() -> None:
    assert registry.DEFAULT_ENGINE_ID == "whitebox_workflows"


def test_a_caller_that_names_no_engine_gets_the_default() -> None:
    from hydromodpy.spatial.terrain.whitebox_engine import WhiteboxTerrainEngine

    assert registry.get(None) is WhiteboxTerrainEngine


def test_an_in_tree_engine_resolves_by_its_declared_id() -> None:
    from hydromodpy.spatial.terrain.numpy_engine import NumpyTerrainEngine

    assert registry.get("numpy_d8") is NumpyTerrainEngine


def test_every_declared_id_is_the_engine_id_of_the_class_behind_it() -> None:
    """A second name for one engine is how a request and a seal disagree."""
    for engine_id in registry.builtin_engine_ids():
        assert registry.get(engine_id).engine_id == engine_id


# ---------------------------------------------------------------------------
# What it refuses
# ---------------------------------------------------------------------------


def test_an_unknown_name_is_refused_and_the_message_names_what_is_served() -> None:
    with pytest.raises(TerrainRequestError) as raised:
        registry.get("pysheds")

    message = str(raised.value)
    assert "pysheds" in message
    assert "whitebox_workflows" in message
    assert registry.ENTRY_POINT_GROUP in message


def test_a_class_that_does_not_satisfy_the_port_is_refused_by_name(clean_registry) -> None:
    with pytest.raises(TypeError) as raised:
        clean_registry.register(_EngineMissingAMember)

    assert "delineate" in str(raised.value)


def test_a_class_with_no_engine_id_is_refused(clean_registry) -> None:
    with pytest.raises(TypeError):
        clean_registry.register(_EngineWithoutAnId)


def test_a_second_registration_of_one_id_is_refused_unless_replaced(clean_registry) -> None:
    clean_registry.register(_ConformingEngine)
    with pytest.raises(ValueError):
        clean_registry.register(_ConformingEngine)

    assert clean_registry.register(_ConformingEngine, replace=True) is _ConformingEngine


# ---------------------------------------------------------------------------
# Building one
# ---------------------------------------------------------------------------


def test_an_option_reaches_the_engine_that_names_it(clean_registry) -> None:
    clean_registry.register(_EngineTakingABackend)
    sentinel = object()

    built = clean_registry.create("test-with-backend", backend=sentinel)

    assert built.backend is sentinel


def test_an_option_never_reaches_the_engine_that_does_not_name_it(clean_registry) -> None:
    """The whole reason a caller can pass ``backend`` without knowing the engine."""
    clean_registry.register(_ConformingEngine)

    built = clean_registry.create("test-conforming", backend=object())

    assert isinstance(built, _ConformingEngine)


def test_building_an_unknown_name_raises_the_same_refusal_as_resolving_it() -> None:
    with pytest.raises(TerrainRequestError):
        registry.create("pysheds")


# ---------------------------------------------------------------------------
# The third party, end to end
# ---------------------------------------------------------------------------


def _install_plugin(monkeypatch: pytest.MonkeyPatch, name: str, target: type) -> None:
    """Publish *target* under *name* in the entry-point group, for one test."""

    class _FakeEntryPoint:
        def __init__(self) -> None:
            self.name = name

        def load(self) -> type:
            return target

        def __repr__(self) -> str:  # pragma: no cover - only in warnings
            return f"<entry point {name!r}>"

    monkeypatch.setattr(registry, "_REGISTRY", dict(registry._REGISTRY))
    monkeypatch.setattr(registry, "_BUILTIN_PATHS", dict(registry._BUILTIN_PATHS))
    monkeypatch.setattr(registry, "_PLUGINS_LOADED", False)
    monkeypatch.setattr(
        registry,
        "entry_points",
        lambda group: (_FakeEntryPoint(),) if group == registry.ENTRY_POINT_GROUP else (),
    )


def test_an_engine_installed_beside_this_build_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_plugin(monkeypatch, "test-conforming", _ConformingEngine)

    assert registry.get("test-conforming") is _ConformingEngine
    assert "test-conforming" in registry.list_engine_ids()


def test_a_plugin_taking_a_name_this_build_ships_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A published, byte-gated description names ``whitebox_workflows``."""
    _install_plugin(monkeypatch, "whitebox_workflows", _ConformingEngine)
    from hydromodpy.spatial.terrain.whitebox_engine import WhiteboxTerrainEngine

    assert registry.get("whitebox_workflows") is WhiteboxTerrainEngine


def test_a_plugin_whose_name_is_not_its_engine_id_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_plugin(monkeypatch, "another-name", _ConformingEngine)

    with pytest.raises(TerrainRequestError):
        registry.get("another-name")


def test_a_plugin_that_does_not_satisfy_the_port_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_plugin(monkeypatch, "test-incomplete", _EngineMissingAMember)

    with pytest.raises(TerrainRequestError):
        registry.get("test-incomplete")


def test_a_broken_entry_point_group_does_not_take_down_a_built_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _explode(group: str) -> tuple[object, ...]:
        raise RuntimeError("unreadable distribution metadata")

    monkeypatch.setattr(registry, "_REGISTRY", dict(registry._REGISTRY))
    monkeypatch.setattr(registry, "_PLUGINS_LOADED", False)
    monkeypatch.setattr(registry, "entry_points", _explode)

    assert registry.get("numpy_d8") is not None


REPO_ROOT = Path(__file__).resolve().parents[3]
"""Anchored on this file, never on the working directory.

``Path("hydromodpy").rglob(...)`` reads the cwd, so the two gates below scanned
**zero files and passed** whenever pytest was invoked from anywhere but the
repository root -- ``cd tests && pytest unit/terrain/...`` was enough. A gate
that answers "nothing names it" by looking at nothing is the hollow green F10b
already paid for once, and :func:`_python_files` is what keeps it from being
answerable that way.
"""

SECOND_DISTRIBUTION_NAMES = (
    "hydromodpy-terrain-scipy",
    "hydromodpy_terrain_scipy",
    "scipy_d8",
)
"""Every spelling of the second distribution: the project, the package, the id.

The three are searched and not just the id, because naming the import package in
``hydromodpy/`` would couple the host to it just as surely, and a
``pyproject.toml`` extra naming the project would put it back in the build.
"""


def _python_files(tree: str) -> list[Path]:
    """Return the Python files of one tree, and refuse to return none.

    The floor is the anti-vacuity control: both trees hold hundreds of modules,
    so a handful means the scan is looking somewhere else and the assertion
    below would hold over an empty set.
    """
    files = sorted((REPO_ROOT / tree).rglob("*.py"))
    assert len(files) > 100, f"{tree} scan found {len(files)} files, so it is not scanning {tree}"
    return files


def _names_found(paths: list[Path], names: tuple[str, ...]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {name: [] for name in names}
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        for name in names:
            if name in text:
                found[name].append(str(path.relative_to(REPO_ROOT)))
    return {name: hits for name, hits in found.items() if hits}


def test_no_repository_file_names_the_third_party_engine() -> None:
    """The point of the whole phase, asserted rather than assumed.

    ``hydromodpy-terrain-scipy`` is a real distribution of this tree, installed
    beside the build and resolved through the entry-point group. If it is ever
    named by a module of ``hydromodpy/``, an engine that is supposed to arrive
    from outside has been wired in, and the substitutability the port claims is
    back to being a claim.

    ``pysheds`` is kept alongside it, for ``hydromodpy/`` only: it is the name
    the campaign first planned to ship and the one the tests of this file use as
    an engine no installation serves, so it has to stay absent from the package
    while staying available to the tests.
    """
    assert _names_found(_python_files("hydromodpy"), (*SECOND_DISTRIBUTION_NAMES, "pysheds")) == {}


def test_no_test_of_this_repository_names_the_second_distribution() -> None:
    """The other half: the suites that judge it must not know it either.

    This file is the one exception and says so by excluding itself. It has to
    name the distribution somewhere in order to assert its absence everywhere
    else, which is the same shape the F10b gate takes for its probe.
    """
    elsewhere = [path for path in _python_files("tests") if path != Path(__file__).resolve()]

    assert _names_found(elsewhere, SECOND_DISTRIBUTION_NAMES) == {}


def test_the_naming_gate_sees_a_file_that_does_name_it() -> None:
    """The negative control. Without it the two gates above prove nothing.

    They are string scans, and a string scan that looks at the wrong tree is
    green for free. This one plants every spelling in a file and requires the
    same helper to report all three.
    """
    planted = _names_found([Path(__file__).resolve()], SECOND_DISTRIBUTION_NAMES)

    assert sorted(planted) == sorted(SECOND_DISTRIBUTION_NAMES)


# ---------------------------------------------------------------------------
# The capability refuses at its boundary
# ---------------------------------------------------------------------------


def test_the_capability_refuses_an_engine_this_installation_does_not_serve() -> None:
    from hydromodpy.spatial.site_selection.hydrology.capability import TerrainDelineateRequest
    from hydromodpy.spatial.site_selection.hydrology.worker import (
        _refuse_an_engine_this_installation_does_not_serve,
    )

    inputs = TerrainDelineateRequest.model_validate(
        {
            "dem": {"href": "dem.tif", "type": "image/tiff; application=geotiff"},
            "outlets": [{"site_id": "cheze", "x": 348120.0, "y": 6781450.0}],
            "crs_project": "EPSG:2154",
            "engine": "pysheds",
        }
    )

    with pytest.raises(ConfigValidationError) as raised:
        _refuse_an_engine_this_installation_does_not_serve(inputs)

    assert "inputs.engine" in str(raised.value)
    assert registry.ENTRY_POINT_GROUP in str(raised.value)


def test_a_request_that_names_no_engine_carries_the_default() -> None:
    from hydromodpy.spatial.site_selection.hydrology.capability import TerrainDelineateRequest

    inputs = TerrainDelineateRequest.model_validate(
        {
            "dem": {"href": "dem.tif", "type": "image/tiff; application=geotiff"},
            "outlets": [{"site_id": "cheze", "x": 348120.0, "y": 6781450.0}],
            "crs_project": "EPSG:2154",
        }
    )

    assert inputs.engine == registry.DEFAULT_ENGINE_ID
