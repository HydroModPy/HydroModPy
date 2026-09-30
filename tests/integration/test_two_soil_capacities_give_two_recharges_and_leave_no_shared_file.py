"""A calibrated soil capacity gets its own recharge folder, never a shared one.

``run_trial_light`` marks a trial's sandbox with ``PRIVATE_TRIAL_RECHARGE_KEY``
only when the phase samples a value the recharge is computed from
(``_trial_owns_its_recharge``); MODFLOW 6 then writes RCHA into
``<trial>/_recharge`` instead of the phase's ``_shared_recharge``. This is the
full-pipeline proof, on a real MODFLOW 6 solve: two trials of a phase that
samples ``ru`` write two different recharge stacks, each in its own folder,
removed with the trial unless kept for debugging; a phase that samples only
``K``, soil frozen, shares one recharge like every other run.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

_NPER = 100
_DAYS = pd.date_range("2001-01-01", periods=_NPER, freq="D")
_SAFRAN_X = np.array([250.0, 750.0])
_SAFRAN_Y = np.array([250.0, 750.0])
_RAIN_MEAN_MM_DAY = {(0, 0): 3.0, (0, 1): 4.0, (1, 0): 2.0, (1, 1): 5.0}
_RU_PATH = "flow.sinks_sources.recharge.soil.ru"
_K_PATH = "flow.param.K.field.value"

# A synthetic 20 x 20 grid of 50 m cells (1 km x 1 km), covered by a 2 x 2
# SAFRAN grid, transient MODFLOW 6, soil mode. `transit_time` and a gamma /
# sinusoidal forcing (not a short repeating cycle) keep the recharge and EVTA
# stacks above the binary threshold for every ru: a periodic input settles
# into an exactly-repeating float64 cycle within the window and collapses.
_PROJECT_TOML = """
[workflow]
mode = "simulation"

[workspace]
project_root = "{root}"

[simulation]
name = "soil_two_ru"

[simulation.time]
start_datetime = "2001-01-01"
end_datetime = "2001-04-10"
step_value = "1 day"

