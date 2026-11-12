"""Tests of `protocols.boilerplate`."""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.config_network import (
    CalibNetworkModel,
    MatchingHydrographicNetworkOptions,
)
from hydromodpy.calibration.config_objective import CalibrationProtocolDecl
from hydromodpy.calibration.config_outputs import validate_calib_output
from hydromodpy.calibration.protocols import boilerplate
from hydromodpy.calibration.protocols.boilerplate import methods_paragraph
from hydromodpy.calibration.protocols.registry import (
    deviations_in_force,
    protocol_options_away_from_the_recipe,
    protocol_record,
)
from hydromodpy.calibration.runners import staged_report
from hydromodpy.calibration.runners.staged_report import geographic_choices, methods_paragraph_for
from hydromodpy.catchment.preprocess.geographic_config import GeographicConfig
from hydromodpy.model.domain.geometry import RasterGeometry
from hydromodpy.model.model import Geometry
from hydromodpy.solver.modflow_nwt.nwt import nwt_solver
from tests._helpers.model_factory import make_model
from tests.unit.calibration._factories_runners import make_report

# From test_the_dem_conditioning_is_an_offered_departure.py
# Filling the DEM is the paper's; breaching it is a departure a file chooses.
#
# The protocol declares the key with the paper's value, so the Methods
# paragraph names it only when a file moves it off that value. The key lives
# under [geographic], so the run and ``hmp check`` read it there,
# and only when the file wrote it. The solvers fall back on the same default.


NAME = "matching_hydrographic_network"
STAGES = ["steady_conductivity"]


def _entry() -> dict:
    deviations = {item["key"]: item for item in protocol_record(NAME)["deviations"]}
    return deviations["dem_correc_type"]


def _paragraph(document: dict) -> str:

    net = validate_calib_output({"support": "network", "map": {"complete": "map.gpkg"}})
    cfg = SimpleNamespace(
        protocol=MatchingHydrographicNetworkOptions(name=NAME), outputs={"net": net}
    )
    steady = SimpleNamespace(
        name="steady_conductivity",
        report=SimpleNamespace(best_parameters={"K": 1.0e-5}, best_cost=0.5, extra={}),
    )
    text = methods_paragraph_for(cfg, [steady], [], geographic=geographic_choices(document))
    assert text is not None
    return text


class TestTheRunReadsTheGeographicSection:
    """The key lives under [geographic], which the paragraph used never to read."""

    def test_a_capped_breach_names_its_limits_so_the_run_can_be_reproduced(self) -> None:
        declared = _paragraph(
            {
                "geographic": {
                    "dem_correc_type": "capped_breach",
                    "capped_breach": {"max_depth": 0.8, "max_distance": "0.1 km"},
                }
            }
        )
        defaulted = _paragraph({"geographic": {"dem_correc_type": "capped_breach"}})

        assert "max_depth = 0.8 m" in declared
        assert "max_distance = 100 m" in declared
        assert "max_depth = 0.5 m, max_distance = 200 m" in defaulted

    def test_a_file_that_writes_fill_does_not_depart(self) -> None:
        text = _paragraph({"geographic": {"dem_correc_type": "fill"}})

        assert "dem_correc_type" not in text

    def test_an_unset_key_stays_silent(self) -> None:
        assert "dem_correc_type" not in _paragraph({"geographic": {"crs_project": "EPSG:2154"}})
        assert "dem_correc_type" not in _paragraph({})


class TestTheCheckReadsWhatTheFileWrote:
    def _item(self, geographic):

        calibration = SimpleNamespace(
            outputs={},
            protocol=MatchingHydrographicNetworkOptions(name="matching_hydrographic_network"),
        )
        return next(
            item
            for item in deviations_in_force(calibration, geographic)
            if item.key == "dem_correc_type"
        )

    def test_a_written_breach_is_reported(self) -> None:
        item = self._item(GeographicConfig.model_construct(dem_correc_type="breach"))

        assert (item.written, item.value, item.state) == (True, "breach", "departs")


class TestTheSolverFallbackFollowsTheConfig:
    """A geographic object without the key conditions the DEM as the config would."""

    def _captured(self, monkeypatch, module, call) -> dict:
        seen: dict = {}

        def fake(**kwargs):
            seen.update(kwargs)
            return "routing"

        monkeypatch.setattr(module, "build_solver_routing_context", fake)
        call()
        return seen

    def _model(self, tmp_path):
        return SimpleNamespace(
            routing_ctx=None,
            grid_ctx=object(),
            dem_watershed_path=str(tmp_path / "dem.tif"),
            full_path=str(tmp_path),
            inputs=make_model(
                geometry=Geometry(
                    cells=None,
                    domain=None,
                    raster=RasterGeometry.from_geographic(SimpleNamespace()),
                )
            ),
        )

    def test_nwt_falls_back_to_the_config_default(self, monkeypatch, tmp_path) -> None:
        model = self._model(tmp_path)
        seen = self._captured(
            monkeypatch,
            nwt_solver,
            lambda: nwt_solver.ModflowNwt._ensure_solver_routing_context(model),
        )

        assert seen["dem_correc_type"] == "fill"


