"""The bounds of ``mode = "scale"`` are factors, faced with nothing physical.

A scale multiplies the base value of the file, so ``[0.5, 2]`` on a specific
yield says "half to twice". The bounds were faced with the physical ceiling of
the property as if they were its values, and ``Sy`` scaled by ``[0.5, 2]`` was
refused, "upper bound 2.0 outside [0.0001, 0.5]", while the product the run
writes is checked anyway.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.calibration.optim.parameters import (
    ParameterSpace,
    apply_parameter_to_config,
)
from hydromodpy.calibration.preflight import _check_bounds_against_physics


def _space(mode: str) -> ParameterSpace:
    return ParameterSpace.from_toml_mapping(
        {"Sy": {"bounds": [0.5, 2.0], "mode": mode, "path": "flow.sy"}}
    )


def test_a_scale_of_half_to_twice_is_accepted() -> None:
    (parameter,) = _space("scale").parameters

    assert (parameter.lower, parameter.upper, parameter.mode) == (0.5, 2.0, "scale")


def test_the_same_bounds_as_values_are_still_refused() -> None:
    with pytest.raises(ValueError, match="upper bound 2.0"):
        _space("replace")


def test_the_product_is_still_faced_with_the_ceiling() -> None:
    (parameter,) = _space("scale").parameters
    cfg = SimpleNamespace(flow=SimpleNamespace(sy=0.3))

    apply_parameter_to_config(cfg, parameter, 1.5)
    assert cfg.flow.sy == pytest.approx(0.45)
    with pytest.raises(ValueError, match="candidate"):
        apply_parameter_to_config(cfg, parameter, 2.0)


def test_the_check_says_nothing_of_a_scale() -> None:
    decl = SimpleNamespace(mode="scale", units=None, search_space="identity")

    assert _check_bounds_against_physics("calibration.parameters.Sy", "Sy", decl, [0.5, 2.0]) == []


PROJECT = """\
[site]
name = "p"

[geographic]
crs_project = "EPSG:2154"

[geographic.catchment]
catch_def = "from_outlet_coord"
dem_init_path = "DEM.tif"
x_outlet = 389285.9
y_outlet = 6816518.7
snap_dist = "150 m"
buff_area = "10%"

[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2002-12-31"
step_value = 1
step_unit = "month"

[flow]
param_list = ["K", "Sy"]

[flow.param.K.field]
kind = "homogeneous"
unit = "m/s"
value = 5e-5

[flow.param.Sy.field]
kind = "homogeneous"
unit = "-"
value = 0.05

[workflow]
mode = "calibration"

[calibration.parameters.Sy]
bounds = [0.5, 2.0]
mode = "scale"
"""


def test_a_scale_on_a_catalogue_name_loads(tmp_path) -> None:
    from hydromodpy.config import HydroModPyConfig

    (tmp_path / "data" / "dem").mkdir(parents=True)
    (tmp_path / "data" / "dem" / "DEM.tif").write_bytes(b"x")
    project = tmp_path / "projects" / "p"
    project.mkdir(parents=True)
    (project / "project.toml").write_text(PROJECT, encoding="utf-8")

    cfg = HydroModPyConfig.from_toml(project / "project.toml")

    assert cfg.calibration.parameters["Sy"].bounds == [0.5, 2.0]
