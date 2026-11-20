"""Each code a check can give has a document that gives it, at the path it names.

``CHECK_CODES`` is the closed set, the keys of ``[check]`` in ``schema/phrases.toml``.
A code that a document of ``check`` gives has its row in ``CHECK_ROWS``. A code that
only a file, a sites project, a calibration or an input header gives has its own test.
Each Pydantic error type of ``PYDANTIC_CODES`` has a row that says the code it
becomes. A test of each table says that no code is left without a row.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
import rasterio
from affine import Affine

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.preflight import _check_the_budgets
from hydromodpy.config.check import CHECK_CODES, check, phrase
from hydromodpy.config.input_headers import read_input_headers
from hydromodpy.config.section_loader import PYDANTIC_CODES, code_of
from hydromodpy.data.variables.dem.config import FileDemSource
from hydromodpy.project.api import check as check_source
from hydromodpy.schema.phrases import LANGS
from tests.unit.project.launch.test_plan import write_sites_project

SYNTHETIC = {"source_mode": "synthetic"}
LAKE = {"bedleak": 1e-6, "initial_stage": 10.0}
K_FIELD = {"kind": "homogeneous", "value": 1e-5}
K_PARAMETER = {"param_list": ["K"], "param": {"K": {"field": K_FIELD}}}
PROFILE = {"kind": "exponential", "characteristic_depth": "15 m"}
SOIL = {
    "simulation": {
        "time": {
            "start_datetime": "2015-01-01",
            "end_datetime": "2016-12-31",
            "step_value": "1 day",
        }
    },
    "data": {
        "types": ["precipitation", "etp"],
        "precipitation": {"sources": [{"source": "sim2", "extent": "watershed"}]},
        "etp": {"sources": [{"source": "sim2", "extent": "watershed"}]},
    },
}


def _with(path: str, value: Any, **sections: Any) -> dict[str, Any]:
    """Return a synthetic document that writes *value* at the dotted *path*."""
    document: dict[str, Any] = {"geographic": dict(SYNTHETIC), **sections}
    *heads, leaf = path.split(".")
    node = document
    for head in heads:
        node = node.setdefault(head, {})
    node[leaf] = value
    return document


def _soil_document(**flow: Any) -> dict[str, Any]:
    return {
        **SOIL,
        "geographic": dict(SYNTHETIC),
        "solver": {"backend": "modflow6"},
        "flow": {"first_period_steady": False, **flow},
    }


# One row per code of a document: the document, the path, the code and the severity it gets.
CHECK_ROWS = [
    pytest.param({}, "geographic", "to_fill", "to_fill", id="to_fill"),
    pytest.param(
        _with("simulation.time", {"end_datetime": "2001-01-01", "step_value": "1 day"}),
        "simulation.time",
        "refused_value",
        "error",
        id="refused_value",
    ),
    pytest.param(_with("domain.foo", 1), "domain.foo", "unknown_key", "error", id="unknown_key"),
    pytest.param(
        {"geographic": SYNTHETIC, "modflow": {}},
        "modflow",
        "retired_section",
        "error",
        id="retired_section",
    ),
    pytest.param(
        _with("solver.drain_bed_thickness_m", -1.0),
        "solver.drain_bed_thickness_m",
        "out_of_range",
        "error",
        id="out_of_range",
    ),
    pytest.param(
        _with("solver.modflow6.runtime.mf6_ims_complexity", "x"),
        "solver.modflow6.runtime.mf6_ims_complexity",
        "not_a_choice",
        "error",
        id="not_a_choice",
    ),
    pytest.param(
        _with("domain.supports.aquifer", 1.0),
        "domain.supports.aquifer",
        "wrong_type",
        "error",
        id="wrong_type",
    ),
    pytest.param(
        _with("solver.backend", "nope"),
        "solver.backend",
        "unknown_name",
        "error",
        id="unknown_name",
    ),
    pytest.param(
        {
            "geographic": SYNTHETIC,
            "solver": {"backend": "modflow_nwt"},
            "flow": {"sinks_sources": {"lakes": {"lac": LAKE}}},
        },
        "",
        "incompatible",
        "error",
        id="incompatible",
    ),
    pytest.param(
        {
            "geographic": SYNTHETIC,
            "solver": {"backend": "modflow6"},
            "flow": {"restart_from": "prior.hds", "ic": {"kind": "spinup_cyclic"}},
        },
        "",
        "contamination",
        "error",
        id="contamination",
    ),
    pytest.param(
        {"geographic": SYNTHETIC, "modflow6": {"runtime": {"mf6_ims_complexity": "SIMPLE"}}},
        "modflow6",
        "old_key",
        "warning",
        id="old_key",
    ),
    pytest.param(
        _with("calibration.forward_model", "linear_reservoir", flow=K_PARAMETER),
        "calibration.forward_model",
        "retired_key",
        "error",
        id="retired_key",
    ),
    pytest.param(
        _soil_document(
            sinks_sources={"recharge": {"enabled": False, "soil": {"ru": "150 mm"}}},
        ),
        "",
        "cross_rule",
        "error",
        id="cross_rule",
    ),
    pytest.param(
        {
            "geographic": SYNTHETIC,
            "solver": {"backend": "modflow6"},
            "domain": {"layers": {"nlay": 2}},
            "flow": {
                "param_list": ["K"],
                "param": {"K": {"field": K_FIELD, "field_vertical_profile": PROFILE}},
            },
        },
        "",
        "cross_warning",
        "warning",
        id="cross_warning",
    ),
    pytest.param(
        {
            "geographic": SYNTHETIC,
            "domain": {"layers": {"genmtd_lay": "list", "lay_proportions": [0.5, 0.5], "nlay": 5}},
        },
        "",
        "section_warning",
        "warning",
        id="section_warning",
    ),
    pytest.param(
        _soil_document(sinks_sources={"recharge": {"soil": {"ru": "150 mm", "spinup": "none"}}}),
        "flow.sinks_sources.recharge.soil.spinup",
        "experimental_key",
        "warning",
        id="experimental_key",
    ),
]


@pytest.mark.parametrize(("document", "path", "code", "severity"), CHECK_ROWS)
def test_a_document_gets_its_code_at_the_path_it_names(
    tmp_path: Path, document: dict[str, Any], path: str, code: str, severity: str
) -> None:
    found = check(document, base=tmp_path)

    assert (path, code, severity) in [(item.path, item.code, item.severity) for item in found]


# The codes that a file, a project, a calibration or the headers of the inputs give.


@pytest.mark.parametrize(
    ("text", "code"),
    [("not = [valid", "bad_toml"), ('base_config = "missing.toml"\n', "bad_chain")],
    ids=["bad_toml", "bad_chain"],
)
def test_a_file_that_cannot_be_read_is_one_diagnostic(tmp_path: Path, text: str, code: str) -> None:
    path = tmp_path / "run.toml"
    path.write_text(text, encoding="utf-8")

    [found] = check_source(path)

    assert (found.path, found.code, found.severity) == ("", code, "error")


def test_sites_case(tmp_path: Path) -> None:
    project = write_sites_project(tmp_path, k_cells=("5e-5", "not_a_number"))

    [found] = check_source(project / "project.toml")

    assert (found.path, found.code, found.severity) == (
        "flow.param.K.field.value",
        "sites_case",
        "error",
    )
    assert "sites.csv:3 column k -> flow.param.K.field.value" in found.detail


def test_calibration_preflight() -> None:
    config = CalibrationConfig.model_validate(
        {
            "method": "grid",
            "max_trials": 4,
            "method_options": {"points_per_dim": 3},
            "parameters": {
                "K": {"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"},
                "Sy": {"bounds": [0.01, 0.3], "path": "flow.param.Sy.field.value"},
            },
        }
    )

    [found] = _check_the_budgets(config)

    assert (found.code, found.severity) == ("calibration_preflight", "error")
    assert "max_trials = 4 is below the 9 evaluations" in found.detail


def test_input_unreachable(tmp_path: Path) -> None:
    sections = _sections_with_a_dem(FileDemSource(path=tmp_path / "gone.tif"))

    [found] = read_input_headers(sections, base=tmp_path)

    assert (found.path, found.code, found.severity) == (
        "data.dem.sources[0].path",
        "input_unreachable",
        "error",
    )
    assert "does not exist" in found.detail


def test_input_header(tmp_path: Path) -> None:
    path = tmp_path / "dem.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="float32",
        transform=Affine(25.0, 0.0, 1000.0, 0.0, -25.0, 5000.0),
    ) as target:
        target.write(np.ones((4, 4), dtype="float32"), 1)

    found = read_input_headers(_sections_with_a_dem(FileDemSource(path=path)), base=tmp_path)

    errors = [item for item in found if item.code == "input_header" and item.severity == "error"]
    assert [item.path for item in errors] == ["data.dem.sources[0].path"]
    assert "no CRS" in errors[0].detail


def _sections_with_a_dem(source: FileDemSource) -> Any:
    return SimpleNamespace(
        data=SimpleNamespace(dem=SimpleNamespace(sources=[source])),
        geographic=SimpleNamespace(crs_project="EPSG:2154", catchment=None),
    )


FROM_A_DOCUMENT = {row.values[2] for row in CHECK_ROWS}
FROM_ELSEWHERE = {
    "bad_toml",
    "bad_chain",
    "sites_case",
    "calibration_preflight",
    "input_unreachable",
    "input_header",
}


def test_every_code_has_a_row() -> None:
    assert FROM_A_DOCUMENT | FROM_ELSEWHERE == CHECK_CODES
    assert not FROM_A_DOCUMENT & FROM_ELSEWHERE


@pytest.mark.parametrize("code", sorted(CHECK_CODES))
def test_every_code_has_its_phrase_in_each_language(code: str) -> None:
    assert all(phrase(code, lang).strip() for lang in LANGS)


# The error types of Pydantic and the code each one becomes.


@pytest.mark.parametrize(("error_type", "code"), sorted(PYDANTIC_CODES.items()))
def test_a_pydantic_error_type_becomes_its_check_code(error_type: str, code: str) -> None:
    assert code in CHECK_CODES
    assert code_of(error_type, "") == code


def test_a_family_of_error_types_is_read_by_its_name() -> None:
    assert code_of("missing_argument", "") == "to_fill"
    assert code_of("greater_than", "") == "out_of_range"
    assert code_of("float_parsing", "") == "wrong_type"
    assert code_of("a_type_pydantic_adds_tomorrow", "") == "refused_value"
