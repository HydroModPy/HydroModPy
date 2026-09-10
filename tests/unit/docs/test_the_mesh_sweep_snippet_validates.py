"""The mesh sweep the docs print has to be a comparison the schema accepts.

The refusal a user meets when they try to calibrate a mesh points at this
snippet, so a snippet that does not load sends them from one dead end to
another. It is extracted from the page and validated here, which is what stops
it drifting when the comparison schema moves.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

PAGE = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "source"
    / "user_guide"
    / "workflows"
    / "calibration-recipes.rst"
)


def _snippet() -> dict:
    text = PAGE.read_text(encoding="utf-8")
    block = text.split("# mesh_sweep.toml")[1].split(".. code-block:: bash")[0]
    body = "\n".join(
        line[3:] if line.startswith("   ") else line for line in block.splitlines()
    )
    return tomllib.loads(body)


def test_the_page_still_ships_the_snippet() -> None:
    assert "# mesh_sweep.toml" in PAGE.read_text(encoding="utf-8")


def test_it_is_a_comparison_the_schema_accepts(tmp_path) -> None:
    from hydromodpy.analysis.comparison.experiment_config import SimulationComparisonConfig

    doc = _snippet()
    base = tmp_path / "project.toml"
    base.write_text("[workflow]\nmode = \"simulation\"\n", encoding="utf-8")
    doc["comparison"]["base_simulation_config"] = base.name

    cfg = SimulationComparisonConfig.from_toml(doc, config_path=tmp_path / "sweep.toml")

    assert [sim.id for sim in cfg.comparison.simulation] == ["mesh_500", "mesh_350", "mesh_250"]


def test_every_run_states_the_mesh_it_is_there_for(tmp_path) -> None:
    doc = _snippet()

    sizes = [
        run["overlay"]["mesh_catchment"]["zone_meshing"]["global_size"]
        for run in doc["comparison"]["simulation"]
    ]

    assert sizes == sorted(sizes, reverse=True)
    assert len(set(sizes)) == len(sizes)


def test_it_compares_the_quantity_the_criterion_reads() -> None:
    names = {item["variable"] for item in _snippet()["comparison"]["observable"]}

    assert "seepage_areas" in names
