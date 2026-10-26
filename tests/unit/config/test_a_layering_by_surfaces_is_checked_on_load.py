"""A layering by surfaces is checked when the project file is read.

Its rasters and ``[data.layer_base]`` name the same bases, MODFLOW-NWT reads it
only when a thin layer keeps its minimum thickness, and a vertical profile of K
on fewer than five layers is warned about.
"""

from __future__ import annotations

import logging
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

[domain.layers]
{layers}

[flow]
param_list = ["K"]

[flow.param.K.field]
kind = "homogeneous"
value = "1e-5 m/s"
{profile}
{data}
"""

SURFACES = """genmtd_lay = "surfaces"
pinch_out = "{pinch_out}"

[[domain.layers.layer]]
name = "weathered"
surface = "weathered_base"

[[domain.layers.layer]]
name = "rock"
"""

LAYER_BASE = """
[[data.layer_base.sources]]
name = "{name}"
path = "weathered.tif"
"""

PROFILE = """
[flow.param.K.field_vertical_profile]
mode = "exponential"
characteristic_depth = "15 m"
"""


def _load(
    tmp_path: Path,
    *,
    backend: str = "modflow6",
    pinch_out: str = "pass_through",
    base_name: str | None = "weathered_base",
    layers: str | None = None,
    profile: str = "",
) -> HydroModPyConfig:
    (tmp_path / "weathered.tif").touch()
    path = tmp_path / "project.toml"
    path.write_text(
        PROJECT_TOML.format(
            backend=backend,
            layers=layers or SURFACES.format(pinch_out=pinch_out),
            profile=profile,
            data="" if base_name is None else LAYER_BASE.format(name=base_name),
        ),
        encoding="utf-8",
    )
    return HydroModPyConfig.from_toml(path)


def test_a_layering_by_surfaces_loads_with_its_layer_base(tmp_path: Path) -> None:
    cfg = _load(tmp_path)

    assert cfg.domain.layers.base_surface_names == ("weathered_base",)
    assert [source.name for source in cfg.data.layer_base.sources] == ["weathered_base"]


def test_a_base_surface_no_data_declares_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError, match=r"does not declare them"):
        _load(tmp_path, base_name=None)


def test_a_declared_base_no_layer_reads_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError, match=r"no layer of \[domain.layers\] reads"):
        _load(tmp_path, base_name="other_base", layers='genmtd_lay = "constant"\nnlay = 2')


def test_modflow_nwt_refuses_pass_through_cells_on_load(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError, match="MODFLOW-NWT does not have"):
        _load(tmp_path, backend="modflow_nwt")


def test_modflow_nwt_reads_a_layering_that_keeps_the_minimum_thickness(tmp_path: Path) -> None:
    cfg = _load(tmp_path, backend="modflow_nwt", pinch_out="keep_min_thickness")

    assert not cfg.domain.layers.has_pass_through_cells


def test_a_k_profile_on_fewer_than_five_layers_is_warned_about(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        _load(tmp_path, profile=PROFILE)

    assert "builds 2 layer(s)" in caplog.text
    assert "at least five layers" in caplog.text


def test_a_k_profile_on_five_layers_is_not_warned_about(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        _load(
            tmp_path,
            base_name=None,
            layers='genmtd_lay = "constant"\nnlay = 5',
            profile=PROFILE,
        )

    assert "at least five layers" not in caplog.text
