"""Tests of `runners.phase_regime`."""

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

# From test_calibration_protocols.py
# A published calibration method has to be nameable, not retyped.
#
# The two-stage stream-network calibration was reachable only by hand-writing the
# whole assembly: two phases, their engines and budgets, the regime and time-grid
# overrides that make one stage steady and the other transient, and the objective
# block wiring. A hundred lines of TOML that carry no site information, that every
# project copied, and that no file identified as a published method.
#
# The protocol names it. The file states what belongs to the site, the protocol
# writes the assembly, and the run records which method produced it and what to
# cite. It says each stage's regime, and ``runners/phase_regime.py`` writes what
# the regime means (``test_runners_phase_regime.py``).


_SIMULATION = {
    "time": {
        "start_datetime": "1995-01-01",
        "end_datetime": "2020-12-31",
        "step_value": 1,
        "step_unit": "day",
    }
}


def _doc(**calibration: object) -> dict[str, object]:
    # deepcopy and not dict(): a shallow copy shares the nested [time] table,
    # so a test that writes into ``doc["simulation"]["time"]`` writes into
    # _SIMULATION itself and poisons every later test of the process.
    # ``_steady(1995, ...)`` below does exactly that, on purpose, to check a
    # refusal. Under xdist the classes of one module land on different workers,
    # so the damage showed up as an intermittent red in unrelated tests.
    return {
        "simulation": copy.deepcopy(_SIMULATION),
        "data": {"hydrometry": {"sources": [{"station_ids": ["NANCON"]}]}},
        "calibration": {
            "protocol": "matching_hydrographic_network",
            "parameters": {
                "K": {"bounds": [1e-8, 1e-2], "search_space": "log"},
                "Sy": {"bounds": [1e-4, 0.5], "search_space": "log"},
            },
            "outputs": {
                "seepage_network": {
                    "support": "network",
                    "map": {"complete": "nancon.gpkg"},
                }
            },
            **calibration,
        },
    }


class TestWhatItWrites:
    def test_a_steady_window_it_is_given_reaches_the_stage(self) -> None:
        window = {"start": "2001-01-01", "end": "2001-12-31"}
        steady = expand_calibration_protocol(
            _doc(protocol={"name": "matching_hydrographic_network", "steady_window": window})
        )["calibration"]["phases"][0]

        assert steady["steady_window"] == window
        assert "steady_window" in steady["description"]

    def test_a_genuinely_different_hydrograph_output_is_still_refused(self) -> None:
        doc = _doc()
        doc["calibration"]["outputs"]["hydrograph"] = {
            "variable": "head",
            "support": "point",
            "x": 1.0,
            "y": 2.0,
        }

        with pytest.raises(ValueError, match="reserved"):
            expand_calibration_protocol(doc)

    @pytest.mark.parametrize(
        "hydrometry",
        [
            # Several stations named: not B11's to guess, so it keeps the old route.
            {"sources": [{"station_ids": ["NANCON", "OTHER"]}]},
            # No 'station_ids' at all (an 'extent' or a 'mask_path'): not knowable here.
            {"sources": [{"extent": [0, 0, 1, 1]}]},
            None,
        ],
        ids=["ambiguous_station", "source_discovered_at_load_time", "no_loaded_station"],
    )
    def test_an_unknown_station_falls_back_to_the_single_metric_route(self, hydrometry) -> None:
        doc = _doc()
        doc["data"] = {} if hydrometry is None else {"hydrometry": hydrometry}

        expanded = expand_calibration_protocol(doc)["calibration"]

        transient = expanded["phases"][1]
        assert transient["variable"] == "discharge"
        assert transient["objective"] == "nse_log"
        assert "objective_blocks" not in transient
        assert "hydrograph" not in (expanded.get("outputs") or {})


class TestWhatItRefuses:
    def test_a_file_that_writes_its_own_stages_is_refused(self) -> None:
        """The protocol writes the stages; declaring both is a contradiction."""
        with pytest.raises(ValueError, match="phases"):
            expand_calibration_protocol(_doc(phases=[{"name": "mine", "parameters": ["K"]}]))

    def test_a_missing_conductivity_parameter_is_named(self) -> None:
        doc = _doc()
        del doc["calibration"]["parameters"]["K"]

        with pytest.raises(ValueError, match="'K'"):
            expand_calibration_protocol(doc)

    def test_a_missing_network_output_is_named(self) -> None:
        doc = _doc()
        doc["calibration"]["outputs"] = {}

        with pytest.raises(ValueError, match="network"):
            expand_calibration_protocol(doc)

    def test_two_network_outputs_have_to_be_told_apart(self) -> None:
        doc = _doc()
        doc["calibration"]["outputs"]["other_network"] = {
            "support": "network",
            "map": {"complete": "other.gpkg"},
        }

        with pytest.raises(ValueError, match="network_output"):
            expand_calibration_protocol(doc)


