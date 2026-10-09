"""Draw the figures of the platform guides, light and dark, from finished runs.

Three figures, each from runs the guide itself makes:

- ``sweep``: the seepage area and the gauge scores of the K sweep of
  ``guides/sweep-a-parameter`` (runs ``sweep_k_<K>`` written by
  ``docs/source/guides/recipes/sweep_k.py`` in the folder of example 04);
- ``piezometers``: the table ``share/piezometers.csv`` that
  ``docs/source/guides/recipes/read_piezometers.py`` writes for
  ``guides/read-piezometers``;
- ``ardennes``: the water-table depth map of the run ``ardennes_steady`` of
  ``guides/outside-france``, which needs a DEM the user supplies
  (``data/dem/dem_ardennes_25831.tif``, not shipped).

Usage::

    python tools/docs/figures/render_platform_figures.py sweep \
        --project <workspace>/projects/04_streamflow_intermittence_in_transient
    python tools/docs/figures/render_platform_figures.py ardennes \
        --abroad <workspace>/projects/ardennes
"""

from __future__ import annotations

import argparse
import io
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from PIL import Image  # noqa: E402

import hydromodpy as hmp  # noqa: E402
from hydromodpy.display.style import apply_theme  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "docs" / "source" / "_static" / "figures" / "guides"
MAX_BYTES = 150 * 1024
SWEEP_K = (1e-5, 2e-5, 5e-5, 1e-4, 2e-4)


def save(fig, out: Path, name: str, dark: bool, width: int = 1200) -> None:
    """Write the figure as WebP under 150 KB, lowering the quality if needed."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    image = Image.open(buf).convert("RGB")
    height = round(image.size[1] * width / image.size[0])
    image = image.resize((width, height), Image.LANCZOS)
    quality = 80
    while True:
        data = io.BytesIO()
        image.save(data, format="WEBP", quality=quality, method=6)
        if data.tell() <= MAX_BYTES or quality <= 40:
            break
        quality -= 5
    path = out / f"{name}{'-dark' if dark else ''}.webp"
    path.write_bytes(data.getvalue())
    print(path.name, image.size, data.tell(), "quality", quality)


def sweep(project: Path, out: Path, dark: bool) -> None:
    cat = hmp.open(project)
    runs = [cat[f"sweep_k_{k:.0e}"] for k in SWEEP_K]
    months = runs[0].periods.edges[:-1]
    in_catchment = runs[0].catchment_mask.ravel()
    cell_km2 = runs[0].grid.cell_size ** 2 / 1e6
    areas, rows = {}, []
    for run in runs:
        seepage = hmp.read(run, "seepage_mask").to_numpy() > 0
        areas[run.params["K"]] = (seepage & in_catchment).sum(axis=1) * cell_km2
        scores = run.metrics.query("station_id == 'NANCON'").set_index("metric_name")["value"]
        rows.append({"K": run.params["K"], "NSE": scores["nse"], "log NSE": scores["log_nse"]})
    table = pd.DataFrame(rows).set_index("K")
    apply_theme("dark" if dark else "default")
    fig, (left, right) = plt.subplots(
        1, 2, figsize=(11, 4.2), width_ratios=[1.8, 1], constrained_layout=True
    )
    colors = plt.get_cmap("viridis")(
        np.linspace(0.15 if dark else 0, 1 if dark else 0.9, len(runs))
    )
    for (k, area), color in zip(areas.items(), colors, strict=True):
        left.plot(months, area, color=color, label=f"K = {k:.0e} m/s")
    left.set_yscale("log")
    left.set_ylabel("seepage area (km2)")
    left.legend(fontsize="small")
    right.plot(table.index, table["NSE"], "o-", label="NSE")
    right.plot(table.index, table["log NSE"], "s--", label="NSE on log Q")
    right.set_xscale("log")
    right.set_xlabel("K (m/s)")
    right.set_ylabel("score of the flow at the gauge")
    right.legend()
    save(fig, out, "sweep_k", dark)


def piezometers(project: Path, out: Path, dark: bool) -> None:
    wide = pd.read_csv(project / "share" / "piezometers.csv", index_col="time", parse_dates=True)
    apply_theme("dark" if dark else "default")
    fig, ax = plt.subplots(figsize=(8, 3.8), constrained_layout=True)
    for column in wide.columns:
        ax.plot(wide.index, wide[column], label=column)
    ax.invert_yaxis()
    ax.set_ylabel("depth of the water table (m)")
    ax.legend(ncol=4, fontsize="small")
    save(fig, out, "read_piezometers", dark, width=1000)


def ardennes(abroad: Path, out: Path, dark: bool) -> None:
    from hydromodpy.display.runs import (
        figure_options_from_run,
        matplotlib_backend,
        render_figure,
    )

    run = hmp.open(abroad)["ardennes_steady"]
    options = dict(figure_options_from_run(run, "watertable_depth_map"))
    with matplotlib_backend(dpi=150):
        apply_theme("dark" if dark else "default")
        fig = render_figure("watertable_depth_map", run, **options)
        save(fig, out, "outside_france_watertable_depth_map", dark, width=1000)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("figure", choices=("sweep", "piezometers", "ardennes"))
    parser.add_argument("--project", type=Path, help="example 04 project with the runs")
    parser.add_argument("--abroad", type=Path, help="project holding the run ardennes_steady")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    source = args.abroad if args.figure == "ardennes" else args.project
    if source is None:
        parser.error(
            f"{args.figure} needs --{'abroad' if args.figure == 'ardennes' else 'project'}"
        )
    draw = {"sweep": sweep, "piezometers": piezometers, "ardennes": ardennes}[args.figure]
    for dark in (False, True):
        draw(source, args.out, dark)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
