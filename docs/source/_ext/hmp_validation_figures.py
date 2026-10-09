"""Figures of the Validation page that need a plotting library.

Three kinds, drawn with matplotlib (Agg) from the recorded results and saved
as WebP files in the build output, one light and one dark variant each:

* ``maps``: plan-view error of the 2D cases, one panel per solver.
* ``spacetime``: error over space and time of the transient 1D cases.
* ``samples``: the points a calibration method evaluated, against the truth.

A file name is the hash of what it shows, so an unchanged figure is not drawn
again. A record without the data draws nothing.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
from collections.abc import Callable
from html import escape
from pathlib import Path
from typing import Any

import numpy as np

OUT_DIR: Path | None = None
SUBDIR = Path("_static") / "validation-figures"
# The drawing code is part of each image key: a change to it redraws every figure.
VERSION = hashlib.sha1(Path(__file__).read_bytes()).hexdigest()[:8]
MAX_BYTES = 120_000

# Page palette (Okabe-Ito), same order as the classes hmp-val-s0 to hmp-val-s5.
OKABE = ["#e69f00", "#0072b2", "#009e73", "#cc79a7", "#d55e00", "#56b4e9"]
OKABE_DARK = ["#e69f00", "#56b4e9", "#009e73", "#cc79a7", "#d55e00", "#f0e442"]
MARKERS = ["o", "s", "^", "D", "v", "h"]
THEMES = {
    "light": {
        "bg": "#ffffff",
        "fg": "#222832",
        "muted": "#6c7480",
        "grid": "#d9dde2",
        "edge": "#9aa1ab",
        "okabe": OKABE,
        "diverging": ["#2166ac", "#f4f4f4", "#b2182b"],
        "sequential": "viridis",
        "accent": "#222832",
    },
    "dark": {
        "bg": "#14181e",
        "fg": "#dde1e6",
        "muted": "#9aa3ad",
        "grid": "#2c333b",
        "edge": "#5b636d",
        "okabe": OKABE_DARK,
        "diverging": ["#6fb1e8", "#30363d", "#f08a7e"],
        "sequential": "plasma",
        "accent": "#f2f4f6",
    },
}

Style = Callable[[str, set[int]], int]


def set_output(outdir: Path) -> None:
    """Name the build output folder the images are written to."""
    global OUT_DIR
    OUT_DIR = Path(outdir)


# ----------------------------------------------------------------- helpers


def _arr(values: list) -> np.ndarray:
    return np.array([np.nan if v is None else v for v in values], dtype=float)


def _symmetric_limit(arrays: list[np.ndarray]) -> float:
    peak = max((float(np.nanmax(np.abs(a))) for a in arrays if np.isfinite(a).any()), default=0.0)
    return peak if peak > 0 else 1.0


def _style_axes(ax, theme: dict, *, grid: bool = False) -> None:
    ax.set_facecolor(theme["bg"])
    for spine in ax.spines.values():
        spine.set_color(theme["muted"])
        spine.set_linewidth(0.6)
    ax.tick_params(colors=theme["muted"], labelsize=7, width=0.5, length=2.5)
    ax.xaxis.label.set_color(theme["muted"])
    ax.yaxis.label.set_color(theme["muted"])
    ax.xaxis.label.set_size(7.5)
    ax.yaxis.label.set_size(7.5)
    if grid:
        ax.grid(True, color=theme["grid"], linewidth=0.5)
        ax.set_axisbelow(True)


def _figure(theme: dict, nrows: int, ncols: int, panel: tuple[float, float], **kwargs):
    import matplotlib

    matplotlib.use("Agg", force=False)
    from matplotlib.figure import Figure

    fig = Figure(
        figsize=(panel[0] * ncols + 0.9, panel[1] * nrows + 0.6),
        facecolor=theme["bg"],
        layout="constrained",
    )
    axes = fig.subplots(nrows, ncols, squeeze=False, **kwargs)
    return fig, axes


def _cmap(theme: dict):
    from matplotlib.colors import LinearSegmentedColormap

    return LinearSegmentedColormap.from_list("hmp_div", theme["diverging"])


def _title(ax, text: str, theme: dict) -> None:
    ax.set_title(text, fontsize=8, color=theme["fg"], pad=3)


def _encode(fig) -> bytes:
    """WebP bytes of a figure, with a quality that keeps the file small."""
    from PIL import Image

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, facecolor=fig.get_facecolor())
    image = Image.open(io.BytesIO(buf.getvalue())).convert("RGB")
    data = b""
    for quality in (88, 78, 68, 58, 48):
        out = io.BytesIO()
        image.save(out, format="WEBP", quality=quality, method=6)
        data = out.getvalue()
        if len(data) <= MAX_BYTES:
            break
    return data


# ------------------------------------------------------------------- maps


def _cells(m: dict) -> tuple[list[np.ndarray], np.ndarray]:
    """Cell polygons and errors of a map record, sea or inactive cells left out."""
    err = _arr(m["error"])
    if "grid" in m:
        xe = _arr(m["grid"]["x_edges"])
        ye = _arr(m["grid"]["y_edges"])
        rows, cols = np.divmod(np.arange(err.size), xe.size - 1)
        polys = [
            np.array(
                [[xe[c], ye[r]], [xe[c + 1], ye[r]], [xe[c + 1], ye[r + 1]], [xe[c], ye[r + 1]]]
            )
            for r, c in zip(rows, cols, strict=True)
        ]
    else:
        verts = np.asarray(m["vertices"], dtype=float)
        polys = [verts[face] for face in m["faces"]]
    shown = np.flatnonzero(np.isfinite(err))
    return [polys[i] for i in shown], err[shown]


def _robust_limit(errors: list[np.ndarray]) -> tuple[float, bool]:
    """A symmetric colour limit that a few hot cells do not set.

    The limit is the 99th percentile of the absolute error over all panels, so
    a handful of cells cannot wash out the rest. Returns the limit and whether
    some cells go past it.
    """
    values = np.concatenate([np.abs(e) for e in errors if e.size]) if errors else np.array([])
    if not values.size:
        return 1.0, False
    limit = float(np.percentile(values, 99.0))
    peak = float(values.max())
    if limit <= 0.0:
        return (peak if peak > 0 else 1.0), False
    return limit, peak > 1.05 * limit


def draw_maps(panels: list[tuple[str, dict]], theme_name: str) -> bytes:
    """Plan-view simulated minus reference, one panel per solver, one shared scale."""
    from matplotlib.collections import PolyCollection
    from matplotlib.patches import Circle

    theme = THEMES[theme_name]
    cmap = _cmap(theme)
    cells = [_cells(m) for _, m in panels]
    limit, clipped = _robust_limit([err for _, err in cells])
    # Frame the cells where the error shows on the scale: a pumping case has a
    # wide domain and an error that lives around the well.
    seen = [
        np.concatenate([polys[i] for i in np.flatnonzero(np.abs(err) >= 0.02 * limit)])
        for polys, err in cells
        if polys and (np.abs(err) >= 0.02 * limit).any()
    ] or [np.concatenate(polys) for polys, _ in cells if polys]
    corners = np.concatenate(seen)
    (x0, y0), (x1, y1) = corners.min(axis=0), corners.max(axis=0)
    pad = 0.05 * max(x1 - x0, y1 - y0)
    ncols = 2 if len(panels) == 4 else min(len(panels), 3)
    nrows = math.ceil(len(panels) / ncols)
    fig, axes = _figure(theme, nrows, ncols, (2.5, 2.5), sharex=True, sharey=True)
    mappable = None
    for ax in axes.ravel():
        ax.set_visible(False)
    for ax, (label, m), (polys, err) in zip(axes.ravel(), panels, cells, strict=False):
        ax.set_visible(True)
        _style_axes(ax, theme)
        coll = PolyCollection(
            polys,
            array=err,
            cmap=cmap,
            edgecolors=theme["edge"],
            linewidths=0.15,
            antialiaseds=True,
        )
        coll.set_clim(-limit, limit)
        ax.add_collection(coll)
        mappable = coll
        ax.set_xlim(x0 - pad, x1 + pad)
        ax.set_ylim(y0 - pad, y1 + pad)
        ax.set_aspect("equal")
        overlay = m.get("overlay") or {}
        if "coast_circle" in overlay:
            cx, cy, r = overlay["coast_circle"]
            ax.add_patch(
                Circle((cx, cy), r, fill=False, ec=theme["accent"], lw=0.8, ls=(0, (4, 2)))
            )
        if "well" in overlay:
            ax.plot(
                *overlay["well"],
                marker="*",
                ms=8,
                mfc=theme["accent"],
                mec=theme["bg"],
                mew=0.5,
                ls="",
            )
        ax.set_xlabel("x (m)")
        ax.set_ylabel("y (m)")
        _title(ax, label, theme)
    if mappable is not None:
        cbar = fig.colorbar(
            mappable,
            ax=axes.ravel().tolist(),
            shrink=0.85,
            pad=0.02,
            aspect=25,
            extend="both" if clipped else "neither",
        )
        cbar.set_label("simulated minus reference (m)", color=theme["muted"], fontsize=7.5)
        cbar.ax.tick_params(colors=theme["muted"], labelsize=7, width=0.5)
        cbar.outline.set_edgecolor(theme["muted"])
        cbar.outline.set_linewidth(0.5)
    return _encode(fig)


# -------------------------------------------------------------- space-time


def draw_spacetime(panels: list[tuple[str, dict]], theme_name: str) -> bytes:
    """Error over x and time, one panel per solver, one shared symmetric scale."""
    theme = THEMES[theme_name]
    cmap = _cmap(theme)
    errors = [np.array([_arr(row) for row in s["error"]]) for _, s in panels]
    limit = _symmetric_limit(errors)
    ncols = min(len(panels), 3)
    nrows = math.ceil(len(panels) / ncols)
    fig, axes = _figure(theme, nrows, ncols, (2.5, 2.3), sharex=True, sharey=True)
    for ax in axes.ravel():
        ax.set_visible(False)
    mesh = None
    for k, (ax, (label, s), err) in enumerate(zip(axes.ravel(), panels, errors, strict=False)):
        ax.set_visible(True)
        _style_axes(ax, theme)
        mesh = ax.pcolormesh(
            _arr(s["x"]),
            _arr(s["t"]),
            err,
            cmap=cmap,
            vmin=-limit,
            vmax=limit,
            shading="auto",
            rasterized=True,
        )
        _title(ax, label, theme)
        if k % ncols == 0:
            ax.set_ylabel(panels[0][1]["t_label"])
        if k >= len(panels) - ncols:
            ax.set_xlabel(panels[0][1]["x_label"])
    if mesh is not None:
        cbar = fig.colorbar(mesh, ax=axes.ravel().tolist(), shrink=0.85, pad=0.02, aspect=25)
        unit = panels[0][1].get("unit") or ""
        cbar.set_label(f"simulated minus reference ({unit})", color=theme["muted"], fontsize=7.5)
        cbar.ax.tick_params(colors=theme["muted"], labelsize=7, width=0.5)
        cbar.outline.set_edgecolor(theme["muted"])
        cbar.outline.set_linewidth(0.5)
    return _encode(fig)


# ------------------------------------------------------------- landscapes


def _spans_decade(values: np.ndarray) -> bool:
    v = values[np.isfinite(values)]
    return bool(v.size and v.min() > 0 and v.max() / v.min() > 10.0)


def _method_colors(n: int, theme: dict) -> list[str]:
    return [theme["okabe"][i % len(theme["okabe"])] for i in range(n)]


def _by_method(entries: list[dict]) -> list[dict]:
    """One entry per method name: the runs of a method share a colour and a marker."""
    merged: dict[str, dict] = {}
    for e in entries:
        if e["name"] not in merged:
            merged[e["name"]] = {
                **e,
                "points": list(e["points"]),
                "objective": list(e["objective"]),
            }
            continue
        m = merged[e["name"]]
        m["points"] += e["points"]
        m["objective"] += e["objective"]
        m["n_evaluated"] += e["n_evaluated"]
    return list(merged.values())


def draw_samples(entries: list[dict], theme_name: str) -> bytes:
    """The evaluated points of each method, with the truth and each best point."""
    theme = THEMES[theme_name]
    names = list(entries[0]["parameters"])
    entries = _by_method([e for e in entries if list(e["parameters"]) == names])
    colors = _method_colors(len(entries), theme)
    pts = [
        np.array([[np.nan if v is None else v for v in r] for r in e["points"]]) for e in entries
    ]
    obj = [_arr(e["objective"]) for e in entries]
    truth = entries[0].get("truth") or {}
    n_par = len(names)
    all_obj = np.concatenate(obj)

    if n_par == 2:
        fig, axes = _figure(theme, 1, 1, (5.2, 3.8))
        ax = axes[0, 0]
        _style_axes(ax, theme, grid=True)
        positive = all_obj[all_obj > 0]
        cvals = np.log10(np.where(all_obj > 0, all_obj, positive.min() if positive.size else 1.0))
        lo, hi = float(cvals.min()), float(cvals.max())
        if hi - lo < 1e-9:
            hi = lo + 1.0
        sc = None
        start = 0
        for e, p, o, m in zip(entries, pts, obj, MARKERS, strict=False):
            c = cvals[start : start + o.size]
            start += o.size
            sc = ax.scatter(
                p[:, 0], p[:, 1], c=c, cmap=theme["sequential"], vmin=lo, vmax=hi,
                marker=m, s=22, edgecolors=theme["muted"], linewidths=0.3, zorder=3,
                label=f"{e['name']} ({e['n_evaluated']} evaluations)",
            )  # fmt: skip
            b = int(np.nanargmin(o))
            ax.scatter(
                [p[b, 0]], [p[b, 1]], marker=m, s=70, facecolors="none",
                edgecolors=theme["accent"], linewidths=1.6, zorder=5,
            )  # fmt: skip
        if all(n in truth and truth[n] is not None for n in names):
            ax.scatter(
                [truth[names[0]]], [truth[names[1]]], marker="X", s=90,
                c=theme["accent"], edgecolors=theme["bg"], linewidths=0.8, zorder=6, label="truth",
            )  # fmt: skip
        allp = np.concatenate(pts)
        if _spans_decade(allp[:, 0]):
            ax.set_xscale("log")
        if _spans_decade(allp[:, 1]):
            ax.set_yscale("log")
        ax.set_xlabel(names[0])
        ax.set_ylabel(names[1])
        leg = ax.legend(fontsize=7, frameon=False, labelcolor=theme["fg"], loc="best")
        for handle in leg.legend_handles:
            handle.set_color(theme["muted"])
        if sc is not None:
            cbar = fig.colorbar(sc, ax=ax, shrink=0.85, pad=0.02, aspect=25)
            cbar.set_label("log10 objective", color=theme["muted"], fontsize=7.5)
            cbar.ax.tick_params(colors=theme["muted"], labelsize=7, width=0.5)
            cbar.outline.set_edgecolor(theme["muted"])
            cbar.outline.set_linewidth(0.5)
        return _encode(fig)

    ncols = min(n_par, 3)
    nrows = math.ceil(n_par / ncols)
    fig, axes = _figure(theme, nrows, ncols, (3.2 if n_par == 1 else 2.6, 2.6), sharey=True)
    for ax in axes.ravel():
        ax.set_visible(False)
    obj_log = _spans_decade(all_obj)
    handles = []
    for j, (ax, name) in enumerate(zip(axes.ravel(), names, strict=False)):
        ax.set_visible(True)
        _style_axes(ax, theme, grid=True)
        allx = np.concatenate([p[:, j] for p in pts])
        for i, (e, p, o) in enumerate(zip(entries, pts, obj, strict=False)):
            h = ax.scatter(
                p[:, j], o, marker=MARKERS[i % len(MARKERS)], s=20, c=colors[i % len(colors)],
                edgecolors=theme["bg"], linewidths=0.3, alpha=0.9, zorder=3,
                label=f"{e['name']} ({e['n_evaluated']} evaluations)",
            )  # fmt: skip
            if j == 0:
                handles.append(h)
            b = int(np.nanargmin(o))
            ax.scatter(
                [p[b, j]], [o[b]], marker=MARKERS[i % len(MARKERS)], s=75, facecolors="none",
                edgecolors=theme["accent"], linewidths=1.6, zorder=5,
            )  # fmt: skip
        t = truth.get(name)
        if t is not None:
            ax.axvline(t, color=theme["accent"], lw=1.0, ls=(0, (5, 2)), zorder=2)
        if _spans_decade(allx):
            ax.set_xscale("log")
        if obj_log:
            ax.set_yscale("log")
        ax.set_xlabel(name)
        if j % ncols == 0:
            ax.set_ylabel("objective")
    from matplotlib.lines import Line2D

    extra = [Line2D([0], [0], color=theme["accent"], lw=1.0, ls=(0, (5, 2)))]
    axes.ravel()[0].legend(
        [*handles, *extra],
        [*(h.get_label() for h in handles), "truth"],
        fontsize=7, frameon=False, labelcolor=theme["fg"], loc="best",
    )  # fmt: skip
    return _encode(fig)


# --------------------------------------------------------- grouping + HTML


def _write(kind: str, payload: Any, draw: Callable[[Any, str], bytes]) -> str | None:
    """Draw both variants unless they exist, return the HTML name stem."""
    if OUT_DIR is None:
        return None
    key = hashlib.sha1(
        json.dumps([VERSION, kind, payload], sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    folder = OUT_DIR / SUBDIR
    folder.mkdir(parents=True, exist_ok=True)
    for theme in THEMES:
        path = folder / f"{key}-{theme}.webp"
        if not path.exists():
            path.write_bytes(draw(payload, theme))
    return key


def _img(key: str, alt: str, docname: str) -> str:
    base = "../" * docname.count("/") + SUBDIR.as_posix()
    alt = escape(alt, quote=True)
    return "".join(
        f'<img class="only-{theme}" src="{base}/{key}-{theme}.webp" alt="{alt}" loading="lazy">'
        for theme in THEMES
    )


def _figure_html(key: str, alt: str, caption: str, docname: str) -> str:
    return (
        f'<figure class="hmp-val-fig hmp-val-wide">{_img(key, alt, docname)}'
        f"<figcaption>{escape(caption)}</figcaption></figure>"
    )


def _panels(records: list[dict], field: str, label: Callable[[dict], str], order) -> dict:
    """Records with ``field`` data, grouped by case, solvers in page order."""
    groups: dict[Any, list[tuple[str, dict]]] = {}
    for r in sorted(records, key=order):
        for item in r.get(field) or []:
            groups.setdefault(r.get("case"), []).append((label(r), item))
    return groups


def maps_figures(records, label, order, docname) -> list[str]:
    out = []
    for panels in _panels(records, "maps", label, order).values():
        key = _write("maps", panels, draw_maps)
        if key is None:
            continue
        names = ", ".join(p[0] for p in panels)
        out.append(
            _figure_html(
                key,
                f"Plan-view map of simulated minus reference head, one panel per solver: {names}",
                "Head error in plan view, simulated minus reference, one scale for all panels; "
                "blank cells are sea or inactive.",
                docname,
            )
        )
    return out


def spacetime_figures(records, label, order, docname) -> list[str]:
    out = []
    for panels in _panels(records, "spacetime", label, order).values():
        key = _write("spacetime", panels, draw_spacetime)
        if key is None:
            continue
        names = ", ".join(p[0] for p in panels)
        out.append(
            _figure_html(
                key,
                f"Head error over position and time, simulated minus reference: {names}",
                "Head error over position and time, simulated minus reference, "
                "one symmetric scale for all panels.",
                docname,
            )
        )
    return out


def samples_figures(records, label, order, docname) -> list[str]:
    out = []
    many = sum(bool(r.get("samples")) for r in records) > 1
    for r in sorted(records, key=order):
        entries = r.get("samples") or []
        if not entries:
            continue
        key = _write("samples", entries, draw_samples)
        if key is None:
            continue
        n_par = len(entries[0]["parameters"])
        names = ", ".join(e["name"] for e in entries)
        what = {
            1: "objective against the parameter",
            2: "the two parameters, coloured by objective",
        }
        caption = (
            f"Points evaluated by {names}: "
            + what.get(n_par, "objective against each parameter")
            + "; the truth is marked and the best point of each method is ringed."
        )
        alt = f"Calibration landscape of {names}: " + what.get(n_par, "objective per parameter")
        if many:
            caption = f"{label(r)}. {caption}"
        out.append(_figure_html(key, alt, caption, docname))
    return out


def figures_html(
    records: list[dict], *, label: Callable[[dict], str], order: Callable[[dict], Any], docname: str
) -> str:
    """The maps, space-time and landscape figures of a case, or an empty string."""
    parts = [
        *maps_figures(records, label, order, docname),
        *spacetime_figures(records, label, order, docname),
        *samples_figures(records, label, order, docname),
    ]
    return f'<div class="hmp-val-figs hmp-val-figs-wide">{"".join(parts)}</div>' if parts else ""
