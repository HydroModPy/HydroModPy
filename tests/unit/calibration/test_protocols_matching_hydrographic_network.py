"""Tests of `protocols.matching_hydrographic_network`."""

from __future__ import annotations

import copy
import datetime
import math
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.config_network import MatchingHydrographicNetworkOptions
from hydromodpy.calibration.optim.adapters.scipy_adapter import ScipyNelderMead
from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.protocols import matching_hydrographic_network as module
from hydromodpy.calibration.protocols.matching_hydrographic_network import (
    DEFAULTS_BY_VERSION,
    HYDROGRAPH_BLOCK,
    HYDROGRAPH_OUTPUT,
    STEADY_STAGE,
    TRANSIENT_STAGE,
    _write_hydrograph_output,
    why_the_spin_up_year_is_scored,
)
from hydromodpy.calibration.protocols.registry import expand_calibration_protocol, protocol_record
from hydromodpy.calibration.runners.session_scope import _protocol_of_session
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from tests.unit.calibration._factories_scoring import make_document

# From test_a_removed_key_on_the_hydrograph_output_is_named.py
# A sealed run whose hydrograph output still carries a removed key is refused for that key.
#
# The protocol compares the point output it writes with the one a sealed run
# spelled out. An output that no longer validates is not another output under
# the same name: the refusal names the key, here the per-output
# ``diagonal_neighbors`` the descent D made obsolete.


def _sealed(**extra: object) -> dict[str, object]:
    return {
        HYDROGRAPH_OUTPUT: {
            "variable": "discharge",
            "support": "point",
            "observes": "NANCON",
            **extra,
        }
    }


def test_a_removed_key_is_named_and_not_read_as_a_collision() -> None:
    outputs = _sealed(diagonal_neighbors=False)

    with pytest.raises(
        ValueError, match="'diagonal_neighbors', which this output does not"
    ) as info:
        _write_hydrograph_output(
            outputs,
            MatchingHydrographicNetworkOptions(name="matching_hydrographic_network"),
            "NANCON",
        )

    assert "Rename it" not in str(info.value)


def test_another_output_under_the_name_is_still_a_collision() -> None:
    outputs = _sealed(observes="OTHER")

    with pytest.raises(ValueError, match="Rename it"):
        _write_hydrograph_output(
            outputs,
            MatchingHydrographicNetworkOptions(name="matching_hydrographic_network"),
            "NANCON",
        )


# From test_the_protocol_is_versioned.py
# A number that informed a decision must be replayable with the recipe of its era.
#
# Naming a method is not enough for that. A recipe improves, and a file that ran
# version 1.2 and silently gets 1.3 has lost the only guarantee a pin exists to
# give. So the version is declared, a file may pin one the table holds, a pin writes
# the values of its version for every key the file leaves empty, and any other pin
# is refused rather than approximated.
#
# Two more things the record has to carry, for the same reason. Where this
# implementation departs from its publication, because a protocol that silently
# improves on its paper is no longer that paper's method. And what running it on
# each backend is actually worth, in a vocabulary that separates "a case runs this"
# from "nothing forbids it and nobody tried".


NAME = "matching_hydrographic_network"


class TestTheVersion:
    def test_the_record_carries_it(self) -> None:
        assert protocol_record(NAME)["version"] == "1.3"

    def test_a_mismatched_pin_is_refused_rather_than_approximated(self) -> None:
        with pytest.raises(ValueError, match="carries 1.2, 1.3.*replayable"):
            expand_calibration_protocol(make_document(protocol={"name": NAME, "version": "0.9"}))

    def test_the_released_1_1_is_refused_now_that_its_defaults_moved(self) -> None:
        """v2.0.0a1 shipped 1.1; the fill, the spin-up year and the length bound moved since."""
        with pytest.raises(ValueError, match="replayable"):
            expand_calibration_protocol(
                make_document(protocol={"name": "matching_hydrographic_network", "version": "1.1"})
            )


def _network_output_of(protocol: object, **written: object) -> dict[str, object]:
    doc = make_document(protocol=protocol)
    doc["calibration"]["outputs"]["seepage_network"].update(written)
    return expand_calibration_protocol(doc)["calibration"]["outputs"]["seepage_network"]