[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["modflow6"]

[geographic]
source_mode = "synthetic"
crs_project = "EPSG:2154"

[geographic.synthetic]
case_id = "soil_two_ru"

[geographic.synthetic.grid]
length_x = "1000 m"
length_y = "1000 m"
nx = 20
ny = 20

[geographic.synthetic.topography]
kind = "linear"
base_elevation = 20.0
right_to_left_amplitude = 5.0

[domain.depth_model]
kind = "constant_thickness"
thickness = "20 m"

[data]
types = ["precipitation", "etp"]

[[data.precipitation.sources]]
source = "custom"
path = "{precip_path}"

[[data.etp.sources]]
source = "custom"
path = "{etp_path}"

[flow]
param_list = ["K", "Sy", "Ss"]
active_sinks_sources = ["recharge", "etp"]
active_bc = ["drainage"]
first_period_steady = false

[flow.ic]
type = "steady_state"

[flow.param.K.field]
kind = "homogeneous"
unit = "m/s"
value = 1e-5

[flow.param.Sy.field]
kind = "homogeneous"
unit = "-"
value = 0.1

[flow.param.Ss.field]
kind = "homogeneous"
unit = "m-1"
value = 1e-5

[flow.sinks_sources.recharge.soil]
ru = "150 mm"
spinup = "none"
transit_time = "5 days"

[display]
enabled = false
"""


def _write_forcing_netcdf(path: Path, name: str, values: np.ndarray) -> None:
    dataset = xr.Dataset(
        {name: (("time", "y", "x"), values)},
        coords={"time": _DAYS.values, "y": _SAFRAN_Y, "x": _SAFRAN_X},
    )
    dataset.attrs["crs"] = "EPSG:2154"
    dataset[name].attrs["nodata"] = -9999.0
    dataset.to_netcdf(path)


def _precipitation_values() -> np.ndarray:
    """Gamma-distributed daily rain, one shape per SAFRAN cell, never repeating."""
    rng = np.random.default_rng(0)
    arr = np.zeros((_NPER, 2, 2))
    for (iy, ix), mean in _RAIN_MEAN_MM_DAY.items():
        arr[:, iy, ix] = rng.gamma(shape=0.6, scale=mean / 0.6, size=_NPER)
    return arr


def _etp_values() -> np.ndarray:
    """A smooth, never-repeating seasonal-like curve, same on every cell."""
    day = np.arange(_NPER)
    curve = 2.0 + 1.0 * np.sin(2.0 * np.pi * day / 40.0)
    return np.broadcast_to(curve[:, None, None], (_NPER, 2, 2)).copy()


def _write_project(tmp_path: Path) -> Path:
    precip_path = tmp_path / "precip.nc"
    etp_path = tmp_path / "etp.nc"
    _write_forcing_netcdf(precip_path, "precipitation", _precipitation_values())
    _write_forcing_netcdf(etp_path, "etp", _etp_values())
    config_path = tmp_path / "project.toml"
    config_path.write_text(
        _PROJECT_TOML.format(
            root=tmp_path.as_posix(),
            precip_path=precip_path.as_posix(),
            etp_path=etp_path.as_posix(),
        ),
        encoding="utf-8",
    )
    return config_path


@pytest.fixture(scope="module", autouse=True)
def _ensure_bootstrap():
    """Wire the deferred TrialPipelineProvider before any run_trial_light call."""
    import hydromodpy

    hydromodpy.bootstrap()


def _zero_metric(ctx, *, objective, variable):
    return 0.0, {}


def _prepare(tmp_path: Path, *, override_paths, parameter_space):
    from hydromodpy.calibration.runners.trial import prepare_trials

    config_path = _write_project(tmp_path)
    return prepare_trials(
        config_path, override_paths=override_paths, parameter_space=parameter_space
    )


def _ru_space():
    from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace

    return ParameterSpace([CalibParameter(name="ru", lower=10.0, upper=500.0, path=_RU_PATH)])


def _k_space():
    from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace

    return ParameterSpace([CalibParameter(name="K", lower=1e-7, upper=1e-3, path=_K_PATH)])


def _recharge_digest(recharge_dir: Path) -> str:
    period_zero = sorted(recharge_dir.glob("rcha_*.0.bin"))
    assert len(period_zero) == 1, f"expected one period-0 recharge file in {recharge_dir}"
    return period_zero[0].name.split("_", 1)[1].split(".", 1)[0]


@pytest.mark.integration
@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.allow_subprocess
def test_two_ru_trials_write_two_recharges_in_their_own_folders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hydromodpy.calibration.runners.trial import run_trial_light

    monkeypatch.setenv("HMP_KEEP_TRIAL_SCRATCH", "1")
    prepared = _prepare(tmp_path, override_paths={"ru": _RU_PATH}, parameter_space=_ru_space())
    scratch = Path(prepared.ctx.setup.workspace.solver_scratch_folder)

    digests: dict[int, str] = {}
    for trial_id, ru in ((1, 50.0), (2, 200.0)):
        result = run_trial_light(prepared, {"ru": ru}, metric_fn=_zero_metric, trial_id=trial_id)
        assert result.status == "completed", result.error
        recharge_dir = scratch / f"soil_two_ru_trial{trial_id:06d}" / "_recharge"
        assert recharge_dir.is_dir()
        digests[trial_id] = _recharge_digest(recharge_dir)

    assert digests[1] != digests[2]
    assert not list(scratch.rglob("_shared_recharge"))


@pytest.mark.integration
@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.allow_subprocess
def test_a_trial_that_is_not_kept_removes_its_recharge_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hydromodpy.calibration.runners.trial import run_trial_light

    monkeypatch.delenv("HMP_KEEP_TRIAL_SCRATCH", raising=False)
    prepared = _prepare(tmp_path, override_paths={"ru": _RU_PATH}, parameter_space=_ru_space())
    scratch = Path(prepared.ctx.setup.workspace.solver_scratch_folder)

    result = run_trial_light(prepared, {"ru": 50.0}, metric_fn=_zero_metric, trial_id=1)

    assert result.status == "completed", result.error
    assert not (scratch / "soil_two_ru_trial000001").exists()


@pytest.mark.integration
@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.allow_subprocess
def test_a_k_only_phase_shares_the_frozen_soils_recharge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hydromodpy.calibration.runners.trial import run_trial_light

    monkeypatch.setenv("HMP_KEEP_TRIAL_SCRATCH", "1")
    prepared = _prepare(tmp_path, override_paths={"K": _K_PATH}, parameter_space=_k_space())
    scratch = Path(prepared.ctx.setup.workspace.solver_scratch_folder)

    result = run_trial_light(prepared, {"K": 2.0e-5}, metric_fn=_zero_metric, trial_id=1)

    assert result.status == "completed", result.error
    assert (scratch / "_shared_recharge").is_dir()
    assert not (scratch / "soil_two_ru_trial000001" / "_recharge").exists()
