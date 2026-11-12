"""Regime of a calibration phase (steady over one window, or transient) and the protocol that writes it.

A steady phase becomes one stress period over a window of dates, counted in days.
The two-stage network protocol writes its stages, the water-budget gate rejects
trials whose mass balance error is above a threshold (percent).
"""

from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.config_phases import CalibPhaseDecl, fold_a_legacy_regime
from hydromodpy.calibration.protocols.registry import expand_calibration_protocol
from hydromodpy.calibration.runners import trial as trial_module
from hydromodpy.calibration.runners.phase_regime import _declared_lake_names, regime_overrides
from hydromodpy.calibration.runners.staged_runner import _phase_plans
from hydromodpy.calibration.runners.verdict import water_budget_verdict
from hydromodpy.core.exceptions import ConfigValidationError, SolverDivergedError
from hydromodpy.solver.base.plan import (
    WATER_BUDGET_METRIC,
    WATER_BUDGET_WORST_METRIC,
    RunSlot,
    SolverRun,
)
from hydromodpy.solver.modflow_common.listing import model_percent_discrepancies
from tests.unit.calibration._factories_runners import FakePipeline

WINDOW = {"start": "2001-01-01", "end": "2001-12-31"}
NETWORK_OUTPUT = {"support": "network", "map": {"complete": "nancon.gpkg"}}
PARAMETERS = {
    "K": {"bounds": [1e-8, 1e-2], "search_space": "log"},
    "Sy": {"bounds": [1e-4, 0.5], "search_space": "log"},
}


def protocol_doc(**calibration: object) -> dict[str, object]:
    # Built fresh at each call: the nested [time] table is written into by some tests.
    return {
        "simulation": {
            "time": {
                "start_datetime": "1995-01-01",
                "end_datetime": "2020-12-31",
                "step_value": 1,
                "step_unit": "day",
            }
        },
        "data": {"hydrometry": {"sources": [{"station_ids": ["NANCON"]}]}},
        "calibration": {
            "protocol": "matching_hydrographic_network",
            "parameters": copy.deepcopy(PARAMETERS),
            "outputs": {"seepage_network": copy.deepcopy(NETWORK_OUTPUT)},
            **calibration,
        },
    }


def sealed_before_the_regime(start="1995-01-01", end="2020-12-31", days=9497):
    """The stages the protocol wrote for `protocol_doc()` before phases said their regime."""
    return [
        {
            "name": "steady_conductivity",
            "description": "Match the simulated seepage network to the mapped one by "
            f"moving K, steady state over {start}..{end}.",
            "method": "bisection",
            "max_trials": 20,
            "parameters": ["K"],
            "objective_blocks": ["network_extension"],
            "freeze_on_success": True,
            "overrides": {
                "flow.flow_regime": "steady",
                "simulation.time.start_datetime": start,
                "simulation.time.end_datetime": end,
                "simulation.time.step_unit": "day",
                "simulation.time.step_value": days,
            },
        },
        {
            "name": "transient_storage",
            "description": "Read Sy from the observed hydrograph, K frozen, transient.",
            "method": "scipy_nelder_mead",
            "max_trials": 120,
            "parameters": ["Sy"],
            "variable": "discharge",
            "objective": "nse_log",
            "depends_on": "steady_conductivity",
            "overrides": {"flow.flow_regime": "transient"},
        },
    ]


def sealed_doc(**calibration: object) -> dict[str, object]:
    """`protocol_doc()` as a run sealed it, with steady_max_trials at its old value of 20."""
    declared = calibration.pop("protocol", {"name": "matching_hydrographic_network"})
    protocol = {"steady_max_trials": 20, **dict(declared)}
    return protocol_doc(protocol=protocol, **calibration)


def phase(**fields: Any) -> CalibPhaseDecl:
    return CalibPhaseDecl.model_validate({"name": "stage", "parameters": ["K"], **fields})


def steady_over(start: object, end: object) -> dict[str, Any]:
    document = {"simulation": {"time": {"start_datetime": start, "end_datetime": end}}}
    return regime_overrides(phase(regime="steady"), document)


def lake_document(lake: str) -> dict[str, Any]:
    return {
        "flow": {"sinks_sources": {"lakes": {lake: {}}}},
        "simulation": {"time": {"start_datetime": "2000-01-01", "end_datetime": "2001-01-01"}},
    }