def _leaves(row: dict, path: tuple[str, ...] = ()):
    for key, value in row.items():
        if isinstance(value, dict):
            yield from _leaves(value, (*path, key))
        else:
            yield (*path, key), value


class TestTheSessionWritesItsDepartures:
    def _session_protocol(self, protocol: object):
        doc = expand_calibration_protocol(make_document(protocol=protocol))
        cfg = CalibrationConfig.model_validate(doc["calibration"])
        return _protocol_of_session(cfg, None)

    def test_a_file_without_a_pin_writes_every_default_that_departs(self) -> None:
        record = self._session_protocol(NAME)

        assert record.version == "1.3"
        departures = {item.key: item for item in record.departures}
        assert departures["map.drawn_by"].value == "heads"
        assert departures["map.drawn_by"].written is False
        assert departures["verdict.max_catchment_mismatch"].value == "0.05"
        assert departures["model.seepage_threshold"].always is False
        assert departures["steady_recharge_window"].always is False
        assert "steady_recharge_window" in departures
        assert "dem_correc_type" not in departures

    def test_a_pin_on_1_2_writes_its_own_defaults(self) -> None:
        record = self._session_protocol({"name": NAME, "version": "1.2"})

        assert record.version == "1.2"
        departures = {item.key for item in record.departures}
        assert "map.drawn_by" not in departures
        assert "verdict.max_catchment_mismatch" not in departures


# From test_the_protocol_leaves_the_spin_up_year_out.py
# The protocol's transient stage does not score the spin-up year by default.
#
# The transient stage runs the project's own time grid, whose first year starts
# from an initial condition the run did not produce. The protocol used to write
# a scoring window on that stage only when the file declared one, so without it
# the hydrograph, and a two-bound network scored in the same phase, read the
# spin-up year like any other. It now opens the window one year after
# ``[simulation.time].start_datetime``. A window or a warm-up the file declares
# still wins, and the steady stage is written as before.


def _stages(doc) -> tuple[dict, dict]:
    steady, transient = expand_calibration_protocol(doc)["calibration"]["phases"]
    return steady, transient


class TestTheDefaultWindow:
    def test_no_storage_stage_means_no_window_at_all(self) -> None:
        phases = expand_calibration_protocol(
            make_document(protocol={"name": NAME, "storage": None})
        )["calibration"]["phases"]

        assert [phase["name"] for phase in phases] == [STEADY_STAGE]
        assert "window" not in phases[0]


class TestADeclarationWins:
    def test_a_window_on_the_calibration_leaves_the_phase_to_inherit_it(self) -> None:
        window = {"start": "1997-01-01", "end": "2020-12-31"}

        _, transient = _stages(make_document(window=window))

        assert "window" not in transient


class TestTheCheckSaysWhenTheWindowCannotApply:
    """The expansion drops the window silently; ``--check`` prints why."""

    def _why(self, doc) -> str | None:
        calibration = CalibrationConfig.model_validate(
            expand_calibration_protocol(doc)["calibration"]
        )
        time = doc["simulation"]["time"]
        return why_the_spin_up_year_is_scored(
            calibration,
            SimpleNamespace(
                start_datetime=datetime.datetime.fromisoformat(time["start_datetime"]),
                end_datetime=datetime.datetime.fromisoformat(time["end_datetime"]),
            ),
        )

    def test_no_storage_stage_says_nothing(self) -> None:
        doc = make_document(
            start="2000-01-01", end="2000-12-31", protocol={"name": NAME, "storage": None}
        )

        assert self._why(doc) is None

    def test_a_sealed_stage_without_a_window_is_named(self) -> None:
        fresh = expand_calibration_protocol(make_document())["calibration"]
        sealed_phases = copy.deepcopy(fresh["phases"])
        del sealed_phases[1]["window"]
        sealed_phases[1]["description"] = (
            "Read Sy from the observed hydrograph, K frozen, transient."
        )

        why = self._why(
            make_document(phases=sealed_phases, objective_blocks=fresh["objective_blocks"])
        )

        assert why is not None
        assert f"the {TRANSIENT_STAGE} phase this file writes has no window" in why


