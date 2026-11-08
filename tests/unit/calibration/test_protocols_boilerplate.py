"""Tests of `protocols.boilerplate`."""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.config import (
    CalibNetworkModel,
    CalibOutputNetwork,
    CalibOutputPoint,
    CalibrationProtocolDecl,
    MatchingHydrographicNetworkOptions,
    validate_calib_output,
)
from hydromodpy.calibration.protocols import (
    boilerplate,
    deviations_in_force,
    protocol_options_away_from_the_recipe,
    protocol_record,
)
from hydromodpy.calibration.protocols.boilerplate import methods_paragraph
from hydromodpy.calibration.runners import staged_runner
from hydromodpy.calibration.runners.staged_runner import _geographic_choices, _methods_paragraph_for
from hydromodpy.catchment.preprocess.geographic_config import GeographicConfig
from hydromodpy.model.domain.geometry import RasterGeometry
from hydromodpy.model.model import Geometry
from hydromodpy.solver.modflow6 import build
from hydromodpy.solver.modflow_nwt.nwt import nwt_solver
from tests._helpers.model_factory import make_model
from tests.unit.calibration._factories_runners import make_report

# From test_the_dem_conditioning_is_an_offered_departure.py
# Filling the DEM is the paper's; breaching it is a departure a file chooses.
#
# The protocol declares the key with the paper's value, so the Methods
# paragraph names it only when a file moves it off that value. The key lives
# under [geographic], so the run and ``hmp config check`` read it there,
# and only when the file wrote it. The solvers fall back on the same default.


NAME = "matching_hydrographic_network"
STAGES = ["steady_conductivity"]


def _entry() -> dict:
    deviations = {item["key"]: item for item in protocol_record(NAME)["deviations"]}
    return deviations["dem_correc_type"]


def test_the_entry_pins_the_paper_s_fill() -> None:
    entry = _entry()
    assert entry["paper_value"] == "fill"
    assert "FillDepressions" in entry["paper"]
    assert "'fill' by default" in entry["here"]
    assert "'breach' is offered and departs" in entry["here"]


def test_breach_is_named_in_the_methods_paragraph() -> None:
    prose = methods_paragraph(NAME, stages_that_ran=STAGES, chosen={"dem_correc_type": "breach"})
    assert "dem_correc_type was set to 'breach'" in prose


def test_the_capped_breach_is_an_offered_departure_that_names_its_limits() -> None:
    entry = _entry()
    assert "'capped_breach'" in entry["here"]
    assert "[geographic.capped_breach]" in entry["here"]
    prose = methods_paragraph(
        NAME, stages_that_ran=STAGES, chosen={"dem_correc_type": "capped_breach"}
    )
    assert "dem_correc_type was set to 'capped_breach'" in prose


def test_fill_is_not_read_as_a_departure() -> None:
    prose = methods_paragraph(NAME, stages_that_ran=STAGES, chosen={"dem_correc_type": "fill"})
    assert "departs from the published method" not in prose


def _paragraph(document: dict) -> str:

    net = validate_calib_output({"support": "network", "map": {"complete": "map.gpkg"}})
    cfg = SimpleNamespace(
        protocol=MatchingHydrographicNetworkOptions(name=NAME), outputs={"net": net}
    )
    steady = SimpleNamespace(
        name="steady_conductivity",
        report=SimpleNamespace(best_parameters={"K": 1.0e-5}, best_cost=0.5, extra={}),
    )
    text = _methods_paragraph_for(cfg, [steady], [], geographic=_geographic_choices(document))
    assert text is not None
    return text


class TestTheRunReadsTheGeographicSection:
    """The key lives under [geographic], which the paragraph used never to read."""

    def test_a_file_that_breaches_is_named_in_its_methods(self) -> None:
        text = _paragraph({"geographic": {"dem_correc_type": "breach"}})

        assert "dem_correc_type was set to 'breach'" in text
        assert "FillDepressions" in text

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

    def test_the_default_left_unwritten_is_not_reported(self) -> None:
        item = self._item(GeographicConfig.model_construct(crs_project="EPSG:2154"))

        assert (item.written, item.value, item.state) == (False, "fill", "as_paper")


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

    def test_modflow6_falls_back_to_the_config_default(self, monkeypatch, tmp_path) -> None:
        model = self._model(tmp_path)
        seen = self._captured(
            monkeypatch, build, lambda: build.ensure_solver_routing_context(model)
        )

        assert seen["dem_correc_type"] == "fill"

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