class TestItReadsBackWhatItWrote:
    """A run seals its own configuration and is re-read from it.

    That file carries the ``protocol`` table *and* the stages the table
    produced, on purpose: the run records which method it followed and what that
    method assembled. Reloading it was refused as a contradiction, which made
    every staged project unable to round-trip through its own dumpers.
    """

    def test_a_file_that_is_broken_twice_still_gets_the_actionable_message(self) -> None:
        """Expanding now runs first, and its own failure must not bury the advice."""
        once = expand_calibration_protocol(_doc())
        doc = _doc(phases=once["calibration"]["phases"])
        del doc["calibration"]["parameters"]["K"]

        with pytest.raises(ValueError) as caught:
            expand_calibration_protocol(doc)

        assert "Keep one" in str(caught.value)
        assert "'K'" in str(caught.value)


def _sealed_before_the_regime(start: str = "1995-01-01", end: str = "2020-12-31", days: int = 9497):
    """The stages the protocol wrote for ``_doc()`` before phases said their regime.

    Produced by the expansion at 41c8e07e1 and trimmed to the keys it wrote: the
    regime is five override paths, and the steady description embeds the dates.
    """
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


def _sealed_doc(**calibration: object) -> dict[str, object]:
    """``_doc()`` as a run sealed then dumps it: the protocol table carries its defaults.

    Only the one that has moved since matters here: ``steady_max_trials`` was 20
    when these stages were sealed, and a dumped file says so.
    """
    declared = calibration.pop("protocol", {"name": "matching_hydrographic_network"})
    protocol = {"steady_max_trials": 20, **dict(declared)}
    return _doc(protocol=protocol, **calibration)


class TestItReadsBackARunSealedBeforeTheRegime:
    """A run sealed before phases said their regime has to stay replayable.

    ``hmp run <ref> --resume`` reads the sealed file through
    ``HydroModPyConfig.from_toml``, which compares its stages with what the
    protocol writes today.
    """

    def test_a_window_the_protocol_names_has_to_be_the_sealed_one(self) -> None:
        window = {"start": "2001-01-01", "end": "2001-12-31"}
        protocol = {"name": "matching_hydrographic_network", "steady_window": window}

        same = _sealed_before_the_regime("2001-01-01", "2001-12-31", 365)
        expanded = expand_calibration_protocol(_sealed_doc(protocol=protocol, phases=same))
        assert expanded["calibration"]["phases"][0]["steady_window"] == window

        with pytest.raises(ValueError, match="phases"):
            expand_calibration_protocol(
                _sealed_doc(protocol=protocol, phases=_sealed_before_the_regime())
            )

    def test_a_transient_objective_that_no_longer_matches_is_refused(self) -> None:
        """A real drift in the criterion is not this legacy spelling."""
        sealed = _sealed_before_the_regime()
        sealed[1]["objective"] = "kge"

        with pytest.raises(ValueError, match="phases"):
            expand_calibration_protocol(_sealed_doc(phases=sealed))

    def test_a_sealed_stage_still_reads_back_when_the_station_is_still_not_known(self) -> None:
        """The other legacy spelling: still single-metric today, so nothing to fold."""
        doc = _sealed_doc(phases=_sealed_before_the_regime())
        doc["data"]["hydrometry"]["sources"][0]["station_ids"] = ["NANCON", "OTHER"]

        expanded = expand_calibration_protocol(doc)["calibration"]

        transient = expanded["phases"][1]
        assert transient["variable"] == "discharge"
        assert "objective_blocks" not in transient


