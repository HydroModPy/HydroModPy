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

from hydromodpy.display.figures._stream_comparison import (
    AGREEMENT_COLORS,
    CASING_COLOR,
    CELL_WEIGHT_PT,
)
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
    CELL_M,
    NX,
    NY,
    cell,
    column_cells,
    comparison_run,
    drawn_cells,
    legend_labels,
    legend_note,
    map_key,
)
from ._render_helpers import relative_luminance

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


def _class_collection(ax, value: int):
    """The one collection drawn under an agreement class."""
    label = agreement_label(value)
    return next(item for item in ax.collections if str(item.get_label()) == label)


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
        assert legend_labels(ax) == [
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
        assert "tau = 1e+06" in legend_note(ax)
    finally:
        mpl.close(fig)


def test_confusion_map_names_the_threshold_it_was_drawn_at(mpl) -> None:
    fig, ax = mpl.subplots()

    SeepageNetworkConfusionMap().render(_partition_run(), ax, tau_specific_ratio=0.25)

    try:
        assert "tau = 0.25 of the mean recharge" in legend_note(ax)
    finally:
        mpl.close(fig)


def test_the_key_and_the_note_sit_outside_the_map(mpl) -> None:
    # They used to share the inside of the axes, the legend wherever
    # matplotlib found room and the note pinned to the foot. On the Nancon
    # they landed on each other and the third class was read through the note.
    # Drawn the way the gallery draws it, through plot().
    fig = SeepageNetworkConfusionMap().plot(_partition_run())
    ax = fig.axes[0]

    try:
        fig.canvas.draw()
        key = map_key(ax).get_window_extent()
        frame = ax.get_window_extent()
        assert key.y1 <= frame.y0 + 1.0, (
            f"the key overlaps the map: key {key.y0}-{key.y1}, map {frame.y0}-{frame.y1}"
        )
        assert not ax.texts, "nothing may be left floating over the subject"
    finally:
        mpl.close(fig)


def test_the_key_stays_off_the_map_on_an_axes_the_caller_built(mpl) -> None:
    # Matplotlib reserves room for an outside figure legend only when the
    # figure carries a layout engine, and render() is public: called on a
    # plain subplots() the key was drawn over the map. Measured before the
    # fix, on a figure with no engine, the key ran 6.6 px into the axes.
    fig, ax = mpl.subplots(figsize=(7.0, 6.2), dpi=150)

    SeepageNetworkConfusionMap().render(_partition_run(), ax)

    try:
        assert fig.get_layout_engine() is not None, (
            "the map has to give the figure the engine that reserves the room"
        )
        fig.canvas.draw()
        key = map_key(ax).get_window_extent()
        frame = ax.get_window_extent()
        assert key.y1 <= frame.y0 + 1.0, (
            f"the key overlaps the map: key {key.y0}-{key.y1}, map {frame.y0}-{frame.y1}"
        )
    finally:
        mpl.close(fig)


def test_the_network_is_widened_once_and_not_class_by_class(mpl) -> None:
    # A class of this map is a one-cell-wide line, so it needs weight to
    # survive the page. Given a stroke each, the three classes interleave cell
    # by cell along the same line and every one of them widens over the two
    # beside it: rendered on the Nancon at the shipped figsize, valid held the
    # most cells of the three (609 against 508) and printed the least ink of
    # the three, 5.2 px a cell against 11.9 for missing, which was drawn last.
    # The weight is carried once, by a casing over their union.
    from matplotlib.colors import to_rgba

    fig, ax = mpl.subplots()

    SeepageNetworkConfusionMap().render(_partition_run(), ax)

    try:
        casing = next(item for item in ax.collections if str(item.get_label()) == "_network casing")
        assert float(casing.get_linewidth()[0]) == pytest.approx(CELL_WEIGHT_PT)
        assert drawn_cells(casing) == sorted(
            _class_cells(ax, AGREEMENT_VALID)
            + _class_cells(ax, AGREEMENT_EXCESS)
            + _class_cells(ax, AGREEMENT_MISSING)
        ), "the casing covers the three classes and nothing else"
        assert tuple(np.asarray(casing.get_facecolor()).reshape(-1)) == pytest.approx(
            to_rgba(CASING_COLOR)
        )
        for value in (AGREEMENT_VALID, AGREEMENT_EXCESS, AGREEMENT_MISSING, AGREEMENT_NEITHER):
            assert float(_class_collection(ax, value).get_linewidth()[0]) == 0.0, (
                f"{agreement_label(value)} may not widen over the class beside it"
            )
    finally:
        mpl.close(fig)


def test_the_map_opens_on_the_catchment_and_says_so(mpl) -> None:
    # The three classes only ever live inside the delineated catchment. A run
    # whose catchment is the two western columns must frame those, not the
    # five columns of mesh around them.
    fig, ax = mpl.subplots()

    SeepageNetworkConfusionMap().render(_partition_run(catchment_columns=[0, 1]), ax)

    try:
        assert ax.get_xlim()[1] < 3 * CELL_M
        assert "the delineated catchment" in legend_note(ax)
    finally:
        mpl.close(fig)


def test_the_ground_is_counted_on_what_the_frame_shows(mpl) -> None:
    # The three classes are the numbers a trial publishes and stay whole; the
    # ground is not, and a reader checks it by looking at the grey in front of
    # them. Counted over the mesh it contradicted the page: on the Nancon the
    # key said 58 714 cells of no stream in a window holding 53 703.
    fig, ax = mpl.subplots()

    SeepageNetworkConfusionMap().render(_partition_run(catchment_columns=[1, 2, 3]), ax)

    try:
        # The frame holds the three middle columns, nine cells, four of which
        # the criterion classifies.
        assert legend_labels(ax) == [
            "valid: simulated and mapped (2 cells)",
            "excess: simulated only (1 cell)",
            "missing: mapped only (1 cell)",
            "no stream (5 cells)",
        ]
        ground = _class_collection(ax, AGREEMENT_NEITHER)
        assert len(ground.get_paths()) == NX * NY - 4, (
            "the ground is still drawn over the whole mesh, only counted on the frame"
        )
    finally:
        mpl.close(fig)


def test_a_caller_may_ask_for_the_whole_mesh(mpl) -> None:
    fig, ax = mpl.subplots()

    SeepageNetworkConfusionMap().render(_partition_run(catchment_columns=[0, 1]), ax, extent="mesh")

    try:
        assert ax.get_xlim()[1] >= NX * CELL_M
        assert "the whole mesh" in legend_note(ax)
    finally:
        mpl.close(fig)


def test_the_catchment_frame_hides_no_class(mpl) -> None:
    # The criterion scores nothing outside the delineated catchment, so the
    # default frame can drop no cell the legend counts. The note says nothing
    # rather than warning about a loss that cannot happen here.
    fig, ax = mpl.subplots()

    SeepageNetworkConfusionMap().render(_partition_run(catchment_columns=[0, 1]), ax)

    try:
        xmin, xmax = ax.get_xlim()
        ymin, ymax = ax.get_ylim()
        classified = [
            collection
            for value in (AGREEMENT_VALID, AGREEMENT_EXCESS, AGREEMENT_MISSING)
            for collection in ax.collections
            if str(collection.get_label()) == agreement_label(value)
        ]
        assert classified, "the run must classify something for this to say anything"
        for collection in classified:
            for path in collection.get_paths():
                centre = path.vertices.mean(axis=0)
                assert xmin <= centre[0] <= xmax and ymin <= centre[1] <= ymax
    finally:
        mpl.close(fig)


def test_an_unknown_frame_is_refused(mpl) -> None:
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="extent must be"):
            SeepageNetworkConfusionMap().render(_partition_run(), ax, extent="everything")
    finally:
        mpl.close(fig)


