"""Methods paragraph a calibration run writes about itself, and the options it reports.

The paragraph is generated from the declarations that ran and from the stages that
completed, not the stages that were planned. Windows are dates, widths are in
parameter units, recharge is in m/s, DEM breach limits are in m.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.config_network import MatchingHydrographicNetworkOptions
from hydromodpy.calibration.config_objective import CalibrationProtocolDecl
from hydromodpy.calibration.config_outputs import validate_calib_output
from hydromodpy.calibration.protocols import boilerplate
from hydromodpy.calibration.protocols.boilerplate import methods_paragraph
from hydromodpy.calibration.protocols.registry import (
    deviations_in_force,
    protocol_options_away_from_the_recipe,
)
from hydromodpy.calibration.runners import staged_report
from hydromodpy.calibration.runners.staged_report import geographic_choices, methods_paragraph_for
from hydromodpy.catchment.preprocess.geographic_config import GeographicConfig
from hydromodpy.model.domain.geometry import RasterGeometry
from hydromodpy.model.model import Geometry
from hydromodpy.solver.modflow_nwt.nwt import nwt_solver
from tests._helpers.model_factory import make_model
from tests.unit.calibration._factories_runners import make_report

NAME = "matching_hydrographic_network"
STEADY = ["steady_conductivity"]
BOTH = ["steady_conductivity", "transient_storage"]


def paragraph_for_geographic(document: dict) -> str:
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


# Filling the DEM is the paper's. Breaching it is a departure a file chooses, read
# from the [geographic] section.
GEOGRAPHIC = [
    pytest.param(
        {
            "geographic": {
                "dem_correc_type": "capped_breach",
                "capped_breach": {"max_depth": 0.8, "max_distance": "0.1 km"},
            }
        },
        ["max_depth = 0.8 m", "max_distance = 100 m"],
        [],
        id="capped breach with its limits",
    ),
    pytest.param(
        {"geographic": {"dem_correc_type": "capped_breach"}},
        ["max_depth = 0.5 m, max_distance = 200 m"],
        [],
        id="capped breach with default limits",
    ),
    pytest.param({"geographic": {"dem_correc_type": "fill"}}, [], ["dem_correc_type"], id="fill"),
    pytest.param(
        {"geographic": {"crs_project": "EPSG:2154"}}, [], ["dem_correc_type"], id="key not set"
    ),
    pytest.param({}, [], ["dem_correc_type"], id="no geographic section"),
]


@pytest.mark.parametrize(("document", "present", "absent"), GEOGRAPHIC)
def test_dem_conditioning_in_the_paragraph(document, present, absent) -> None:
    text = paragraph_for_geographic(document)

    assert all(part in text for part in present)
    assert not any(part in text for part in absent)


def test_written_breach_is_reported_by_the_check() -> None:
    calibration = SimpleNamespace(
        outputs={}, protocol=MatchingHydrographicNetworkOptions(name=NAME)
    )
    geographic = GeographicConfig.model_construct(dem_correc_type="breach")
    item = next(
        item
        for item in deviations_in_force(calibration, geographic)
        if item.key == "dem_correc_type"
    )

    assert (item.written, item.value, item.state) == (True, "breach", "departs")


def test_nwt_falls_back_to_the_config_dem_default(monkeypatch, tmp_path) -> None:
    # A geographic object without the key conditions the DEM as the config would.
    model = SimpleNamespace(
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
    seen: dict = {}

    def fake(**kwargs):
        seen.update(kwargs)
        return "routing"

    monkeypatch.setattr(nwt_solver, "build_solver_routing_context", fake)
    nwt_solver.ModflowNwt._ensure_solver_routing_context(model)

    assert seen["dem_correc_type"] == "fill"


def test_swapped_engine_in_the_paragraph() -> None:
    # A protocol keeps its name when its engine is swapped, so the prose must say so.
    declared = CalibrationProtocolDecl.model_validate(
        {"name": NAME, "steady_metric": "distance_mean"}
    )
    prose = methods_paragraph(
        NAME,
        stages_that_ran=BOTH,
        options=protocol_options_away_from_the_recipe(NAME, declared),
    )

    assert "steady_metric = 'distance_mean' instead of 'distance_gap'" in prose


WINDOW = {"start": "1995-01-01", "end": "2020-12-31", "days": 9497}

PARAGRAPHS = [
    pytest.param(
        {
            "stages_that_ran": STEADY,
            "options": [{"key": "storage", "here": False, "recipe": "Sy"}],
        },
        ["left the stage that fits the storage out"],
        ["did not complete"],
        id="stage left out by the file",
    ),
    pytest.param(
        {"stages_that_ran": STEADY, "held": {"Sy": 0.033827}},
        ["did not settle", "Sy = 0.03383"],
        ["keeps the value it entered"],
        id="unsettled stage holds a value",
    ),
    pytest.param(
        {"stages_that_ran": STEADY, "stages_declared": 1},
        ["1 of the 1 stages completed"],
        ["did not complete"],
        id="one stage declared and run",
    ),
    pytest.param(
        {"stages_that_ran": []},
        ["No stage", "no calibrated value is reported"],
        [],
        id="no stage completed",
    ),
    pytest.param(
        {"stages_that_ran": BOTH, "calibrated": {"K": 3.14e-6, "Sy": 0.0587}},
        ["K = 3.14e-06", "Sy = 0.0587"],
        [],
        id="calibrated values",
    ),
    pytest.param(
        {"stages_that_ran": STEADY, "backend": "boussinesq"},
        ["not supported on the boussinesq backend", "The backend says:", "release_flux"],
        [],
        id="unsupported backend",
    ),
    pytest.param(
        {"stages_that_ran": STEADY, "backend": "modflow6"},
        [],
        ["not covered by a test case", "not supported"],
        id="tested backend modflow6",
    ),
    pytest.param(
        {"stages_that_ran": STEADY, "backend": "modflow_nwt"},
        [],
        ["not covered by a test case", "not supported"],
        id="tested backend modflow_nwt",
    ),
    pytest.param(
        {"stages_that_ran": STEADY, "steady_window": WINDOW},
        ["1995-01-01 to 2020-12-31", "9497 day(s)"],
        [],
        id="steady window span and days",
    ),
    pytest.param(
        {
            "stages_that_ran": STEADY,
            "steady_window": {
                "start": "2000-01-01",
                "end": "2002-12-31",
                "days": 1096,
                "mean_recharge_m_s": 1.392e-8,
            },
        },
        ["mean recharge 1.392e-08 m/s"],
        [],
        id="steady window mean recharge",
    ),
    # A conditional width and an absent width are two sentences, never one blended claim.
    pytest.param(
        {
            "stages_that_ran": BOTH,
            "conditional_widths": {
                "transient_storage": "conditional on K, frozen by steady_conductivity"
            },
        },
        [
            "Reported parameter uncertainty is conditional on the following: "
            "transient_storage: conditional on K, frozen by steady_conductivity."
        ],
        [],
        id="conditional width",
    ),
    pytest.param(
        {
            "stages_that_ran": STEADY,
            "absent_widths": {"steady_conductivity": "not attached: this phase was reused"},
        },
        [
            "No parameter uncertainty was built for: "
            "steady_conductivity: not attached: this phase was reused."
        ],
        ["is conditional on the following"],
        id="absent width",
    ),
    pytest.param(
        {
            "stages_that_ran": BOTH,
            "conditional_widths": {"transient_storage": "conditional on K"},
            "absent_widths": {"steady_conductivity": "not attached: this phase was reused"},
        },
        ["is conditional on the following", "was built for"],
        [".."],
        id="both kinds of width",
    ),
]


@pytest.mark.parametrize(("kwargs", "present", "absent"), PARAGRAPHS)
def test_methods_paragraph(kwargs, present, absent) -> None:
    text = methods_paragraph(NAME, **kwargs)

    assert all(part in text for part in present)
    assert not any(part in text for part in absent)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        pytest.param("methods_paragraph", "anything", id="paragraph"),
        pytest.param("steady_window", WINDOW, id="steady window"),
    ],
)
def test_report_holds_what_is_known(key, value) -> None:
    assert make_report(n_trials=0, best_cost=None, **{key: value}).to_dict()[key] == value


def test_paragraph_is_built_from_settled_stages() -> None:
    source = inspect.getsource(staged_report.methods_paragraph_for)

    assert "_settled(run.report)" in source


def test_paragraph_names_what_its_protocol_declares(monkeypatch) -> None:
    class Quiet(type(boilerplate.get_protocol(NAME))):
        name = "quiet_probe"
        deviations = ()
        declared_observables = ("release_flux",)

    monkeypatch.setattr(boilerplate, "get_protocol", lambda _name: Quiet())

    text = methods_paragraph(
        NAME,
        stages_that_ran=STEADY,
        steady_window={"start": "2000-01-01", "end": "2000-12-31"},
        backend="modflow6",
    )

    assert "over its steady window, 2000-01-01 to 2000-12-31." in text
    assert "every run" not in text
    assert "on the modflow6 backend, on which it is expected to work but is not covered" in text


def test_refusals() -> None:
    with pytest.raises(ValueError, match="Registered"):
        methods_paragraph("abherve", stages_that_ran=[])