def test_steady_window_reaches_stage():
    protocol = {"name": "matching_hydrographic_network", "steady_window": WINDOW}

    steady = expand_calibration_protocol(protocol_doc(protocol=protocol))["calibration"]["phases"][
        0
    ]

    assert steady["steady_window"] == WINDOW
    assert "steady_window" in steady["description"]


UNKNOWN_STATIONS = [
    # Several stations named: not known here, so the old route stays.
    pytest.param({"sources": [{"station_ids": ["NANCON", "OTHER"]}]}, id="ambiguous station"),
    # No 'station_ids' at all (an 'extent' or a 'mask_path').
    pytest.param({"sources": [{"extent": [0, 0, 1, 1]}]}, id="source found at load time"),
    pytest.param(None, id="no station"),
]


@pytest.mark.parametrize("hydrometry", UNKNOWN_STATIONS)
def test_unknown_station_single_metric(hydrometry):
    doc = protocol_doc()
    doc["data"] = {} if hydrometry is None else {"hydrometry": hydrometry}

    expanded = expand_calibration_protocol(doc)["calibration"]

    transient = expanded["phases"][1]
    assert transient["variable"] == "discharge"
    assert transient["objective"] == "nse_log"
    assert "objective_blocks" not in transient
    assert "hydrograph" not in (expanded.get("outputs") or {})


def test_dumped_file_broken_twice():
    # A run seals the protocol table and the stages it wrote, so reading back is allowed.
    once = expand_calibration_protocol(protocol_doc())
    doc = protocol_doc(phases=once["calibration"]["phases"], parameters={"Sy": PARAMETERS["Sy"]})

    with pytest.raises(ValueError) as caught:
        expand_calibration_protocol(doc)

    assert "Keep one" in str(caught.value)
    assert "'K'" in str(caught.value)


PROTOCOL_REFUSALS = [
    pytest.param(
        {"phases": [{"name": "mine", "parameters": ["K"]}]},
        "phases",
        id="own stages next to protocol",
    ),
    pytest.param({"parameters": {"Sy": PARAMETERS["Sy"]}}, "'K'", id="no conductivity"),
    pytest.param({"outputs": {}}, "network", id="no network output"),
    pytest.param(
        {"outputs": {"seepage_network": NETWORK_OUTPUT, "other_network": NETWORK_OUTPUT}},
        "network_output",
        id="two network outputs",
    ),
    pytest.param(
        {
            "outputs": {
                "seepage_network": NETWORK_OUTPUT,
                "hydrograph": {"variable": "head", "support": "point", "x": 1.0, "y": 2.0},
            }
        },
        "reserved",
        id="other hydrograph output",
    ),
]


@pytest.mark.parametrize(("calibration", "match"), PROTOCOL_REFUSALS)
def test_protocol_refusals(calibration, match):
    with pytest.raises(ValueError, match=match):
        expand_calibration_protocol(protocol_doc(**calibration))


def test_sealed_window_matches_protocol():
    protocol = {"name": "matching_hydrographic_network", "steady_window": WINDOW}

    same = sealed_before_the_regime("2001-01-01", "2001-12-31", 365)
    expanded = expand_calibration_protocol(sealed_doc(protocol=protocol, phases=same))
    assert expanded["calibration"]["phases"][0]["steady_window"] == WINDOW

    with pytest.raises(ValueError, match="phases"):
        expand_calibration_protocol(
            sealed_doc(protocol=protocol, phases=sealed_before_the_regime())
        )


def test_drifted_objective_refused():
    sealed = sealed_before_the_regime()
    sealed[1]["objective"] = "kge"

    with pytest.raises(ValueError, match="phases"):
        expand_calibration_protocol(sealed_doc(phases=sealed))


def test_sealed_stage_unknown_station():
    doc = sealed_doc(phases=sealed_before_the_regime())
    doc["data"]["hydrometry"]["sources"][0]["station_ids"] = ["NANCON", "OTHER"]

    transient = expand_calibration_protocol(doc)["calibration"]["phases"][1]

    assert transient["variable"] == "discharge"
    assert "objective_blocks" not in transient


LEGACY_STEADY = {
    "name": "stage",
    "parameters": ["K"],
    "overrides": {
        "flow.flow_regime": "steady",
        "simulation.time.start_datetime": "2000-01-01",
        "simulation.time.end_datetime": "2002-12-31",
        "simulation.time.step_unit": "day",
        "simulation.time.step_value": 1096,
        "display.overrides.seepage_map.timestep": 0,
    },
}


def test_partial_legacy_not_folded():
    partial = {**LEGACY_STEADY, "overrides": {"flow.flow_regime": "steady"}}

    assert fold_a_legacy_regime(partial) is None


