"""A scoring window beside a network output read in one state.

That output is dated at the stamp of the state it reads, the stamp that closes
its period. A window that holds the stamp scores it; one that does not is
refused, naming both, at the first trial and by ``hmp calibrate --check``
before any solve. So ``scoring_window.start`` is the one way to leave a spin-up
out of a composite that scores a hydrograph and a network together.
"""

from __future__ import annotations

import pandas as pd
import pytest

from hydromodpy.calibration.config import (
    CalibObjectiveBlockDecl,
    CalibrationConfig,
    MatchingHydrographicNetworkOptions,
    validate_calib_output,
)
from hydromodpy.calibration.metrics.observable_scoring import refuse_window_without_dates
from hydromodpy.core.config_kit.profile import Profile
from tests.unit.calibration.test_preflight import _preflight, _write

MONTHS = tuple(pd.date_range("2000-01-01", periods=37, freq="MS"))
BLOCKS = [CalibObjectiveBlockDecl(name="network", metric="distance_gap", uses_outputs=["net"])]


def _network(time: str = "last") -> dict[str, object]:
    return {
        "net": validate_calib_output(
            {"support": "network", "stream_geometry_path": "n.gpkg", "time": time}
        )
    }


class TestTheRule:
    def test_before_the_grid_is_known_the_state_counts_as_dated(self) -> None:
        refuse_window_without_dates(_network(), BLOCKS, (pd.Timestamp("2001-01-01"), None), {})

    def test_a_window_holding_the_stamp_is_accepted(self) -> None:
        refuse_window_without_dates(
            _network(), BLOCKS, (pd.Timestamp("2001-01-01"), None), {}, boundaries=MONTHS
        )

    def test_a_window_ending_before_the_last_state_is_refused_naming_both(self) -> None:
        window = (pd.Timestamp("2001-01-01"), pd.Timestamp("2002-06-30"))
        with pytest.raises(ValueError) as caught:
            refuse_window_without_dates(_network(), BLOCKS, window, {}, boundaries=MONTHS)
        message = str(caught.value)
        assert "scoring_window 2001-01-01 to 2002-06-30" in message
        assert "time = 'last'" in message
        assert "2002-12" in message and "stamped 2003-01-01" in message

    def test_a_dated_state_before_the_window_is_refused(self) -> None:
        with pytest.raises(ValueError, match="stamped 2000-11-01"):
            refuse_window_without_dates(
                _network("2000-10-15"),
                BLOCKS,
                (pd.Timestamp("2001-01-01"), None),
                {},
                boundaries=MONTHS,
            )

    def test_a_date_the_run_does_not_hold_is_refused_by_output(self) -> None:
        with pytest.raises(ValueError, match="network output 'net' has time = '2004-01-01'"):
            refuse_window_without_dates(
                _network("2004-01-01"),
                BLOCKS,
                (pd.Timestamp("2001-01-01"), None),
                {},
                boundaries=MONTHS,
            )

    def test_a_typed_vector_still_has_no_date_to_cut(self) -> None:
        outputs = {
            "q": validate_calib_output(
                {
                    "support": "boundary",
                    "variable": "discharge",
                    "boundary_id": "outlet",
                    "observed_values": [1.0, 2.0],
                }
            )
        }
        blocks = [CalibObjectiveBlockDecl(name="flows", metric="rmse", uses_outputs=["q"])]
        with pytest.raises(ValueError, match="no time axis to cut on"):
            refuse_window_without_dates(outputs, blocks, (pd.Timestamp("2001-01-01"), None), {})


_PHASE = """
[calibration]

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
transform = "log"
path = "flow.param.K.field.value"
units = "m/s"

[calibration.outputs.net]
support = "network"
stream_geometry_path = "{geometry}"
time = "{time}"

[[calibration.objective_blocks]]
name = "network"
metric = "distance_gap"
uses_outputs = ["net"]

[[calibration.phases]]
name = "conductivity"
parameters = ["K"]
method = "grid"
max_iter = 4
regime = "{regime}"
{window}
"""


def _window_findings(tmp_path, *, time: str, window: str, regime: str = "transient") -> str:
    geometry = tmp_path / "streams.gpkg"
    geometry.write_bytes(b"map")
    path = _write(
        tmp_path,
        _PHASE.format(geometry=geometry, time=time, window=window, regime=regime),
    )
    return " | ".join(
        f"{item.where}: {item.detail}"
        for item in _preflight(path)
        if "scoring_window" in item.detail or "time =" in item.detail
    )


