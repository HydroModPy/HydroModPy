"""The run emits the prose describing what it did, with citations.

Borrowed from fMRIPrep, where it is the highest-yield reproducibility feature the
project has. Two properties earn it: it cannot drift from what ran, because it is
generated from the same declarations that ran, and it is conditioned on the
stages that COMPLETED rather than on the ones that were planned.

That second property is the whole point. A two-stage method whose transient stage
died would otherwise be written up as a two-stage calibration, and the specific
yield it never touched would be reported as calibrated.
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration.protocols.boilerplate import methods_paragraph

NAME = "matching_hydrographic_network"


class TestWhatItAlwaysSays:
    def test_it_names_the_protocol_and_its_version(self) -> None:
        text = methods_paragraph(NAME, stages_that_ran=["steady_conductivity"])

        assert NAME in text
        assert "version 1.2" in text

    def test_it_cites_the_publication(self) -> None:
        text = methods_paragraph(NAME, stages_that_ran=["steady_conductivity"])

        assert "Abherve" in text
        assert "10.5194/hess-27-3221-2023" in text


class TestItDescribesWhatRan:
    def test_two_completed_stages_are_both_described(self) -> None:
        text = methods_paragraph(NAME, stages_that_ran=["steady_conductivity", "transient_storage"])

        assert "2 of the 2 stages completed" in text
        assert "(1)" in text and "(2)" in text

    def test_one_completed_stage_says_the_other_did_not(self) -> None:
        text = methods_paragraph(NAME, stages_that_ran=["steady_conductivity"])

        assert "1 of the 2 stages completed" in text
        assert "did not complete" in text
        assert "keeps the value it entered" in text

    def test_no_completed_stage_reports_no_value(self) -> None:
        text = methods_paragraph(NAME, stages_that_ran=[])

        assert "No stage" in text
        assert "no calibrated value is reported" in text


class TestItReportsTheNumbers:
    def test_the_calibrated_values_appear(self) -> None:
        text = methods_paragraph(
            NAME,
            stages_that_ran=["steady_conductivity", "transient_storage"],
            calibrated={"K": 3.14e-6, "Sy": 0.0587},
        )

        assert "K = 3.14e-06" in text
        assert "Sy = 0.0587" in text


class TestItReportsTheDepartures:
    def test_a_departure_from_the_paper_is_named_with_both_values(self) -> None:
        text = methods_paragraph(
            NAME,
            stages_that_ran=["steady_conductivity"],
            chosen={"weighting": "area"},
        )

        assert "departs from the published method" in text
        assert "weighting" in text
        assert "one cell one vote" in text

    def test_a_run_on_the_paper_s_settings_claims_no_departure(self) -> None:
        text = methods_paragraph(NAME, stages_that_ran=["steady_conductivity"])

        assert "departs from the published method" not in text

    def test_a_file_that_restates_the_paper_s_own_value_claims_no_departure(self) -> None:
        # Negative control: the paper's own weighting is 'cell'. A reader
        # comparing chosen[key] to Deviation.paper only by presence in `chosen`
        # would report this as a departure even though nothing moved.
        text = methods_paragraph(
            NAME,
            stages_that_ran=["steady_conductivity"],
            chosen={"weighting": "cell", "diagonal_neighbors": True},
        )

        assert "departs from the published method" not in text

    def test_diagonal_neighbors_false_is_the_one_that_departs(self) -> None:
        text = methods_paragraph(
            NAME,
            stages_that_ran=["steady_conductivity"],
            chosen={"diagonal_neighbors": False},
        )

        assert "departs from the published method" in text
        assert "diagonal_neighbors" in text

    def test_the_touch_rasterisation_departs_and_crossing_does_not(self) -> None:
        touch = methods_paragraph(
            NAME,
            stages_that_ran=["steady_conductivity"],
            chosen={"observed_rasterization": "touch"},
        )
        crossing = methods_paragraph(
            NAME,
            stages_that_ran=["steady_conductivity"],
            chosen={"observed_rasterization": "crossing"},
        )

        assert "observed_rasterization was set to 'touch'" in touch
        assert "departs from the published method" not in crossing

    def test_the_run_reads_the_network_output_and_not_a_gauge(self) -> None:
        # A point output defaults diagonal_neighbors to false, the network one
        # to true: the paragraph must not read the gauge as the criterion.
        from types import SimpleNamespace

        from hydromodpy.calibration.config import (
            MatchingHydrographicNetworkOptions,
            validate_calib_output,
        )
        from hydromodpy.calibration.runners.staged_runner import _methods_paragraph_for

        outputs = {
            "gauge": validate_calib_output(
                {"support": "point", "variable": "discharge", "x": 0.0, "y": 0.0}
            ),
            "net": validate_calib_output(
                {
                    "support": "network",
                    "stream_geometry_path": "map.gpkg",
                    "observed_rasterization": "touch",
                }
            ),
        }
        cfg = SimpleNamespace(
            protocol=MatchingHydrographicNetworkOptions(name=NAME), outputs=outputs
        )

        steady = SimpleNamespace(
            name="steady_conductivity",
            report=SimpleNamespace(best_parameters={"K": 1.0e-5}, best_objective=0.5, extra={}),
        )

        text = _methods_paragraph_for(cfg, [steady], [])

        assert text is not None
        assert "observed_rasterization was set to 'touch'" in text
        assert "diagonal_neighbors" not in text

    def test_a_declared_validity_length_departs_in_metres_and_auto_does_not(self) -> None:
        from types import SimpleNamespace

        from hydromodpy.calibration.config import (
            MatchingHydrographicNetworkOptions,
            validate_calib_output,
        )
        from hydromodpy.calibration.runners.staged_runner import _methods_paragraph_for

        def paragraph(**declared: object) -> str:
            net = validate_calib_output(
                {"support": "network", "stream_geometry_path": "map.gpkg", **declared}
            )
            cfg = SimpleNamespace(
                protocol=MatchingHydrographicNetworkOptions(name=NAME), outputs={"net": net}
            )
            steady = SimpleNamespace(
                name="steady_conductivity",
                report=SimpleNamespace(best_parameters={"K": 1.0e-5}, best_objective=0.5, extra={}),
            )
            text = _methods_paragraph_for(cfg, [steady], [])
            assert text is not None
            return text

        declared = paragraph(validity_length="300 m")

        assert "validity_length was set to '300 m'" in declared
        assert "roptim = Doptim / DEMres <= 2" in declared
        assert "validity_length" not in paragraph()


class TestItReportsTheBackend:
    def test_an_untested_backend_is_stated(self) -> None:
        text = methods_paragraph(
            NAME, stages_that_ran=["steady_conductivity"], backend="modflow_nwt"
        )

        assert "not covered by a test case" in text

    def test_a_tested_backend_needs_no_caveat(self) -> None:
        text = methods_paragraph(NAME, stages_that_ran=["steady_conductivity"], backend="modflow6")

        assert "not covered by a test case" not in text


class TestItReportsTheSteadyWindow:
    def test_the_span_and_day_count_are_named(self) -> None:
        text = methods_paragraph(
            NAME,
            stages_that_ran=["steady_conductivity"],
            steady_window={"start": "1995-01-01", "end": "2020-12-31", "days": 9497},
        )

        assert "1995-01-01 to 2020-12-31" in text
        assert "9497 day(s)" in text

    def test_the_mean_recharge_is_named_when_known(self) -> None:
        text = methods_paragraph(
            NAME,
            stages_that_ran=["steady_conductivity"],
            steady_window={
                "start": "2000-01-01",
                "end": "2002-12-31",
                "days": 1096,
                "mean_recharge_m_s": 1.392e-8,
            },
        )

        assert "mean recharge 1.392e-08 m/s" in text

    def test_nothing_is_said_without_a_steady_window(self) -> None:
        text = methods_paragraph(NAME, stages_that_ran=["steady_conductivity"])

        assert "steady window" not in text


def test_an_unknown_protocol_is_refused_with_the_list() -> None:
    with pytest.raises(ValueError, match="Registered"):
        methods_paragraph("abherve", stages_that_ran=[])


class TestItReportsParameterUncertaintyWidths:
    """A width that WAS attached but is conditional is a different claim from

    no width having been built at all -- ``conditional_widths`` and
    ``absent_widths`` must render as two distinct sentences, never merged into
    one that would read as if every listed stage carried a number.
    """

    def test_a_conditional_width_is_reported_in_its_own_sentence(self) -> None:
        # Negative control: delete the `if conditional_widths:` block in
        # boilerplate.py and this goes red.
        text = methods_paragraph(
            NAME,
            stages_that_ran=["steady_conductivity", "transient_storage"],
            conditional_widths={
                "transient_storage": "conditional on K, frozen by steady_conductivity"
            },
        )

        assert (
            "Reported parameter uncertainty is conditional on the following: "
            "transient_storage: conditional on K, frozen by steady_conductivity."
        ) in text

    def test_an_absent_width_is_reported_in_a_different_sentence(self) -> None:
        # Negative control: delete the `if absent_widths:` block in
        # boilerplate.py and this goes red.
        text = methods_paragraph(
            NAME,
            stages_that_ran=["steady_conductivity"],
            absent_widths={"steady_conductivity": "not attached: this phase was reused"},
        )

        assert (
            "No parameter uncertainty was built for: "
            "steady_conductivity: not attached: this phase was reused."
        ) in text
        assert "is conditional on the following" not in text

    def test_neither_key_appears_when_no_width_note_exists(self) -> None:
        text = methods_paragraph(NAME, stages_that_ran=["steady_conductivity"])

        assert "parameter uncertainty" not in text.lower()

    def test_the_two_families_never_share_one_sentence(self) -> None:
        # Both present at once: still two sentences, not one blended claim,
        # and no double period from a note that already ends with one.
        text = methods_paragraph(
            NAME,
            stages_that_ran=["steady_conductivity", "transient_storage"],
            conditional_widths={"transient_storage": "conditional on K"},
            absent_widths={"steady_conductivity": "not attached: this phase was reused"},
        )

        assert "is conditional on the following" in text
        assert "was built for" in text
        assert ".." not in text


class TestTheStagedReportCarriesIt:
    def test_the_report_holds_the_paragraph(self) -> None:
        from hydromodpy.calibration.runners.staged_runner import StagedCalibrationReport

        report = StagedCalibrationReport(
            phases=(),
            frozen=(),
            root_session_id="abc",
            methods_paragraph="anything",
        )

        assert report.to_dict()["methods_paragraph"] == "anything"

    def test_a_report_without_a_protocol_carries_none(self) -> None:
        from hydromodpy.calibration.runners.staged_runner import StagedCalibrationReport

        summary = StagedCalibrationReport(phases=(), frozen=(), root_session_id="abc").to_dict()

        assert "methods_paragraph" not in summary

    def test_the_steady_window_is_carried_when_known(self) -> None:
        from hydromodpy.calibration.runners.staged_runner import StagedCalibrationReport

        window = {"start": "1995-01-01", "end": "2020-12-31", "days": 9497}
        summary = StagedCalibrationReport(
            phases=(), frozen=(), root_session_id="abc", steady_window=window
        ).to_dict()

        assert summary["steady_window"] == window

    def test_a_report_without_a_steady_phase_carries_none(self) -> None:
        from hydromodpy.calibration.runners.staged_runner import StagedCalibrationReport

        summary = StagedCalibrationReport(phases=(), frozen=(), root_session_id="abc").to_dict()

        assert "steady_window" not in summary

    def test_it_is_built_from_the_stages_that_converged(self) -> None:
        """Not from the stages that were planned: that is the whole property."""
        import inspect

        from hydromodpy.calibration.runners import staged_runner

        source = inspect.getsource(staged_runner._methods_paragraph_for)

        assert "_converged(run.report)" in source
