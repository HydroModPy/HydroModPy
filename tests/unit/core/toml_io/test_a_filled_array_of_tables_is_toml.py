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

import tomllib
from pathlib import Path

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.core.toml_io.generator import generate_toml_from_instances

pytestmark = pytest.mark.fast

_STAGED = {
    "parameters": {
        "K": {"bounds": [1e-8, 1e-2], "search_space": "log"},
        "Sy": {"bounds": [1e-4, 0.5], "search_space": "log"},
    },
    "phases": [
        {
            "name": "steady_conductivity",
            "method": "bisection",
            "parameters": ["K"],
            "variable": "discharge",
            "objective": "nse",
            "method_options": {"sweep_points": 7},
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
            "method_options": {},
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
        root=CalibrationConfig,
    )
    return tomllib.loads(destination.read_text())["calibration"]


def test_an_empty_mapping_survives_as_an_empty_table(written: dict) -> None:
    assert written["phases"][1]["method_options"] == {}


def test_the_entry_parses_at_the_documented_default(tmp_path: Path) -> None:
    """``exclude_none`` defaults to False, and an unset optional is a None.

    ``precision = `` is not a TOML line. The key steps out commented instead,
    and reload restores the None it already defaults to.
    """
    config = CalibrationConfig.model_validate(_STAGED)
    destination = tmp_path / "with_nones.toml"

    generate_toml_from_instances(
        {"calibration": config},
        output_path=destination,
        profile="expert",
        root=CalibrationConfig,
    )
    reloaded = CalibrationConfig.model_validate(
        tomllib.loads(destination.read_text())["calibration"]
    )

    assert reloaded.phases[0].precision is None
    assert reloaded.model_dump(mode="json", exclude_none=True) == config.model_dump(
        mode="json", exclude_none=True
    )
