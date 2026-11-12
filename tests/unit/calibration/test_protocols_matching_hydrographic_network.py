"""Two-stage protocol that matches the hydrographic network, and its recipe versions.

Stage one fits the conductivity K (m/s) on the steady network, stage two reads the
specific yield Sy (-) from the hydrograph with K frozen. Windows are ISO dates.
A version pin replays the defaults of its era, and a departure from the paper is
recorded.
"""

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

NAME = "matching_hydrographic_network"
OPTIONS = MatchingHydrographicNetworkOptions(name=NAME)

REFERENCE = (
    Path(__file__).resolve().parents[3]
    / "examples"
    / "projects"
    / "21_nancon_network_calibration"
    / "ref_example04.toml"
)

# Steady trace of a Nancon session run with these options on 2026-09-08:
# log10 K against the mean offset, in meters. Nine solves, one of them a repeat.
NANCON_STEADY_TRACE = {
    -5.0: 287.3839080695424,
    -4.4: 186.641131046373,
    -3.8: 300.1191516816517,
    -4.55: 214.26321839924782,
    -4.25: 185.7234104098768,
    -3.95: 232.09030552780553,
    -4.1: 208.383141357349,
    -4.2875: 192.34474990832632,
}


def sealed_outputs(**extra: object) -> dict[str, object]:
    return {
        HYDROGRAPH_OUTPUT: {
            "variable": "discharge",
            "support": "point",
            "observes": "NANCON",
            **extra,
        }
    }


def calibration_stub(*, protocol_window=None, window=None, protocol_name=NAME, phase_window=None):
    declared = SimpleNamespace(name=protocol_name, storage=True, window=protocol_window)
    phase = SimpleNamespace(name=TRANSIENT_STAGE, window=phase_window)
    return SimpleNamespace(protocol=declared, window=window, phases=[phase], validation_window=None)


def session_protocol(protocol: object):
    doc = expand_calibration_protocol(make_document(protocol=protocol))
    cfg = CalibrationConfig.model_validate(doc["calibration"])
    return _protocol_of_session(cfg, None)


def why_for(doc: dict) -> str | None:
    calibration = CalibrationConfig.model_validate(expand_calibration_protocol(doc)["calibration"])
    time = doc["simulation"]["time"]
    return why_the_spin_up_year_is_scored(
        calibration,
        SimpleNamespace(
            start_datetime=datetime.datetime.fromisoformat(time["start_datetime"]),
            end_datetime=datetime.datetime.fromisoformat(time["end_datetime"]),
        ),
    )


def replay(sugg: ParamSuggestion) -> EvaluationResult:
    point = round(math.log10(float(sugg.values["K"])), 6)
    return EvaluationResult(
        trial_id=sugg.trial_id,
        sim_id=None,
        cost=NANCON_STEADY_TRACE[point],
        status="completed",
    )


@pytest.fixture(scope="module")
def reference_calibration():
    return HydroModPyConfig.from_toml(REFERENCE).calibration


def test_removed_key_named() -> None:
    # The per-output ``diagonal_neighbors`` key no longer exists.
    outputs = sealed_outputs(diagonal_neighbors=False)

    with pytest.raises(
        ValueError, match="'diagonal_neighbors', which this output does not"
    ) as info:
        _write_hydrograph_output(outputs, OPTIONS, "NANCON")

    assert "Rename it" not in str(info.value)


def test_other_output_is_collision() -> None:
    with pytest.raises(ValueError, match="Rename it"):
        _write_hydrograph_output(sealed_outputs(observes="OTHER"), OPTIONS, "NANCON")


def test_other_output_error_kept() -> None:
    outputs = {HYDROGRAPH_OUTPUT: {"variable": "discharge", "support": "point", "observes": 3.5}}

    with pytest.raises(ValidationError):
        _write_hydrograph_output(outputs, OPTIONS, "NANCON")


def test_record_version() -> None:
    assert protocol_record(NAME)["version"] == "1.3"


