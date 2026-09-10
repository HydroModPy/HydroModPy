"""A reference configuration a reader copies has to load.

Three shapes are documented: one parameter against one gauge, several targets
weighted against each other, and a published protocol named instead of retyped.
They are shipped as real TOML rather than as fenced snippets so a rename of a
key breaks them here rather than in the reader's terminal.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.protocols import expand_calibration_protocol
from hydromodpy.core.toml_io.loader import load_toml_with_base_config

RECIPES = Path(__file__).resolve().parents[3] / "docs" / "source" / "user_guide" / "recipes"

_NAMES = (
    "calibration_single_gauge",
    "calibration_multi_objective",
    "calibration_matching_hydrographic_network",
)


def _calibration(name: str) -> CalibrationConfig:
    raw = expand_calibration_protocol(load_toml_with_base_config(RECIPES / f"{name}.toml"))
    return CalibrationConfig.model_validate(raw["calibration"])


def test_the_three_recipes_are_shipped() -> None:
    assert sorted(path.stem for path in RECIPES.glob("*.toml")) == sorted(_NAMES)


@pytest.mark.parametrize("name", _NAMES)
def test_a_recipe_loads(name: str) -> None:
    assert _calibration(name) is not None


def test_the_single_gauge_recipe_scores_one_series() -> None:
    cfg = _calibration("calibration_single_gauge")

    assert cfg.objective_blocks == []
    assert cfg.variable == "discharge"
    assert list(cfg.parameters) == ["K"]


def test_the_multi_objective_weights_read_as_shares() -> None:
    cfg = _calibration("calibration_multi_objective")

    weights = {block.name: block.weight for block in cfg.objective_blocks}
    assert weights == {"hydrograph": 0.65, "piezometry": 0.25, "lake": 0.10}
    assert sum(weights.values()) == pytest.approx(1.0)


def test_the_protocol_recipe_expands_into_the_published_two_stages() -> None:
    cfg = _calibration("calibration_matching_hydrographic_network")

    assert cfg.protocol is not None
    assert [phase.name for phase in cfg.phases or []] == [
        "steady_conductivity",
        "transient_storage",
    ]
    assert cfg.objective_blocks[0].metric == "distance_gap"
    assert cfg.phases[0].overrides["simulation.time.step_value"] == 9497