class TestOneSpellingOfAnInstant:
    """A TOML file writes a date three legal ways and they have to agree.

    ``start_datetime = 2000-01-01`` parses as a date, ``2000-01-01T00:00:00`` as
    a datetime, a quoted value stays a string. Rendering them straight into the
    stage description and the time overrides made the assembly depend on the
    spelling, so a file re-read from its own dump expanded to different stages.
    The stages now say the regime and read no date at all; the overrides it
    writes are checked in ``test_runners_phase_regime.py``.
    """

    @staticmethod
    def _steady(start: object, end: object) -> dict:
        doc = _doc()
        doc["simulation"]["time"]["start_datetime"] = start
        doc["simulation"]["time"]["end_datetime"] = end
        return expand_calibration_protocol(doc)["calibration"]["phases"][0]


# From test_phase_regime.py
# A phase states its flow regime, and steady means one period over a window.
#
# Saying "steady" used to take five dotted paths and a day count worked out by
# hand, 1096 for 2000-2002 with its leap year. The protocol computed that count
# for itself only. ``regime`` says it once, for a phase written by hand and for
# one a protocol writes, and ``runners/phase_regime.py`` is the one place that
# turns it into the paths the trials run with.


_DOCUMENT = {
    "simulation": {
        "time": {
            "start_datetime": "2000-01-01",
            "end_datetime": "2002-12-31",
            "step_value": "1 month",
        }
    }
}


def _phase(**fields: Any) -> CalibPhaseDecl:
    return CalibPhaseDecl.model_validate({"name": "stage", "parameters": ["K"], **fields})


def _steady_over(start: object, end: object) -> dict[str, Any]:
    document = {"simulation": {"time": {"start_datetime": start, "end_datetime": end}}}
    return regime_overrides(_phase(regime="steady"), document)


def _schema_has(schema: dict[str, Any], dotted: str) -> bool:
    """Say whether a dotted path names a field of the JSON schema."""
    defs = schema.get("$defs", {})

    def resolve(node: dict[str, Any]) -> list[dict[str, Any]]:
        if "$ref" in node:
            return resolve(defs[node["$ref"].rsplit("/", 1)[-1]])
        branches = node.get("anyOf") or node.get("oneOf") or node.get("allOf")
        if branches:
            return [leaf for branch in branches for leaf in resolve(branch)]
        return [node]

    nodes = [schema]
    for key in dotted.split("."):
        nodes = [
            child
            for node in nodes
            for resolved in resolve(node)
            if (child := resolved.get("properties", {}).get(key)) is not None
        ]
        if not nodes:
            return False
    return True


class TestSteady:
    def test_a_named_window_needs_no_simulation_time(self) -> None:
        phase = _phase(regime="steady", steady_window={"start": "2001-01-01", "end": "2001-01-31"})

        assert regime_overrides(phase, {})["simulation.time.step_value"] == 31

    def test_a_window_missing_a_bound_is_named(self) -> None:
        phase = _phase(regime="steady", steady_window={"start": "2001-01-01"})

        with pytest.raises(ValueError, match="missing end"):
            regime_overrides(phase, _DOCUMENT)

    def test_a_window_that_runs_backwards_is_refused(self) -> None:
        with pytest.raises(ValueError, match="not a forward window"):
            _steady_over("2002-12-31", "2000-01-01")


class TestOneSpellingOfAnInstant__phase_regime:
    """A TOML file writes a date three legal ways and they have to agree.

    ``start_datetime = 2000-01-01`` parses as a date, ``2000-01-01T00:00:00`` as
    a datetime, a quoted value stays a string. Rendering them straight into the
    time overrides made the model depend on the spelling, so a file re-read
    from its own dump ran a different one.
    """

    def test_a_bound_that_is_not_midnight_keeps_its_time(self) -> None:
        overrides = _steady_over("1995-01-01T06:00:00", "2020-12-31")

        assert overrides["simulation.time.start_datetime"] == "1995-01-01T06:00:00"

    @pytest.mark.parametrize(
        ("start", "match"),
        [
            pytest.param("not a date", "simulation.time.start_datetime", id="not_an_instant"),
            # Their span is undefined, and pandas says so with a raw TypeError.
            pytest.param("1995-01-01T00:00:00+02:00", "offset", id="one_offset_and_one_without"),
            # pandas reads an int as nanoseconds since 1970; a config never means that.
            pytest.param(1995, "simulation.time.start_datetime", id="a_bare_number"),
            pytest.param(pd.NaT, "simulation.time.start_datetime", id="not_a_time"),
        ],
    )
    def test_a_bound_that_is_not_an_instant_is_refused(self, start, match) -> None:
        with pytest.raises(ValueError, match=match):
            _steady_over(start, "2020-12-31")


