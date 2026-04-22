"""Animation builders that stitch pre-rendered PNG frames together.

Three optional backends:

- :func:`build_gif` (PIL) — always available with the base install.
- :func:`build_mp4` (imageio + ffmpeg) — silently skipped when missing.
- :func:`build_plotly_slider` (plotly) — silently skipped when missing.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def build_gif(
    *,
    frame_paths: list[Path],
    gif_path: Path,
    duration_ms: int = 200,
) -> Path | None:
    """Assemble PNG frames into an animated GIF."""
    from PIL import Image

    if not frame_paths:
        return None
    images = [Image.open(p) for p in frame_paths]
    try:
        images[0].save(
            gif_path,
            save_all=True,
            append_images=images[1:],
            duration=duration_ms,
            loop=0,
        )
    finally:
        for img in images:
            img.close()
    return gif_path


def build_mp4(
    *,
    frame_paths: list[Path],
    mp4_path: Path,
    fps: int = 10,
) -> Path | None:
    """Assemble PNG frames into an MP4 (requires imageio/ffmpeg)."""
    if not frame_paths:
        return None
    try:
        import imageio.v2 as imageio
    except ModuleNotFoundError:
        logger.warning("Skipping MP4: optional dependency 'imageio' not installed.")
        return None
    try:
        with imageio.get_writer(
            mp4_path,
            fps=max(1, int(fps)),
            codec="libx264",
            macro_block_size=1,
        ) as writer:
            for path in frame_paths:
                writer.append_data(imageio.imread(path))
    except Exception as exc:
        logger.warning("Skipping MP4: imageio/ffmpeg backend unavailable: %s", exc)
        return None
    return mp4_path


def build_plotly_slider(
    *,
    frame_paths: list[Path],
    html_path: Path | None = None,
    show_in_browser: bool = True,
    title: str = "Animation frames",
) -> Path | None:
    """Build an HTML image-slider (requires plotly)."""
    if not frame_paths:
        return None
    try:
        import plotly.graph_objects as go
    except ModuleNotFoundError:
        logger.warning("Skipping HTML slider: optional dependency 'plotly' not installed.")
        return None

    def _b64(path: Path) -> str:
        return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("utf-8")

    sources = [_b64(p) for p in frame_paths]
    base = dict(
        source=sources[0],
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
        sizex=1,
        sizey=1,
        xanchor="center",
        yanchor="middle",
        sizing="contain",
    )
    frames = [
        go.Frame(name=str(i), layout=go.Layout(images=[dict(base, source=s)]))
        for i, s in enumerate(sources)
    ]
    fig = go.Figure(
        layout=go.Layout(
            title=title,
            images=[base],
            sliders=[
                {
                    "steps": [
                        {
                            "method": "animate",
                            "args": [
                                [str(k)],
                                {"mode": "immediate", "frame": {"duration": 0, "redraw": True}},
                            ],
                            "label": f"{k + 1}",
                        }
                        for k in range(len(sources))
                    ],
                    "x": 0.5,
                    "xanchor": "center",
                    "y": -0.01,
                    "yanchor": "top",
                    "len": 0.85,
                    "pad": {"t": 40},
                }
            ],
        ),
        frames=frames,
    )
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    if html_path is not None:
        html_path.parent.mkdir(parents=True, exist_ok=True)
        fig.write_html(html_path)
    if show_in_browser:
        fig.show("browser")
    return html_path