_FROM_JULY = '[calibration.phases.scoring_window]\nstart = "2000-07-01"'
_TO_JUNE = '[calibration.phases.scoring_window]\nend = "2000-06-30"'
# The steady span is a day count: a unitless timedelta warns under the pinned NumPy.
_NO_GENERIC_UNIT = pytest.mark.filterwarnings(
    "error:The 'generic' unit for NumPy timedelta:DeprecationWarning"
)


class TestTheCheckBeforeTheRun:
    """The project runs 2000 at a daily step: the last state is stamped 2001-01-01."""

    def test_a_window_holding_the_last_state_is_no_finding(self, tmp_path) -> None:
        assert _window_findings(tmp_path, time="last", window=_FROM_JULY) == ""

    def test_a_window_ending_before_it_is_named_with_its_phase(self, tmp_path) -> None:
        found = _window_findings(tmp_path, time="last", window=_TO_JUNE)
        assert "[[calibration.phases]] 'conductivity'" in found
        assert "scoring_window open to 2000-06-30" in found
        assert "stamped 2001-01-01" in found

    def test_a_dated_state_outside_the_window_is_named(self, tmp_path) -> None:
        found = _window_findings(tmp_path, time="2000-03-15", window=_FROM_JULY)
        assert "stamped 2000-03-16" in found

    def test_a_date_the_run_does_not_hold_is_named_without_a_window(self, tmp_path) -> None:
        found = _window_findings(tmp_path, time="2005-03-15", window="")
        assert "[calibration.outputs.net]" in found
        assert "outside the record" in found

    @_NO_GENERIC_UNIT
    def test_a_steady_phase_holds_every_date_of_its_window(self, tmp_path) -> None:
        found = _window_findings(tmp_path, time="2000-03-15", window="", regime="steady")
        assert found == ""

    @_NO_GENERIC_UNIT
    def test_a_steady_state_is_stamped_at_the_end_of_its_window(self, tmp_path) -> None:
        found = _window_findings(tmp_path, time="2000-03-15", window=_TO_JUNE, regime="steady")
        assert "stamped 2001-01-01" in found


class TestTheWindowIsWrittenInDates:
    def test_a_protocol_window_with_a_bad_date_fails_when_the_file_is_read(self) -> None:
        with pytest.raises(ValueError, match="is not a date"):
            MatchingHydrographicNetworkOptions.model_validate(
                {"name": "matching_hydrographic_network", "scoring_window": {"start": "2001-13-01"}}
            )

    def test_a_protocol_window_keeps_the_table_it_was_written_as(self) -> None:
        declared = MatchingHydrographicNetworkOptions.model_validate(
            {"name": "matching_hydrographic_network", "scoring_window": {"start": "2001-01-01"}}
        )
        assert declared.scoring_window == {"start": "2001-01-01"}

    def test_a_steady_span_needs_both_bounds(self) -> None:
        with pytest.raises(ValueError, match="missing end"):
            MatchingHydrographicNetworkOptions.model_validate(
                {"name": "matching_hydrographic_network", "steady_window": {"start": "2000-01-01"}}
            )

    def test_an_unknown_bound_is_refused(self) -> None:
        with pytest.raises(ValueError, match="start"):
            MatchingHydrographicNetworkOptions.model_validate(
                {"name": "matching_hydrographic_network", "scoring_window": {"begin": "2001-01-01"}}
            )

    def test_the_sample_counts_are_expert_keys(self) -> None:
        from hydromodpy.calibration.config import CalibObjectiveBlockDecl as Block

        def profile(model, field: str) -> object:
            return next(
                item for item in model.model_fields[field].metadata if isinstance(item, Profile)
            )

        assert profile(CalibrationConfig, "warmup_periods") is Profile.EXPERT
        assert profile(Block, "warmup") is Profile.EXPERT
        assert profile(CalibrationConfig, "scoring_window") is Profile.USER

    def test_the_sample_counts_still_load(self) -> None:
        cfg = CalibrationConfig.model_validate(
            {"parameters": {"K": {"bounds": [1e-8, 1e-2]}}, "warmup_periods": 12}
        )
        assert cfg.warmup_periods == 12
