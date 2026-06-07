"""Tests for animation builders that create user-facing files."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.display.animation import build_gif, build_mp4, build_plotly_slider


def _write_png(path: Path, color: tuple[int, int, int]) -> None:
    image = pytest.importorskip("PIL.Image")
    image.new("RGB", (4, 3), color).save(path)


def test_build_gif_returns_none_for_empty_frame_list(tmp_path) -> None:
    out = tmp_path / "empty.gif"

    assert build_gif(frame_paths=[], gif_path=out) is None
    assert not out.exists()


def test_build_gif_writes_all_frames_and_duration(tmp_path) -> None:
    image = pytest.importorskip("PIL.Image")
    frame_a = tmp_path / "frame_a.png"
    frame_b = tmp_path / "frame_b.png"
    _write_png(frame_a, (255, 0, 0))
    _write_png(frame_b, (0, 0, 255))
    out = tmp_path / "movie.gif"

    result = build_gif(frame_paths=[frame_a, frame_b], gif_path=out, duration_ms=123)

    assert result == out
    assert out.exists()
    with image.open(out) as gif:
        assert gif.n_frames == 2
        assert abs(gif.info["duration"] - 123) <= 10


def test_build_mp4_returns_none_for_empty_frame_list(tmp_path) -> None:
    out = tmp_path / "empty.mp4"

    assert build_mp4(frame_paths=[], mp4_path=out) is None
    assert not out.exists()


def test_build_plotly_slider_writes_embedded_frame_html(tmp_path) -> None:
    pytest.importorskip("plotly.graph_objects")
    frame_a = tmp_path / "frame_a.png"
    frame_b = tmp_path / "frame_b.png"
    _write_png(frame_a, (10, 20, 30))
    _write_png(frame_b, (40, 50, 60))
    out = tmp_path / "nested" / "slider.html"

    result = build_plotly_slider(
        frame_paths=[frame_a, frame_b],
        html_path=out,
        show_in_browser=False,
        title="Observed heads",
    )

    html = out.read_text(encoding="utf-8")
    assert result == out
    assert "Observed heads" in html
    assert html.count("data:image/png;base64") >= 2
