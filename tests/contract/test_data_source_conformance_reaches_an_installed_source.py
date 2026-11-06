"""The conformance suite of the data-source port reaches a source it does not name.

``add-a-data-source.rst`` tells a plugin author to run the suite from a clone, with the
plugin installed. This file installs a source the suite has never heard of and runs the
suite on it, in a subprocess because ``importlib.metadata`` reads the entry points once.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ._installed_probe import REPO_ROOT, collected, run_suite, unpack

# One worker runs the file, so the collection below runs once.
pytestmark = pytest.mark.xdist_group("data_source_conformance_probe")

SUITE = "tests/contract/test_data_source_contract.py"
PROBE_ID = "conformance-probe-gauge"

PROBE_MODULE = """\
from hydromodpy.data.source import require_period, require_selectors


class ProbeSource:
    source_id = "conformance-probe-gauge"
    payload_kind = "points"
    extent_crs = "EPSG:4326"
    selectors = ("extent",)
    period_need = "required"
    hosts = ("probe.example",)
    writes_out_dir = False
    variables = ("probe_level",)

    def fetch(self, request):
        require_selectors(self, request)
        require_period(self, request)
        raise AssertionError("the suite reached the provider of a source it cannot stub")
"""


@pytest.fixture(scope="module")
def installed_probe(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A module and its ``.dist-info``, what a wheel unpacks to. No build, no network."""
    return unpack(
        tmp_path_factory.mktemp("probe_site_packages"), "hmp_source_probe", PROBE_MODULE,
        "hydromodpy.data.source", PROBE_ID, "ProbeSource",
    )  # fmt: skip


def test_the_suite_holds_an_installed_source_to_its_declarations_and_refusals(
    installed_probe: Path, tmp_path: Path
) -> None:
    listing = run_suite(SUITE, tmp_path / "collect", "--collect-only", "-q", site_packages=installed_probe)  # fmt: skip
    assert listing.returncode == 0, listing.stdout[-4000:]
    nodes = [line for line in listing.stdout.splitlines() if PROBE_ID in line]
    assert len(nodes) >= 6, listing.stdout[-4000:]

    result = run_suite(SUITE, tmp_path / "run", "-q", "-k", PROBE_ID, site_packages=installed_probe)  # fmt: skip

    assert result.returncode == 0, result.stdout[-8000:]
    passed = re.search(r"(\d+) passed", result.stdout)
    assert passed is not None and int(passed.group(1)) == len(nodes), result.stdout[-4000:]
