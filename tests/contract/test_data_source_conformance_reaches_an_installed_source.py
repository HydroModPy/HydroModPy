"""The conformance suite of the data-source port reaches a source it does not name.

``add-a-data-source.rst`` tells a plugin author to run the suite from a clone, with the
plugin installed. This file installs a source the suite has never heard of and runs the
suite on it, in a subprocess because ``importlib.metadata`` reads the entry points once.

The entry point of the probe carries the joined name the registry keys it on,
``<section>_<source_id>``: a third-party source serves a section of its own choosing --
one no shipped TOML model describes -- and the name it is published under is the section
and the id joined by ``_``, exactly the rule the solver backends follow.
"""

from __future__ import annotations

import re
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import ClassVar

import pytest

import hydromodpy.core.plugin_registry as plugin_registry
from hydromodpy.core.exceptions import DataRequestError
from hydromodpy.data.source import registry

from ._installed_probe import run_suite, unpack

# One worker runs the file, so the collection below runs once.
pytestmark = pytest.mark.xdist_group("data_source_conformance_probe")

SUITE = "tests/contract/test_data_source_contract.py"
PROBE_SECTION = "conformance-probe"
PROBE_ID = "conformance-probe-gauge"
PROBE_KEY = f"{PROBE_SECTION}_{PROBE_ID}"

PROBE_MODULE = """\\
from hydromodpy.data.source.port import require_period, require_selectors


class ProbeSource:
    source_id = "conformance-probe-gauge"
    section = "conformance-probe"
    payload_kind = "points"
    extent_crs = "EPSG:4326"
    selectors = ("extent",)
    period_need = "required"
    writes_out_dir = False
    variables = ("probe_level",)
    hosts = ("probe.example",)

    def fetch(self, request):
        require_selectors(self, request)
        require_period(self, request)
        raise AssertionError("the suite reached the provider of a source it cannot stub")
"""


@pytest.fixture(scope="module")
def installed_probe(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A module and its ``.dist-info``, what a wheel unpacks to. No build, no network."""
    return unpack(
        tmp_path_factory.mktemp("probe_site_packages"),
        "hmp_source_probe",
        PROBE_MODULE,
        "hydromodpy.data.source",
        PROBE_KEY,
        "ProbeSource",
    )  # fmt: skip


def test_the_suite_holds_an_installed_source_to_its_declarations_and_refusals(
    installed_probe: Path, tmp_path: Path
) -> None:
    listing = run_suite(SUITE, tmp_path / "collect", "--collect-only", "-q", site_packages=installed_probe)  # fmt: skip
    assert listing.returncode == 0, listing.stdout[-4000:]
    nodes = [line for line in listing.stdout.splitlines() if PROBE_KEY in line]
    assert len(nodes) >= 6, listing.stdout[-8000:]
    # One test of the suite is a shipped-only one: the licence table has no
    # entry for a foreign source, and the suite skips it for one by design.
    shipped_only = [node for node in nodes if "reads_its_hosts_in_the_licence_table" in node]
    assert len(shipped_only) == 1, nodes

    result = run_suite(SUITE, tmp_path / "run", "-q", "-k", PROBE_KEY, site_packages=installed_probe)  # fmt: skip

    assert result.returncode == 0, result.stdout[-8000:]
    passed = re.search(r"(\d+) passed", result.stdout)
    assert passed is not None and int(passed.group(1)) == len(nodes) - len(shipped_only), (
        result.stdout[-4000:]
    )


class _IdOnlyProbeSource:
    """The probe source, published under its id alone: a name that is not a key."""

    source_id: ClassVar[str] = PROBE_ID
    section: ClassVar[str] = PROBE_SECTION
    payload_kind: ClassVar[str] = "points"
    extent_crs: ClassVar[str] = "EPSG:4326"
    selectors: ClassVar[tuple[str, ...]] = ("extent",)
    period_need: ClassVar[str] = "required"
    writes_out_dir: ClassVar[bool] = False
    variables: ClassVar[tuple[str, ...]] = ("probe_level",)
    hosts: ClassVar[tuple[str, ...]] = ("probe.example",)

    def fetch(self, request):  # pragma: no cover - never reached
        raise AssertionError("a source published under a name that is not its key answers nothing")


def test_a_probe_published_under_its_id_alone_registers_nothing(
    isolated_registry: object,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The entry-point name is the joined key; the class declares it and cannot diverge.

    A name that is not what the class declares is ignored with a warning, on the
    rule D21 set for the solver backends: the name is what a document writes,
    the id is what the run is stamped with, and two words for one plugin is how
    they start describing different things.
    """
    bare = EntryPoint(
        name=PROBE_ID,
        value="tests.stub:ProbeSource",
        group=registry.ENTRY_POINT_GROUP,
    )
    object.__setattr__(bare, "load", lambda: _IdOnlyProbeSource)
    monkeypatch.setattr(
        plugin_registry,
        "entry_points",
        lambda *, group: (bare,),
    )
    with caplog.at_level("WARNING"):
        assert registry.data_sources.load_plugins() == 0
    assert PROBE_ID in caplog.text
    with pytest.raises(DataRequestError):
        registry.data_sources.get(PROBE_SECTION, PROBE_ID)