# From test_the_reference_replication_keeps_its_estimator.py
# The MODFLOW 6 replication of the reference script must not drift to the recipe.
#
# ``ref_example04.toml`` exists to be read beside ``example_04_calibration.py``: it
# measures what changes when the published estimator is replaced by the script's
# own mean offset. Someone tidying it toward the protocol's published defaults
# would delete the only thing it is for, and the file would still validate. So the
# values it departs on are gated, not commented.


REFERENCE = (
    Path(__file__).resolve().parents[3]
    / "examples"
    / "projects"
    / "21_nancon_network_calibration"
    / "ref_example04.toml"
)


@pytest.fixture(scope="module")
def calibration__reference_replication():
    return HydroModPyConfig.from_toml(REFERENCE).calibration


# The steady trace of a Nancon session run with these options on 2026-09-08:
# log10 K against the mean offset, in meters. Nine solves, one of them a repeat.
_NANCON_STEADY_TRACE = {
    -5.0: 287.3839080695424,
    -4.4: 186.641131046373,
    -3.8: 300.1191516816517,
    -4.55: 214.26321839924782,
    -4.25: 185.7234104098768,
    -3.95: 232.09030552780553,
    -4.1: 208.383141357349,
    -4.2875: 192.34474990832632,
}


def _replay(sugg: ParamSuggestion) -> EvaluationResult:
    point = round(math.log10(float(sugg.values["K"])), 6)
    return EvaluationResult(
        trial_id=sugg.trial_id,
        sim_id=None,
        cost=_NANCON_STEADY_TRACE[point],
        status="completed",
    )


def test_stage_one_meets_its_own_tolerance_well_inside_its_budget(
    calibration__reference_replication,
) -> None:
    # A simplex that runs out of its max_trials = 60 reports not converged. On
    # the recorded Nancon trace the simplex meets xatol and fatol after 9
    # solves, so the steady stage converges and freezes K for the transient one.
    steady = calibration__reference_replication.phases[0]
    lower, upper = calibration__reference_replication.parameters["K"].bounds
    space = ParameterSpace([CalibParameter(name="K", lower=lower, upper=upper, search_space="log")])
    optimizer = ScipyNelderMead(space, **steady.method_options)
    engine = CalibrationEngine(
        space=space, optimizer=optimizer, evaluator=_replay, max_trials=steady.max_trials
    )

    session = engine.run()

    assert session.converged
    assert session.extension == 0
    assert len(session.history) == 9


def test_stage_two_reads_storage_from_the_hydrograph_with_conductivity_frozen(
    calibration__reference_replication,
) -> None:
    assert calibration__reference_replication.phases[0].freeze_on_success is True
    storage = calibration__reference_replication.phases[1]
    assert storage.depends_on == STEADY_STAGE
    assert storage.parameters == ["Sy"]
    assert storage.objective_blocks == [HYDROGRAPH_BLOCK]
    assert storage.max_trials == 120
    assert storage.method_options["xatol"] == pytest.approx(3.7e-5)
    # The reference scores the whole calibration window, with no spin-up year cut.
    # The protocol leaves the first year out by default, so the file says so.
    assert storage.window is not None
    assert (storage.window.start, storage.window.end) == ("1995-01-01", None)

    hydrograph = next(
        block
        for block in calibration__reference_replication.objective_blocks
        if block.name == HYDROGRAPH_BLOCK
    )
    assert hydrograph.metric == "nse_log"
    assert hydrograph.uses_outputs == [HYDROGRAPH_OUTPUT]
    output = calibration__reference_replication.outputs[HYDROGRAPH_OUTPUT]
    assert output.observes == "NANCON"
    assert output.variable == "discharge"


def test_the_two_stage_card_is_asked_for_by_its_current_name() -> None:
    text = REFERENCE.read_text(encoding="utf-8")
    assert "matching_hydrographic_network_card" in text
    assert "abherve_two_stage_card" not in text


# The readers of a declaration, on the shapes a file or a sealed run can bring.


def _calibration(*, protocol_window=None, window=None, protocol_name=NAME, phase_window=None):
    declared = SimpleNamespace(name=protocol_name, storage=True, window=protocol_window)
    phase = SimpleNamespace(name=TRANSIENT_STAGE, window=phase_window)
    return SimpleNamespace(protocol=declared, window=window, phases=[phase], validation_window=None)