def test_confusion_map_classes_stay_apart_in_greyscale() -> None:
    luminances = sorted(
        relative_luminance(AGREEMENT_COLORS[value])
        for value in (AGREEMENT_VALID, AGREEMENT_EXCESS, AGREEMENT_MISSING)
    )
    gaps = [high - low for low, high in zip(luminances[:-1], luminances[1:], strict=False)]
    assert min(gaps) > 0.1, (
        "the three classes must stay readable on a greyscale print, so their "
        f"lightnesses may not collide: {luminances}"
    )


def test_the_cells_with_no_stream_recede_behind_the_three_classes() -> None:
    background = relative_luminance(AGREEMENT_COLORS[AGREEMENT_NEITHER])
    classes = [
        relative_luminance(AGREEMENT_COLORS[value])
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


class TestTheHeavyRebuildIsShared:
    """Six figures of one gallery ask for the same comparison. It is built once.

    On the Nancon at 25 m the rebuild floods 345 260 cells and runs two full
    distance passes. Doing that once per figure is the reason a gallery took
    longer to draw than the solve took to run.
    """

    def test_two_calls_on_one_run_return_the_same_object(self) -> None:
        from hydromodpy.display.figures._memo import RunMemo

        memo = RunMemo()
        calls: list[int] = []

        class _Run:
            pass

        run = _Run()

        def build():
            calls.append(1)
            return object()

        first = memo.get_or_build(run, ("a",), build)
        second = memo.get_or_build(run, ("a",), build)

        assert first is second
        assert len(calls) == 1

    def test_a_different_knob_is_a_different_entry(self) -> None:
        from hydromodpy.display.figures._memo import RunMemo

        memo = RunMemo()

        class _Run:
            pass

        run = _Run()
        first = memo.get_or_build(run, ("a",), object)
        second = memo.get_or_build(run, ("b",), object)

        assert first is not second

    def test_two_runs_never_share_an_entry_even_named_alike(self) -> None:
        # The failure this guards: keying on a run's id instead of the run.
        # Two runs a caller named the same would answer with each other's mesh,
        # and the figure would be silently wrong rather than slow.
        from hydromodpy.display.figures._memo import RunMemo

        memo = RunMemo()

        class _Run:
            sim_id = "same-name"

        first = memo.get_or_build(_Run(), ("a",), object)
        second = memo.get_or_build(_Run(), ("a",), object)

        assert first is not second

    def test_a_run_that_cannot_be_weakly_referenced_is_simply_not_cached(self) -> None:
        # A speed difference, never an answer difference.
        from types import SimpleNamespace

        from hydromodpy.display.figures._memo import RunMemo

        memo = RunMemo()
        run = SimpleNamespace(sim_id="stub")
        sentinel = object()

        assert memo.get_or_build(run, ("a",), lambda: sentinel) is sentinel
        assert memo.get_or_build(run, ("a",), lambda: sentinel) is sentinel


class TestTheLegendDoesNotSearchOnADenseMap:
    """``loc="best"`` scores every candidate corner against every artist.

    Measured on the Nancon at 25 m, one legend entry over a 243 552-polygon
    collection took 99.3 s to place against 1.1 s pinned. It was the single
    largest cost of the gallery, larger than the solve.
    """

    def _axes(self, n_paths: int):
        import matplotlib

        matplotlib.use("Agg")
        import numpy as np
        from matplotlib.collections import PolyCollection
        from matplotlib.figure import Figure

        ax = Figure().subplots()
        squares = [
            np.array([[i, 0.0], [i + 1.0, 0.0], [i + 1.0, 1.0], [i, 1.0]]) for i in range(n_paths)
        ]
        ax.add_collection(PolyCollection(squares))
        ax.plot([0, 1], [0, 1], label="something")
        return ax

    def test_a_collection_counts_for_its_paths_and_not_for_one(self) -> None:
        from hydromodpy.display.legend_placement import axes_element_count

        assert axes_element_count(self._axes(500)) >= 500

    def test_a_light_axes_still_gets_the_placed_legend(self) -> None:
        from hydromodpy.display.legend_placement import LEGEND_PLACEMENT, place_legend

        ax = self._axes(10)
        assert len(ax.collections[0].get_paths()) < LEGEND_PLACEMENT.best_placement_limit
        legend = place_legend(ax)
        assert legend is not None
        assert legend._loc == 0  # matplotlib's code for "best"

    def test_a_dense_axes_gets_a_pinned_legend(self) -> None:
        from hydromodpy.display.legend_placement import LEGEND_PLACEMENT, place_legend

        ax = self._axes(LEGEND_PLACEMENT.best_placement_limit + 1)
        legend = place_legend(ax)
        assert legend is not None
        assert legend._loc != 0

    def test_an_axes_with_nothing_to_show_gets_no_legend(self) -> None:
        import matplotlib
        from matplotlib.figure import Figure

        from hydromodpy.display.legend_placement import place_legend

        matplotlib.use("Agg")
        assert place_legend(Figure().subplots()) is None

    def test_an_explicit_location_is_never_overridden(self) -> None:
        from hydromodpy.display.legend_placement import LEGEND_PLACEMENT, place_legend

        ax = self._axes(LEGEND_PLACEMENT.best_placement_limit + 1)
        legend = place_legend(ax, loc="lower left")
        assert legend is not None
        assert legend._loc == 3  # matplotlib's code for "lower left"


# --------------------------------------------------------------------------- #
# what a stage that measured no distance gets asked for
# --------------------------------------------------------------------------- #


def _storage_stage_run() -> SimpleNamespace:
    """The second stage of a staged calibration: a cost per trial, nothing else.

    It promotes a run of its own, so the figures listed for the whole file are
    asked to draw it, and the network diagnostics the first stage published are
    absent from its session.
    """
    rows = [
        {
            "iteration": index,
            "parameters": {"Sy": {"value": value}},
            "objective_value": 0.2 + 0.01 * index,
            "status": "completed",
        }
        for index, value in enumerate((0.05, 0.08))
    ]
    return SimpleNamespace(
        sim_id="sim-storage",
        name="storage-stage",
        solver="modflow6",
        has_table=lambda _name: True,
        has_field=lambda _name: True,
        calibration_iterations=pd.DataFrame(rows),
    )


def _available_run(diagnostics: list[dict[str, float]]) -> SimpleNamespace:
    run = _session_run([1e-4, 1e-3], diagnostics)
    run.solver = "modflow6"
    run.has_table = lambda _name: True
    run.has_field = lambda _name: True
    return run


@pytest.mark.parametrize(
    ("figure", "diagnostic"),
    [
        (BisectionBracketTraceFigure(), "J_signed"),
        (DownslopeDistanceCrossingFigure(), "D_so"),
    ],
)
def test_a_stage_without_the_diagnostic_reports_itself_unavailable(figure, diagnostic) -> None:
    # Raising here instead cost a converged stage its promoted run: the display
    # step could only read a render failure, and on_error = "raise" propagated it.
    reason = figure.unavailable_reason(_storage_stage_run())

    assert reason is not None
    assert diagnostic in reason


@pytest.mark.parametrize(
    ("figure", "diagnostics"),
    [
        (
            BisectionBracketTraceFigure(),
            [
                {"D_so": 100.0, "D_os": 300.0, "J_signed": -200.0},
                {"D_so": 300.0, "D_os": 100.0, "J_signed": 200.0},
            ],
        ),
        (
            DownslopeDistanceCrossingFigure(),
            [{"D_so": 100.0, "D_os": 300.0}, {"D_so": 300.0, "D_os": 100.0}],
        ),
    ],
)
def test_the_stage_that_published_them_stays_available(figure, diagnostics) -> None:
    assert figure.unavailable_reason(_available_run(diagnostics)) is None