def test_a_transient_metric_the_registry_does_not_know_is_refused() -> None:
    with pytest.raises(ValueError, match="transient_metric"):
        _declared(transient_metric="bogus")


def test_naming_the_protocol_alone_moves_nothing() -> None:
    assert protocol_options_away_from_the_recipe(NAME, _declared()) == ()


def test_restating_a_recipe_value_is_not_a_departure() -> None:
    # The reference file writes the published values out so it can be read beside
    # the script it replicates. Writing them must not read as changing them.
    declared = _declared(transient_metric="nse_log", transient_method="scipy_nelder_mead")
    assert protocol_options_away_from_the_recipe(NAME, declared) == ()


def test_a_swapped_estimator_and_engine_are_both_reported() -> None:
    declared = _declared(steady_metric="distance_mean", steady_method="scipy_nelder_mead")
    moved = {
        item["key"]: (item["here"], item["recipe"])
        for item in protocol_options_away_from_the_recipe(NAME, declared)
    }
    assert moved == {
        "steady_metric": ("distance_mean", "distance_gap"),
        "steady_method": ("scipy_nelder_mead", "bisection"),
    }


def test_the_pinned_version_is_not_an_option_that_moved() -> None:
    # A pin is a replayability guarantee, not a departure from the method.
    assert protocol_options_away_from_the_recipe(NAME, _declared(version="1.2")) == ()


def test_the_record_carries_the_departures_only_when_a_file_is_given() -> None:
    assert "options_away_from_the_recipe" not in protocol_record(NAME)
    record = protocol_record(NAME, _declared(steady_method="scipy_nelder_mead"))
    assert record["options_away_from_the_recipe"] == [
        {"key": "steady_method", "here": "scipy_nelder_mead", "recipe": "bisection"}
    ]


def test_the_methods_prose_says_the_engine_was_swapped() -> None:
    declared = _declared(steady_metric="distance_mean")
    prose = methods_paragraph(
        NAME,
        stages_that_ran=["steady_conductivity", "transient_storage"],
        options=protocol_options_away_from_the_recipe(NAME, declared),
    )
    assert "steady_metric = 'distance_mean' instead of 'distance_gap'" in prose


def test_the_prose_stays_silent_when_nothing_moved() -> None:
    prose = methods_paragraph(NAME, stages_that_ran=["steady_conductivity"])
    assert "moved off the recipe" not in prose


def test_the_descent_rule_is_declared_as_an_offered_departure() -> None:
    """The paper's own tool traces D8, and so does HydroModPy by default.

    D4 stays offered, and choosing it departs from the publication the protocol
    cites, so the entry names both and pins the paper's value: the Methods
    paragraph reports the key only when a file moved it off that value.
    """
    record = protocol_record(NAME)
    deviations = {item["key"]: item for item in record["deviations"]}
    assert "D8" in deviations["model.neighbours"]["paper"]
    assert "'D8' by default" in deviations["model.neighbours"]["here"]
    assert "'D4'" in deviations["model.neighbours"]["here"]
    assert deviations["model.neighbours"]["paper_value"] == "D8"
    # The why carries both measurements, so a reader does not have to find them.
    why = deviations["model.neighbours"]["why"]
    assert "6.6 per cent" in why
    assert "64.631" in why


