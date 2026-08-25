"""The three figures that read the downslope stream-network criterion.

The two curves are driven exactly as a session drives them: one row per trial,
the sampled parameter nested under ``parameters`` and the criterion diagnostics
nested under ``metrics``, prefixed with the name of the output that emitted
them.

The confusion map is driven by a run alone, as a ``[display].figures`` entry
drives it, over the grid of :mod:`tests.unit.display._network_comparison_run`
whose partition is known before the criterion is ever called.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display.figure_registry import get as get_figure
from hydromodpy.display.figures._stream_comparison import AGREEMENT_COLORS
from hydromodpy.display.figures.bisection_bracket_trace import BisectionBracketTraceFigure
from hydromodpy.display.figures.downslope_distance_crossing import (
    DownslopeDistanceCrossingFigure,
)
from hydromodpy.display.figures.seepage_network_confusion_map import SeepageNetworkConfusionMap
from hydromodpy.results.derive.stream_network import (
    AGREEMENT_EXCESS,
    AGREEMENT_MISSING,
    AGREEMENT_NEITHER,
    AGREEMENT_VALID,
    agreement_label,
)

from ._network_comparison_run import (
    AXIS_COLUMN,
    NX,
    NY,
    cell,
    column_cells,
    comparison_run,
    drawn_cells,
)

L_REF = 250.0


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


def _session_run(
    parameter_values: list[float],
    diagnostics: list[dict[str, float | None]],
    *,
    name: str = "cheze-bisection",
    output: str = "streams",
) -> SimpleNamespace:
    """A Run carrying one calibration session, in the shape a journal writes."""
    rows = []
    for index, (value, metrics) in enumerate(zip(parameter_values, diagnostics, strict=True)):
        payload = {
            f"{output}.{key}": number for key, number in metrics.items() if number is not None
        }
        payload[f"{output}.L_ref"] = L_REF
        rows.append(
            {
                "iteration": index,
                "parameters": {"K_over_R": {"value": value}},
                "metrics": payload,
                "status": "completed" if metrics.get("D_os") is not None else "failed",
            }
        )
    return SimpleNamespace(
        sim_id="sim-cheze",
        name=name,
        calibration_iterations=pd.DataFrame(rows),
    )


def _crossing_run(**kwargs) -> SimpleNamespace:
    """Two straight lines meeting once, at a value the test can predict."""
    return _session_run(
        [1e-4, 1e-3],
        [
            {"D_so": 100.0, "D_os": 300.0},
            {"D_so": 300.0, "D_os": 100.0},
        ],
        **kwargs,
    )


def _line(ax, label_prefix: str):
    return next(line for line in ax.lines if str(line.get_label()).startswith(label_prefix))


def _relative_luminance(color: str) -> float:
    """Perceived brightness of one colour, the quantity a greyscale print keeps."""
    from matplotlib.colors import to_rgb

    channels = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in to_rgb(color)
    ]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


# --------------------------------------------------------------------------- #
# downslope_distance_crossing
# --------------------------------------------------------------------------- #


def test_crossing_draws_both_distances_on_a_log_axis_in_metres(mpl) -> None:
    fig, ax = mpl.subplots()

    DownslopeDistanceCrossingFigure().render(_crossing_run(), ax)

    try:
        assert ax.get_xscale() == "log"
        assert ax.get_ylabel() == "Downslope distance (m)"
        assert ax.get_xlabel() == "K_over_R (-)"
        assert _line(ax, "D_so").get_ydata().tolist() == [100.0, 300.0]
        assert _line(ax, "D_os").get_ydata().tolist() == [300.0, 100.0]
        assert "cheze-bisection" in ax.get_title()
    finally:
        mpl.close(fig)


def test_crossing_marks_the_intersection_with_its_parameter_value(mpl) -> None:
    # The residual goes -200 m to +200 m over one decade, so the zero sits at
    # the middle of that decade in log space.
    fig, ax = mpl.subplots()

    DownslopeDistanceCrossingFigure().render(_crossing_run(), ax)

    try:
        marker = _line(ax, "crossing")
        assert marker.get_xdata()[0] == pytest.approx(10.0**-3.5)
        annotation = ax.texts[0].get_text()
        assert "K_over_R" in annotation
        assert f"{10.0**-3.5:.4g}" in annotation
    finally:
        mpl.close(fig)


def test_crossing_leaves_a_gap_where_a_trial_failed(mpl) -> None:
    run = _session_run(
        [1e-5, 1e-4, 1e-3],
        [
            {"D_so": 100.0, "D_os": 300.0},
            {"D_so": None, "D_os": None},
            {"D_so": 300.0, "D_os": 100.0},
        ],
    )
    fig, ax = mpl.subplots()

    DownslopeDistanceCrossingFigure().render(run, ax)

    try:
        values = _line(ax, "D_so").get_ydata()
        assert np.isnan(values[1]), "a failed trial must break the line, not read as zero"
        assert values[0] == 100.0 and values[2] == 300.0
        # The abscissa stays, so the curve keeps the spacing of the sweep.
        assert _line(ax, "D_so").get_xdata().tolist() == [1e-5, 1e-4, 1e-3]
    finally:
        mpl.close(fig)


def test_crossing_bands_are_one_reference_length_either_side(mpl) -> None:
    fig, ax = mpl.subplots()

    DownslopeDistanceCrossingFigure().render(_crossing_run(), ax)

    try:
        assert len(ax.collections) == 2, "one band per curve"
        labels = [text.get_text() for text in ax.get_legend().get_texts()]
        assert f"one reference length either side ({L_REF:.0f} m)" in labels
        extents = [collection.get_datalim(ax.transData) for collection in ax.collections]
        # The D_so band spans 100 - 250 clipped at zero, up to 300 + 250.
        assert min(extent.y0 for extent in extents) == pytest.approx(0.0)
        assert max(extent.y1 for extent in extents) == pytest.approx(300.0 + L_REF)
    finally:
        mpl.close(fig)


def test_crossing_reports_a_range_that_never_changes_sign(mpl) -> None:
    run = _session_run(
        [1e-4, 1e-3],
        [
            {"D_so": 300.0, "D_os": 100.0},
            {"D_so": 400.0, "D_os": 100.0},
        ],
    )
    fig, ax = mpl.subplots()

    DownslopeDistanceCrossingFigure().render(run, ax)

    try:
        assert not [line for line in ax.lines if str(line.get_label()).startswith("crossing")]
        assert "no sign change" in ax.texts[0].get_text()
    finally:
        mpl.close(fig)


def test_crossing_refuses_a_non_positive_parameter(mpl) -> None:
    run = _session_run(
        [0.0, 1e-3],
        [{"D_so": 100.0, "D_os": 300.0}, {"D_so": 300.0, "D_os": 100.0}],
    )
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="non-positive"):
            DownslopeDistanceCrossingFigure().render(run, ax)
    finally:
        mpl.close(fig)


def test_crossing_names_the_output_when_two_publish_the_same_diagnostic(mpl) -> None:
    run = _crossing_run()
    frame = run.calibration_iterations
    frame["metrics"] = [
        {**payload, "other.D_so": 1.0, "other.D_os": 2.0} for payload in frame["metrics"]
    ]
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="several outputs publish"):
            DownslopeDistanceCrossingFigure().render(run, ax)
        DownslopeDistanceCrossingFigure().render(run, ax, output="streams")
        assert _line(ax, "D_so").get_ydata().tolist() == [100.0, 300.0]
    finally:
        mpl.close(fig)


def test_crossing_reads_the_json_blocks_the_index_hands_back(mpl) -> None:
    # The journal keeps the two nested blocks as dicts and DuckDB keeps them
    # as text; the figure must read the same session either way.
    run = _crossing_run()
    frame = run.calibration_iterations
    frame["parameters"] = [json.dumps(block) for block in frame["parameters"]]
    frame["metrics"] = [json.dumps(block) for block in frame["metrics"]]
    fig, ax = mpl.subplots()

    DownslopeDistanceCrossingFigure().render(run, ax)

    try:
        assert ax.get_xlabel() == "K_over_R (-)"
        assert _line(ax, "D_so").get_ydata().tolist() == [100.0, 300.0]
        assert _line(ax, "crossing").get_xdata()[0] == pytest.approx(10.0**-3.5)
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# seepage_network_confusion_map
# --------------------------------------------------------------------------- #


def _partition_run(**kwargs):
    """A run whose three classes are known before the criterion is called.

    Seepage halfway down the mapped column and on the south-east corner. The
    first closes down the column and agrees with the map, the second crosses
    two cells of the flank before joining it, and the northern cell of the map
    is left with no simulated stream at all: two valid, two excess, one
    missing, whatever the criterion is asked afterwards.
    """
    return comparison_run(seepage_cells=[cell(AXIS_COLUMN, 1), cell(4, 0)], **kwargs)


def _class_cells(ax, value: int) -> list[int]:
    """The grid cells drawn under one agreement class, empty when it has none."""
    label = agreement_label(value)
    for collection in ax.collections:
        if str(collection.get_label()) == label:
            return drawn_cells(collection)
    return []


def test_confusion_map_draws_the_partition_the_run_carries(mpl) -> None:
    fig, ax = mpl.subplots()

    SeepageNetworkConfusionMap().render(_partition_run(), ax)

    try:
        assert _class_cells(ax, AGREEMENT_VALID) == [
            cell(AXIS_COLUMN, 0),
            cell(AXIS_COLUMN, 1),
        ]
        assert _class_cells(ax, AGREEMENT_EXCESS) == [cell(3, 0), cell(4, 0)]
        assert _class_cells(ax, AGREEMENT_MISSING) == [cell(AXIS_COLUMN, 2)]
        assert len(_class_cells(ax, AGREEMENT_NEITHER)) == NX * NY - 5
        assert [text.get_text() for text in ax.get_legend().get_texts()] == [
            "valid: simulated and mapped (2 cells)",
            "excess: simulated only (2 cells)",
            "missing: mapped only (1 cell)",
            "no stream (10 cells)",
        ]
        assert ax.get_xlabel() == "x (m)"
        assert ax.get_ylabel() == "y (m)"
        assert "nancon" in ax.get_title()
    finally:
        mpl.close(fig)


def test_confusion_map_gives_every_class_its_own_colour(mpl) -> None:
    from matplotlib.colors import to_rgb

    fig, ax = mpl.subplots()

    SeepageNetworkConfusionMap().render(_partition_run(), ax)

    try:
        for value, color in AGREEMENT_COLORS.items():
            drawn = next(
                collection
                for collection in ax.collections
                if str(collection.get_label()) == agreement_label(value)
            )
            face = tuple(np.asarray(drawn.get_facecolor()).reshape(-1)[:3])
            assert face == pytest.approx(to_rgb(color))
    finally:
        mpl.close(fig)


def test_confusion_map_cells_belong_to_exactly_one_class(mpl) -> None:
    fig, ax = mpl.subplots()

    SeepageNetworkConfusionMap().render(_partition_run(), ax)

    try:
        drawn = [index for value in AGREEMENT_COLORS for index in _class_cells(ax, value)]
        assert sorted(drawn) == list(range(NX * NY)), (
            "the four classes partition the mesh: every cell is drawn once"
        )
    finally:
        mpl.close(fig)


def test_confusion_map_follows_the_seepage_threshold_it_is_asked_for(mpl) -> None:
    fig, ax = mpl.subplots()

    # A threshold far above what any cell releases leaves no simulated stream,
    # so the whole mapped column is missing and nothing is valid or excess.
    SeepageNetworkConfusionMap().render(_partition_run(), ax, tau_specific_ratio=1.0e6)

    try:
        assert _class_cells(ax, AGREEMENT_MISSING) == column_cells(AXIS_COLUMN)
        assert _class_cells(ax, AGREEMENT_VALID) == []
        assert _class_cells(ax, AGREEMENT_EXCESS) == []
        assert "tau = 1e+06" in ax.texts[0].get_text()
    finally:
        mpl.close(fig)


def test_confusion_map_names_the_threshold_it_was_drawn_at(mpl) -> None:
    fig, ax = mpl.subplots()

    SeepageNetworkConfusionMap().render(_partition_run(), ax, tau_specific_ratio=0.25)

    try:
        assert "tau = 0.25 of the mean recharge" in ax.texts[0].get_text()
    finally:
        mpl.close(fig)


def test_confusion_map_classes_stay_apart_in_greyscale() -> None:
    luminances = sorted(
        _relative_luminance(AGREEMENT_COLORS[value])
        for value in (AGREEMENT_VALID, AGREEMENT_EXCESS, AGREEMENT_MISSING)
    )
    gaps = [high - low for low, high in zip(luminances[:-1], luminances[1:], strict=False)]
    assert min(gaps) > 0.1, (
        "the three classes must stay readable on a greyscale print, so their "
        f"lightnesses may not collide: {luminances}"
    )


def test_the_cells_with_no_stream_recede_behind_the_three_classes() -> None:
    background = _relative_luminance(AGREEMENT_COLORS[AGREEMENT_NEITHER])
    classes = [
        _relative_luminance(AGREEMENT_COLORS[value])
        for value in (AGREEMENT_VALID, AGREEMENT_EXCESS, AGREEMENT_MISSING)
    ]

    assert background - max(classes) > 0.1, (
        "the cells no network claims cover most of a catchment; drawn as dark "
        f"as a class they would carry the eye instead of it: {background}"
    )


def test_confusion_map_is_rendered_from_a_run_alone(tmp_path) -> None:
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.display.runs import render_figures_for_run

    cfg = DisplayConfig(
        enabled=True,
        figures=["seepage_network_confusion_map"],
        on_error="raise",
    )

    report = render_figures_for_run(_partition_run(), cfg, output_dir=tmp_path)

    assert report.rendered == ("seepage_network_confusion_map",)
    assert report.skipped == ()
    assert (tmp_path / "seepage_network_confusion_map.png").exists()


def test_confusion_map_is_skipped_by_the_gallery_rather_than_crashing(tmp_path) -> None:
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.display.runs import render_figures_for_run

    cfg = DisplayConfig(
        enabled=True,
        figures=["seepage_network_confusion_map"],
        on_error="raise",
    )

    report = render_figures_for_run(comparison_run(with_release=False), cfg, output_dir=tmp_path)

    assert report.rendered == ()
    assert [item.name for item in report.skipped] == ["seepage_network_confusion_map"]
    assert "release_flux" in report.skipped[0].reason
    assert "render failed" not in report.skipped[0].reason


def test_confusion_map_names_what_it_needs_when_the_run_kept_no_release_flux() -> None:
    reason = SeepageNetworkConfusionMap().unavailable_reason(comparison_run(with_release=False))

    assert reason is not None
    assert "release_flux" in reason


# --------------------------------------------------------------------------- #
# bisection_bracket_trace
# --------------------------------------------------------------------------- #


def _bracket_run(**kwargs) -> SimpleNamespace:
    """A sweep that changes sign once, then two bisection steps closing on it."""
    return _session_run(
        [1e-5, 1e-3, 1e-4, 3.2e-5],
        [
            {"D_so": 0.0, "D_os": 0.0, "J_signed": 300.0},
            {"D_so": 0.0, "D_os": 0.0, "J_signed": -400.0},
            {"D_so": 0.0, "D_os": 0.0, "J_signed": -120.0},
            {"D_so": 0.0, "D_os": 0.0, "J_signed": 40.0},
        ],
        **kwargs,
    )


def test_bracket_trace_plots_every_evaluation_in_order_around_a_zero_line(mpl) -> None:
    fig, ax = mpl.subplots()

    BisectionBracketTraceFigure().render(_bracket_run(), ax)

    try:
        assert ax.get_xlabel() == "Evaluation order (-)"
        assert ax.get_ylabel() == "Signed residual D_so - D_os (m)"
        zero = _line(ax, "zero residual")
        assert list(zero.get_ydata()) == [0.0, 0.0]

        excess = next(
            collection
            for collection in ax.collections
            if str(collection.get_label()).startswith("D_so - D_os >=")
        )
        assert excess.get_offsets().tolist() == [[1.0, 300.0], [4.0, 40.0]]
        missing = next(
            collection
            for collection in ax.collections
            if str(collection.get_label()).startswith("D_so - D_os <")
        )
        assert missing.get_offsets().tolist() == [[2.0, -400.0], [3.0, -120.0]]
    finally:
        mpl.close(fig)


def test_bracket_trace_closes_the_band_onto_zero(mpl) -> None:
    from hydromodpy.display.figures.bisection_bracket_trace import _running_bracket

    values = np.array([1e-5, 1e-3, 1e-4, 3.2e-5])
    residual = np.array([300.0, -400.0, -120.0, 40.0])

    trace = _running_bracket(values, residual)

    # Nothing brackets the first point; the second one opens [1e-5, 1e-3];
    # each following evaluation lands inside and tightens it.
    assert not np.isfinite(trace.parameter_low[0])
    assert trace.parameter_low[1] == pytest.approx(1e-5)
    assert trace.parameter_high[1] == pytest.approx(1e-3)
    assert trace.parameter_high[2] == pytest.approx(1e-4)
    assert trace.parameter_low[3] == pytest.approx(3.2e-5)
    widths = trace.residual_high[1:] - trace.residual_low[1:]
    assert list(widths) == sorted(widths, reverse=True), "the bracket may only tighten"
    assert trace.is_closed


def test_bracket_trace_names_the_closed_bracket(mpl) -> None:
    fig, ax = mpl.subplots()

    BisectionBracketTraceFigure().render(_bracket_run(), ax)

    try:
        note = ax.texts[0].get_text()
        assert "K_over_R in [3.2e-05, 0.0001]" in note
        assert "factor" in note
    finally:
        mpl.close(fig)


def test_bracket_trace_names_the_failure_when_no_sign_change(mpl) -> None:
    run = _session_run(
        [1e-5, 1e-4, 1e-3],
        [
            {"D_so": 0.0, "D_os": 0.0, "J_signed": 300.0},
            {"D_so": 0.0, "D_os": 0.0, "J_signed": 120.0},
            {"D_so": 0.0, "D_os": 0.0, "J_signed": 40.0},
        ],
    )
    fig, ax = mpl.subplots()

    BisectionBracketTraceFigure().render(run, ax)

    try:
        assert "no sign change: no root is bracketed" in ax.texts[0].get_text()
        labels = [text.get_text() for text in ax.get_legend().get_texts()]
        assert not any(label.startswith("bracket") for label in labels)
    finally:
        mpl.close(fig)


def test_bracket_trace_keeps_a_failed_evaluation_on_the_zero_line(mpl) -> None:
    run = _session_run(
        [1e-5, 1e-4, 1e-3],
        [
            {"D_so": 0.0, "D_os": 0.0, "J_signed": 300.0},
            {"D_so": None, "D_os": None},
            {"D_so": 0.0, "D_os": 0.0, "J_signed": -40.0},
        ],
    )
    fig, ax = mpl.subplots()

    BisectionBracketTraceFigure().render(run, ax)

    try:
        failed = next(
            collection
            for collection in ax.collections
            if str(collection.get_label()).startswith("failed evaluation")
        )
        assert failed.get_offsets().tolist() == [[2.0, 0.0]]
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #


def test_the_three_figures_are_registered_under_their_own_name() -> None:
    expected = {
        "downslope_distance_crossing": DownslopeDistanceCrossingFigure,
        "bisection_bracket_trace": BisectionBracketTraceFigure,
        "seepage_network_confusion_map": SeepageNetworkConfusionMap,
    }
    for name, figure_cls in expected.items():
        figure = get_figure(name)
        assert isinstance(figure, figure_cls)
        assert figure.spec.name == name
