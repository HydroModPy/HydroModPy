"""Curves of the two downslope distances (m) against a calibrated parameter, and where they cross.

The curves are driven as a calibration session drives them: one row per trial,
the sampled parameter nested under ``parameters`` and the criterion diagnostics
nested under ``components``, prefixed with the name of the output that emitted
them. The reference length ``h_obs`` is 250 m.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from hydromodpy.display.figures.downslope_distance_crossing import DownslopeDistanceCrossingFigure
from hydromodpy.results.session.view import Session

from ._calibration_journal import journal_session

H_OBS = 250.0
RISING = {"D_so": 100.0, "D_os": 300.0}
FALLING = {"D_so": 300.0, "D_os": 100.0}


def session_run(
    project: Path,
    parameter_values: list[float],
    diagnostics: list[dict[str, float]],
    *,
    output: str = "streams",
    parameter: str = "K_over_R",
    block: dict | None = None,
    other_output: bool = False,
) -> Session:
    """One calibration session in the shape a journal writes.

    ``block`` adds keys to the block of the sampled parameter. ``other_output``
    adds the same two distances under a second output.
    """
    rows = []
    for index, (value, diagnostic) in enumerate(zip(parameter_values, diagnostics, strict=True)):
        payload = {f"{output}.{key}": number for key, number in diagnostic.items()}
        payload[f"{output}.h_obs"] = H_OBS
        if other_output:
            payload.update({"other.D_so": 1.0, "other.D_os": 2.0})
        rows.append(
            {
                "trial": index + 1,
                "parameters": {parameter: {"value": value, **(block or {})}},
                "components": payload,
                "status": "completed",
            }
        )
    return journal_session(project / uuid.uuid4().hex, rows, name="cheze-bisection")


def crossing_run(project: Path, **kwargs) -> Session:
    """Two straight lines meeting once, between 1e-4 and 1e-3."""
    return session_run(project, [1e-4, 1e-3], [RISING, FALLING], **kwargs)


def line(ax, label_prefix: str):
    return next(item for item in ax.lines if str(item.get_label()).startswith(label_prefix))


def test_crossing_is_marked_at_its_parameter_value(mpl, tmp_path) -> None:
    # The residual goes -200 m to +200 m over one decade, so the zero sits at
    # the middle of that decade in log space.
    _, ax = mpl.subplots()

    DownslopeDistanceCrossingFigure().render(crossing_run(tmp_path), ax)

    assert line(ax, "crossing").get_xdata()[0] == pytest.approx(10.0**-3.5)
    annotation = ax.texts[0].get_text()
    assert "K_over_R" in annotation
    assert f"{10.0**-3.5:.4g}" in annotation


def test_bands_are_one_reference_length_either_side(mpl, tmp_path) -> None:
    _, ax = mpl.subplots()

    DownslopeDistanceCrossingFigure().render(crossing_run(tmp_path), ax)

    assert len(ax.collections) == 2, "one band per curve"
    labels = [text.get_text() for text in ax.get_legend().get_texts()]
    assert f"one reference length either side ({H_OBS:.0f} m)" in labels
    extents = [collection.get_datalim(ax.transData) for collection in ax.collections]
    # The D_so band spans 100 - 250 clipped at zero, up to 300 + 250.
    assert min(extent.y0 for extent in extents) == pytest.approx(0.0)
    assert max(extent.y1 for extent in extents) == pytest.approx(300.0 + H_OBS)


def test_range_that_never_changes_sign(mpl, tmp_path) -> None:
    run = session_run(
        tmp_path,
        [1e-4, 1e-3],
        [{"D_so": 300.0, "D_os": 100.0}, {"D_so": 400.0, "D_os": 100.0}],
    )
    _, ax = mpl.subplots()

    DownslopeDistanceCrossingFigure().render(run, ax)

    assert not [item for item in ax.lines if str(item.get_label()).startswith("crossing")]
    assert "no sign change" in ax.texts[0].get_text()


def test_output_is_named_when_two_publish_the_same_diagnostic(mpl, tmp_path) -> None:
    run = crossing_run(tmp_path, other_output=True)
    _, ax = mpl.subplots()

    with pytest.raises(ValueError, match="several outputs publish"):
        DownslopeDistanceCrossingFigure().render(run, ax)
    DownslopeDistanceCrossingFigure().render(run, ax, output="streams")

    assert line(ax, "D_so").get_ydata().tolist() == [100.0, 300.0]
    assert ax.get_xlabel() == "K_over_R (-)"
    assert line(ax, "crossing").get_xdata()[0] == pytest.approx(10.0**-3.5)


def test_axis_labels_carry_the_declared_unit(mpl, tmp_path) -> None:
    run = crossing_run(tmp_path, parameter="K", block={"units": "m/s"})
    _, ax = mpl.subplots()

    DownslopeDistanceCrossingFigure().render(run, ax)

    assert ax.get_xlabel() == "K (m/s)"
    assert ax.get_ylabel() == "Downslope distance (m)"


def test_non_positive_parameter_is_refused(mpl, tmp_path) -> None:
    run = session_run(tmp_path, [0.0, 1e-3], [RISING, FALLING])
    _, ax = mpl.subplots()

    with pytest.raises(ValueError, match="non-positive"):
        DownslopeDistanceCrossingFigure().render(run, ax)


def test_stage_without_the_diagnostic_is_unavailable(tmp_path) -> None:
    # The second stage of a staged calibration publishes a cost per trial and
    # no network diagnostic. Raising instead cost a converged stage its run.
    rows = [
        {
            "trial": i,
            "parameters": {"Sy": {"value": v}},
            "cost": 0.2 + 0.01 * i,
            "status": "completed",
        }
        for i, v in enumerate((0.05, 0.08), start=1)
    ]
    stage = journal_session(tmp_path, rows, name="storage-stage")

    reason = DownslopeDistanceCrossingFigure().unavailable_reason(stage)

    assert reason is not None
    assert "D_so" in reason


def test_stage_that_published_the_diagnostic_is_available(tmp_path) -> None:
    assert DownslopeDistanceCrossingFigure().unavailable_reason(crossing_run(tmp_path)) is None
