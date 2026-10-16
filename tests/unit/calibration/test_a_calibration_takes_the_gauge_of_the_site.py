"""``[site] gauge`` is the station a calibration scores at, unless the document says otherwise.

``apply_project_defaults`` writes the gauge into ``observed_station_id`` (on
the section, on each phase) and into ``observes`` of a point output that
names no station, no position and no observed values. A written station that
is not the gauge is refused with both keys. ``[metrics] window`` is the
default scoring window.
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration.config import apply_project_defaults
from hydromodpy.core.site.gauge import GaugeConflictError

pytestmark = pytest.mark.unit

GAUGE = "J0014010"


def _defaults(section: dict, *, gauge: str | None = GAUGE, window: dict | None = None) -> dict:
    return apply_project_defaults(section, site_gauge=gauge, metrics_window=window)


class TestTheSectionAndThePhases:
    def test_the_gauge_is_the_station_when_none_is_written(self) -> None:
        resolved = _defaults({"phases": [{"name": "steady_k"}, {"name": "sy"}]})

        assert resolved["observed_station_id"] == GAUGE
        assert [phase["observed_station_id"] for phase in resolved["phases"]] == [GAUGE, GAUGE]

    def test_a_phase_that_writes_the_gauge_keeps_it(self) -> None:
        resolved = _defaults({"phases": [{"name": "sy", "observed_station_id": GAUGE}]})

        assert resolved["phases"][0]["observed_station_id"] == GAUGE

    def test_a_phase_that_names_another_station_is_refused_with_both_keys(self) -> None:
        with pytest.raises(GaugeConflictError) as caught:
            _defaults({"phases": [{"name": "sy", "observed_station_id": "J9999999"}]})

        assert "site.gauge = 'J0014010'" in str(caught.value)
        assert "calibration.phases.sy.observed_station_id = 'J9999999'" in str(caught.value)

    def test_a_section_that_names_another_station_is_refused_with_both_keys(self) -> None:
        with pytest.raises(GaugeConflictError, match="calibration.observed_station_id"):
            _defaults({"observed_station_id": "J9999999"})

    def test_without_a_gauge_nothing_is_written(self) -> None:
        section = {"observed_station_id": "J9999999", "phases": [{"name": "sy"}]}

        assert _defaults(section, gauge=None) == section


class TestThePointOutputs:
    def test_an_output_with_neither_station_nor_position_observes_the_gauge(self) -> None:
        resolved = _defaults({"outputs": {"q": {"support": "point", "variable": "discharge"}}})

        assert resolved["outputs"]["q"]["observes"] == GAUGE

    @pytest.mark.parametrize(
        "located",
        [
            {"x": 1.0, "y": 2.0},
            {"geometry": "POINT (1 2)"},
            {"observed_values": [1.0, 2.0]},
        ],
        ids=["x_y", "geometry", "observed_values"],
    )
    def test_an_output_that_locates_or_scores_itself_takes_no_gauge(self, located) -> None:
        output = {"support": "point", "variable": "head", **located}

        resolved = _defaults({"outputs": {"piezo": output}})

        assert resolved["outputs"]["piezo"] == output
        assert "observes" not in resolved["outputs"]["piezo"]

    def test_an_output_with_its_own_position_and_another_station_is_left_alone(self) -> None:
        output = {"support": "point", "variable": "head", "x": 1.0, "y": 2.0, "observes": "P1"}

        assert _defaults({"outputs": {"piezo": output}})["outputs"]["piezo"] == output

    def test_an_output_that_names_another_station_without_a_position_is_refused(self) -> None:
        with pytest.raises(GaugeConflictError, match="calibration.outputs.q.observes = 'J9'"):
            _defaults({"outputs": {"q": {"support": "point", "observes": "J9"}}})

    def test_a_network_output_is_not_a_point(self) -> None:
        output = {"support": "network", "stream_geometry_path": "streams.gpkg"}

        assert _defaults({"outputs": {"net": output}})["outputs"]["net"] == output


class TestTheScoringWindow:
    WINDOW = {"start": "2001-01-01", "end": "2002-12-31"}

    def test_the_metrics_window_is_the_default(self) -> None:
        resolved = _defaults({}, window=self.WINDOW)

        assert resolved["scoring_window"] == {"start": "2001-01-01", "end": "2002-12-31"}

    def test_a_written_window_or_a_warmup_wins(self) -> None:
        own = {"start": "2010-01-01", "end": "2010-12-31"}

        assert _defaults({"scoring_window": own}, window=self.WINDOW)["scoring_window"] == own
        assert "scoring_window" not in _defaults({"warmup_periods": 12}, window=self.WINDOW)

    def test_each_phase_but_a_steady_one_takes_the_metrics_window(self) -> None:
        own = {"start": "2002-01-01", "end": "2002-12-31"}
        phases = [
            {"name": "steady_k", "regime": "steady"},
            {"name": "transient_sy", "regime": "transient"},
            {"name": "own", "scoring_window": own},
        ]

        resolved = _defaults({"phases": phases}, window=self.WINDOW)

        assert "scoring_window" not in resolved
        steady, transient, written = resolved["phases"]
        assert "scoring_window" not in steady
        assert transient["scoring_window"] == {"start": "2001-01-01", "end": "2002-12-31"}
        assert written["scoring_window"] == own

    def test_a_half_window_is_no_default(self) -> None:
        assert "scoring_window" not in _defaults({}, window={"start": "2001-01-01", "end": None})
