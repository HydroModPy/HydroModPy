"""The K tensor past K and Kv is checked when the project file is read.

K22 and the three angles reach MODFLOW 6 only, so MODFLOW-NWT and Boussinesq
refuse them. An angle takes no vertical profile, and a dip stays within a
quarter turn.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigValidationError

PROJECT_TOML = """
[workflow]
mode = "simulation"

[workspace]

[geographic]
source_mode = "synthetic"
crs_project = "EPSG:2154"

[solver]
backend = {{ backend = "{backend}" }}

[flow]
param_list = ["K", {ids}]

[flow.param.K.field]
kind = "homogeneous"
value = "1e-5 m/s"
{params}
"""

PARAM = """
[flow.param.{param_id}.field]
kind = "homogeneous"
value = {value}
"""

PROFILE = """
[flow.param.{param_id}.field_vertical_profile]
mode = "exponential"
characteristic_depth = "15 m"
"""


def _load(
    tmp_path: Path,
    values: dict[str, str],
    *,
    backend: str = "modflow6",
    profile_on: str | None = None,
) -> HydroModPyConfig:
    params = "".join(
        PARAM.format(param_id=param_id, value=value) for param_id, value in values.items()
    )
    if profile_on is not None:
        params += PROFILE.format(param_id=profile_on)
    path = tmp_path / "project.toml"
    path.write_text(
        PROJECT_TOML.format(
            backend=backend,
            ids=", ".join(f'"{param_id}"' for param_id in values),
            params=params,
        ),
        encoding="utf-8",
    )
    return HydroModPyConfig.from_toml(path)


TENSOR = {"K22": '"2e-6 m/s"', "angle1": "30.0", "angle2": "-20.0", "angle3": "5.0"}


def test_modflow6_reads_k22_and_the_three_angles(tmp_path: Path) -> None:
    cfg = _load(tmp_path, TENSOR)
    assert set(cfg.flow.param) == {"K", *TENSOR}


@pytest.mark.parametrize("backend", ["modflow_nwt", "boussinesq"])
def test_a_solver_without_the_tensor_refuses_an_angle(tmp_path: Path, backend: str) -> None:
    with pytest.raises(ConfigValidationError, match="only MODFLOW 6 reads"):
        _load(tmp_path, {"angle2": "10.0"}, backend=backend)


def test_modflow_nwt_refuses_k22(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError, match="K22"):
        _load(tmp_path, {"K22": '"2e-6 m/s"'}, backend="modflow_nwt")


def test_an_angle_with_a_vertical_profile_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError, match="scale the angle with depth"):
        _load(tmp_path, {"angle1": "30.0"}, profile_on="angle1")


def test_k22_takes_a_vertical_profile_like_k(tmp_path: Path) -> None:
    cfg = _load(tmp_path, {"K22": '"2e-6 m/s"'}, profile_on="K22")
    assert cfg.flow.param["K22"].field_vertical_profile is not None


def test_a_dip_past_the_vertical_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError, match="dip of the K tensor"):
        _load(tmp_path, {"angle2": "120.0"})