def test_the_rasterisation_deviation_names_heads_as_the_new_default() -> None:
    """The criterion's own default is 'heads', not 'crossing'.

    The Deviation entry has to agree with that default: 'heads' traces the
    model's own descent from the map's free ends and departs from the paper,
    'crossing' is WhiteboxTools' own rule and reproduces the paper, 'touch' is
    kept to replay an old session.
    """
    record = protocol_record(NAME)
    deviations = {item["key"]: item for item in record["deviations"]}
    entry = deviations["map.drawn_by"]
    assert "'heads' from version 1.3" in entry["here"]
    assert "it departs from the paper" in entry["here"]
    assert "'crossing' is offered and matches the paper" in entry["here"]
    assert "'touch'" in entry["here"]
    assert entry["paper_value"] == "crossing"


def _model(neighbours: str) -> CalibNetworkModel:
    return CalibNetworkModel.model_construct(_fields_set={"neighbours"}, neighbours=neighbours)


def _diagonal_item(*outputs_named: tuple[str, object]):
    calibration = SimpleNamespace(outputs=dict(outputs_named), protocol=_declared())
    return next(item for item in deviations_in_force(calibration) if item.key == "model.neighbours")


def test_the_value_a_file_actually_set_is_reported_even_when_it_is_false() -> None:
    # A boolean default is the case a "skip what is None" reader gets wrong, and it
    # is the one that matters here: false IS the departure.
    item = _diagonal_item(
        ("net", CalibOutputNetwork.model_construct(support="network", model=_model("D4")))
    )

    assert item.written is True
    assert item.value == "D4"
    assert item.state == "departs"


def test_a_gauge_s_own_neighbours_are_not_read_as_the_network_s() -> None:
    # Only the network output carries the criterion's model.neighbours: a
    # value found on a gauge would report a departure the criterion never made.
    item = _diagonal_item(
        ("gauge", CalibOutputPoint.model_construct(support="point", model=_model("D4"))),
        ("net", CalibOutputNetwork.model_construct(support="network", model=_model("D8"))),
    )

    assert item.value == "D8"
    assert item.state == "as_paper"


def test_a_default_the_file_left_unwritten_is_not_claimed_by_it() -> None:
    # "this file sets True" for a value the file never wrote sent the reader
    # looking for a line that is not there.
    item = _diagonal_item(("net", CalibOutputNetwork.model_construct(support="network")))

    assert item.written is False
    assert item.value == "D8"


def test_a_value_the_version_writes_is_not_claimed_by_the_file() -> None:
    # The expansion writes the values of the version into the output, so a value
    # that is merely the version's is set on the model and chosen by nobody.
    item = _diagonal_item(
        ("net", CalibOutputNetwork.model_construct(support="network", model=_model("D8")))
    )

    assert item.written is False


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
    def test_it_names_the_protocol_and_its_version(self) -> None:
        text = methods_paragraph(NAME, stages_that_ran=["steady_conductivity"])

        assert NAME in text
        assert "version 1.3" in text

    def test_a_stage_the_file_left_out_did_not_fail(self) -> None:
        text = methods_paragraph(
            NAME,
            stages_that_ran=["steady_conductivity"],
            options=[{"key": "storage", "here": False, "recipe": "Sy"}],
        )

        assert "left the stage that fits the storage out" in text
        assert "did not complete" not in text

    def test_a_pinned_file_says_its_pin(self) -> None:
        text = methods_paragraph(NAME, stages_that_ran=["steady_conductivity"], version="1.2")

        assert "version 1.2" in text

    def test_it_says_where_it_departs_in_every_run(self) -> None:
        text = methods_paragraph(NAME, stages_that_ran=["steady_conductivity"])

        assert "departs from it in every run" in text
        for key in ("d_os_support", "outlet_sealed_into_d_so_target"):
            assert key in text

    def test_a_departure_that_depends_on_the_file_is_told_only_when_it_holds(self) -> None:
        held = methods_paragraph(
            NAME,
            stages_that_ran=["steady_conductivity"],
            conditional_in_force=["steady_recharge_window"],
        )
        silent = methods_paragraph(NAME, stages_that_ran=["steady_conductivity"])

        assert "steady_recharge_window" in held
        assert "steady_recharge_window" not in silent

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