@pytest.mark.parametrize(
    ("version", "match"),
    [
        pytest.param("0.9", "carries 1.2, 1.3.*replayable", id="unknown pin"),
        # v2.0.0a1 shipped 1.1. The fill, the spin-up year and the length bound moved since.
        pytest.param("1.1", "replayable", id="released 1.1"),
    ],
)
def test_pin_refused_not_approximated(version, match) -> None:
    with pytest.raises(ValueError, match=match):
        expand_calibration_protocol(make_document(protocol={"name": NAME, "version": version}))


def test_unpinned_file_writes_departures() -> None:
    record = session_protocol(NAME)

    assert record.version == "1.3"
    departures = {item.key: item for item in record.departures}
    assert departures["map.drawn_by"].value == "heads"
    assert departures["map.drawn_by"].written is False
    assert departures["verdict.max_catchment_mismatch"].value == "0.05"
    assert departures["model.seepage_threshold"].always is False
    assert departures["steady_recharge_window"].always is False
    assert "dem_correc_type" not in departures


def test_pin_1_2_writes_defaults() -> None:
    # The second expansion takes the path where the 1.2 notice was already told.
    session_protocol({"name": NAME, "version": "1.2"})
    record = session_protocol({"name": NAME, "version": "1.2"})

    assert record.version == "1.2"
    departures = {item.key for item in record.departures}
    assert "map.drawn_by" not in departures
    assert "verdict.max_catchment_mismatch" not in departures


# The transient stage does not score the spin-up year by default.
def test_no_storage_stage_means_no_window() -> None:
    phases = expand_calibration_protocol(make_document(protocol={"name": NAME, "storage": None}))[
        "calibration"
    ]["phases"]

    assert [phase["name"] for phase in phases] == [STEADY_STAGE]
    assert "window" not in phases[0]


def test_phase_inherits_calibration_window() -> None:
    window = {"start": "1997-01-01", "end": "2020-12-31"}

    _, transient = expand_calibration_protocol(make_document(window=window))["calibration"][
        "phases"
    ]

    assert "window" not in transient


def test_no_storage_stage_silent() -> None:
    doc = make_document(
        start="2000-01-01", end="2000-12-31", protocol={"name": NAME, "storage": None}
    )

    assert why_for(doc) is None


def test_sealed_stage_without_window() -> None:
    fresh = expand_calibration_protocol(make_document())["calibration"]
    sealed_phases = copy.deepcopy(fresh["phases"])
    del sealed_phases[1]["window"]
    sealed_phases[1]["description"] = "Read Sy from the observed hydrograph, K frozen, transient."

    why = why_for(make_document(phases=sealed_phases, objective_blocks=fresh["objective_blocks"]))

    assert why is not None
    assert f"the {TRANSIENT_STAGE} phase this file writes has no window" in why


# The replication of the reference script must not drift to the recipe: the file
# departs from the published defaults on purpose, so its values are gated.
def test_stage_one_meets_tolerance(reference_calibration) -> None:
    # On the recorded Nancon trace the simplex meets xatol and fatol after 9 solves.
    steady = reference_calibration.phases[0]
    lower, upper = reference_calibration.parameters["K"].bounds
    space = ParameterSpace([CalibParameter(name="K", lower=lower, upper=upper, search_space="log")])
    optimizer = ScipyNelderMead(space, **steady.method_options)
    engine = CalibrationEngine(
        space=space, optimizer=optimizer, evaluator=replay, max_trials=steady.max_trials
    )

    session = engine.run()

    assert session.converged
    assert session.extension == 0
    assert len(session.history) == 9


def test_stage_two_reads_storage(reference_calibration) -> None:
    assert reference_calibration.phases[0].freeze_on_success is True
    storage = reference_calibration.phases[1]
    assert storage.depends_on == STEADY_STAGE
    assert storage.parameters == ["Sy"]
    assert storage.objective_blocks == [HYDROGRAPH_BLOCK]
    assert storage.max_trials == 120
    assert storage.method_options["xatol"] == pytest.approx(3.7e-5)
    # The reference scores the whole calibration window, with no spin-up year cut.
    assert storage.window is not None
    assert (storage.window.start, storage.window.end) == ("1995-01-01", None)

    hydrograph = next(
        block for block in reference_calibration.objective_blocks if block.name == HYDROGRAPH_BLOCK
    )
    assert hydrograph.metric == "nse_log"
    assert hydrograph.uses_outputs == [HYDROGRAPH_OUTPUT]
    output = reference_calibration.outputs[HYDROGRAPH_OUTPUT]
    assert output.observes == "NANCON"
    assert output.variable == "discharge"


