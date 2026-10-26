"""Boussinesq refuses a layering it would ignore.

Boussinesq solves one layer over the whole aquifer and never reads
``[domain.layers]``. A file, a calibration phase or an older solver table that
asks it for more than one layer, or for layers by surfaces, is refused when it
is read. A sealed run is read as it was run, with a warning. The adapter refuses
it again at the solve, for a layering assigned after the load.
"""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigError, ConfigValidationError
from hydromodpy.solver.boussinesq.adapters.flow import BoussinesqFlowAdapter
from hydromodpy.spatial.domain.layers_config import VerticalGridConfig

pytestmark = pytest.mark.unit

PROJECT_TOML = """
[workflow]
mode = "simulation"

[workspace]

[geographic]
source_mode = "synthetic"
crs_project = "EPSG:2154"

[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["{solver}"]

[mesh]
engine = "triangle"

[flow]
param_list = ["K"]

[flow.param.K.field]
kind = "homogeneous"
value = "1e-5 m/s"
{extra}
"""

CALIBRATION = """
[calibration]
method = "grid"

[calibration.parameters.K]
bounds = [1e-9, 1e-3]
path = "flow.param.K.field.value"

[[calibration.phases]]
name = "deep"
parameters = ["K"]

[calibration.phases.overrides]
{overrides}
"""

SURFACES = """
[domain.layers]
genmtd_lay = "surfaces"

[[domain.layers.layer]]
name = "weathered"
depth = 15.0

[[domain.layers.layer]]
name = "rock"
"""

PROFILE = """
[flow.param.K.field_vertical_profile]
mode = "exponential"
characteristic_depth = "15 m"
"""

IGNORED = "boussinesq would ignore"


def _write(tmp_path: Path, extra: str = "", *, solver: str = "boussinesq") -> Path:
    path = tmp_path / "project.toml"
    path.write_text(PROJECT_TOML.format(solver=solver, extra=extra), encoding="utf-8")
    return path


def _load(tmp_path: Path, extra: str = "", *, solver: str = "boussinesq") -> HydroModPyConfig:
    return HydroModPyConfig.from_toml(_write(tmp_path, extra, solver=solver))


@pytest.mark.parametrize(
    "layers",
    [
        "",
        "[domain.layers]\nnlay = 1\n",
        '[domain.layers]\ngenmtd_lay = "list"\nlay_proportions = [1.0]\n',
    ],
    ids=["default", "one_constant_layer", "one_listed_layer"],
)
def test_one_layer_loads(tmp_path: Path, layers: str) -> None:
    cfg = _load(tmp_path, layers)

    assert cfg.domain.layers.layer_count == 1


@pytest.mark.parametrize(
    ("layers", "asked"),
    [
        ("[domain.layers]\nnlay = 3\n", "builds 3 layers (genmtd_lay = 'constant')"),
        (
            '[domain.layers]\ngenmtd_lay = "decay"\nnlay = 4\nlay_decay = 2.0\n',
            "builds 4 layers (genmtd_lay = 'decay')",
        ),
        (
            '[domain.layers]\ngenmtd_lay = "list"\nlay_proportions = [0.4, 0.6]\n',
            "builds 2 layers (genmtd_lay = 'list')",
        ),
    ],
    ids=["constant", "decay", "list"],
)
def test_more_than_one_layer_is_refused(tmp_path: Path, layers: str, asked: str) -> None:
    with pytest.raises(ConfigValidationError) as excinfo:
        _load(tmp_path, layers)

    message = str(excinfo.value)
    assert f"[domain.layers] {asked}, which {IGNORED}" in message
    assert "Remove [domain.layers], or run the flow with 'modflow6' or 'modflow_nwt'" in message


def test_layers_by_surfaces_are_refused_even_for_one_layer(tmp_path: Path) -> None:
    one = '[domain.layers]\ngenmtd_lay = "surfaces"\n\n[[domain.layers.layer]]\nname = "all"\n'
    for layers in (SURFACES, one):
        with pytest.raises(ConfigValidationError) as excinfo:
            _load(tmp_path, layers)

        message = str(excinfo.value)
        assert "gives each layer its own base (genmtd_lay = 'surfaces')" in message
        assert "sgrid.vertical" not in message


def test_modflow6_still_reads_the_layers(tmp_path: Path) -> None:
    cfg = _load(tmp_path, SURFACES, solver="modflow6")

    assert cfg.domain.layers.layer_count == 2


def test_an_older_solver_table_is_refused_with_the_same_message(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError) as excinfo:
        _load(tmp_path, "[modflow6.sgrid.vertical]\nnlay = 5\n")

    message = str(excinfo.value)
    assert f"[domain.layers] builds 5 layers (genmtd_lay = 'constant'), which {IGNORED}" in message
    assert "[modflow6.sgrid.vertical] or [modflownwt.sgrid.vertical] of an older file" in message


@pytest.mark.parametrize(
    "override",
    ['"domain.layers.nlay" = 3', '"modflow6.sgrid.vertical.nlay" = 3'],
    ids=["dotted_override", "older_dotted_override"],
)
def test_a_phase_that_asks_for_layers_is_refused(tmp_path: Path, override: str) -> None:
    with pytest.raises(ConfigValidationError) as excinfo:
        _load(tmp_path, CALIBRATION.format(overrides=override))

    message = str(excinfo.value)
    assert (
        "the domain.layers override of calibration phase 'deep' builds 3 layers "
        f"(genmtd_lay = 'constant'), which {IGNORED}"
    ) in message


def test_a_phase_that_keeps_one_layer_loads(tmp_path: Path) -> None:
    cfg = _load(tmp_path, CALIBRATION.format(overrides='"domain.layers.nodata" = -1.0'))

    assert cfg.calibration.phases[0].overrides == {"domain.layers.nodata": -1.0}


def test_a_sealed_run_reads_with_a_warning(caplog: pytest.LogCaptureFixture) -> None:
    snapshot = tomllib.loads(
        PROJECT_TOML.format(solver="boussinesq", extra="[domain.layers]\nnlay = 3\n")
    )
    with caplog.at_level(logging.WARNING):
        cfg = HydroModPyConfig.from_snapshot(snapshot)

    assert cfg.domain.layers.layer_count == 3
    assert IGNORED in caplog.text
    assert "This sealed run was solved on one layer." in caplog.text


def test_a_k_profile_says_boussinesq_reads_the_top_only(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        _load(tmp_path, PROFILE)

    assert "boussinesq reads K at the top of the aquifer only" in caplog.text
    assert "at least five layers" not in caplog.text


def test_the_adapter_refuses_a_layering_assigned_after_the_load() -> None:
    layers = VerticalGridConfig(nlay=3)
    ctx = SimpleNamespace(
        state=SimpleNamespace(cfg=SimpleNamespace(domain=SimpleNamespace(layers=layers)))
    )

    with pytest.raises(ConfigError, match=rf"builds 3 layers .*{IGNORED}"):
        BoussinesqFlowAdapter().execute(ctx)
