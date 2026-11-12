"""The three figures that read the downslope stream-network criterion.

The two curves are driven exactly as a session drives them: one row per trial,
the sampled parameter nested under ``parameters`` and the criterion diagnostics
nested under ``components``, prefixed with the name of the output that emitted
them.

The confusion map is driven by a run alone, as a ``[display].figures`` entry
drives it, over the grid of :mod:`tests.unit.display._network_comparison_run`
whose partition is known before the criterion is ever called.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import numpy as np
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
from hydromodpy.results.derive.stream_network.comparison import (
    AGREEMENT_EXCESS,
    AGREEMENT_MISSING,
    AGREEMENT_NEITHER,
    AGREEMENT_VALID,
    agreement_label,
)
from hydromodpy.results.session.view import Session

from ._calibration_journal import (
    K_BOUNDS,
    TWO_ROOT_CONFIG,
    TWO_ROOTS,
    journal_session,
    two_root_rows,
)
from ._network_comparison_run import (
    AXIS_COLUMN,
    cell,
    column_cells,
    comparison_run,
    drawn_cells,
    legend_note,
)

H_OBS = 250.0


def _session_run(
    project: Path,
    parameter_values: list[float],
    diagnostics: list[dict[str, float | None]],
    *,
    name: str = "cheze-bisection",
    output: str = "streams",
    parameter: str = "K_over_R",
    block: dict | None = None,
    other_output: bool = False,
) -> Session:
    """One calibration session, in the shape a journal writes.

    ``block`` adds keys to the block of the sampled parameter and
    ``other_output`` adds the same two distances under a second output.
    """
    rows = []
    for index, (value, diagnostic) in enumerate(zip(parameter_values, diagnostics, strict=True)):
        payload = {
            f"{output}.{key}": number for key, number in diagnostic.items() if number is not None
        }
        payload[f"{output}.h_obs"] = H_OBS
        if other_output:
            payload.update({"other.D_so": 1.0, "other.D_os": 2.0})
        rows.append(
            {
                "trial": index + 1,
                "parameters": {parameter: {"value": value, **(block or {})}},
                "components": payload,
                "status": "completed" if diagnostic.get("D_os") is not None else "failed",
            }
        )
    return journal_session(project / uuid.uuid4().hex, rows, name=name)


def _crossing_run(project: Path, **kwargs) -> Session:
    """Two straight lines meeting once, at a value the test can predict."""
    return _session_run(
        project,
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


def test_crossing_marks_the_intersection_with_its_parameter_value(mpl, tmp_path) -> None:
    # The residual goes -200 m to +200 m over one decade, so the zero sits at
    # the middle of that decade in log space.
    fig, ax = mpl.subplots()

    DownslopeDistanceCrossingFigure().render(_crossing_run(tmp_path), ax)

    try:
        marker = _line(ax, "crossing")
        assert marker.get_xdata()[0] == pytest.approx(10.0**-3.5)
        annotation = ax.texts[0].get_text()
        assert "K_over_R" in annotation
        assert f"{10.0**-3.5:.4g}" in annotation
    finally:
        mpl.close(fig)


def test_crossing_bands_are_one_reference_length_either_side(mpl, tmp_path) -> None:
    fig, ax = mpl.subplots()

    DownslopeDistanceCrossingFigure().render(_crossing_run(tmp_path), ax)

    try:
        assert len(ax.collections) == 2, "one band per curve"
        labels = [text.get_text() for text in ax.get_legend().get_texts()]
        assert f"one reference length either side ({H_OBS:.0f} m)" in labels
        extents = [collection.get_datalim(ax.transData) for collection in ax.collections]
        # The D_so band spans 100 - 250 clipped at zero, up to 300 + 250.
        assert min(extent.y0 for extent in extents) == pytest.approx(0.0)
        assert max(extent.y1 for extent in extents) == pytest.approx(300.0 + H_OBS)
    finally:
        mpl.close(fig)


def test_crossing_reports_a_range_that_never_changes_sign(mpl, tmp_path) -> None:
    run = _session_run(
        tmp_path,
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


def test_crossing_refuses_a_non_positive_parameter(mpl, tmp_path) -> None:
    run = _session_run(
        tmp_path,
        [0.0, 1e-3],
        [{"D_so": 100.0, "D_os": 300.0}, {"D_so": 300.0, "D_os": 100.0}],
    )
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="non-positive"):
            DownslopeDistanceCrossingFigure().render(run, ax)
    finally:
        mpl.close(fig)


def test_crossing_names_the_output_when_two_publish_the_same_diagnostic(mpl, tmp_path) -> None:
    run = _crossing_run(tmp_path, other_output=True)
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="several outputs publish"):
            DownslopeDistanceCrossingFigure().render(run, ax)
        DownslopeDistanceCrossingFigure().render(run, ax, output="streams")
        assert _line(ax, "D_so").get_ydata().tolist() == [100.0, 300.0]
        assert ax.get_xlabel() == "K_over_R (-)"
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


def test_confusion_map_gives_every_class_its_own_color(mpl) -> None:
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


def test_confusion_map_follows_the_seepage_threshold_it_is_asked_for(mpl) -> None:
    fig, ax = mpl.subplots()

    # A threshold far above what any cell releases leaves no simulated stream,
    # so the whole mapped column is missing and nothing is valid or excess.
    SeepageNetworkConfusionMap().render(_partition_run(), ax, tau_specific_ratio=1.0e6)

    try:
        assert _class_cells(ax, AGREEMENT_MISSING) == column_cells(AXIS_COLUMN)
        assert _class_cells(ax, AGREEMENT_VALID) == []
        assert _class_cells(ax, AGREEMENT_EXCESS) == []
        assert "above 1e+06 times its recharge" in legend_note(ax)
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


def test_an_unknown_frame_is_refused(mpl) -> None:
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="extent must be"):
            SeepageNetworkConfusionMap().render(_partition_run(), ax, extent="everything")
    finally:
        mpl.close(fig)


def test_confusion_map_names_what_it_needs_when_the_run_kept_no_release_flux() -> None:
    reason = SeepageNetworkConfusionMap().unavailable_reason(comparison_run(with_release=False))

    assert reason is not None
    assert "release_flux" in reason


# --------------------------------------------------------------------------- #
# bisection_bracket_trace
# --------------------------------------------------------------------------- #


def _bracket_run(project: Path, **kwargs) -> Session:
    """A sweep that changes sign once, then two bisection steps closing on it."""
    return _session_run(
        project,
        [1e-5, 1e-3, 1e-4, 3.2e-5],
        [
            {"D_so": 0.0, "D_os": 0.0, "J_signed": 300.0},
            {"D_so": 0.0, "D_os": 0.0, "J_signed": -400.0},
            {"D_so": 0.0, "D_os": 0.0, "J_signed": -120.0},
            {"D_so": 0.0, "D_os": 0.0, "J_signed": 40.0},
        ],
        **kwargs,
    )


def test_bracket_trace_closes_the_band_onto_zero(mpl, tmp_path) -> None:
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


def test_bracket_trace_names_the_closed_bracket(mpl, tmp_path) -> None:
    fig, ax = mpl.subplots()

    BisectionBracketTraceFigure().render(_bracket_run(tmp_path), ax)

    try:
        note = ax.texts[0].get_text()
        assert "K_over_R in [3.2e-05, 0.0001]" in note
        assert "factor" in note
    finally:
        mpl.close(fig)


def test_bracket_trace_names_the_failure_when_no_sign_change(mpl, tmp_path) -> None:
    run = _session_run(
        tmp_path,
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


def test_bracket_trace_keeps_a_failed_evaluation_on_the_zero_line(mpl, tmp_path) -> None:
    run = _session_run(
        tmp_path,
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


def _two_root_run(tmp_path):
    return journal_session(
        tmp_path,
        two_root_rows(),
        method="bisection",
        phase="transient_conductivity",
        config=TWO_ROOT_CONFIG,
        bounds=K_BOUNDS,
        best_trial=24,
        root_search=TWO_ROOTS,
    )


def test_bracket_trace_is_available_on_a_search_over_two_bounds(tmp_path) -> None:
    # Two bounds publish J_signed_minimal and J_signed_maximal, never J_signed.
    assert BisectionBracketTraceFigure().unavailable_reason(_two_root_run(tmp_path)) is None


def test_bracket_trace_draws_both_residuals_both_brackets_and_each_root(mpl, tmp_path) -> None:
    from ._calibration_journal import TWO_ROOT_J

    fig, ax = mpl.subplots()

    BisectionBracketTraceFigure().render(_two_root_run(tmp_path), ax)

    try:
        for bound in ("minimal", "maximal"):
            series = next(
                collection
                for collection in ax.collections
                if collection.get_label() == f"D_so - D_os, {bound} bound"
            )
            assert np.asarray(series.get_offsets())[:, 1].tolist() == pytest.approx(
                TWO_ROOT_J[bound]
            )
            assert any(
                collection.get_label() == f"bracket {bound}" for collection in ax.collections
            )
        rings = {
            str(collection.get_label()): np.asarray(collection.get_offsets())[0]
            for collection in ax.collections
            if str(collection.get_label()).startswith("K*_")
        }
        # Each root is ringed at the evaluation that closed it: trials 15 and 23.
        assert rings["K*_minimal = 2.564e-05"][0] == pytest.approx(15 - 0.12)
        assert rings["K*_maximal = 1.358e-06"][0] == pytest.approx(23 + 0.12)
        returned = next(line for line in ax.lines if str(line.get_label()).startswith("returned"))
        assert returned.get_xdata()[0] == pytest.approx(24.0)
        note = ax.texts[0].get_text()
        assert "K*_minimal = 2.564e-05, bracket [2.548e-05, 2.564e-05]" in note
        assert "K*_maximal = 1.358e-06, bracket [1.358e-06, 1.366e-06]" in note
        assert "Delta = log10(K*_maximal / K*_minimal) = -1.28 decade(s)" in note
        assert "returned K = 5.9e-06" in note
    finally:
        mpl.close(fig)


def test_crossing_labels_the_parameter_with_the_unit_the_session_declared(mpl, tmp_path) -> None:
    run = _crossing_run(tmp_path, parameter="K", block={"units": "m/s"})
    fig, ax = mpl.subplots()

    DownslopeDistanceCrossingFigure().render(run, ax)

    try:
        assert ax.get_xlabel() == "K (m/s)"
        assert ax.get_ylabel() == "Downslope distance (m)"
    finally:
        mpl.close(fig)


class TestTheHeavyRebuildIsShared:
    """Six figures of one gallery ask for the same comparison. It is built once.

    On the Nancon at 25 m the rebuild floods 345 260 cells and runs two full
    distance passes. Doing that once per figure is the reason a gallery took
    longer to draw than the solve took to run.
    """

    def test_two_calls_on_one_run_return_the_same_object(self) -> None:
        from hydromodpy.results.derive.run_memo import RunMemo

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
        from hydromodpy.results.derive.run_memo import RunMemo

        memo = RunMemo()

        class _Run:
            pass

        run = _Run()
        first = memo.get_or_build(run, ("a",), object)
        second = memo.get_or_build(run, ("b",), object)

        assert first is not second


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

    def test_a_dense_axes_gets_a_pinned_legend(self) -> None:
        from hydromodpy.display.style import LEGEND_BEST_PLACEMENT_LIMIT, place_legend

        ax = self._axes(LEGEND_BEST_PLACEMENT_LIMIT + 1)
        legend = place_legend(ax)
        assert legend is not None
        assert legend._loc != 0

    def test_an_explicit_location_is_never_overridden(self) -> None:
        from hydromodpy.display.style import LEGEND_BEST_PLACEMENT_LIMIT, place_legend

        ax = self._axes(LEGEND_BEST_PLACEMENT_LIMIT + 1)
        legend = place_legend(ax, loc="lower left")
        assert legend is not None
        assert legend._loc == 3  # matplotlib's code for "lower left"


# --------------------------------------------------------------------------- #
# what a stage that measured no distance gets asked for
# --------------------------------------------------------------------------- #


def _storage_stage_run(project: Path) -> Session:
    """The second stage of a staged calibration: a cost per trial, nothing else.

    It promotes a run of its own, so the figures listed for the whole file are
    asked to draw it, and the network diagnostics the first stage published are
    absent from its session.
    """
    rows = [
        {
            "trial": index,
            "parameters": {"Sy": {"value": value}},
            "cost": 0.2 + 0.01 * index,
            "status": "completed",
        }
        for index, value in enumerate((0.05, 0.08), start=1)
    ]
    return journal_session(project, rows, name="storage-stage")


def _available_run(project: Path, diagnostics: list[dict[str, float]]) -> Session:
    return _session_run(project, [1e-4, 1e-3], diagnostics)


@pytest.mark.parametrize(
    ("figure", "diagnostic"),
    [
        (BisectionBracketTraceFigure(), "J_signed"),
        (DownslopeDistanceCrossingFigure(), "D_so"),
    ],
)
def test_a_stage_without_the_diagnostic_reports_itself_unavailable(
    figure, diagnostic, tmp_path
) -> None:
    # Raising here instead cost a converged stage its promoted run: the display
    # step could only read a render failure, and on_error = "raise" propagated it.
    reason = figure.unavailable_reason(_storage_stage_run(tmp_path))

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
def test_the_stage_that_published_them_stays_available(figure, diagnostics, tmp_path) -> None:
    assert figure.unavailable_reason(_available_run(tmp_path, diagnostics)) is None