def test_reference_card_name() -> None:
    text = REFERENCE.read_text(encoding="utf-8")

    assert "matching_hydrographic_network_card" in text
    assert "abherve_two_stage_card" not in text


SILENT_CHECKS = [
    pytest.param(
        calibration_stub(protocol_name="other"),
        SimpleNamespace(start_datetime="2000-01-01"),
        id="another protocol",
    ),
    pytest.param(
        calibration_stub(window={"start": "2000-01-01"}),
        SimpleNamespace(start_datetime="2000-01-01"),
        id="window on the calibration",
    ),
    pytest.param(calibration_stub(), SimpleNamespace(start_datetime=None), id="no start date"),
]


@pytest.mark.parametrize(("calibration", "time"), SILENT_CHECKS)
def test_spin_up_check_silent(calibration, time) -> None:
    assert why_the_spin_up_year_is_scored(calibration, time) is None


SPIN_UP = [
    pytest.param(
        calibration_stub(protocol_window={"start": "2000-01-01"}), False, id="protocol window"
    ),
    pytest.param(calibration_stub(window={"start": "2000-01-01"}), False, id="calibration window"),
    pytest.param(calibration_stub(), True, id="no window"),
]


@pytest.mark.parametrize(("calibration", "expected"), SPIN_UP)
def test_spin_up_year_scored(calibration, expected) -> None:
    assert module._scores_the_spin_up_year(calibration, None) is expected


def test_default_window_needs_a_run_start() -> None:
    window = {"start": "2001-01-01"}

    assert not module._is_the_default_window(window, calibration_stub(), SimpleNamespace(), None)
    assert not module._is_window("2001-01-01", window)


def test_output_takes_version_defaults() -> None:
    version = next(reversed(DEFAULTS_BY_VERSION))
    default_rule = DEFAULTS_BY_VERSION[version]["map"]["drawn_by"]

    assert module._with_the_defaults_of(version, "not a table") == "not a table"
    assert ("heads" in module._with_the_defaults_of(version, {})["map"]) is (
        default_rule == "heads"
    )
    assert "heads" in module._with_the_defaults_of(version, {"map": {"drawn_by": "heads"}})["map"]


def test_named_network_output() -> None:
    options = MatchingHydrographicNetworkOptions(name=NAME, network_output="net")

    assert module._resolve_network_output({"net": {}}, options) == "net"
    with pytest.raises(ValueError, match="names 'net', but .* declares nothing"):
        module._resolve_network_output({}, options)


@pytest.mark.parametrize(
    "sources",
    [
        pytest.param(["NANCON"], id="plain name"),
        pytest.param([{"station_ids": ["A"]}, {"mask_path": "m.shp"}], id="one without station"),
        pytest.param([{"station_ids": ["A"]}, {"station_ids": ["B"]}], id="two stations"),
    ],
)
def test_no_station_unless_one_named(sources) -> None:
    document = {"data": {"hydrometry": {"sources": sources}}}

    assert module._resolve_observed_station(document) is None


@pytest.mark.parametrize("value", ["not a date", "NaT"])
def test_non_date_bound_refused(value) -> None:
    with pytest.raises(ValueError, match=r"window.start is not a date"):
        module._instant(value, "window.start")


@pytest.mark.parametrize(
    ("stamp", "spelled"),
    [
        pytest.param("2000-01-05", "2000-01-05", id="naive midnight"),
        pytest.param("2000-01-05 06:00", "2000-01-05T06:00:00", id="naive hour"),
        pytest.param("2000-01-05", "2000-01-05T00:00:00+01:00", id="aware midnight"),
    ],
)
def test_instant_spelling(stamp, spelled) -> None:
    tz = "Europe/Paris" if "+" in spelled else None

    assert module._spelled(pd.Timestamp(stamp, tz=tz)) == spelled
