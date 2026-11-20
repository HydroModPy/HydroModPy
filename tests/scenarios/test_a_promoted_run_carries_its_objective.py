"""A promoted run carries the objective its session minimized, and is labeled by it.

``hmp calibrate calib.toml`` plays a grid of three values of Sy on the transient island,
scored on the head of W1. The phase declares its window. The run the session
promotes is scored again on the calibration period of its seal, by the pairing the trials used, so its ``metrics``
table holds a row of role ``calibration`` whose value is the cost of the trial. The seal
names the rule the cost was read under and its components. The label is read under
rule 3: the run is calibrated because a window was scored, and a value on a bound of
its range adds the reason ``bound_reached``. The text of its method renders in English
and in French.
"""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path

import pyarrow.parquet as pq

from hydromodpy.core.fields.precision import MAX_RELATIVE_ERROR
from hydromodpy.results.method import method_text
from hydromodpy.results.metric_rule import CALIBRATION_ROLE, METRIC_RULE_VERSION
from hydromodpy.results.record.label import label_of
from hydromodpy.results.record.manifest import read_seal
from hydromodpy.results.session.journal import read_trials
from hydromodpy.results.storage.contract import PARQUET_FILE_SUFFIX, TABLES_DIRNAME
from hydromodpy.results.validity_rules import RULE_VERSION
from tests.scenarios.factory import island_files
from tests.scenarios.launcher import Scenario, play

VARIANT = "calage_sy"

WINDOW = 'window = { start = "2003-01-01", end = "2003-03-31" }\n'
"""The window the phase scores, written out so the trials and the run read the same days."""


def _files() -> dict[str, str]:
    """The transient island calibrated on Sy, its phase scoring a declared window."""
    files = dict(island_files(VARIANT))
    phase = 'regime = "transient"\n'
    assert files["calib.toml"].count(phase) == 1
    files["calib.toml"] = files["calib.toml"].replace(phase, phase + WINDOW)
    return files


def test_a_promoted_run_carries_its_objective(tmp_path: Path, scenario_env, scenario_cache) -> None:
    scenario = Scenario(
        name=VARIANT,
        covers="a promoted run scored on its calibration period, its objective sealed",
        files=_files(),
        argv=("calibrate", "calib.toml"),
        expected_s=60.0,
    )
    played = play(scenario, tmp_path / "play", scenario_env, scenario_cache)
    log = played.log.read_text(encoding="utf-8", errors="replace")[-3000:]
    assert played.returncode == 0, log

    run_dir = played.root / "runs" / VARIANT
    seal = read_seal(run_dir)
    by = seal.checks.calibrated_by
    assert by is not None
    assert by.rule == METRIC_RULE_VERSION
    assert by.components, "the seal names the parts of the cost"
    calibration = {name for name, w in by.windows.items() if w.role == CALIBRATION_ROLE}
    assert calibration, "the session scored a dated period"

    table = pq.read_table(run_dir / TABLES_DIRNAME / f"metrics{PARQUET_FILE_SUFFIX}").to_pandas()
    searched = table[(table["window_role"] == CALIBRATION_ROLE) & (table["metric"] == by.metric)]
    assert set(searched["window_name"]) == calibration
    assert set(searched["metric_rule_version"]) == {METRIC_RULE_VERSION}
    (scored,) = searched[searched["station_id"] == "W1"]["value"].tolist()

    best = min(
        (trial for trial in read_trials(played.root / "sessions" / VARIANT)),
        key=lambda trial: trial.cost,
    )
    assert by.trial == best.trial
    assert math.isclose(scored, by.cost, rel_tol=MAX_RELATIVE_ERROR, abs_tol=0.0)

    result = label_of(seal, run_dir)
    codes = [cause.code for cause in result.causes]
    assert (result.label, result.rule_version) == ("calibrated", RULE_VERSION)
    assert ("bound_reached" in codes) == bool(seal.checks.bounds_hit)
    if seal.checks.bounds_hit:
        assert codes[-1] == "bound_reached"

    english = method_text(run_dir, lang="en", today=date(2026, 11, 11))
    french = method_text(run_dir, lang="fr", today=date(2026, 11, 11))
    assert english and french and english != french
