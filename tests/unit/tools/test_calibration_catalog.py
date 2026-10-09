"""The catalog of calibration methods and metrics is read from the code, whole.

The reference page of the methods and the theory page of the inverse problem
are rendered from ``tools.docs.calibration_catalog``. A method registered
without its options model, an option without a description, or a metric
without its formula would show as a hole on the site: these tests catch it
here instead.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import get_args

import pytest

from hydromodpy.calibration.criteria.formulas import METRIC_FORMULAS
from hydromodpy.calibration.criteria.series import HIGHER_IS_BETTER, METRICS
from hydromodpy.calibration.optim.method_config import CalibrationMethodConfig
from hydromodpy.calibration.optim.optimizer import CHOSEN_FROM, available_optimizers
from tools.docs import calibration_catalog

EXT = Path(__file__).resolve().parents[3] / "docs" / "source" / "_ext"


@pytest.fixture(scope="module")
def payload() -> dict:
    return calibration_catalog.build()


def _models() -> dict[str, type]:
    members = get_args(get_args(CalibrationMethodConfig)[0])
    return {member.model_fields["method"].default: member for member in members}


def test_every_registered_method_is_in_the_catalog(payload: dict) -> None:
    names = {row["name"] for row in payload["methods"]}
    assert set(available_optimizers()) <= names
    assert all(row["registered"] for row in payload["methods"])


def test_each_method_lists_exactly_the_options_its_model_accepts(payload: dict) -> None:
    models = _models()
    for row in payload["methods"]:
        accepted = set(models[row["name"]].model_fields) - {"method"}
        assert {option["name"] for option in row["options"]} == accepted, row["name"]


def test_every_option_says_what_it_sets(payload: dict) -> None:
    blank = [
        f"{row['name']}.{option['name']}"
        for row in payload["methods"]
        for option in row["options"]
        if not option["description"]
    ]
    assert blank == []


def test_every_method_says_what_it_does_and_when_to_use_it(payload: dict) -> None:
    for row in payload["methods"]:
        assert row["summary"], row["name"]
        assert any("Use it" in paragraph for paragraph in row["details"]), row["name"]


def test_the_defaults_are_the_ones_of_the_models(payload: dict) -> None:
    rows = {row["name"]: row for row in payload["methods"]}
    options = {option["name"]: option for option in rows["bisection"]["options"]}
    assert options["sweep_points"]["default"] == 7
    assert options["rel_tol"]["default"] == pytest.approx(0.01)
    lhs = {option["name"]: option for option in rows["lhs"]["options"]}
    assert lhs["n_samples"]["required"] is True


def test_the_traits_come_from_the_adapters(payload: dict) -> None:
    rows = {row["name"]: row for row in payload["methods"]}
    assert rows["bisection"]["max_parameters"] == 1
    assert rows["bisection"]["needs_signed_residual"] is True
    assert rows["bisection"]["counts_its_budget"] is True
    assert rows["scipy_de"]["supports_parallel"] is False
    assert rows["grid"]["restarts_explore_differently"] is False
    assert rows["da_mh_gp"]["reads_cost_as"] == "rmse"
    assert [name for name, row in rows.items() if row["chosen_rank"] is not None] == sorted(
        CHOSEN_FROM
    )


def test_every_metric_has_its_formula() -> None:
    assert set(METRIC_FORMULAS) == set(METRICS)
    for name, formula in METRIC_FORMULAS.items():
        assert formula.score and formula.reads, name


def test_the_metric_rows_follow_the_kernels(payload: dict) -> None:
    rows = {row["name"]: row for row in payload["metrics"]}
    assert set(rows) == set(METRICS)
    for name, row in rows.items():
        assert row["higher_is_better"] is (name in HIGHER_IS_BETTER)
        assert row["cost"] == ("1 - score" if name in HIGHER_IS_BETTER else "score")
    assert rows["distance_gap"]["signed"] is True
    assert rows["distance_gap"]["unit"] == "m"
    assert rows["rmse"]["normalize_cost"] == "standard deviation of the observations"
    assert rows["nse"]["normalize_cost"] == "refused"


def test_the_extension_renders_every_method_and_metric(payload: dict) -> None:
    sys.path.insert(0, str(EXT))
    try:
        import hmp_calibration
    finally:
        sys.path.remove(str(EXT))

    summary = hmp_calibration.methods_summary_rst(payload["methods"], link=True)
    for row in payload["methods"]:
        assert f"<calibration-method-{row['name']}>" in summary
        section = hmp_calibration.method_section_rst(row)
        assert section.startswith(f"``{row['name']}``")
        for option in row["options"]:
            assert f"``{option['name']}``" in section
    table = hmp_calibration.metrics_table_rst(payload["metrics"])
    formulas = hmp_calibration.metrics_formulas_rst(payload["metrics"])
    for row in payload["metrics"]:
        assert f"``{row['name']}``" in table
        assert row["score"] in formulas
