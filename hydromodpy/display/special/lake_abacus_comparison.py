"""Stage-volume and stage-area curves of a lake, as stored and as the simulation followed.

The reference abacus is the storage the lake uses. The carved curves are what the cells
flooded at each stage add up to, so a gap means the mesh bowl is not the real one. The
gap biases the lake-aquifer exchange, not the lake water balance. Volume runs on the
bottom axis and area on the top axis, both against the stage. A dashed line marks the
weir level when the run keeps it in its config snapshot, and a note says so when not.
The full-pool gap in volume, the NSE and the RMSE of the carved curves and the name of the
lake are written on the figure. A run with several lakes and no station draws the largest.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from matplotlib.transforms import offset_copy

from hydromodpy.core.scoring.metrics import nse, rmse
from hydromodpy.display import static
from hydromodpy.display.subject import FigureNotApplicable
from hydromodpy.display.theme import Theme, unit_text
from hydromodpy.results.run.lake_abacus_view import run_lake_abacus

VOLUME_SCALE = 1e6
AREA_SCALE = 1e6


def _lake_abacus(run: Any, station: str | None) -> dict:
    """Return the stored abacus of the lake named by ``station``, else of the largest lake."""
    lake = None if station is None else station.removeprefix("lake:")
    try:
        probe = run_lake_abacus(run, lake)
    except KeyError as error:
        what = "" if lake is None else f" named {lake!r}"
        raise FigureNotApplicable(f"Run {run.name!r} holds no lake abacus{what}.") from error
    return probe


def _weir_level(run: Any, lake: str) -> float | None:
    """Return the invert of the first outlet of ``lake`` in the config snapshot, else None."""
    snapshot = run.config_snapshot or {}
    try:
        lakes = snapshot["flow"]["sinks_sources"]["lakes"]
        outlet = (lakes[lake] if lake in lakes else next(iter(lakes.values())))["outlets"][0]
        return float(str(outlet["invert"]).split()[0])
    except (KeyError, IndexError, StopIteration, TypeError, ValueError):
        return None


def _fit(real: Any, carved: Any) -> tuple[float, float] | None:
    """Return the NSE and the RMSE of the carved curve against the stored one, else None."""
    real, carved = np.asarray(real, float), np.asarray(carved, float)
    kept = np.isfinite(real) & np.isfinite(carved)
    if not kept.any():
        return None
    return float(nse(carved[kept], real[kept])), float(rmse(carved[kept], real[kept]))


def draw(subject: Any, ax: Any, theme: Theme, *, station: str | None = None) -> None:
    """Draw the reference and carved curves against the stage, and the weir level."""
    data = _lake_abacus(subject, station)
    lake = str(data["lake_id"])
    stage = np.asarray(data["stage"], float)
    top = ax.twiny()
    curves = (
        (ax, "volume", VOLUME_SCALE, "-", "Mm3"),
        (top, "sarea", AREA_SCALE, ":", "km2"),
    )
    for axis, key, scale, dash, unit in curves:
        for kind, role, name in (
            ("real", "observed", "reference"),
            ("sim", "simulated_alt", "carved mesh"),
        ):
            values = np.asarray(data[f"{kind}_{key}"], float) / scale
            text = f"{name}, {'volume' if key == 'volume' else 'area'}"
            style = static.line_style(theme, role)
            axis.plot(values, stage, ls=dash, label=text if axis is ax else None, **style)
            if axis is top:
                ax.plot([], [], ls=dash, label=text, **style)
        axis.set_xlim(left=0)
        axis.set_xlabel(f"{'Volume' if key == 'volume' else 'Area'} ({unit_text(unit)})")
    weir = _weir_level(subject, lake)
    if weir is not None:
        ax.axhline(weir, ls="--", label="weir level", **static.line_style(theme, "bounds"))
    ax.set_ylabel(f"Stage ({unit_text(str(data.get('stage_unit', 'm')))} a.s.l.)")
    static.style_axes(ax, theme)
    static.style_axes(top, theme, grid=False)
    top.spines["top"].set_visible(True)
    top.xaxis.set_label_position("top")
    real = float(np.asarray(data["real_volume"], float)[-1])
    lines = [f"Lake {lake}" + (f", the largest of {len(data['lake_ids'])}" if station is None and len(data["lake_ids"]) > 1 else "")]  # fmt: skip
    for key, name, scale, unit in (("volume", "volume", VOLUME_SCALE, "Mm3"), ("sarea", "area", AREA_SCALE, "km2")):  # fmt: skip
        fit = _fit(data[f"real_{key}"], data[f"sim_{key}"])
        if fit is not None:
            lines.append(f"Carved {name}: NSE {fit[0]:+.4f}, RMSE {fit[1] / scale:.3g} {unit_text(unit)}")  # fmt: skip
    if real > 0.0:
        gap = 100.0 * (float(np.asarray(data["sim_volume"], float)[-1]) - real) / real
        lines.append(f"Full pool: {gap:+.1f} % volume")
    if weir is None:
        lines.append("Weir level not stored in the run")
    if lines:
        static.note(ax, "\n".join(lines), theme, loc="lower right")
    leg = static.legend(ax, theme)
    above = offset_copy(ax.transAxes, fig=ax.figure, y=3.4 * theme.small, units="points")
    leg.set_bbox_to_anchor((1.0, 1.0), transform=above)
