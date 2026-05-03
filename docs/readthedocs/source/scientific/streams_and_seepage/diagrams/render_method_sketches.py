"""Render didactic stream/seepage method sketches for the documentation."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg", force=True)

from matplotlib import pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, Polygon, Rectangle  # noqa: E402


ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "_static" / "concepts" / "streams_and_seepage"

INK = "#10253d"
BLUE = "#1f77b4"
WATER = "#6bb8d6"
WATER_DARK = "#255d87"
GROUND = "#ddc99f"
BASE = "#b9c3bc"
LINE = "#6a5a3b"
GRID = "#dfe7f0"
MUTED = "#687890"
ORANGE = "#a06100"
YELLOW = "#ffd45c"


def _figure(title: str) -> tuple[plt.Figure, plt.Axes]:
    fig, ax = plt.subplots(figsize=(14.4, 8.1), dpi=100)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.text(
        0.03,
        0.935,
        title,
        fontsize=26,
        color=INK,
        weight="bold",
        va="top",
    )
    return fig, ax


def _box(ax: plt.Axes, x: float, y: float, text: str, width: float = 0.24) -> None:
    ax.text(
        x,
        y,
        text,
        fontsize=18,
        color=INK,
        va="top",
        ha="left",
        bbox={
            "boxstyle": "round,pad=0.35,rounding_size=0.08",
            "facecolor": "white",
            "edgecolor": MUTED,
            "linewidth": 2,
        },
        wrap=True,
    )


def _arrow(
    ax: plt.Axes,
    xy1: tuple[float, float],
    xy2: tuple[float, float],
    color: str = WATER_DARK,
    lw: float = 3.5,
) -> None:
    ax.add_patch(
        FancyArrowPatch(
            xy1,
            xy2,
            arrowstyle="-|>",
            mutation_scale=24,
            linewidth=lw,
            color=color,
            shrinkA=0,
            shrinkB=0,
        )
    )


def _ground(ax: plt.Axes) -> None:
    ax.add_patch(
        Polygon(
            [
                (0.03, 0.64),
                (0.27, 0.56),
                (0.38, 0.42),
                (0.52, 0.40),
                (0.70, 0.52),
                (0.88, 0.57),
                (0.88, 0.18),
                (0.03, 0.18),
            ],
            closed=True,
            facecolor=GROUND,
            edgecolor="none",
            alpha=0.82,
        )
    )
    ax.add_patch(
        Rectangle((0.03, 0.18), 0.85, 0.12, facecolor=BASE, edgecolor="none", alpha=0.72)
    )
    ax.plot(
        [0.03, 0.27, 0.38, 0.52, 0.70, 0.88],
        [0.64, 0.56, 0.42, 0.40, 0.52, 0.57],
        color=LINE,
        lw=4,
    )
    ax.text(0.055, 0.225, "low-permeability base", fontsize=18, color="#344052")


def _water_table(ax: plt.Axes) -> None:
    xs = [0.08, 0.22, 0.33, 0.46, 0.58, 0.78, 0.85]
    ys = [0.59, 0.55, 0.50, 0.42, 0.40, 0.405, 0.39]
    ax.plot(xs, ys, color=BLUE, lw=5)
    ax.text(0.09, 0.625, "solved water table", color=BLUE, fontsize=19, weight="bold")


def _save(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)


def render_stream_stage_boundary() -> None:
    fig, ax = _figure("Method 1 - Stream boundary")
    _box(ax, 0.07, 0.825, "input:\nstream support\n+ prescribed stage/head")
    _box(ax, 0.61, 0.825, "result:\nexchange flux\ncomputed by the solver")
    _ground(ax)
    _water_table(ax)

    ax.add_patch(
        Polygon(
            [(0.42, 0.43), (0.56, 0.43), (0.53, 0.35), (0.46, 0.36)],
            closed=True,
            facecolor=WATER,
            edgecolor=WATER_DARK,
            lw=3,
            alpha=0.92,
        )
    )
    ax.add_patch(Rectangle((0.42, 0.435), 0.165, 0.03, fill=False, edgecolor=BLUE, lw=2.5))
    ax.text(0.39, 0.335, "stream support\n(cells or edges)", fontsize=18, color=INK)

    _arrow(ax, (0.29, 0.51), (0.43, 0.43))
    ax.text(0.35, 0.475, "groundwater\nflow", fontsize=18, color=WATER_DARK, ha="center")
    _arrow(ax, (0.58, 0.60), (0.545, 0.455))
    ax.text(0.58, 0.595, "computed\nexchange flux", fontsize=18, color=WATER_DARK, ha="center")

    ax.text(
        0.06,
        0.08,
        "Concept: the stage/head is prescribed; the exchanged flux is not prescribed directly.",
        fontsize=20,
        color=INK,
    )
    _save(fig, OUT / "method_stream_stage_boundary.png")


def render_seepage_drainage_operator() -> None:
    fig, ax = _figure("Method 2 - Seepage / drainage")
    _box(ax, 0.07, 0.825, "input:\nrelease support\n+ conductance\n+ activation level")
    _box(ax, 0.63, 0.825, "result:\npositive outflow only\nwhere the head activates\nrelease")
    _ground(ax)
    _water_table(ax)

    ax.plot([0.33, 0.63], [0.445, 0.445], color=ORANGE, lw=2.5, ls="--")
    ax.text(0.635, 0.405, "activation level", fontsize=17, color=ORANGE)

    cells = [(0.36, 0.425, False), (0.43, 0.425, True), (0.50, 0.425, True), (0.57, 0.425, False)]
    for x, y, active in cells:
        edge = ORANGE if active else MUTED
        face = YELLOW if active else "#eef2f6"
        ax.add_patch(Rectangle((x, y), 0.035, 0.038, facecolor=face, edgecolor=edge, lw=2.2))
        if active:
            _arrow(ax, (x + 0.017, y + 0.038), (x + 0.017, y + 0.105), color=ORANGE, lw=3)
            ax.text(x + 0.002, y + 0.07, "outflow", fontsize=17, color=ORANGE)

    _arrow(ax, (0.29, 0.53), (0.425, 0.455))
    _arrow(ax, (0.76, 0.505), (0.61, 0.46))
    ax.text(0.35, 0.505, "groundwater\nflow", fontsize=18, color=WATER_DARK, ha="center")
    ax.text(0.70, 0.515, "groundwater\nflow", fontsize=18, color=WATER_DARK, ha="center")

    ax.text(
        0.06,
        0.08,
        "Concept: release is conditional. No outflow is produced where solved head stays below the activation level.",
        fontsize=20,
        color=INK,
    )
    _save(fig, OUT / "method_seepage_drainage_operator.png")


def render_simulated_active_postprocess() -> None:
    fig, ax = _figure("Method 3 - Simulated active network")
    ax.text(0.11, 0.785, "solver cells / mesh faces", fontsize=18, color=MUTED)

    x0, y0 = 0.11, 0.22
    width, height = 0.47, 0.54
    nx, ny = 9, 8
    for i in range(nx + 1):
        x = x0 + width * i / nx
        ax.plot([x, x], [y0, y0 + height], color=GRID, lw=1.4)
    for j in range(ny + 1):
        y = y0 + height * j / ny
        ax.plot([x0, x0 + width], [y, y], color=GRID, lw=1.4)
    ax.add_patch(Rectangle((x0, y0), width, height, fill=False, edgecolor="#9aaabd", lw=2))

    pts = [(0.185, 0.67), (0.245, 0.565), (0.315, 0.475), (0.39, 0.375), (0.47, 0.285)]
    for x, y in pts:
        ax.scatter([x], [y], s=340, facecolor=YELLOW, edgecolor=ORANGE, linewidth=2, zorder=3)
    for p1, p2 in zip(pts, pts[1:]):
        _arrow(ax, p1, p2, color=WATER_DARK, lw=5)
        ax.plot([p1[0], p2[0]], [p1[1], p2[1]], color=BLUE, lw=2, zorder=2)

    ax.text(0.12, 0.15, "local positive outflow sources", fontsize=18, color=ORANGE)
    _box(ax, 0.63, 0.825, "input field:\nlocal positive\noutflow_drain", width=0.2)
    _box(ax, 0.63, 0.60, "routing:\naccumulate downstream\non raster or mesh graph", width=0.26)
    _box(ax, 0.63, 0.34, "view layer:\nthreshold/time rule\n-> active mask", width=0.26)
    _arrow(ax, (0.56, 0.68), (0.615, 0.735))
    _arrow(ax, (0.55, 0.44), (0.615, 0.52))
    _arrow(ax, (0.51, 0.285), (0.615, 0.315))

    ax.text(
        0.06,
        0.07,
        "Concept: this is a diagnostic built after the solve, not an input boundary condition.",
        fontsize=20,
        color=INK,
    )
    _save(fig, OUT / "method_simulated_active_postprocess.png")


def main() -> None:
    render_stream_stage_boundary()
    render_seepage_drainage_operator()
    render_simulated_active_postprocess()


if __name__ == "__main__":
    main()