@pytest.mark.parametrize(
    ("calibration", "time"),
    [
        (_calibration(protocol_name="other"), SimpleNamespace(start_datetime="2000-01-01")),
        (
            _calibration(window={"start": "2000-01-01"}),
            SimpleNamespace(start_datetime="2000-01-01"),
        ),
        (_calibration(), SimpleNamespace(start_datetime=None)),
    ],
    ids=["another_protocol", "a_window_on_the_calibration", "no_start_date"],
)
def test_the_check_says_nothing_when_the_default_window_cannot_be_the_reason(
    calibration, time
) -> None:
    assert why_the_spin_up_year_is_scored(calibration, time) is None


@pytest.mark.parametrize(
    ("calibration", "metrics_window", "expected"),
    [
        (_calibration(protocol_window={"start": "2000-01-01"}), None, False),
        (_calibration(window={"start": "2000-01-01"}), None, False),
        (_calibration(), None, True),
    ],
)
def test_the_spin_up_year_is_left_out_only_when_no_window_is_written(
    calibration, metrics_window, expected
) -> None:
    assert module._scores_the_spin_up_year(calibration, metrics_window) is expected


def test_a_window_is_the_default_one_only_where_the_run_has_a_start() -> None:
    window = {"start": "2001-01-01"}

    assert not module._is_the_default_window(window, _calibration(), SimpleNamespace(), None)
    assert not module._is_window("2001-01-01", window)


def test_an_output_takes_the_defaults_of_a_version_under_the_rule_it_draws() -> None:
    version = next(reversed(DEFAULTS_BY_VERSION))
    default_rule = DEFAULTS_BY_VERSION[version]["map"]["drawn_by"]

    assert module._with_the_defaults_of(version, "not a table") == "not a table"
    assert ("heads" in module._with_the_defaults_of(version, {})["map"]) is (
        default_rule == "heads"
    )
    assert "heads" in module._with_the_defaults_of(version, {"map": {"drawn_by": "heads"}})["map"]


def test_the_network_output_named_is_the_one_scored_or_the_file_is_refused() -> None:
    options = MatchingHydrographicNetworkOptions(name=NAME, network_output="net")

    assert module._resolve_network_output({"net": {}}, options) == "net"
    with pytest.raises(ValueError, match="names 'net', but .* declares nothing"):
        module._resolve_network_output({}, options)


@pytest.mark.parametrize(
    "sources",
    [
        ["NANCON"],
        [{"station_ids": ["A"]}, {"mask_path": "m.shp"}],
        [{"station_ids": ["A"]}, {"station_ids": ["B"]}],
    ],
)
def test_no_station_is_read_from_sources_that_do_not_name_exactly_one(sources) -> None:
    document = {"data": {"hydrometry": {"sources": sources}}}

    assert module._resolve_observed_station(document) is None


def test_an_output_that_fails_to_validate_for_another_reason_raises_its_own_error() -> None:
    outputs = {HYDROGRAPH_OUTPUT: {"variable": "discharge", "support": "point", "observes": 3.5}}

    with pytest.raises(ValidationError):
        _write_hydrograph_output(outputs, MatchingHydrographicNetworkOptions(name=NAME), "NANCON")


@pytest.mark.parametrize("value", ["not a date", "NaT"])
def test_a_bound_that_is_not_a_date_is_refused_with_its_source(value) -> None:
    with pytest.raises(ValueError, match=r"window.start is not a date"):
        module._instant(value, "window.start")


@pytest.mark.parametrize(
    ("stamp", "spelled"),
    [
        ("2000-01-05", "2000-01-05"),
        ("2000-01-05 06:00", "2000-01-05T06:00:00"),
        ("2000-01-05", "2000-01-05T00:00:00+01:00"),
    ],
)
def test_an_instant_is_spelled_as_a_date_only_at_naive_midnight(stamp, spelled) -> None:
    tz = "Europe/Paris" if "+" in spelled else None

    assert module._spelled(pd.Timestamp(stamp, tz=tz)) == spelled