class TestSaidOnce:
    def test_a_regime_and_one_of_its_paths_in_overrides_is_refused(self) -> None:
        with pytest.raises(ValueError, match="two ways to say the same thing"):
            _phase(regime="steady", overrides={"simulation.time.step_value": 1096})

    def test_a_transient_regime_and_its_flow_regime_override_is_refused(self) -> None:
        with pytest.raises(ValueError, match="flow.flow_regime"):
            _phase(regime="transient", overrides={"flow.flow_regime": "transient"})

    def test_a_steady_window_without_a_steady_regime_is_refused(self) -> None:
        with pytest.raises(ValueError, match="steady_window"):
            _phase(steady_window={"start": "2001-01-01", "end": "2001-12-31"})


class TestTheRunnerHandsThemToThePreparation:
    """``_phase_plans`` resolves each regime before the first phase solves."""

    @staticmethod
    def _config(**phase: Any) -> CalibrationConfig:
        return CalibrationConfig.model_validate(
            {
                "method": "grid",
                "parameters": {
                    "K": {
                        "bounds": [1e-9, 1e-3],
                        "search_space": "log",
                        "path": "flow.param.K.field.value",
                    }
                },
                "phases": [{"name": "stage", "parameters": ["K"], **phase}],
            }
        )

    def test_a_window_it_cannot_read_is_refused_before_the_first_solve(self) -> None:

        cfg = self._config(regime="steady")

        with pytest.raises(ConfigValidationError, match="'stage'.*simulation.time"):
            _phase_plans(cfg, list(enumerate(cfg.phases)), {})


