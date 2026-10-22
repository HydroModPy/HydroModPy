"""End-to-end: ``hmp calibrate`` never opens the index.

``Catalog.__init__`` is patched to raise for the whole command. The search
runs on a real MODFLOW 6 model (a six-cell steady hillslope, two grid points
on K), journals its trials under ``sessions/<case>/`` and promotes its best
trial under ``runs/<case>/``. ``.hmp/index.duckdb`` does not exist afterwards.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.results.session.descriptor import read_session
from hydromodpy.results.session.journal import read_trials

_PROJECT_TOML = """\
[simulation]
name = "hillslope"

[simulation.time]
start_datetime = "2003-01-01 00:00:00"
end_datetime = "2003-01-02 00:00:00"
step_value = "1 day"
coverage_policy = "ignore"

[[simulation.process]]
id = "flow"
type = "flow"
solvers = ["modflow6"]

[workspace]

[geographic]
source_mode = "synthetic"
crs_project = "EPSG:2154"

[geographic.synthetic]
case_id = "never_opens_the_index"

[geographic.synthetic.grid]
length_x = "12 m"
length_y = "2 m"
nx = 6
ny = 1

[geographic.synthetic.topography]
kind = "linear"
base_elevation = 10.0
right_to_left_amplitude = 1.0

[domain.depth_model]
kind = "constant_thickness"
thickness = "5 m"

[flow]
flow_regime = "steady"
active_sinks_sources = ["recharge"]
active_bc = ["drainage"]
param_list = ["K"]

[flow.param.K.field]
kind = "homogeneous"
unit = "m/s"
value = 5e-6

[flow.ic]
type = "top"

[flow.bc.drainage]
application_domain = "top"
kind = "cauchy"
value = "0.0 m2/s"

[flow.sinks_sources.recharge]
first_clim = "mean"

[data]
types = ["recharge"]
inference_mode = "warn"

[[data.recharge.sources]]
source = "synthetic"
values = [0.8]
runoff_ratio = 0.0

[mesh.regular]
shape = [1, 6]

[modflow6.sgrid.vertical]
nlay = 1

[display]
enabled = false
"""

_CALIBRATION = """\
base_config = "project.toml"

[calibration]
method = "grid"
method_options = {{ points_per_dim = 2 }}
variable = "head"
objective = "rmse"
save_runs = "{save_runs}"
use_cache = false

[calibration.parameters.K]
bounds = [1e-6, 1e-4]
search_space = "log"
path = "flow.param.K.field.value"
"""

STATION = "W1"
_CELL = (0, 0, 3)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    import hydromodpy

    hydromodpy.bootstrap()
    root = tmp_path / "hillslope"
    root.mkdir()
    (root / "project.toml").write_text(_PROJECT_TOML, encoding="utf-8")
    return root


def _wire_the_station(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hand the single-metric route a station, the way a project's loader would.

    The record is dated, as a loaded one always is, and the run has one dated
    period to pair it on.
    """
    from hydromodpy.calibration.metrics import composite
    from hydromodpy.calibration.metrics.series import ObservedSeries

    record = pd.Series([5.0, 5.0, 5.0], index=pd.date_range("2003-01-01", periods=3, freq="D"))
    observed = [ObservedSeries(station_id=STATION, variable="head", series=record)]
    monkeypatch.setattr(composite, "load_observed", lambda ctx, variable: observed)
    monkeypatch.setattr(
        composite, "resolve_station_cells", lambda ctx, obs, **kwargs: {STATION: _CELL}
    )


def _refuse_the_index(monkeypatch: pytest.MonkeyPatch) -> None:
    from hydromodpy.results.catalog import facade

    def _refuse(self, *args, **kwargs):
        raise AssertionError("the calibration opened the index")

    monkeypatch.setattr(facade.Catalog, "__init__", _refuse)


@pytest.mark.e2e
@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.allow_subprocess
def test_the_search_never_opens_the_index(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary

    ensure_solver_binary("mf6")
    _wire_the_station(monkeypatch)
    _refuse_the_index(monkeypatch)
    (project / "calage.toml").write_text(_CALIBRATION.format(save_runs="none"), encoding="utf-8")
    import hydromodpy as hmp

    report = hmp.calibrate(project / "calage.toml")

    assert report.n_iterations == 2
    session_dir = project / "sessions" / "calage"
    assert report.session_dir == session_dir
    assert read_session(session_dir).status == "completed"
    assert [line.trial for line in read_trials(session_dir)] == [1, 2]
    assert (session_dir / "config.toml").is_file()
    assert not (project / ".hmp" / "index.duckdb").exists()


@pytest.mark.e2e
@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.allow_subprocess
def test_the_promotion_never_opens_the_index(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The calibrated run is written beside the session by the run pipeline, without the index."""
    from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary

    ensure_solver_binary("mf6")
    _wire_the_station(monkeypatch)
    _refuse_the_index(monkeypatch)
    (project / "calage.toml").write_text(_CALIBRATION.format(save_runs="best_n"), encoding="utf-8")
    import hydromodpy as hmp

    report = hmp.calibrate(project / "calage.toml")

    assert report.promoted == 1
    assert report.best_rel_dir == "runs/calage"
    assert (project / "runs" / "calage" / "manifest.json").is_file()
    best = read_session(project / "sessions" / "calage").best
    assert best is not None and best.rel_dir == "runs/calage"
    assert not (project / ".hmp" / "index.duckdb").exists()
