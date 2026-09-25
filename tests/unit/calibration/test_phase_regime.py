"""A phase states its flow regime, and steady means one period over a window.

Saying "steady" used to take five dotted paths and a day count worked out by
hand, 1096 for 2000-2002 with its leap year. The protocol computed that count
for itself only. ``regime`` says it once, for a phase written by hand and for
one a protocol writes, and ``runners/phase_regime.py`` is the one place that
turns it into the paths the trials run with.
"""

from __future__ import annotations

import datetime
from typing import Any

import pytest

from hydromodpy.calibration.config import (
    PHASE_REGIME_PATHS,
    CalibPhaseDecl,
    CalibrationConfig,
    fold_a_legacy_regime,
)
from hydromodpy.calibration.runners.phase_regime import phase_overrides, regime_overrides

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


class TestThePathsItWrites:
    """The paths are strings: no import tool sees them go stale."""

    @pytest.mark.parametrize("regime", ["steady", "transient"])
    def test_every_path_a_regime_writes_is_a_field_of_the_configuration(self, regime: str) -> None:
        from hydromodpy.config import HydroModPyConfig

        schema = HydroModPyConfig.model_json_schema()
        written = set(regime_overrides(_phase(regime=regime), _DOCUMENT))
        written |= set(PHASE_REGIME_PATHS[regime])

        missing = sorted(path for path in written if not _schema_has(schema, path))

        assert written
        assert missing == []

    def test_the_walker_does_not_accept_any_path(self) -> None:
        from hydromodpy.config import HydroModPyConfig

        schema = HydroModPyConfig.model_json_schema()

        assert _schema_has(schema, "simulation.time.step_value")
        assert not _schema_has(schema, "simulation.time.step_valeu")

    @pytest.mark.parametrize("regime", ["steady", "transient"])
    def test_the_config_lists_what_the_runner_writes(self, regime: str) -> None:
        """config refuses a path twice by this list, and cannot import the runner."""
        written = regime_overrides(_phase(regime=regime), _DOCUMENT)

        assert tuple(written) == PHASE_REGIME_PATHS[regime]


class TestSteady:
    def test_by_default_the_window_is_the_extent_of_the_simulation_time(self) -> None:
        overrides = regime_overrides(_phase(regime="steady"), _DOCUMENT)

        assert overrides == {
            "flow.flow_regime": "steady",
            "simulation.time.start_datetime": "2000-01-01",
            "simulation.time.end_datetime": "2002-12-31",
            "simulation.time.step_unit": "day",
            # 2000 is a leap year.
            "simulation.time.step_value": 1096,
        }

    def test_a_window_the_phase_names_wins_over_the_simulation_time(self) -> None:
        phase = _phase(regime="steady", steady_window={"start": "2001-01-01", "end": "2001-12-31"})

        overrides = regime_overrides(phase, _DOCUMENT)

        assert overrides["simulation.time.start_datetime"] == "2001-01-01"
        assert overrides["simulation.time.end_datetime"] == "2001-12-31"
        assert overrides["simulation.time.step_value"] == 365

    def test_a_named_window_needs_no_simulation_time(self) -> None:
        phase = _phase(regime="steady", steady_window={"start": "2001-01-01", "end": "2001-01-31"})

        assert regime_overrides(phase, {})["simulation.time.step_value"] == 31

    def test_a_steady_phase_without_a_time_window_is_refused(self) -> None:
        with pytest.raises(ValueError, match="simulation.time"):
            regime_overrides(_phase(regime="steady"), {"simulation": {}})

    def test_a_window_missing_a_bound_is_named(self) -> None:
        phase = _phase(regime="steady", steady_window={"start": "2001-01-01"})

        with pytest.raises(ValueError, match="missing end"):
            regime_overrides(phase, _DOCUMENT)

    def test_a_window_that_runs_backwards_is_refused(self) -> None:
        with pytest.raises(ValueError, match="not a forward window"):
            _steady_over("2002-12-31", "2000-01-01")


class TestTransient:
    def test_only_the_regime_is_restated(self) -> None:
        assert regime_overrides(_phase(regime="transient"), _DOCUMENT) == {
            "flow.flow_regime": "transient"
        }

    def test_it_reads_no_time_window(self) -> None:
        assert regime_overrides(_phase(regime="transient"), {}) == {"flow.flow_regime": "transient"}


class TestOneSpellingOfAnInstant:
    """A TOML file writes a date three legal ways and they have to agree.

    ``start_datetime = 2000-01-01`` parses as a date, ``2000-01-01T00:00:00`` as
    a datetime, a quoted value stays a string. Rendering them straight into the
    time overrides made the model depend on the spelling, so a file re-read
    from its own dump ran a different one.
    """

    def test_a_date_a_datetime_and_a_string_write_the_same_overrides(self) -> None:
        as_date = _steady_over(datetime.date(1995, 1, 1), datetime.date(2020, 12, 31))
        as_datetime = _steady_over(datetime.datetime(1995, 1, 1), datetime.datetime(2020, 12, 31))
        as_string = _steady_over("1995-01-01", "2020-12-31")

        assert as_date == as_datetime == as_string

    def test_a_bound_on_midnight_is_written_as_its_date(self) -> None:
        overrides = _steady_over("1995-01-01", "2020-12-31")

        assert overrides["simulation.time.start_datetime"] == "1995-01-01"
        assert overrides["simulation.time.end_datetime"] == "2020-12-31"
        assert overrides["simulation.time.step_value"] == 9497

    def test_a_bound_that_is_not_midnight_keeps_its_time(self) -> None:
        overrides = _steady_over("1995-01-01T06:00:00", "2020-12-31")

        assert overrides["simulation.time.start_datetime"] == "1995-01-01T06:00:00"

    def test_an_offset_is_kept_rather_than_collapsed_onto_a_date(self) -> None:
        """Two bounds two hours apart are two instants, not one date."""
        paris = _steady_over("1995-01-01T00:00:00+02:00", "2020-12-31T00:00:00+02:00")
        utc = _steady_over("1995-01-01T00:00:00+00:00", "2020-12-31T00:00:00+00:00")

        assert paris["simulation.time.start_datetime"] == "1995-01-01T00:00:00+02:00"
        assert utc["simulation.time.start_datetime"] != paris["simulation.time.start_datetime"]

    def test_a_span_that_is_not_an_instant_is_named(self) -> None:
        with pytest.raises(ValueError, match="simulation.time.start_datetime"):
            _steady_over("not a date", "2020-12-31")

    def test_a_window_with_one_offset_and_one_without_is_refused(self) -> None:
        """Their span is undefined, and pandas says so with a raw TypeError."""
        with pytest.raises(ValueError, match="offset"):
            _steady_over("1995-01-01T00:00:00+02:00", "2020-12-31")

    def test_a_bare_number_is_refused_and_not_read_as_an_epoch(self) -> None:
        """pandas reads an int as nanoseconds since 1970; a config never means that."""
        with pytest.raises(ValueError, match="simulation.time.start_datetime"):
            _steady_over(1995, "2020-12-31")


