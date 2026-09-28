"""``validity_length`` on a network output: "auto" or a positive length.

``roptim_max`` is gone from the schema: a file that still carries it loads
through the config migration, never through the model.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import validate_calib_output


def _network(**overrides):
    return validate_calib_output(
        {"support": "network", "stream_geometry_path": "streams.gpkg", **overrides}
    )


def test_auto_is_the_default() -> None:
    assert _network().validity_length == "auto"


@pytest.mark.parametrize(("declared", "metres"), [("150 m", 150.0), ("0.3 km", 300.0), (75, 75.0)])
def test_a_length_is_read_in_metres(declared: object, metres: float) -> None:
    output = _network(validity_length=declared)

    assert float(output.validity_length.to("m").magnitude) == pytest.approx(metres)
    assert output.model_dump()["validity_length"] == pytest.approx(metres)


@pytest.mark.parametrize("declared", ["0 m", "-10 m", "2 s", "two cells"])
def test_a_length_that_is_not_one_is_refused(declared: str) -> None:
    with pytest.raises(ValidationError):
        _network(validity_length=declared)


def test_the_ratio_bound_is_no_longer_a_field() -> None:
    with pytest.raises(ValidationError, match="roptim_max"):
        _network(roptim_max=2.0)


def test_a_declared_length_reaches_the_scoring_options() -> None:
    from hydromodpy.calibration.metrics.solver_extract import _scoring_options

    assert _scoring_options(_network())["validity_length_m"] is None
    assert _scoring_options(_network(validity_length="300 m"))["validity_length_m"] == 300.0


_CALIBRATION = """
[calibration]
method = "bisection"

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
transform = "log"
path = "flow.param.K.field.value"
units = "m/s"

[[calibration.objective_blocks]]
name = "gap"
metric = "distance_gap"
uses_outputs = ["net"]

[calibration.outputs.net]
support = "network"
stream_geometry_path = "streams.gpkg"
roptim_max = {value}
"""


def _calibration_file(tmp_path, value: str):
    path = tmp_path / "calibration.toml"
    path.write_text(_CALIBRATION.format(value=value), encoding="utf-8")
    return path


def test_the_calibration_loader_migrates_the_paper_ratio(tmp_path) -> None:
    """``hmp calibrate`` reads the file the doctor would fix, without the doctor."""
    from hydromodpy.calibration.runners.cli_runner import load_toml_calibration

    path = _calibration_file(tmp_path, "2")
    before = path.read_bytes()

    cfg, raw = load_toml_calibration(path)

    assert cfg.outputs["net"].validity_length == "auto"
    assert "roptim_max" not in raw["calibration"]["outputs"]["net"]
    assert path.read_bytes() == before


def test_the_calibration_loader_refuses_another_ratio_by_name(tmp_path) -> None:
    from hydromodpy.calibration.runners.cli_runner import load_toml_calibration
    from hydromodpy.core.exceptions import ConfigError

    path = _calibration_file(tmp_path, "3")

    with pytest.raises(ConfigError, match="validity_length") as raised:
        load_toml_calibration(path)

    assert path.name in str(raised.value)
    assert "roptim_max = 3 has no exact equivalent" in str(raised.value)