class TestItReportsTheDepartures:
    def test_a_departure_from_the_paper_is_named_with_both_values(self) -> None:
        text = methods_paragraph(
            NAME,
            stages_that_ran=["steady_conductivity"],
            chosen={"model.weighting": "area"},
        )

        assert "departs from the published method" in text
        assert "model.weighting" in text
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
            chosen={"model.weighting": "cell", "model.neighbours": "D8"},
        )

        assert "departs from the published method" not in text

    def test_a_d4_descent_is_the_one_that_departs(self) -> None:
        text = methods_paragraph(
            NAME,
            stages_that_ran=["steady_conductivity"],
            chosen={"model.neighbours": "D4"},
        )

        assert "departs from the published method" in text
        assert "model.neighbours" in text

    def test_the_touch_rasterisation_departs_and_crossing_does_not(self) -> None:
        touch = methods_paragraph(
            NAME,
            stages_that_ran=["steady_conductivity"],
            chosen={"map.drawn_by": "touch"},
        )
        crossing = methods_paragraph(
            NAME,
            stages_that_ran=["steady_conductivity"],
            chosen={"map.drawn_by": "crossing"},
        )

        assert "map.drawn_by was set to 'touch'" in touch
        assert "departs from the published method" not in crossing

    def test_the_run_reads_the_network_output_and_not_a_gauge(self) -> None:
        # Only the network output carries the criterion: the paragraph must
        # not read the gauge as the criterion.

        outputs = {
            "gauge": validate_calib_output(
                {"support": "point", "variable": "discharge", "x": 0.0, "y": 0.0}
            ),
            "net": validate_calib_output(
                {
                    "support": "network",
                    "map": {"complete": "map.gpkg", "drawn_by": "touch"},
                }
            ),
        }
        cfg = SimpleNamespace(
            protocol=MatchingHydrographicNetworkOptions(name=NAME), outputs=outputs
        )

        steady = SimpleNamespace(
            name="steady_conductivity",
            report=SimpleNamespace(best_parameters={"K": 1.0e-5}, best_cost=0.5, extra={}),
        )

        text = _methods_paragraph_for(cfg, [steady], [])

        assert text is not None
        assert "map.drawn_by was set to 'touch'" in text
        assert "model.neighbours" not in text

    def test_a_declared_validity_length_departs_in_metres_and_auto_does_not(self) -> None:

        def paragraph(**declared: object) -> str:
            net = validate_calib_output(
                {"support": "network", "map": {"complete": "map.gpkg"}, **declared}
            )
            cfg = SimpleNamespace(
                protocol=MatchingHydrographicNetworkOptions(name=NAME), outputs={"net": net}
            )
            steady = SimpleNamespace(
                name="steady_conductivity",
                report=SimpleNamespace(best_parameters={"K": 1.0e-5}, best_cost=0.5, extra={}),
            )
            text = _methods_paragraph_for(cfg, [steady], [])
            assert text is not None
            return text

        declared = paragraph(verdict={"validity_length": "300 m"})

        assert "verdict.validity_length was set to '300 m'" in declared
        assert "r_optim = D_optim / DEMres <= 2" in declared
        assert "validity_length" not in paragraph()


class TestItReportsTheBackend:
    def test_an_unsupported_backend_is_stated(self) -> None:
        text = methods_paragraph(
            NAME, stages_that_ran=["steady_conductivity"], backend="boussinesq"
        )

        assert "not supported on the boussinesq backend" in text

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

    def test_a_report_without_a_paragraph_or_a_steady_phase_carries_none(self) -> None:
        summary = make_report(n_trials=0, best_cost=None).to_dict()

        assert "methods_paragraph" not in summary
        assert "steady_window" not in summary

    def test_it_is_built_from_the_stages_that_settled(self) -> None:
        """Not from the stages that were planned: that is the whole property."""

        source = inspect.getsource(staged_runner._methods_paragraph_for)

        assert "_settled(run.report)" in source


def test_the_paragraph_names_what_the_protocol_it_reads_declares(monkeypatch) -> None:
    class Quiet(type(boilerplate.get_protocol(NAME))):
        deviations = ()
        support = {"modflow6": "expected_untested"}

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
