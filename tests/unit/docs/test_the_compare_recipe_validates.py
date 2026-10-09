"""The comparison file the guide ships has to be a comparison the schema accepts.

The guide on comparing methods builds its worked case from fragments and ships
the assembled file as a download. A reader copies that file, so it has to load
when the comparison schema moves.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

RECIPE = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "source"
    / "guides"
    / "files"
    / "compare_ims.toml"
)


BASE = RECIPE.with_name("compare_base.toml")
STEP1 = (
    Path(__file__).resolve().parents[3]
    / "examples"
    / "projects"
    / "04_streamflow_intermittence_in_transient"
    / "step1_minimal.toml"
)


def _document() -> dict:
    return tomllib.loads(RECIPE.read_text(encoding="utf-8"))


def test_it_is_a_comparison_the_schema_accepts(tmp_path) -> None:
    from hydromodpy.analysis.comparison.experiment_config import SimulationComparisonConfig

    doc = _document()
    base = tmp_path / "compare_base.toml"
    base.write_text('[workflow]\nmode = "simulation"\n', encoding="utf-8")

    cfg = SimulationComparisonConfig.from_toml(doc, config_path=tmp_path / "compare_ims.toml")

    assert [sim.id for sim in cfg.comparison.simulation] == ["complex", "moderate"]
    assert cfg.comparison.reference_simulation == "complex"


def test_the_reference_is_one_of_the_children() -> None:
    doc = _document()

    ids = {sim["id"] for sim in doc["comparison"]["simulation"]}

    assert doc["comparison"]["reference_simulation"] in ids


def test_it_names_the_ims_option_the_guide_explains() -> None:
    doc = _document()

    moderate = next(s for s in doc["comparison"]["simulation"] if s["id"] == "moderate")

    assert moderate["overlay"]["modflow6"]["runtime"]["mf6_ims_complexity"] == "MODERATE"


def test_the_base_file_is_step_one_with_its_dem_path_written(tmp_path) -> None:
    from hydromodpy.config import HydroModPyConfig

    text = BASE.read_text(encoding="utf-8").replace(
        'base_config = "step1_minimal.toml"', f'base_config = "{STEP1.as_posix()}"'
    )
    base = tmp_path / "compare_base.toml"
    base.write_text(text, encoding="utf-8")

    cfg = HydroModPyConfig.from_toml(base)

    assert cfg.geographic.catchment.dem_init_path.name == "DEM_armorican_massif.tif"