def test_legacy_window_matching():
    same = {"start": "2000-01-01T00:00:00", "end": "2002-12-31"}
    other = {"start": "2001-01-01", "end": "2002-12-31"}

    assert fold_a_legacy_regime(LEGACY_STEADY, same)["steady_window"] == same
    assert fold_a_legacy_regime(LEGACY_STEADY, other) is None


def test_named_window_needs_no_time():
    named = phase(regime="steady", steady_window={"start": "2001-01-01", "end": "2001-01-31"})

    assert regime_overrides(named, {})["simulation.time.step_value"] == 31  # days of January


def test_bound_keeps_its_time():
    overrides = steady_over("1995-01-01T06:00:00", "2020-12-31")

    assert overrides["simulation.time.start_datetime"] == "1995-01-01T06:00:00"


BAD_WINDOWS = [
    pytest.param("not a date", "2020-12-31", "simulation.time.start_datetime", id="not an instant"),
    # Their span is undefined, and pandas says so with a raw TypeError.
    pytest.param("1995-01-01T00:00:00+02:00", "2020-12-31", "offset", id="one offset only"),
    # pandas reads an int as nanoseconds since 1970, a config never means that.
    pytest.param(1995, "2020-12-31", "simulation.time.start_datetime", id="a bare number"),
    pytest.param(pd.NaT, "2020-12-31", "simulation.time.start_datetime", id="not a time"),
    pytest.param("2002-12-31", "2000-01-01", "not a forward window", id="backward window"),
]


@pytest.mark.parametrize(("start", "end", "match"), BAD_WINDOWS)
def test_bad_window_refused(start, end, match):
    with pytest.raises(ValueError, match=match):
        steady_over(start, end)


def test_half_window_refused():
    document = {"simulation": {"time": {"start_datetime": "2000-01-01"}}}
    half_window = phase(regime="steady", steady_window={"start": "2001-01-01"})

    with pytest.raises(ValueError, match="missing end"):
        regime_overrides(half_window, document)


PHASE_REFUSALS = [
    pytest.param(
        {"regime": "steady", "overrides": {"simulation.time.step_value": 1096}},
        "two ways to say the same thing",
        id="regime and one of its paths",
    ),
    pytest.param(
        {"regime": "transient", "overrides": {"flow.flow_regime": "transient"}},
        "flow.flow_regime",
        id="transient and its flow regime",
    ),
    pytest.param({"steady_window": WINDOW}, "steady_window", id="window without steady regime"),
]


@pytest.mark.parametrize(("fields", "match"), PHASE_REFUSALS)
def test_phase_refusals(fields, match):
    with pytest.raises(ValueError, match=match):
        phase(**fields)


def test_unreadable_window_refused():
    cfg = CalibrationConfig.model_validate(
        {
            "method": "grid",
            "parameters": {
                "K": {
                    "bounds": [1e-9, 1e-3],
                    "search_space": "log",
                    "path": "flow.param.K.field.value",
                }
            },
            "phases": [{"name": "stage", "parameters": ["K"], "regime": "steady"}],
        }
    )

    with pytest.raises(ConfigValidationError, match="'stage'.*simulation.time"):
        _phase_plans(cfg, list(enumerate(cfg.phases)), {})


LAKE_PARAMETERS = [
    pytest.param("lake_bedleak", "cheze", True, id="a lake parameter"),
    pytest.param("K", "cheze", False, id="conductivity with a lake"),
    # The lake name is matched as a whole word, not as a fragment of any name.
    pytest.param("recharge_factor", "a", False, id="a short lake name claims nothing"),
    pytest.param("cheze_k", "cheze", True, id="a parameter named after a lake"),
]


@pytest.mark.parametrize(("parameter", "lake", "refused"), LAKE_PARAMETERS)
def test_steady_phase_lake_parameter(parameter, lake, refused):
    steady = CalibPhaseDecl(name="p", parameters=[parameter], regime="steady")
    document = lake_document(lake)
    if refused:
        with pytest.raises(ValueError, match="lake"):
            regime_overrides(steady, document)
    else:
        assert regime_overrides(steady, document)["flow.flow_regime"] == "steady"


DECLARED_LAKES = [
    pytest.param({"a": {}, "b": {}}, ["a", "b"], id="mapping"),
    pytest.param([{"name": "a"}, {"name": ""}, "x"], ["a"], id="list with unnamed entries"),
    pytest.param([{"size": 1}], ["lake"], id="one unnamed lake"),
    pytest.param(None, [], id="none"),
]


