"""Draw the cohort figures of a campaign summary: one PNG per figure and variable.

A cohort figure draws a table with one row per site, ``summary/by_site`` of a
project, not a run. ``hmp campaign collect`` asks this module for the names it may
draw (:func:`cohort_figure_names`) and draws them under ``summary/figures/``
(:func:`draw_cohort_figures`), each file recorded in the ledger of the folder.
K is in m/s, nse is dimensionless, outlets are in metres of one CRS. A site without
a value is drawn hollow or counted, and never dropped silently.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from matplotlib.colors import LogNorm, Normalize

from hydromodpy.core.logging import get_logger
from hydromodpy.core.version import __version__ as HYDROMODPY_VERSION
from hydromodpy.display import static
from hydromodpy.display.theme import Theme, get_theme

logger = get_logger(__name__)

SITE_COLUMN = "site"
"""Column naming the site of a row."""
LOG_SCALE_SPAN = 10.0
"""Ratio of the largest to the smallest positive value above which a log scale is drawn."""
LABELLED_MAP_SITES = 40
LABELLED_DISTRIBUTION_SITES = 40
"""Most sites whose name is written next to their point, on a map and on a distribution."""
JITTER_SEED = 0
"""Seed of the vertical spread of the points of a distribution, so a figure redraws the same."""


def _values(table: Any, variable: str) -> np.ndarray:
    """Return the cohort column ``variable`` as floats, NaN where missing."""
    if not isinstance(table, pd.DataFrame):
        raise ValueError(
            "draws a cohort table (summary/by_site of a project, one row per site), "
            "and a run is one run; run hmp campaign collect"
        )
    if SITE_COLUMN not in table.columns:
        raise ValueError(f"the cohort table has no {SITE_COLUMN!r} column")
    if variable not in table.columns:
        listed = ", ".join(str(column) for column in table.columns)
        raise ValueError(f"the cohort table has no column {variable!r}; it has {listed}")
    return pd.to_numeric(table[variable], errors="coerce").to_numpy(dtype="float64")


def wants_log(values: np.ndarray, log: bool | None) -> bool:
    """Return whether to draw ``values`` on a log scale.

    ``log`` forces the choice. Left out, a log scale when every finite value is
    positive and they span more than ``LOG_SCALE_SPAN``.
    """
    if log is not None:
        return bool(log)
    finite = values[np.isfinite(values)]
    if finite.size < 2 or np.any(finite <= 0.0):
        return False
    return float(finite.max() / finite.min()) > LOG_SCALE_SPAN


def _outlets(table: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, str | None]:
    """Return the outlet coordinates of every row and their CRS; NaN for a row without one."""
    if "x_outlet" not in table.columns or "y_outlet" not in table.columns:
        empty = np.full(len(table), np.nan)
        return empty, empty.copy(), None
    xs = pd.to_numeric(table["x_outlet"], errors="coerce").to_numpy(dtype="float64")
    ys = pd.to_numeric(table["y_outlet"], errors="coerce").to_numpy(dtype="float64")
    known: set[str] = set()
    if "crs" in table.columns:
        known = {
            str(cell)
            for cell, x in zip(table["crs"], xs, strict=True)
            if not pd.isna(cell) and np.isfinite(x)
        }
    if len(known) > 1:
        raise ValueError(
            f"the outlets of the cohort table are in {len(known)} CRS "
            f"({', '.join(sorted(known))}); move them into one before drawing"
        )
    return xs, ys, next(iter(known), None)


def _name_points(ax: Any, names: Any, xs: Any, ys: Any, theme: Theme) -> None:
    for name, x, y in zip(names, xs, ys, strict=True):
        ax.annotate(
            str(name), (x, y), xytext=(3, 3), textcoords="offset points", **static.text_style(theme)
        )


def draw_map(
    table: pd.DataFrame, variable: str, ax: Any, theme: Theme, *, log: bool | None = None
) -> None:
    """Draw one point per site at its outlet, coloured by ``variable``.

    A site without a value is drawn hollow, so a reader sees which catchments the
    table leaves empty. The colour is on a log scale when ``wants_log`` says so.
    """
    values = _values(table, variable)
    xs, ys, crs = _outlets(table)
    placed = np.isfinite(xs) & np.isfinite(ys)
    if not placed.any():
        raise ValueError("no site of the cohort table has an outlet to place")
    valued = placed & np.isfinite(values)
    if valued.any():
        low, high = float(values[valued].min()), float(values[valued].max())
        use_log = wants_log(values, log) and low > 0
        points = ax.scatter(
            xs[valued], ys[valued], c=values[valued], cmap=theme.ramps["sequential"],
            norm=LogNorm(low, high) if use_log else Normalize(low, high), s=40,
            edgecolors=theme.ink, linewidths=theme.line_width, zorder=3,
        )  # fmt: skip
        static.colorbar(ax.figure, points, ax, theme, label=variable)
    empty = placed & ~np.isfinite(values)
    if empty.any():
        ax.scatter(
            xs[empty], ys[empty], facecolors="none", edgecolors=theme.muted, s=40, zorder=2,
            label=f"no {variable}",
        )  # fmt: skip
    ax.set_title(f"{variable} of the best case of each site ({int(placed.sum())} sites)")
    if crs == "EPSG:4326":
        static.style_axes(ax, theme, grid=False)
        ax.set_xlabel("longitude (°)")
        ax.set_ylabel("latitude (°)")
    else:
        static.map_axes(ax, theme, crs=crs or "CRS")
    ax.set_aspect("equal", adjustable="datalim")
    if int(placed.sum()) <= LABELLED_MAP_SITES:
        _name_points(ax, table[SITE_COLUMN][placed], xs[placed], ys[placed], theme)
    if empty.any():
        static.legend(ax, theme)


def draw_distribution(
    table: pd.DataFrame, variable: str, ax: Any, theme: Theme, *, log: bool | None = None
) -> None:
    """Draw how ``variable`` spreads over the sites: a box of the quartiles and every site.

    The sites without a value are counted in the title.
    """
    values = _values(table, variable)
    finite = np.isfinite(values)
    if not finite.any():
        raise ValueError(f"no site of the cohort table has a {variable}")
    kept = values[finite]
    ax.boxplot(
        kept, orientation="horizontal", widths=0.5, showfliers=False,
        **{part: {"color": theme.ink, "linewidth": theme.line_width}
           for part in ("boxprops", "whiskerprops", "capprops", "medianprops")},
    )  # fmt: skip
    spread = 1.0 + np.random.default_rng(JITTER_SEED).uniform(-0.12, 0.12, kept.size)
    ax.scatter(kept, spread, s=16, color=theme.roles["simulated"], alpha=0.8, zorder=3)
    if kept.size <= LABELLED_DISTRIBUTION_SITES:
        _name_points(ax, table[SITE_COLUMN][finite], kept, spread, theme)
    if wants_log(values, log):
        ax.set_xscale("log")
    ax.set_yticks([])
    ax.set_xlabel(variable)
    missing = int((~finite).sum())
    suffix = f", {missing} without a value" if missing else ""
    ax.set_title(f"{variable} over {kept.size} sites{suffix}")
    static.style_axes(ax, theme)


@dataclass(frozen=True)
class CohortFigure:
    """A cohort figure: what draws it and the size of its page in millimetres."""

    draw: Callable[..., None]
    width_mm: float
    height_mm: float


COHORT_FIGURES = {
    "map": CohortFigure(draw_map, 120.0, 105.0),
    "distribution": CohortFigure(draw_distribution, 120.0, 60.0),
}
"""The names ``[sites.summary] figures`` writes."""


def cohort_figure_names() -> list[str]:
    """Return the cohort figures, sorted."""
    return sorted(COHORT_FIGURES)


def draw_cohort_figures(
    map_frame: pd.DataFrame,
    names: Sequence[str],
    variables: Sequence[str],
    figures_dir: Path,
) -> tuple[list[Path], list[str]]:
    """Draw each cohort figure for each variable; return the files written and those skipped.

    A figure the cohort cannot give (a variable without a finite value, a
    table without outlets) is skipped and named, ``<figure> of <variable>:
    <reason>``; the others are drawn.
    """
    theme = get_theme("default")
    written: list[Path] = []
    skipped: list[str] = []
    for name in names:
        figure = COHORT_FIGURES[name]
        for variable in variables:
            target = figures_dir / f"{name}_{variable}.png"
            fig = static.new_figure(theme, width=figure.width_mm, height_mm=figure.height_mm)
            try:
                figure.draw(map_frame, variable, fig.axes[0], theme)
            except ValueError as exc:
                skipped.append(f"{name} of {variable}: {exc}")
                logger.warning("summary figure %s of %s skipped: %s", name, variable, exc)
                continue
            static.save(fig, target, theme)
            record_collected_file(
                figures_dir,
                target,
                producer=f"display.figures.{name}",
                options={"variable": variable},
            )
            written.append(target)
    return written, skipped


def record_collected_file(
    directory: Path, path: Path, *, producer: str, options: Mapping[str, Any]
) -> None:
    """Add a file of the summary, drawn from many runs, to the ledger of its directory."""
    from hydromodpy.core.io.file_digest import sha256_of
    from hydromodpy.results.ledger import Ledger, LedgerEntry

    entry = LedgerEntry(
        file=path.relative_to(directory).as_posix(),
        producer=producer,
        options=dict(options),
        hydromodpy_version=HYDROMODPY_VERSION,
        at=datetime.now(UTC),
        sha256=sha256_of(path),
        identity=None,
    )
    ledger = Ledger.read(directory)
    ledger.append(entry)
    ledger.write(directory)


__all__ = [
    "COHORT_FIGURES",
    "CohortFigure",
    "cohort_figure_names",
    "draw_cohort_figures",
    "draw_distribution",
    "draw_map",
    "record_collected_file",
    "wants_log",
]
