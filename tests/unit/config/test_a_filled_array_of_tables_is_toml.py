"""A mapping inside an array-of-tables entry is written as TOML, not as Python.

``generate_toml_from_instances`` formatted an entry's values with a helper that
knew scalars, paths, quantities and lists. A dict fell through to ``str(val)``,
which is a Python repr: ``overrides = {'flow.flow_regime': 'steady'}``, with
single quotes and no ``=``. The file did not parse at all, and nothing noticed
because the only section that fills such a table -- a staged calibration -- was
refused earlier for another reason.

The dotted keys are the second half of it: ``simulation.time.step_value`` left
bare is a path into three nested tables, not the one key an override names.
"""

from __future__ import annotations

import copy
import tomllib
from pathlib import Path

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.core.toml_io.generator import generate_toml_from_instances

pytestmark = pytest.mark.fast

_STAGED = {
    "parameters": {
        "K": {"bounds": [1e-8, 1e-2], "transform": "log"},
        "Sy": {"bounds": [1e-4, 0.5], "transform": "log"},
    },
    "phases": [
        {
            "name": "steady_conductivity",
            "method": "bisection",
            "parameters": ["K"],
            "variable": "discharge",
            "objective": "nse",
            "optimizer_kwargs": {"sweep_points": 7},
            "overrides": {
                "flow.flow_regime": "steady",
                "simulation.time.start_datetime": "2000-01-01T00:00:00",
                "simulation.time.step_value": 1096,
            },
        },
        {
            "name": "transient_storage",
            "method": "scipy_nelder_mead",
            "parameters": ["Sy"],
            "variable": "discharge",
            "objective": "nse_log",
            "depends_on": "steady_conductivity",
            "optimizer_kwargs": {},
            "overrides": {"flow.flow_regime": "transient"},
        },
    ],
}


@pytest.fixture
def written(tmp_path: Path) -> dict:
    config = CalibrationConfig.model_validate(_STAGED)
    destination = tmp_path / "staged.toml"
    generate_toml_from_instances(
        {"calibration": config},
        output_path=destination,
        profile="expert",
        exclude_none=True,
    )
    return tomllib.loads(destination.read_text())["calibration"]


def test_the_entry_parses_and_keeps_its_dotted_keys_whole(written: dict) -> None:
    overrides = written["phases"][0]["overrides"]

    assert overrides["simulation.time.step_value"] == 1096
    assert overrides["simulation.time.start_datetime"] == "2000-01-01T00:00:00"
    assert overrides["flow.flow_regime"] == "steady"


def test_an_empty_mapping_survives_as_an_empty_table(written: dict) -> None:
    assert written["phases"][1]["optimizer_kwargs"] == {}


def test_the_staged_calibration_reloads_into_itself(written: dict) -> None:
    expected = CalibrationConfig.model_validate(_STAGED)

    reloaded = CalibrationConfig.model_validate(written)

    assert reloaded.model_dump(mode="json", exclude_none=True) == expected.model_dump(
        mode="json", exclude_none=True
    )


def test_the_entry_parses_at_the_documented_default(tmp_path: Path) -> None:
    """``exclude_none`` defaults to False, and an unset optional is a None.

    ``tolerance = `` is not a TOML line. The key steps out commented instead,
    and reload restores the None it already defaults to.
    """
    config = CalibrationConfig.model_validate(_STAGED)
    destination = tmp_path / "with_nones.toml"

    generate_toml_from_instances({"calibration": config}, output_path=destination, profile="expert")
    reloaded = CalibrationConfig.model_validate(
        tomllib.loads(destination.read_text())["calibration"]
    )

    assert reloaded.phases[0].tolerance is None
    assert reloaded.model_dump(mode="json", exclude_none=True) == config.model_dump(
        mode="json", exclude_none=True
    )


def test_a_quote_and_a_newline_in_a_value_survive(tmp_path: Path) -> None:
    """A raw quote ends the string early and a raw newline ends the line."""
    staged = copy.deepcopy(_STAGED)
    staged["phases"][0]["description"] = 'a "quoted" word\nand a second line'
    config = CalibrationConfig.model_validate(staged)
    destination = tmp_path / "escaped.toml"

    generate_toml_from_instances(
        {"calibration": config}, output_path=destination, profile="expert", exclude_none=True
    )
    written = tomllib.loads(destination.read_text())["calibration"]

    assert written["phases"][0]["description"] == 'a "quoted" word\nand a second line'


def test_a_none_inside_a_mapping_steps_out_rather_than_breaking_the_file(
    tmp_path: Path,
) -> None:
    """TOML has no null, so the key cannot be written at all."""
    staged = copy.deepcopy(_STAGED)
    staged["phases"][0]["overrides"]["flow.unset"] = None
    config = CalibrationConfig.model_validate(staged)
    destination = tmp_path / "with_null.toml"

    generate_toml_from_instances(
        {"calibration": config}, output_path=destination, profile="expert", exclude_none=True
    )
    overrides = tomllib.loads(destination.read_text())["calibration"]["phases"][0]["overrides"]

    assert "flow.unset" not in overrides
    assert overrides["flow.flow_regime"] == "steady"
