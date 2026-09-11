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
        assert "version 1.0" in text

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


class TestItReportsTheBackend:
    def test_an_untested_backend_is_stated(self) -> None:
        text = methods_paragraph(
            NAME, stages_that_ran=["steady_conductivity"], backend="modflow_nwt"
        )

        assert "not covered by a test case" in text

    def test_a_tested_backend_needs_no_caveat(self) -> None:
        text = methods_paragraph(NAME, stages_that_ran=["steady_conductivity"], backend="modflow6")

        assert "not covered by a test case" not in text


def test_an_unknown_protocol_is_refused_with_the_list() -> None:
    with pytest.raises(ValueError, match="Registered"):
        methods_paragraph("abherve", stages_that_ran=[])


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

    def test_it_is_built_from_the_stages_that_converged(self) -> None:
        """Not from the stages that were planned: that is the whole property."""
        import inspect

        from hydromodpy.calibration.runners import staged_runner

        source = inspect.getsource(staged_runner._methods_paragraph_for)

        assert "_converged(run.report)" in source
