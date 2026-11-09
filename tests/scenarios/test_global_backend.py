"""The global backend of the run, played through the real pipeline on the basin.

The basin of the catchment walks the catchment mesh and hands the whole domain
to the one-cell global model, the linear reservoir the ``[solver]`` section
names. A river trace the mesh engine ignores is refused when the file is read:
the planner would grade a family the mesh never builds.

The run itself closes at the seal: the one cell is the domain in area, the
``discharge`` series reads at the station of the catchment and ``Run.grid``
answers like any run. On a run of five-day periods and a daily recharge, the
recharge of every day of a period still reaches the run: the source's own step
carries its twenty values, and no reading of the period means can answer for
the water.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest
import zarr

from tests.scenarios.factory import basin_files
from tests.scenarios.launcher import Scenario, play

STEADY_DISCHARGE_M3_S = 1.5e-3 * 610.0 * 610.0 / 86400.0


def _runs(played) -> dict[str, Path]:
    """Return the run folders a played scenario left, by run name."""
    return {Path(path).name: played.root / path for kind, path in played.targets if kind == "run"}


def test_the_basin_runs_its_global_backend_to_the_seal(tmp_path, scenario_env, scenario_cache):
    """The daily basin closes with the global model and reads its series back."""
    scenario = Scenario(
        name="basin_daily",
        covers="a basin run of the catchment, global model on, closed at the seal",
        files=basin_files(),
        argv=("run", "project.toml"),
    )

    played = play(scenario, tmp_path / "play", scenario_env, scenario_cache)

    assert played.returncode == 0, played.log.read_text(encoding="utf-8")[-2000:]
    runs = _runs(played)
    assert list(runs) == ["basin"]
    run = hmp_open(runs["basin"])

    # The one cell of the engine is the whole synthetic domain: 610 m by 610 m.
    assert abs(float(run.grid.catchment_area_m2) - 610.0 * 610.0) < 1.0

    discharge = hmp_read_discharge(run)
    assert isinstance(discharge, pd.Series)
    assert discharge.size == 20
    # The steady state of a constant recharge of 1.5 mm per day over the cell.
    assert float(discharge.iloc[-1]) == pytest.approx(STEADY_DISCHARGE_M3_S, rel=1e-6)


def test_a_recharge_written_at_its_own_step_reaches_the_run_in_twenty_values(
    tmp_path, scenario_env, scenario_cache
):
    """A 5-day run keeps the daily step of its source: 20 native values, not 4."""
    scenario = Scenario(
        name="basin_5d",
        covers="a basin run on five-day periods, the recharge at the step of its source",
        files=basin_files(with_daily_recharge=True),
        argv=("run", "project.toml"),
        timeout_s=300.0,
    )

    played = play(scenario, tmp_path / "play", scenario_env, scenario_cache)

    assert played.returncode == 0, played.log.read_text(encoding="utf-8")[-2000:]
    runs = _runs(played)
    assert list(runs) == ["basin_5d"]
    fields = zarr.open(str(runs["basin_5d"] / "fields.zarr"), mode="r")
    # A point source is kept under its station id, the one row of the
    # station table the factory writes.
    recharge = fields["forcing"]["recharge"]
    assert sorted(recharge.group_keys()) == ["BASIN_5D"]
    forcing = recharge["BASIN_5D"]

    values = forcing["values"][:]
    timestamps = forcing["timestamps"][:].astype("datetime64[ns]")
    assert values.size == 20
    steps = pd.Series(timestamps).diff().dropna()
    assert bool((steps == pd.Timedelta(days=1)).all())


def hmp_open(run_dir: Path):
    """Open one run folder with the facade, from the test process."""
    import hydromodpy as hmp

    return hmp.open(run_dir)


def hmp_read_discharge(run):
    """Read the whole-catchment discharge series of one run."""
    import hydromodpy as hmp

    return hmp.read(run, "discharge", sel={"station": "catchment"})


def test_a_river_trace_written_beside_the_basin_is_refused(tmp_path, scenario_env, scenario_cache):
    """A family the mesh engine ignores is refused with its own sentence."""
    files = basin_files()
    files["project.toml"] = files["project.toml"].replace(
        "[data]",
        '[mesh.families]\nrivers = "cell"\n\n[data]',
    )
    scenario = Scenario(
        name="basin_rivers",
        covers="a basin run whose mesh carries a river trace the basin engine ignores",
        files=files,
        argv=("run", "project.toml"),
    )

    played = play(scenario, tmp_path / "play", scenario_env, scenario_cache)

    log = played.log.read_text(encoding="utf-8")
    assert played.returncode != 0, log[-2000:]
    said = re.search(
        r"rivers = [\"']cell[\"'], and the mesh engine\s+'?catchment'? ignores it", log
    )
    assert said is not None, log[-2000:]