# From test_the_protocol_records_what_moved.py
# An option moved off the recipe has to show up where the number is read.
#
# A protocol keeps its name when its engine is swapped, which is the point of
# having options at all. What must not happen is a run reporting a published
# method while running a different estimator, with nothing saying so. The check
# output, the persisted record and the Methods prose are the three places a reader
# looks, so all three are gated here.


def _declared(**options: object) -> CalibrationProtocolDecl:
    return CalibrationProtocolDecl.model_validate({"name": NAME, **options})


def test_the_methods_prose_says_the_engine_was_swapped() -> None:
    declared = _declared(steady_metric="distance_mean")
    prose = methods_paragraph(
        NAME,
        stages_that_ran=["steady_conductivity", "transient_storage"],
        options=protocol_options_away_from_the_recipe(NAME, declared),
    )
    assert "steady_metric = 'distance_mean' instead of 'distance_gap'" in prose


def _model(neighbours: str) -> CalibNetworkModel:
    return CalibNetworkModel.model_construct(_fields_set={"neighbours"}, neighbours=neighbours)


def _diagonal_item(*outputs_named: tuple[str, object]):
    calibration = SimpleNamespace(outputs=dict(outputs_named), protocol=_declared())
    return next(item for item in deviations_in_force(calibration) if item.key == "model.neighbours")


# From test_the_run_writes_its_own_methods.py
# The run emits the prose describing what it did, with citations.
#
# Borrowed from fMRIPrep, where it is the highest-yield reproducibility feature the
# project has. Two properties earn it: it cannot drift from what ran, because it is
# generated from the same declarations that ran, and it is conditioned on the
# stages that COMPLETED rather than on the ones that were planned.
#
# That second property is the whole point. A two-stage method whose transient stage
# died would otherwise be written up as a two-stage calibration, and the specific
# yield it never touched would be reported as calibrated.


class TestWhatItAlwaysSays:
    def test_a_stage_the_file_left_out_did_not_fail(self) -> None:
        text = methods_paragraph(
            NAME,
            stages_that_ran=["steady_conductivity"],
            options=[{"key": "storage", "here": False, "recipe": "Sy"}],
        )

        assert "left the stage that fits the storage out" in text
        assert "did not complete" not in text


class TestItDescribesWhatRan:
    def test_an_unsettled_stage_says_the_value_the_run_holds(self) -> None:
        text = methods_paragraph(
            NAME, stages_that_ran=["steady_conductivity"], held={"Sy": 0.033827}
        )

        assert "did not settle" in text
        assert "Sy = 0.03383" in text
        assert "keeps the value it entered" not in text

    def test_a_file_declaring_one_stage_does_not_miss_a_second(self) -> None:
        text = methods_paragraph(NAME, stages_that_ran=["steady_conductivity"], stages_declared=1)

        assert "1 of the 1 stages completed" in text
        assert "did not complete" not in text

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


class TestItReportsTheBackend:
    def test_an_unsupported_backend_is_stated(self) -> None:
        text = methods_paragraph(
            NAME, stages_that_ran=["steady_conductivity"], backend="boussinesq"
        )

        assert "not supported on the boussinesq backend" in text
        # The refusal is the backend's own answer, so the sentence says what the
        # backend declares rather than a verdict read from a table.
        assert "The backend says:" in text
        assert "release_flux" in text

    @pytest.mark.parametrize("backend", ["modflow6", "modflow_nwt"])
    def test_a_tested_backend_needs_no_caveat(self, backend: str) -> None:
        text = methods_paragraph(NAME, stages_that_ran=["steady_conductivity"], backend=backend)

        assert "not covered by a test case" not in text
        assert "not supported" not in text


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


class TestTheReportCarriesIt:
    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("methods_paragraph", "anything"),
            ("steady_window", {"start": "1995-01-01", "end": "2020-12-31", "days": 9497}),
        ],
    )
    def test_the_report_holds_what_is_known(self, key, value) -> None:
        assert make_report(n_trials=0, best_cost=None, **{key: value}).to_dict()[key] == value

    def test_it_is_built_from_the_stages_that_settled(self) -> None:
        """Not from the stages that were planned: that is the whole property."""

        source = inspect.getsource(staged_report.methods_paragraph_for)

        assert "_settled(run.report)" in source


def test_the_paragraph_names_what_the_protocol_it_reads_declares(monkeypatch) -> None:
    class Quiet(type(boilerplate.get_protocol(NAME))):
        name = "quiet_probe"
        deviations = ()
        declared_observables = ("release_flux",)

    monkeypatch.setattr(boilerplate, "get_protocol", lambda _name: Quiet())

    text = methods_paragraph(
        NAME,
        stages_that_ran=["steady_conductivity"],
        steady_window={"start": "2000-01-01", "end": "2000-12-31"},
        backend="modflow6",
    )

    assert "over its steady window, 2000-01-01 to 2000-12-31." in text
    assert "every run" not in text
    assert "on the modflow6 backend, on which it is expected to work but is not covered" in text
