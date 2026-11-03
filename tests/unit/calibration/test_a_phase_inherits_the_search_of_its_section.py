"""A phase that writes no search key takes the one ``[calibration]`` writes.

``method``, ``max_trials``, ``precision`` and ``method_options`` were read in
the phase or nowhere: a section that said ``method = "grid"`` left every phase
to be chosen from its criteria, and a phase's budget was ``"auto"`` unless it
wrote one. Key by key, the phase wins, then the section, then the default,
the way ``batch_size``, ``parallel`` and ``uncertainty`` already read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.preflight import preflight_calibration
from hydromodpy.calibration.runners.staged_runner import _phase_config, phase_summaries
from hydromodpy.config import HydroModPyConfig
from hydromodpy.workflow.steps.prepare_solver.dispatch import portable_config_document
from tests.unit.config.test_a_renamed_key_warns_and_a_sealed_one_reads import (
    PROJECT,
    _project,
)

PARAMETERS = {
    "K": {"bounds": [1e-7, 1e-3], "search_space": "log"},
    "Sy": {"bounds": [0.005, 0.35], "search_space": "log"},
}


def _phase(name: str = "k", **fields: Any) -> dict[str, Any]:
    return {"name": name, "parameters": ["K"], "objective": "nse", **fields}


def _cfg(*phases: dict[str, Any], **section: Any) -> CalibrationConfig:
    return CalibrationConfig.model_validate(
        {"parameters": PARAMETERS, "phases": list(phases) or [_phase()], **section}
    )


def _findings(cfg: CalibrationConfig) -> list[Any]:
    class _Config:
        calibration = cfg

    return preflight_calibration(_Config(), source=Path("calibration.toml"))


# -- method ------------------------------------------------------------------


def test_a_phase_runs_the_method_the_section_writes() -> None:
    cfg = _cfg(_phase("a"), _phase("b", method="random_search"), method="grid")
    a, b = cfg.phases

    assert cfg.method_for(a) == ("grid", None)
    assert cfg.method_for(b) == ("random_search", None)


def test_a_phase_with_no_method_anywhere_is_chosen_from_its_criteria() -> None:
    method, reason = _cfg().method_for(_cfg().phases[0])

    assert method == "scipy_nelder_mead"
    assert reason is not None


# -- max_trials --------------------------------------------------------------


def test_a_phase_takes_the_budget_of_the_section_unless_it_writes_one() -> None:
    cfg = _cfg(_phase("a"), _phase("b", max_trials=7), max_trials=40)
    a, b = cfg.phases

    assert (a.max_trials, b.max_trials) == (None, 7)
    assert (cfg.max_trials_for(a), cfg.max_trials_for(b)) == (40, 7)


def test_the_budget_of_a_phase_and_of_a_section_left_unwritten_is_auto() -> None:
    cfg = _cfg()

    assert cfg.max_trials_for(cfg.phases[0]) == "auto"
    assert cfg.max_trials_for(None) == "auto"


def test_a_phase_may_ask_for_auto_against_a_section_budget() -> None:
    cfg = _cfg(_phase(max_trials="auto"), max_trials=40)

    assert cfg.max_trials_for(cfg.phases[0]) == "auto"


# -- precision ---------------------------------------------------------------


def test_a_precision_reaches_a_phase_whose_engine_reads_one() -> None:
    cfg = _cfg(
        _phase("a", method="scipy_nelder_mead"),
        _phase("b", method="scipy_nelder_mead", precision=0.1),
        _phase("c", method="bisection"),
        precision=0.01,
    )
    a, b, c = cfg.phases

    assert [cfg.precision_for(phase) for phase in (a, b, c)] == [0.01, 0.1, 0.01]


def test_a_precision_does_not_reach_an_engine_that_stops_on_its_budget() -> None:
    cfg = _cfg(_phase(method="grid"), _phase("b", method="optuna"), precision=0.01)

    assert [cfg.precision_for(phase) for phase in cfg.phases] == [None, None]
    assert not [finding for finding in _findings(cfg) if "precision" in finding.detail]


def test_a_precision_written_in_a_phase_of_a_budget_engine_is_still_refused() -> None:
    findings = _findings(_cfg(_phase(method="grid", precision=0.01)))

    assert [finding.severity for finding in findings if "precision" in finding.detail] == ["error"]


def test_an_engine_option_written_in_the_phase_wins_over_the_inherited_precision() -> None:
    cfg = _cfg(_phase(method="scipy_nelder_mead", method_options={"xatol": 0.02}), precision=0.01)

    assert cfg.precision_for(cfg.phases[0]) is None
    assert not [finding for finding in _findings(cfg) if "both set" in finding.detail]


# -- method_options ----------------------------------------------------------


def test_a_phase_takes_the_options_of_the_section_when_it_runs_its_method() -> None:
    cfg = _cfg(
        _phase("same"),
        _phase("also", method="bisection"),
        _phase("other", method="grid"),
        _phase("own", method_options={"sweep_points": 3}),
        _phase("none", method_options={}),
        method="bisection",
        method_options={"sweep_points": 5},
    )
    same, also, other, own, none = cfg.phases

    assert cfg.method_options_for(same) == {"sweep_points": 5}
    assert cfg.method_options_for(also) == {"sweep_points": 5}
    assert cfg.method_options_for(other) == {}
    assert cfg.method_options_for(own) == {"sweep_points": 3}
    assert cfg.method_options_for(none) == {}
    assert (same.method_options, none.method_options) == (None, {})


def test_the_options_of_a_phase_need_a_method_in_the_phase_or_in_the_section() -> None:
    with pytest.raises(ValidationError, match="phase 'k' gives method_options and no method"):
        _cfg(_phase(method_options={"sweep_points": 3}))

    inherited = _cfg(_phase(method_options={"sweep_points": 3}), method="bisection")
    assert inherited.method_options_for(inherited.phases[0]) == {"sweep_points": 3}


def test_the_options_of_a_phase_are_checked_against_the_method_it_inherits() -> None:
    with pytest.raises(ValidationError, match="phase 'k' method_options"):
        _cfg(_phase(method_options={"sweep_points": 3}), method="grid")


def test_a_protocol_stage_does_not_take_the_options_of_the_section() -> None:
    cfg = _cfg(
        _phase(method="bisection"),
        method="bisection",
        method_options={"sweep_points": 5},
        protocol={"name": "matching_hydrographic_network"},
    )

    assert cfg.method_options_for(cfg.phases[0]) == {}


# -- what a phase runs -------------------------------------------------------


def test_the_search_a_phase_runs_is_the_resolved_one() -> None:
    cfg = _cfg(
        _phase("a"),
        _phase("b", method="grid", max_trials=9),
        method="scipy_nelder_mead",
        max_trials=40,
        precision=0.02,
    )
    a, b = cfg.phases

    ran = _phase_config(cfg, a)
    assert (ran.method, ran.max_trials, ran.precision, ran.method_options) == (
        "scipy_nelder_mead",
        40,
        0.02,
        {},
    )
    ran = _phase_config(cfg, b)
    assert (ran.method, ran.max_trials, ran.precision) == ("grid", 9, None)


def test_the_listing_says_where_each_key_of_a_phase_comes_from() -> None:
    cfg = _cfg(
        _phase("a"),
        _phase("b", method="grid", max_trials=9, method_options={"points_per_dim": 4}),
        method="scipy_nelder_mead",
        max_trials=40,
        precision=0.02,
    )

    a, b = (row["search"] for row in phase_summaries(cfg))

    assert a == {
        "method": {"value": "scipy_nelder_mead", "source": "section"},
        "max_trials": {"value": 40, "source": "section"},
        "precision": {"value": 0.02, "source": "section"},
        "method_options": {"value": {}, "source": "default"},
    }
    assert b["method"]["source"] == "phase"
    assert b["max_trials"] == {"value": 9, "source": "phase"}
    assert b["precision"] == {"value": None, "source": "default"}
    assert b["method_options"] == {"value": {"points_per_dim": 4}, "source": "phase"}


def test_a_search_that_writes_nothing_lists_its_defaults() -> None:
    (row,) = phase_summaries(_cfg())

    assert row["search"]["max_trials"] == {"value": "auto", "source": "default"}
    assert row["search"]["method"]["source"] == "default"


# -- a protocol and a sealed run ---------------------------------------------


def test_a_protocol_stage_takes_the_section_precision_and_keeps_the_budget_it_wrote(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    toml = project / "project.toml"
    toml.write_text(PROJECT + "\n[calibration]\nprecision = 0.02\nmax_trials = 40\n", "utf-8")

    cfg = HydroModPyConfig.from_toml(toml).calibration
    steady, transient = cfg.phases

    assert [cfg.precision_for(phase) for phase in (steady, transient)] == [0.02, 0.02]
    assert [cfg.max_trials_for(phase) for phase in (steady, transient)] == ["auto", 120]

    run_dir = project / "runs" / "nancon"
    run_dir.mkdir(parents=True)
    sealed = run_dir / "config.toml"
    sealed.write_text(
        portable_config_document(HydroModPyConfig.from_toml(toml), run_dir, project), "utf-8"
    )
    replayed = HydroModPyConfig.from_toml(sealed).calibration
    assert [replayed.max_trials_for(phase) for phase in replayed.phases] == ["auto", 120]
    assert [replayed.precision_for(phase) for phase in replayed.phases] == [0.02, 0.02]
