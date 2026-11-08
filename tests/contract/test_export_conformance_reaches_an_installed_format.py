"""The export conformance suite runs an out-of-tree format it does not name.

``add-an-exporter.rst`` guides a format author to run the suite from a clone,
with their package installed. This file installs an export format the suite has
never heard of and runs the contract suite on it in a child interpreter,
proving that out-of-tree discovery via the ``hydromodpy.export.format`` entry-point
group works without any changes in HydroModPy.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ._installed_probe import collected, run_suite, unpack

pytestmark = pytest.mark.xdist_group("export_format_conformance_probe")

SUITE = "tests/contract/test_export_format_contract.py"
PROBE_FORMAT_ID = "conformance_probe_format"

PROBE_MODULE = """\\
from pathlib import Path
from typing import ClassVar


class ConformanceProbeFormat:
    name: ClassVar[str] = "conformance_probe_format"
    suffix: ClassVar[str] = ".conformance"
    writes: ClassVar[tuple[str, ...]] = ("run",)
    natural: ClassVar[tuple[str, ...]] = ()
    instants: ClassVar[str] = "many"
    reprojects: ClassVar[bool] = False
    help: ClassVar[str] = "Conformance probe format for export contract tests."

    def write(self, job, item, dest: Path) -> list[Path]:
        dest_path = Path(dest)
        out = dest_path / "probe_view.conformance" if dest_path.is_dir() else dest_path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("conformance probe output\\n", encoding="utf-8")
        return [out]
"""


@pytest.fixture(scope="module")
def installed_probe(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A module and its ``.dist-info``, what a wheel unpacks to."""
    return unpack(
        tmp_path_factory.mktemp("probe_site_packages"),
        "hmp_export_probe",
        PROBE_MODULE,
        "hydromodpy.export.format",
        PROBE_FORMAT_ID,
        "ConformanceProbeFormat",
    )


def test_the_suite_collects_nothing_for_a_format_that_is_not_installed(tmp_path: Path) -> None:
    """Without the probe installed, the suite names no probe format."""
    listing = run_suite(SUITE, tmp_path / "uninstalled", "--collect-only", "-q")
    assert listing.returncode == 0, listing.stdout
    assert collected(listing.stdout, SUITE, PROBE_FORMAT_ID) == []


def test_the_suite_holds_an_installed_format_to_its_declarations_and_contract(
    installed_probe: Path, tmp_path: Path
) -> None:
    """An out-of-tree format is discovered, collected and tested against the contract."""
    listing = run_suite(
        SUITE, tmp_path / "collect", "--collect-only", "-q", site_packages=installed_probe
    )
    assert listing.returncode == 0, listing.stdout
    nodes = collected(listing.stdout, SUITE, PROBE_FORMAT_ID)
    assert len(nodes) >= 2, listing.stdout

    result = run_suite(
        SUITE, tmp_path / "run", "-q", "-k", PROBE_FORMAT_ID, site_packages=installed_probe
    )
    assert result.returncode == 0, result.stdout
    passed = re.search(r"(\d+) passed", result.stdout)
    assert passed is not None and int(passed.group(1)) == len(nodes), result.stdout
