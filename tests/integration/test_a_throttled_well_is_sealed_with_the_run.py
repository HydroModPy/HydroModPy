"""A well cut by AUTO_FLOW_REDUCE is sealed with the run, on a real MODFLOW 6 solve.

A well in the first layer of the crest of a small island asks for far more water
than the cell holds. The solve cuts it; the run must say so in its metrics and
in the checks of its seal, and a well the cell can feed must pass.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._helpers.island_project import island_toml, run_island

pytestmark = [
    pytest.mark.integration,
    pytest.mark.mf6,
    pytest.mark.binary,
    pytest.mark.slow,
    pytest.mark.allow_subprocess,
]


def _sealed(root: Path, name: str, well_flux: float) -> dict:
    root.mkdir(parents=True)
    config = root / "project.toml"
    config.write_text(island_toml(name, well_flux=well_flux), encoding="utf-8")
    run_island(config)
    return json.loads((root / "runs" / name / "manifest.json").read_text(encoding="utf-8"))


def _wells_validity(manifest: dict) -> dict:
    (validity,) = [v for v in manifest["checks"]["validities"] if v["name"] == "wells_pumped"]
    return validity


def test_a_starved_well_fails_the_wells_pumped_check(tmp_path: Path) -> None:
    manifest = _sealed(tmp_path / "starved", "starved", well_flux=-2.0)

    validity = _wells_validity(manifest)
    assert validity["passed"] is False
    assert validity["fatal"] is False
    assert 0.0 < validity["value"] < 90.0
    assert "AUTO_FLOW_REDUCE" in validity["message"]


def test_a_well_the_cell_can_feed_passes_the_check(tmp_path: Path) -> None:
    manifest = _sealed(tmp_path / "fed", "fed", well_flux=-0.00001)

    validity = _wells_validity(manifest)
    assert validity["passed"] is True
    assert validity["value"] > 99.0
