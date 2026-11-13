"""Draw requests at the end of a run, the report and its summary, the sealed ``[display]``."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from hydromodpy.core.console.progress import MILESTONE_KEY
from hydromodpy.display import runs
from hydromodpy.display.config import DisplayConfig


@pytest.mark.parametrize(
    ("snapshot", "expected"),
    [
        (None, None),
        ({"other": 1}, None),
        ({"display": {}}, {}),
        ({"display": {"dpi": 300}}, {}),
        ({"display": {"dpi": 90}}, {"dpi": 90}),
        ({"display": {"theme": "dark"}}, {"theme": "dark"}),
    ],
)
def test_sealed_display_values(snapshot, expected):
    written = runs.sealed_display_values(snapshot)
    if written is not None:
        DisplayConfig.model_validate(written)
    assert written == expected


def test_summary_inapplicable(hmp_log_records, tmp_path):
    # A figure inapplicable by nature is not something the user can fix: one milestone
    # line counts them, and the next line, at INFO, names each with its reason.
    report = runs.FigureRenderReport(
        requested=("na_calibration", "head"),
        rendered=("head",),
        skipped=(runs.SkippedFigure(name="na_calibration", reason="stub is not applicable"),),
    )
    runs.log_render_summary(report, destination=tmp_path)

    records = [r for r in hmp_log_records if "runs" in r.name and r.levelno >= logging.INFO]
    assert [r.levelname for r in records] == ["INFO", "INFO"]
    assert getattr(records[0], MILESTONE_KEY, False) is True
    assert records[0].getMessage().endswith("; 1 not applicable to this run")
    assert getattr(records[1], MILESTONE_KEY, False) is False
    assert "na_calibration (stub is not applicable)" in records[1].getMessage()


def test_summary_actionable(hmp_log_records, tmp_path):
    # WARNING so the line survives quiet mode: the user can act on it.
    report = runs.FigureRenderReport(
        requested=("a", "b"),
        skipped=(
            runs.SkippedFigure(name="a", reason="no calibration"),
            runs.SkippedFigure(name="b", reason="render failed: boom", actionable=True),
        ),
    )
    runs.log_render_summary(report, destination=tmp_path)

    records = [r for r in hmp_log_records if "figure(s)" in r.getMessage()]
    assert [r.levelname for r in records] == ["WARNING"]
    assert "a (no calibration)" in records[0].getMessage()
    assert "b (render failed: boom)" in records[0].getMessage()


def test_no_summary_when_empty(tmp_path, hmp_log_records):
    runs.log_render_summary(runs.FigureRenderReport(), destination=tmp_path)

    assert [r for r in hmp_log_records if "figure(s)" in r.getMessage()] == []


def test_merged_reports():
    first = runs.FigureRenderReport(requested=("a",), rendered=("a",))
    second = runs.FigureRenderReport(
        requested=("b",),
        skipped=(runs.SkippedFigure(name="b", reason="no calibration"),),
    )

    merged = first.merged_with(second)

    assert merged.summary() == "Rendered 1/2 figure(s); 1 skipped: b (no calibration)"


def _requests(*fields: dict) -> list:
    from hydromodpy.display.request import FigureRequest

    return [FigureRequest(**field) for field in fields]


def _draw_requests(run, requests, directory: Path, **options):
    from hydromodpy.display.presets import PRESETS
    from hydromodpy.display.theme import get_theme

    return runs.draw_requests(
        run, requests, presets=PRESETS, theme=get_theme("default"), output_dir=directory, **options
    )


def test_draw_requests_names_what_it_drew_and_what_it_skipped(stored_run, tmp_path):
    requests = _requests(
        {"variable": "head", "name": "a"},
        {"variable": "head", "name": "b", "when": "session"},
        {"variable": "discharge", "name": "c", "station": "nope"},
    )

    report = _draw_requests(stored_run, requests, tmp_path)

    assert report.requested == ("a", "c")
    assert report.rendered == ("a",)
    assert [p.name for p in report.written] == ["a.png"]
    assert [(item.name, item.actionable) for item in report.skipped] == [("c", False)]


def test_draw_requests_follows_on_error(stored_run, tmp_path, monkeypatch):
    def broken(*_args, **_keywords):
        raise RuntimeError("boom")

    monkeypatch.setattr(runs, "render", broken)
    requests = _requests({"variable": "head", "name": "a"})

    report = _draw_requests(stored_run, requests, tmp_path)

    assert report.skipped[0].actionable and "boom" in report.skipped[0].reason
    with pytest.raises(RuntimeError, match="boom"):
        _draw_requests(stored_run, requests, tmp_path, on_error="raise")
