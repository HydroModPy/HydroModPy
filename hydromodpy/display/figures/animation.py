"""GIF and Plotly HTML animation builders (non-ultraplot)."""
from __future__ import annotations

import base64
from pathlib import Path

from hydromodpy.support.tools import get_logger

logger = get_logger(__name__)


def build_gif(
    *,
    frame_paths: list[Path],
    gif_path: Path,
    duration_ms: int = 200,
) -> Path | None:
    """Assemble PNG frames into an animated GIF.

    Returns the written path, or *None* when *frame_paths* is empty.
    """
    from PIL import Image

    if not frame_paths:
        return None

    images = [Image.open(path) for path in frame_paths]
    try:
        images[0].save(
            gif_path,
            save_all=True,
            append_images=images[1:],
            duration=duration_ms,
            loop=0,
        )
    finally:
        for image in images:
            image.close()
    return gif_path


def build_plotly_slider(
    *,
    frame_paths: list[Path],
    html_path: Path | None = None,
    show_in_browser: bool = True,
    title: str = "Concentration frames",
) -> Path | None:
    """Build a Plotly image-slider animation from pre-rendered PNGs.

    Returns *html_path* when written, else *None*.
    """
    if not frame_paths:
        return None

    try:
        import plotly.graph_objects as go
    except ModuleNotFoundError:
        logger.warning(
            "Skipping web animation because optional dependency 'plotly' is not installed."
        )
        return None

    def _to_b64(path: Path) -> str:
        with path.open("rb") as fh:
            raw = fh.read()
        return "data:image/png;base64," + base64.b64encode(raw).decode("utf-8")

    image_sources = [_to_b64(p) for p in frame_paths]
    base_image = dict(
        source=image_sources[0],
        xref="paper", yref="paper",
        x=0.5, y=0.5,
        sizex=1, sizey=1,
        xanchor="center", yanchor="middle",
        sizing="contain",
    )

    frames = [
        go.Frame(
            name=str(i),
            layout=go.Layout(images=[dict(base_image, source=src)]),
        )
        for i, src in enumerate(image_sources)
    ]

    fig = go.Figure(
        layout=go.Layout(
            title=title,
            images=[base_image],
            updatemenus=[dict(
                type="buttons",
                showactive=False,
                y=1.05, x=1.15,
                xanchor="right", yanchor="top",
                buttons=[
                    dict(
                        label="Play",
                        method="animate",
                        args=[None, {"frame": {"duration": 500, "redraw": True}, "fromcurrent": True}],
                    ),
                    dict(
                        label="Pause",
                        method="animate",
                        args=[[None], {"frame": {"duration": 0, "redraw": False}, "mode": "immediate"}],
                    ),
                ],
            )],
            sliders=[{
                "steps": [
                    {
                        "method": "animate",
                        "args": [[str(k)], {"mode": "immediate", "frame": {"duration": 0, "redraw": True}}],
                        "label": f"{k + 1}",
                    }
                    for k in range(len(image_sources))
                ],
                "transition": {"duration": 0},
                "x": 0.5, "xanchor": "center",
                "y": -0.01, "yanchor": "top",
                "len": 0.85, "pad": {"t": 40},
            }],
        ),
        frames=frames,
    )

    fig.update_layout(width=1600, height=900, margin=dict(l=60, r=60, t=60, b=90))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)

    if html_path is not None:
        html_path.parent.mkdir(parents=True, exist_ok=True)
        fig.write_html(html_path)

    if show_in_browser:
        fig.show("browser")

    return html_path
