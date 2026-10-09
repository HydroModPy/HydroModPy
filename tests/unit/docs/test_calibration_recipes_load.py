"""The four calibration recipes a reader downloads have to load on example 04.

They are shipped as real TOML files, offered for download by the page
``guides/calibration-recipes``, and written to sit beside ``project.toml`` of
example 04. Each one is loaded here on top of that very file, through the
loader the CLI uses, so a renamed key or a date outside the example breaks this
test rather than the reader's first run.
"""

from __future__ import annotations

import shutil
import tomllib
from datetime import date
from pathlib import Path

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.protocols import expand_calibration_protocol
from hydromodpy.calibration.runners.phase_regime import phase_overrides
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.toml_io.loader import load_toml_with_base_config

ROOT = Path(__file__).resolve().parents[3]
RECIPES = ROOT / "docs" / "source" / "guides" / "recipes"
EX04 = ROOT / "examples" / "projects" / "04_streamflow_intermittence_in_transient"
PAGE = ROOT / "docs" / "source" / "guides" / "calibration-recipes.md"

_NAMES = (
    "calibration_single_gauge",
    "calibration_multi_objective",
    "calibration_matching_hydrographic_network",
    "calibration_staged_by_hand",
)


def _raw(name: str) -> dict:
    return tomllib.loads((RECIPES / f"{name}.toml").read_text(encoding="utf-8"))


def _beside_example_04(name: str, tmp_path: Path) -> Path:
    """Copy the recipe next to the project file of example 04, as the page says."""
    shutil.copy(EX04 / "project.toml", tmp_path / "project.toml")
    target = tmp_path / f"{name}.toml"
    shutil.copy(RECIPES / f"{name}.toml", target)
    return target


def _document(name: str, tmp_path: Path) -> dict:
    return expand_calibration_protocol(
        load_toml_with_base_config(_beside_example_04(name, tmp_path))
    )


def _calibration(name: str, tmp_path: Path) -> CalibrationConfig:
    return CalibrationConfig.model_validate(_document(name, tmp_path)["calibration"])


def _window_of_example_04() -> tuple[date, date]:
    project = tomllib.loads((EX04 / "project.toml").read_text(encoding="utf-8"))
    time = project["simulation"]["time"]
    return date.fromisoformat(time["start_datetime"]), date.fromisoformat(time["end_datetime"])


def test_the_four_recipes_are_shipped() -> None:
    assert sorted(path.stem for path in RECIPES.glob("calibration_*.toml")) == sorted(_NAMES)


def test_the_page_offers_each_recipe_for_download() -> None:
    text = PAGE.read_text(encoding="utf-8")
    for name in _NAMES:
        assert f"{{download}}`recipes/{name}.toml`" in text, name


@pytest.mark.parametrize("name", _NAMES)
def test_a_recipe_points_at_the_project_file_of_example_04(name: str) -> None:
    raw = _raw(name)
    assert raw["base_config"] == "project.toml", name
    assert (EX04 / raw["base_config"]).is_file()
    assert raw["workflow"]["mode"] == "calibration", name
    assert "workspace" not in raw and "geographic" not in raw, name


@pytest.mark.parametrize("name", _NAMES)
def test_a_recipe_loads_on_example_04(name: str, tmp_path) -> None:
    cfg = HydroModPyConfig.from_toml(_beside_example_04(name, tmp_path))
    assert cfg.calibration is not None


@pytest.mark.parametrize("name", _NAMES)
def test_a_recipe_keeps_the_time_window_of_the_example(name: str) -> None:
    """A recipe that moves the dates outside the example's data cannot run on it."""
    raw = _raw(name)
    assert "time" not in raw.get("simulation", {}), name
    first, last = _window_of_example_04()
    text = (RECIPES / f"{name}.toml").read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("start =", "end =")):
            day = date.fromisoformat(stripped.split("=", 1)[1].strip().strip('"'))
            assert first <= day <= last, (name, stripped)


@pytest.mark.parametrize("name", _NAMES)
def test_a_recipe_names_a_protocol_in_one_form(name: str) -> None:
    """``[calibration.protocol] name = ...`` is the form every page teaches."""
    protocol = _raw(name).get("calibration", {}).get("protocol")
    assert protocol is None or isinstance(protocol, dict), name


@pytest.mark.parametrize("name", _NAMES)
def test_no_recipe_counts_its_spin_up_in_samples(name: str) -> None:
    """A spin-up is written in dates, which mean the same span at any step."""
    text = (RECIPES / f"{name}.toml").read_text(encoding="utf-8")
    written = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    assert not any(line.lstrip().startswith(("warmup ", "warmup=")) for line in written)
    assert not any(line.lstrip().startswith("warmup_periods") for line in written)


def test_the_single_gauge_recipe_scans_one_parameter(tmp_path) -> None:
    cfg = _calibration("calibration_single_gauge", tmp_path)

    assert list(cfg.parameters) == ["K"]
    assert cfg.method == "grid"
    assert [block.metric for block in cfg.objective_blocks] == ["nse_log"]
    assert cfg.scoring_window is not None
    assert cfg.scoring_window.start == "2001-01-01"


def test_the_multi_objective_weights_read_as_shares(tmp_path) -> None:
    cfg = _calibration("calibration_multi_objective", tmp_path)

    weights = {block.name: block.weight for block in cfg.objective_blocks}
    assert weights == {"hydrograph": 0.7, "network": 0.3}
    assert sum(weights.values()) == pytest.approx(1.0)
    blocks = {block.name: block for block in cfg.objective_blocks}
    assert blocks["network"].normalize_cost is True


def test_the_protocol_recipe_expands_into_the_published_two_stages(tmp_path) -> None:
    raw = _document("calibration_matching_hydrographic_network", tmp_path)
    cfg = CalibrationConfig.model_validate(raw["calibration"])

    assert cfg.protocol is not None
    assert [phase.name for phase in cfg.phases or []] == [
        "steady_conductivity",
        "transient_storage",
    ]
    assert cfg.objective_blocks[0].metric == "distance_gap"
    assert phase_overrides(cfg.phases[0], raw)["flow.flow_regime"] == "steady"


def test_the_staged_by_hand_recipe_writes_the_same_two_stages(tmp_path) -> None:
    raw = _document("calibration_staged_by_hand", tmp_path)
    cfg = CalibrationConfig.model_validate(raw["calibration"])

    assert cfg.protocol is None
    assert [phase.name for phase in cfg.phases or []] == [
        "steady_conductivity",
        "transient_storage",
    ]
    assert cfg.phases[0].objective_blocks == ["network_extension"]
    assert cfg.phases[1].objective_blocks == {"hydrograph": 0.8, "network_share": 0.2}
    assert cfg.phases[1].scoring_window is not None
    assert cfg.phases[1].scoring_window.start == "2001-01-01"
    assert cfg.phases[1].depends_on == "steady_conductivity"
    assert phase_overrides(cfg.phases[0], raw)["flow.flow_regime"] == "steady"
    assert phase_overrides(cfg.phases[1], raw)["flow.flow_regime"] == "transient"
    assert cfg.phases[0].method == "bisection"
    assert cfg.phases[1].method is None

    blocks = {block.name: block for block in cfg.objective_blocks}
    assert blocks["hydrograph"].metric == "nse_log"
    assert blocks["network_extension"].normalize_cost is False
    assert blocks["network_share"].normalize_cost is True
