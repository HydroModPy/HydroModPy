"""A reference configuration a reader copies has to load.

Four shapes are documented: one parameter against one gauge, several targets
weighted against each other, a published protocol named instead of retyped,
and that same protocol's two stages written out by hand. They are shipped as
real TOML rather than as fenced snippets so a rename of a key breaks them here
rather than in the reader's terminal.
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
    "calibration_staged_by_hand",
)


_STUB_PROJECT = """
[workspace]
project_root = "."

[workflow]
mode = "simulation"

[geographic]
source_mode = "synthetic"

# A calibration moves a parameter the project declares, so the project has to
# declare it. This is the smallest project any of the three recipes can sit on.
[flow]
param_list = ["K", "Sy"]

[flow.param.K.field]
id = "K"
kind = "homogeneous"
unit = "m/s"
value = 6.4e-5

[flow.param.Sy.field]
id = "Sy"
kind = "homogeneous"
unit = "-"
value = 0.05
"""


def _beside_a_project(name: str, tmp_path) -> Path:
    """Copy one recipe next to a project, which is how a reader uses it."""
    (tmp_path / "project.toml").write_text(_STUB_PROJECT, encoding="utf-8")
    (tmp_path / "streams.gpkg").write_bytes(b"")
    target = tmp_path / f"{name}.toml"
    target.write_text((RECIPES / f"{name}.toml").read_text(encoding="utf-8"), encoding="utf-8")
    return target


def _calibration(name: str, tmp_path) -> CalibrationConfig:
    raw = expand_calibration_protocol(load_toml_with_base_config(_beside_a_project(name, tmp_path)))
    return CalibrationConfig.model_validate(raw["calibration"])


def test_every_recipe_is_an_overlay_on_a_project() -> None:
    """A calibration file carries the search; the model it runs comes from the project."""
    import tomllib

    for name in _NAMES:
        raw = tomllib.loads((RECIPES / f"{name}.toml").read_text(encoding="utf-8"))
        assert raw["base_config"] == "project.toml", name
        assert raw["workflow"]["mode"] == "calibration", name


def test_no_recipe_redeclares_the_catchment() -> None:
    """Redeclaring it here is how a calibration and its run drift apart."""
    import tomllib

    for name in _NAMES:
        raw = tomllib.loads((RECIPES / f"{name}.toml").read_text(encoding="utf-8"))
        assert "workspace" not in raw, name
        assert set(raw.get("geographic", {})) <= {"enforce_streams"}, name


def test_the_four_recipes_are_shipped() -> None:
    assert sorted(path.stem for path in RECIPES.glob("*.toml")) == sorted(_NAMES)


@pytest.mark.parametrize("name", _NAMES)
def test_a_recipe_loads(name: str, tmp_path) -> None:
    assert _calibration(name, tmp_path) is not None


def test_the_single_gauge_recipe_scores_one_series(tmp_path) -> None:
    cfg = _calibration("calibration_single_gauge", tmp_path)

    assert cfg.objective_blocks == []
    assert cfg.variable == "discharge"
    assert list(cfg.parameters) == ["K"]


def test_the_multi_objective_weights_read_as_shares(tmp_path) -> None:
    cfg = _calibration("calibration_multi_objective", tmp_path)

    weights = {block.name: block.weight for block in cfg.objective_blocks}
    assert weights == {"hydrograph": 0.65, "piezometry": 0.25, "lake": 0.10}
    assert sum(weights.values()) == pytest.approx(1.0)


def test_the_protocol_recipe_expands_into_the_published_two_stages(tmp_path) -> None:
    cfg = _calibration("calibration_matching_hydrographic_network", tmp_path)

    assert cfg.protocol is not None
    assert [phase.name for phase in cfg.phases or []] == [
        "steady_conductivity",
        "transient_storage",
    ]
    assert cfg.objective_blocks[0].metric == "distance_gap"
    assert cfg.phases[0].overrides["simulation.time.step_value"] == 9497


def test_the_staged_by_hand_recipe_writes_the_same_two_stages(tmp_path) -> None:
    cfg = _calibration("calibration_staged_by_hand", tmp_path)

    assert cfg.protocol is None
    assert [phase.name for phase in cfg.phases or []] == [
        "steady_conductivity",
        "transient_storage",
    ]
    assert cfg.phases[0].objective_blocks == ["network_extent"]
    assert cfg.phases[1].objective_blocks == ["hydrograph", "network_extent"]
    assert cfg.phases[1].depends_on == "steady_conductivity"
    assert cfg.phases[0].overrides["flow.flow_regime"] == "steady"
    assert cfg.phases[1].overrides["flow.flow_regime"] == "transient"

    blocks = {block.name: block for block in cfg.objective_blocks}
    assert blocks["hydrograph"].metric == "nse_log"
    assert blocks["hydrograph"].warmup == 12
    assert blocks["network_extent"].metric == "distance_gap"
