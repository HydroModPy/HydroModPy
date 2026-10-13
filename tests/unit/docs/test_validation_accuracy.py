"""The matrix of the Validation page shows the accuracy of each solver, not its threshold.

``headline_of`` picks the metric that speaks for a test, the cell colours it by
class, and a ``previous`` block on the record marks an error that grew.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def V():
    """hmp_validation is a module of docs/source/_ext, not of a package."""
    ext = ROOT / "docs" / "source" / "_ext"
    sys.path.insert(0, str(ext))
    import hmp_validation

    yield hmp_validation
    sys.path.remove(str(ext))


def metric(name: str, value: float, unit: str = "", threshold: float = 1.0, op: str = "<") -> dict:
    return {
        "name": name,
        "value": value,
        "threshold": threshold,
        "op": op,
        "unit": unit,
        "ideal": None,
    }


def record(
    metrics: list[dict], scale: dict | None = None, outcome: str = "passed", **extra
) -> dict:
    return {"outcome": outcome, "metrics": metrics, "scale": scale, **extra}


HEAD_SCALE = {"value": 2.0, "label": "head range of the reference", "unit": "m"}


def test_a_scaled_record_reads_its_rmse_over_the_scale(V) -> None:
    rec = record(
        [metric("Max abs error", 0.5, "m"), metric("Head-profile RMSE", -0.02, "m")], HEAD_SCALE
    )
    value, kind, label = V.accuracy_of(rec)
    assert (value, kind) == (pytest.approx(0.01), "relative")
    assert label == "Head-profile RMSE / head range of the reference"


def test_a_scaled_record_without_rmse_takes_its_head_error(V) -> None:
    rec = record(
        [metric("Freeboard", 3.0, "m", op=">="), metric("Head max abs error", 0.2, "m")],
        HEAD_SCALE,
    )
    assert V.accuracy_of(rec)[0] == pytest.approx(0.1)


def test_a_position_or_an_increment_is_not_read_against_a_head_scale(V) -> None:
    rec = record(
        [
            metric("Seepage-limit position error", 140.0, "m"),
            metric("Discharge increment", 0.0, "m"),
        ],
        HEAD_SCALE,
    )
    assert V.accuracy_of(rec) is None


def test_the_plain_solver_speaks_for_its_column_not_its_control(V) -> None:
    plain = record([metric("Head-profile RMSE", 0.002, "m")], HEAD_SCALE, solver="modflow6")
    control = record([metric("Head-profile RMSE", 0.2, "m")], HEAD_SCALE, solver="modflow6_k_only")
    head, rec = V.cell_headline([plain, control], "modflow6")
    assert rec is plain and head.value == pytest.approx(0.001)
    assert V.cell_headline([control], "modflow6")[1] is control


def test_a_scaled_record_without_a_metric_in_its_unit_falls_to_the_next_rule(V) -> None:
    rec = record([metric("Largest relative error", 0.03)], HEAD_SCALE)
    assert V.accuracy_of(rec) == (0.03, "relative", "Largest relative error")


def test_a_relative_error_without_scale_takes_the_largest(V) -> None:
    rec = record(
        [
            metric("Largest relative concentration error", 0.02),
            metric("Largest relative position error", -0.04),
            metric("Relative drift of the budget", 0.5),
            metric("cma_es: evaluations used relative", 0.9),
            metric("Nash-Sutcliffe efficiency of the concentration", 0.99, op=">"),
        ]
    )
    assert V.accuracy_of(rec) == (0.04, "relative", "Largest relative position error")


def test_the_distance_of_an_observed_order_is_its_own_kind(V) -> None:
    rec = record([metric("Distance of the observed order from 2", -0.07, threshold=0.2)])
    assert V.accuracy_of(rec) == (
        pytest.approx(0.07),
        "order",
        "Distance of the observed order from 2",
    )


@pytest.mark.parametrize(
    "metrics",
    [
        [],
        [metric("Head RMSE", 0.01, "m")],
        [metric("Absolute distance of K_global to the truth", 0.3)],
        [metric("Largest relative error", None)],
        [metric("Relative error", 0.1, op=">")],
    ],
)
def test_a_record_without_a_distance_to_a_reference_has_no_accuracy(V, metrics) -> None:
    assert V.accuracy_of(record(metrics)) is None


@pytest.mark.parametrize(
    ("fraction", "text"),
    [
        (0.0, "< 0.01 %"),
        (9e-5, "< 0.01 %"),
        (1e-4, "0.010 %"),
        (0.0031, "0.31 %"),
        (0.047, "4.7 %"),
        (0.123, "12 %"),
        (0.0996, "10 %"),
        (0.9996, "100 %"),
        (2.5, "250 %"),
    ],
)
def test_a_percent_has_two_significant_digits(V, fraction: float, text: str) -> None:
    assert V.percent_text(fraction) == text


@pytest.mark.parametrize(
    ("value", "kind", "cls"),
    [
        (0.0009, "relative", "r1"),
        (0.001, "relative", "r2"),
        (0.0099, "relative", "r2"),
        (0.01, "relative", "r3"),
        (0.049, "relative", "r3"),
        (0.05, "relative", "r4"),
        (0.05, "order", "r1"),
        (0.15, "order", "r2"),
        (0.4, "order", "r4"),
    ],
)
def test_the_class_follows_the_error(V, value: float, kind: str, cls: str) -> None:
    assert V.accuracy_class(value, kind) == cls


def cell(V, records: list[dict], **kw) -> str:
    return V.ValidationDirective.cell(records, True, kw.pop("gap", False), **kw)


def test_a_passed_cell_shows_the_percent_and_the_context(V) -> None:
    rec = record([metric("Head-profile RMSE", 0.0062, "m", 0.02)], HEAD_SCALE)
    html = cell(V, [rec], row_best=0.001)
    assert "hmp-val-r2" in html
    assert ">0.31 %<" in html
    assert "Head-profile RMSE / head range of the reference" in html
    assert "threshold &lt; 0.02 m" in html
    assert "31% of the threshold used" in html
    assert "3.1 x the best solver of this case" in html


def test_the_best_solver_of_a_row_says_so_and_a_lone_cell_compares_to_nothing(V) -> None:
    rec = record([metric("Head-profile RMSE", 0.002, "m", 0.02)], HEAD_SCALE)
    assert "the best solver of this case" in cell(V, [rec], row_best=0.001)
    assert "best solver" not in cell(V, [rec], row_best=None)


def test_a_failed_cell_keeps_the_cross_and_its_accuracy(V) -> None:
    rec = record([metric("Head-profile RMSE", 0.2, "m", 0.02)], HEAD_SCALE, outcome="failed")
    html = cell(V, [rec])
    assert "hmp-val-r5" in html
    assert "&#x2717; 10 %" in html


def test_a_cell_without_accuracy_says_pass_or_keeps_the_cross(V) -> None:
    rec = record([metric("Head RMSE", 0.01, "m")])
    assert ">pass<" in cell(V, [rec])
    failed = record([metric("Head RMSE", 2.0, "m")], outcome="failed")
    assert "&#x2717;" in cell(V, [failed])
    assert ">pass<" in cell(V, [record([])])


def test_the_gap_mark_and_the_skipped_cell_are_kept(V) -> None:
    rec = record([metric("Head-profile RMSE", 0.002, "m")], HEAD_SCALE)
    assert "hmp-val-gapmark" in cell(V, [rec], gap=True)
    assert "skipped" in cell(V, [record([], outcome="skipped")])


def test_the_worst_variant_speaks_for_the_cell(V) -> None:
    good = record([metric("Head-profile RMSE", 0.002, "m")], HEAD_SCALE)
    bad = record([metric("Head-profile RMSE", 0.2, "m")], HEAD_SCALE)
    html = cell(V, [good, bad])
    assert ">10 %<" in html
    assert "worst of 2 variants" in html


def previous(value: float) -> dict:
    return {
        "date": "2026-10-01T00:00:00+00:00",
        "commit": "abcdef0123456789",
        "metrics": [{"name": "Head-profile RMSE", "value": value}],
    }


def test_an_error_that_grew_by_more_than_a_fifth_shows_a_red_mark(V) -> None:
    rec = record([metric("Head-profile RMSE", 0.018, "m")], HEAD_SCALE, previous=previous(0.01))
    html = cell(V, [rec])
    assert "hmp-val-up" in html
    assert "error x1.8 since 2026-10-01 (abcdef012)" in html


def test_a_small_change_or_a_rounding_one_shows_no_mark(V) -> None:
    near = record([metric("Head-profile RMSE", 0.0119, "m")], HEAD_SCALE, previous=previous(0.01))
    assert "hmp-val-up" not in cell(V, [near]) and "hmp-val-down" not in cell(V, [near])
    tiny = record([metric("Head-profile RMSE", 5e-13, "m")], HEAD_SCALE, previous=previous(1e-13))
    assert "hmp-val-up" not in cell(V, [tiny])
    none = record([metric("Head-profile RMSE", 0.5, "m")], HEAD_SCALE)
    assert "hmp-val-up" not in cell(V, [none])


def test_an_error_that_fell_shows_a_muted_mark(V) -> None:
    rec = record([metric("Head-profile RMSE", 0.005, "m")], HEAD_SCALE, previous=previous(0.01))
    html = cell(V, [rec])
    assert "hmp-val-down" in html
    assert "error x0.5 since" in html


def test_an_error_that_grew_from_zero_is_marked_without_a_factor(V) -> None:
    rec = record([metric("Head-profile RMSE", 0.01, "m")], HEAD_SCALE, previous=previous(0.0))
    assert "error grew from zero" in cell(V, [rec])


def test_a_previous_without_the_metric_shows_no_mark(V) -> None:
    prev = {"date": "2026-10-01", "commit": "x", "metrics": [{"name": "other", "value": 1e-9}]}
    rec = record([metric("Head-profile RMSE", 0.5, "m")], HEAD_SCALE, previous=prev)
    assert "hmp-val-up" not in cell(V, [rec])


def test_an_order_cell_shows_the_distance_of_the_order(V) -> None:
    rec = record([metric("Distance of the observed order from 2", 0.05, threshold=0.2)])
    html = cell(V, [rec])
    assert "|p - p0| 0.05" in html
    assert "hmp-val-r1" in html


def test_a_word_inside_another_word_does_not_exclude_a_metric(V) -> None:
    rec = record([metric("Largest relative concentration error", 0.02)])
    assert V.accuracy_of(rec) == (0.02, "relative", "Largest relative concentration error")
    ratio_name = record([metric("Relative error to tolerance ratio", 0.02)])
    assert V.accuracy_of(ratio_name) is None


def test_two_errors_under_the_display_floor_are_level(V) -> None:
    tiny = record([metric("Head-profile RMSE", 2e-6, "m", 0.02)], HEAD_SCALE)
    html = cell(V, [tiny], row_best=1e-9)
    assert "the best solver of this case" in html
    assert " x the best" not in html
    near = record([metric("Head-profile RMSE", 0.0204, "m", 0.05)], HEAD_SCALE)
    assert "level with the best solver" in cell(V, [near], row_best=0.0101)