class TestTheSpellingBeforeTheRegime:
    """A phase sealed with its regime as overrides is read as that regime."""

    _STEADY = {
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

    def test_a_phase_missing_one_of_the_paths_is_not_folded(self) -> None:
        partial = {**self._STEADY, "overrides": {"flow.flow_regime": "steady"}}

        assert fold_a_legacy_regime(partial) is None

    def test_a_named_window_is_matched_instant_by_instant(self) -> None:
        same = {"start": "2000-01-01T00:00:00", "end": "2002-12-31"}
        other = {"start": "2001-01-01", "end": "2002-12-31"}

        assert fold_a_legacy_regime(self._STEADY, same)["steady_window"] == same
        assert fold_a_legacy_regime(self._STEADY, other) is None


# From test_the_water_budget_gate_reads_the_model_budget.py
# The water-balance gate reads the model budget, rejects by default, and sees the run.
#
# At HEAD the gate read a key the trial metrics never held, so a threshold of zero
# passed a run at 8 per cent. The catalog figure was the worst of the lake package,
# not of the model. A simulation name with a capital letter broke the MVR writer.


LISTING = """\
  LAK BUDGET FOR ENTIRE MODEL AT END OF TIME STEP    1, STRESS PERIOD   1
 PERCENT DISCREPANCY =          -2.11     PERCENT DISCREPANCY =          -2.45

  VOLUME BUDGET FOR ENTIRE MODEL AT END OF TIME STEP    1, STRESS PERIOD   1
 PERCENT DISCREPANCY =           0.02     PERCENT DISCREPANCY =           0.03
"""


def test_the_model_budget_is_not_the_lake_package_budget(tmp_path: Path) -> None:
    (tmp_path / "m.lst").write_text(LISTING)

    assert model_percent_discrepancies(tmp_path) == [0.02, 0.03]


class _FakePipeline(FakePipeline):
    """The pipeline of a trial whose solver step is the recorder itself.

    The steps are bare objects, so the pipeline runs nothing: ``make_pipeline``
    answers a runner that walks into the crash the trial must report, and
    ``with_solver_launcher`` records the run results the way the solver step of a
    real pipeline would hand them to the launcher.
    """

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


class _FakeTrialContext:
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


def _run(
    monkeypatch,
    discrepancy: float | None,
    threshold: float | None,
    *,
    worst: float | None = None,
    crash: Exception | None = None,
):
    metrics = {}
    if discrepancy is not None:
        metrics[WATER_BUDGET_METRIC] = discrepancy
    if worst is not None:
        metrics[WATER_BUDGET_WORST_METRIC] = worst
    pipeline = _FakePipeline(metrics, crash)
    monkeypatch.setattr(trial_module, "_PIPELINE", pipeline)
    return trial_module.run_trial_light(
        _FakeTrialContext(),
        {"K": 1.0},
        metric_fn=lambda *_a, **_k: (0.9, {"nse": 0.9}),
        reject_water_budget_above=threshold,
    )


@pytest.mark.parametrize(
    ("discrepancy", "threshold", "worst", "status", "error_holds"),
    [
        pytest.param(8.36, 1.0, None, "failed", "8.36", id="a_trial_past_the_threshold"),
        pytest.param(0.2, 1.0, None, "completed", None, id="a_trial_inside_the_threshold"),
        pytest.param(0.2, 0.0, None, "failed", None, id="a_zero_threshold_rejects_any_imbalance"),
        pytest.param(8.36, None, None, "completed", None, id="no_threshold_disables_the_gate"),
        # A run that loses its balance mid-way and recovers at the end is rejected.
        pytest.param(0.02, 1.0, -4.5, "failed", "4.5", id="the_worst_step_not_the_last"),
        pytest.param(0.02, 1.0, 0.4, "completed", None, id="a_closed_run_with_a_small_worst_step"),
        # Absent is not zero, and not an imbalance either.
        pytest.param(None, 1.0, None, "completed", None, id="a_trial_that_reports_no_budget"),
    ],
)
def test_the_water_budget_gate(monkeypatch, discrepancy, threshold, worst, status, error_holds):
    result = _run(monkeypatch, discrepancy, threshold, worst=worst)

    assert result.status == status
    assert error_holds is None or error_holds in (result.error or "")


def test_a_trial_that_did_not_converge_is_not_scored(monkeypatch) -> None:
    """The solver refuses a run that fails to converge; the trial never reaches the score."""
    result = _run(monkeypatch, 0.0, 1.0, crash=SolverDivergedError("did not converge"))

    assert result.status == "crashed"
    assert result.primary_metric != result.primary_metric  # nan


def test_the_verdict_prefers_the_worst_step() -> None:
    verdict = water_budget_verdict(
        {WATER_BUDGET_METRIC: 0.1, WATER_BUDGET_WORST_METRIC: -3.0}, threshold=1.0
    )

    assert verdict is not None
    assert verdict.passed is False
    assert verdict.value == pytest.approx(3.0)


def test_a_steady_phase_cannot_fit_a_parameter_named_after_a_lake() -> None:
    phase = CalibPhaseDecl(name="p", parameters=["cheze_k"], regime="steady")
    document = {
        "flow": {"sinks_sources": {"lakes": {"cheze": {}}}},
        "simulation": {"time": {"start_datetime": "2000-01-01", "end_datetime": "2001-01-01"}},
    }

    with pytest.raises(ValueError, match="lake"):
        regime_overrides(phase, document)


@pytest.mark.parametrize(
    ("parameter", "lake", "refused"),
    [
        pytest.param("lake_bedleak", "cheze", True, id="a_lake_parameter"),
        pytest.param("K", "cheze", False, id="conductivity_with_a_lake"),
        # The lake name is matched as a whole word, not as a fragment of any name.
        pytest.param("recharge_factor", "a", False, id="a_short_lake_name_claims_nothing"),
        pytest.param("cheze_k", "cheze", True, id="a_parameter_named_after_a_lake"),
    ],
)
def test_a_steady_phase_cannot_fit_a_lake_parameter(parameter, lake, refused) -> None:
    phase = CalibPhaseDecl(name="p", parameters=[parameter], regime="steady")
    document = {
        "flow": {"sinks_sources": {"lakes": {lake: {}}}},
        "simulation": {"time": {"start_datetime": "2000-01-01", "end_datetime": "2001-01-01"}},
    }
    if refused:
        with pytest.raises(ValueError, match="lake"):
            regime_overrides(phase, document)
    else:
        assert regime_overrides(phase, document)["flow.flow_regime"] == "steady"


@pytest.mark.parametrize(
    ("lakes", "names"),
    [
        ({"a": {}, "b": {}}, ["a", "b"]),
        ([{"name": "a"}, {"name": ""}, "x"], ["a"]),
        ([{"size": 1}], ["lake"]),
        (None, []),
    ],
)
def test_the_lakes_a_document_declares_are_listed_by_name(lakes, names) -> None:
    document = {"flow": {"sinks_sources": {"lakes": lakes}}}

    assert _declared_lake_names(document) == names
