"""The conformance suite of the data-source port reaches a source it does not name.

``add-a-data-source.rst`` tells a plugin author to run the suite from a clone, with the
plugin installed. This file installs a source the suite has never heard of and runs the
suite on it, in a subprocess because ``importlib.metadata`` reads the entry points once.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

# One worker runs the file, so the collection below runs once.
pytestmark = pytest.mark.xdist_group("data_source_conformance_probe")

REPO_ROOT = Path(__file__).resolve().parents[2]
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


def _pytest(session: Path, site_packages: Path, *arguments: str) -> subprocess.CompletedProcess:
    environment = dict(os.environ)
    environment.pop("PYTEST_XDIST_WORKER", None)
    entries = [site_packages, REPO_ROOT, environment.get("PYTHONPATH")]
    environment["PYTHONPATH"] = os.pathsep.join(str(entry) for entry in entries if entry)
    return subprocess.run(
        [sys.executable, "-m", "pytest", SUITE, "-p", "no:randomly", "-p", "no:cacheprovider",
         f"--basetemp={session}", *arguments],
        cwd=str(REPO_ROOT),
        env=environment,
        capture_output=True,
        text=True,
        timeout=600,
    )  # fmt: skip


@pytest.fixture(scope="module")
def installed_probe(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A module and its ``.dist-info``, what a wheel unpacks to. No build, no network."""
    root = tmp_path_factory.mktemp("probe_site_packages")
    (root / "hmp_source_probe.py").write_text(PROBE_MODULE, encoding="utf-8")
    dist_info = root / "hmp_source_probe-0.1.0.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: hmp-source-probe\nVersion: 0.1.0\n", encoding="utf-8"
    )
    (dist_info / "entry_points.txt").write_text(
        f"[hydromodpy.data.source]\n{PROBE_ID} = hmp_source_probe:ProbeSource\n", encoding="utf-8"
    )
    return root


def test_the_suite_holds_an_installed_source_to_its_declarations_and_refusals(
    installed_probe: Path, tmp_path: Path
) -> None:
    collected = _pytest(tmp_path / "collect", installed_probe, "--collect-only", "-q")
    assert collected.returncode == 0, collected.stdout[-4000:]
    nodes = [line for line in collected.stdout.splitlines() if PROBE_ID in line]
    assert len(nodes) >= 6, collected.stdout[-4000:]

    result = _pytest(tmp_path / "run", installed_probe, "-q", "-k", PROBE_ID)

    assert result.returncode == 0, result.stdout[-8000:]
    passed = re.search(r"(\d+) passed", result.stdout)
    assert passed is not None and int(passed.group(1)) == len(nodes), result.stdout[-4000:]