class TestSaidOnce:
    def test_a_regime_and_one_of_its_paths_in_overrides_is_refused(self) -> None:
        with pytest.raises(ValueError, match="two ways to say the same thing"):
            _phase(regime="steady", overrides={"simulation.time.step_value": 1096})

    def test_a_transient_regime_and_its_flow_regime_override_is_refused(self) -> None:
        with pytest.raises(ValueError, match="flow.flow_regime"):
            _phase(regime="transient", overrides={"flow.flow_regime": "transient"})

    def test_a_transient_regime_keeps_a_time_step_of_its_own(self) -> None:
        """Transient writes the regime only; the step stays the file's to say."""
        phase = _phase(regime="transient", overrides={"simulation.time.step_value": "1 day"})

        assert phase_overrides(phase, _DOCUMENT) == {
            "flow.flow_regime": "transient",
            "simulation.time.step_value": "1 day",
        }

    def test_a_steady_window_without_a_steady_regime_is_refused(self) -> None:
        with pytest.raises(ValueError, match="steady_window"):
            _phase(steady_window={"start": "2001-01-01", "end": "2001-12-31"})

    def test_the_refusal_reaches_the_calibration_that_declares_the_phase(self) -> None:
        with pytest.raises(ValueError, match="two ways to say the same thing"):
            CalibrationConfig.model_validate(
                {
                    "parameters": {
                        "K": {"bounds": [1e-9, 1e-3], "path": "flow.param.K.field.value"}
                    },
                    "phases": [
                        {
                            "name": "stage",
                            "parameters": ["K"],
                            "regime": "steady",
                            "overrides": {"flow.flow_regime": "steady"},
                        }
                    ],
                }
            )


class TestAPhaseWithoutARegime:
    def test_its_overrides_are_what_it_runs_with(self) -> None:
        phase = _phase(overrides={"flow.flow_regime": "steady", "display.enabled": False})

        assert phase.regime is None
        assert phase_overrides(phase, {}) == {
            "flow.flow_regime": "steady",
            "display.enabled": False,
        }

    def test_no_regime_and_no_override_writes_nothing(self) -> None:
        assert phase_overrides(_phase(), _DOCUMENT) == {}

    def test_its_own_overrides_follow_the_regime_s(self) -> None:
        phase = _phase(regime="steady", overrides={"display.enabled": False})

        assert list(phase_overrides(phase, _DOCUMENT)) == [
            *PHASE_REGIME_PATHS["steady"],
            "display.enabled",
        ]


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
                        "transform": "log",
                        "path": "flow.param.K.field.value",
                    }
                },
                "phases": [{"name": "stage", "parameters": ["K"], **phase}],
            }
        )

    def test_a_plan_carries_the_regime_s_overrides(self) -> None:
        from hydromodpy.calibration.runners.staged_runner import _phase_plans

        cfg = self._config(regime="steady")

        (plan,) = _phase_plans(cfg, list(enumerate(cfg.phases)), _DOCUMENT)

        assert plan.overrides["simulation.time.step_value"] == 1096
        assert plan.overrides["flow.flow_regime"] == "steady"

    def test_a_window_it_cannot_read_is_refused_before_the_first_solve(self) -> None:
        from hydromodpy.calibration.runners.staged_runner import _phase_plans
        from hydromodpy.core.exceptions import ConfigValidationError

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

    def test_the_regime_paths_fold_and_every_other_override_stays(self) -> None:
        folded = fold_a_legacy_regime(self._STEADY)

        assert folded is not None
        assert folded["regime"] == "steady"
        assert folded["overrides"] == {"display.overrides.seepage_map.timestep": 0}

    def test_a_phase_missing_one_of_the_paths_is_not_folded(self) -> None:
        partial = {**self._STEADY, "overrides": {"flow.flow_regime": "steady"}}

        assert fold_a_legacy_regime(partial) is None

    def test_a_phase_that_states_its_regime_is_not_folded(self) -> None:
        assert fold_a_legacy_regime({**self._STEADY, "regime": "steady"}) is None

    def test_a_named_window_is_matched_instant_by_instant(self) -> None:
        same = {"start": "2000-01-01T00:00:00", "end": "2002-12-31"}
        other = {"start": "2001-01-01", "end": "2002-12-31"}

        assert fold_a_legacy_regime(self._STEADY, same)["steady_window"] == same
        assert fold_a_legacy_regime(self._STEADY, other) is None