@pytest.mark.parametrize(("lakes", "names"), DECLARED_LAKES)
def test_declared_lake_names(lakes, names):
    document = {"flow": {"sinks_sources": {"lakes": lakes}}}

    assert _declared_lake_names(document) == names


LISTING = """\
  LAK BUDGET FOR ENTIRE MODEL AT END OF TIME STEP    1, STRESS PERIOD   1
 PERCENT DISCREPANCY =          -2.11     PERCENT DISCREPANCY =          -2.45

  VOLUME BUDGET FOR ENTIRE MODEL AT END OF TIME STEP    1, STRESS PERIOD   1
 PERCENT DISCREPANCY =           0.02     PERCENT DISCREPANCY =           0.03
"""


def test_model_budget_not_lake_budget(tmp_path: Path):
    (tmp_path / "m.lst").write_text(LISTING)

    assert model_percent_discrepancies(tmp_path) == [0.02, 0.03]


class RecordingPipeline(FakePipeline):
    """A pipeline whose steps run nothing and whose solver launcher records `metrics`."""

    def __init__(self, metrics: dict[str, float], crash: Exception | None = None) -> None:
        self._metrics = metrics
        self._crash = crash

    def make_state(self, *_a, **_k):
        return object()

    def make_pipeline(self, _steps):
        def run(state):
            if self._crash is not None:
                raise self._crash
            return state

        return SimpleNamespace(run=run)

    def with_solver_launcher(self, steps, recorder):
        recorder.results["run"] = SolverRun(
            slot=RunSlot(Path("unused"), "run"), metrics=self._metrics
        )
        return steps


class TrialContextStub:
    kept_solves = None
    override_paths: dict = {}
    ctx = SimpleNamespace(setup=None)

    def fork(self, _values, slot_request=None, derive_model=False):
        return SimpleNamespace(
            ctx=SimpleNamespace(cfg=None, execution=None),
            cfg_path=None,
            raw_toml={},
            downstream_steps=(object(),),
            earliest=0,
        )


def run_light_trial(monkeypatch, discrepancy, threshold, *, worst=None, crash=None):
    metrics = {}
    if discrepancy is not None:
        metrics[WATER_BUDGET_METRIC] = discrepancy
    if worst is not None:
        metrics[WATER_BUDGET_WORST_METRIC] = worst
    monkeypatch.setattr(trial_module, "_PIPELINE", RecordingPipeline(metrics, crash))
    return trial_module.run_trial_light(
        TrialContextStub(),
        {"K": 1.0},
        metric_fn=lambda *_a, **_k: (0.9, {"nse": 0.9}),
        reject_water_budget_above=threshold,
    )


BUDGET_GATE = [
    pytest.param(8.36, 1.0, None, "failed", "8.36", id="past the threshold"),
    pytest.param(0.2, 1.0, None, "completed", None, id="inside the threshold"),
    pytest.param(0.2, 0.0, None, "failed", None, id="zero threshold rejects any imbalance"),
    pytest.param(8.36, None, None, "completed", None, id="no threshold disables the gate"),
    # A run that loses its balance mid-way and recovers at the end is rejected.
    pytest.param(0.02, 1.0, -4.5, "failed", "4.5", id="worst step, not the last"),
    pytest.param(0.02, 1.0, 0.4, "completed", None, id="closed run with a small worst step"),
    # Absent is not zero, and not an imbalance either.
    pytest.param(None, 1.0, None, "completed", None, id="no budget reported"),
]


@pytest.mark.parametrize(
    ("discrepancy", "threshold", "worst", "status", "error_holds"), BUDGET_GATE
)
def test_water_budget_gate(monkeypatch, discrepancy, threshold, worst, status, error_holds):
    result = run_light_trial(monkeypatch, discrepancy, threshold, worst=worst)

    assert result.status == status
    assert error_holds is None or error_holds in (result.error or "")


def test_diverged_trial_not_scored(monkeypatch):
    result = run_light_trial(monkeypatch, 0.0, 1.0, crash=SolverDivergedError("did not converge"))

    assert result.status == "crashed"
    assert result.primary_metric != result.primary_metric  # nan


def test_verdict_uses_worst_step():
    verdict = water_budget_verdict(
        {WATER_BUDGET_METRIC: 0.1, WATER_BUDGET_WORST_METRIC: -3.0}, threshold=1.0
    )

    assert verdict is not None
    assert verdict.passed is False
    assert verdict.value == pytest.approx(3.0)
