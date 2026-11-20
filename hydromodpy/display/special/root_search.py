"""The distances of a root search against the parameter it searched, one point per evaluation.

A root search looks for the value of one parameter where the simulated seepage network
lies as far from the observed one as the other way round. A search on one bound draws
the mean distance from simulated to observed cells and from observed to simulated cells.
A search on two bounds (a minimal and a maximal map) closes one root per bound, so it
draws the signed gap of each bound, whose zero is the root. Both go on a log axis of the
parameter, each evaluation numbered in the order it ran. The last bracket, the closest
pair of evaluations on both sides of the crossing, is shaded, one per bound. A ring marks
the evaluations under the acceptable cost. The criterion prefix and the bound names of
the components differ between sessions, so they are read from the session.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from hydromodpy.display import static
from hydromodpy.display.special.records import axis_label, ring_acceptable
from hydromodpy.display.subject import FigureNotApplicable
from hydromodpy.display.theme import Theme, unit_text
from hydromodpy.results.derive.root_bracket import (
    closing_root,
    final_bracket,
    sign_changes,
)
from hydromodpy.results.session.acceptance import acceptable_cost, phase_returned

SYMLOG_FLOOR = 10.0
CROWDED = 0.15  # decades of the parameter under which evaluations share one number
DISTANCES = (
    ("D_so", "simulated", "o", "Simulated to observed"),
    ("D_os", "simulated_alt", "s", "Observed to simulated"),
)
SIGNED = "J_signed"
"""The signed gap of a search on one bound. A search on two bounds writes it once per bound, as ``J_signed_<bound>``."""


def _component(components: Any, tail: str) -> float:
    """Return the value of the component named ``<prefix>.<tail>``, NaN when absent."""
    for key, value in components.items():
        if key.endswith("." + tail) and value is not None:
            return float(value)
    return float("nan")


def _bound_components(trials: Any) -> list[str]:
    """Return the signed components of the bounds, when the search ran on two bounds.

    A search on one bound writes the unsuffixed ``J_signed``, so the presence of that
    component rules out the two-bound mode, even when some bound suffix is also written.
    """
    tails = list(dict.fromkeys(key.rpartition(".")[2] for c in trials["components"] for key in c))
    bounds = [tail for tail in tails if tail.startswith(SIGNED + "_")]
    return [] if SIGNED in tails or len(bounds) < 2 else bounds


def _curves(trials: Any) -> list[tuple[str, str, str, np.ndarray, bool]]:
    """Return ``(label, role, marker, values, signed)`` of each curve the session holds."""
    bounds = _bound_components(trials)
    if bounds:
        marks = (("simulated", "o"), ("simulated_alt", "s"))
        return [
            (
                f"Signed gap, {tail.removeprefix(SIGNED + '_')} bound",
                role,
                marker,
                np.array([_component(c, tail) for c in trials["components"]]),
                True,
            )  # fmt: skip
            for tail, (role, marker) in zip(bounds, marks, strict=False)
        ]
    return [
        (label, role, marker, np.array([_component(c, tail) for c in trials["components"]]), False)
        for tail, role, marker, label in DISTANCES
    ]


def _reading(label: str, symbol: str, value: np.ndarray, residual: np.ndarray) -> str:
    """Return the line of the note that reads the final bracket and the root of one residual."""
    changes = sign_changes(value, residual)
    if not changes:
        return f"{label}no sign change: no root is bracketed"
    bracket = final_bracket(value, residual)
    root = closing_root(value, residual)
    line = f"{label}{symbol} = {root:.4g}, bracket [{bracket[0]:.4g}, {bracket[1]:.4g}]"
    line += f", a factor {bracket[1] / bracket[0]:.4g}"
    if len(changes) > 1:
        line += f"\n{label}{len(changes)} sign changes: the root is not unique"
    return line


def draw(subject: Any, ax: Any, theme: Theme) -> None:
    """Draw the curves against the searched parameter, numbered, with the final brackets."""
    trials = subject.trials.drop_duplicates("trial").sort_values("trial")
    trials = trials[(trials["status"] == "completed")]
    curves = _curves(trials)
    keep = np.logical_and.reduce([np.isfinite(values) for *_, values, _ in curves])
    if not keep.any():
        raise FigureNotApplicable(
            f"The session has no root search: no completed trial holds the distances "
            f"{DISTANCES[0][0]} and {DISTANCES[1][0]} or the signed gap of a bound in its components."
        )
    keep &= (trials["phase"] == trials["phase"][keep].iloc[0]).to_numpy()
    rows = trials[keep]
    curves = [(*curve[:3], curve[3][keep], curve[4]) for curve in curves]
    names = {name for row in rows["parameters"] for name in row}
    if len(names) != 1:
        raise FigureNotApplicable(
            f"The root search must run on one parameter, this one searched {sorted(names)}."
        )
    (name,) = names
    value = np.array([row[name]["value"] for row in rows["parameters"]], float)
    number = rows["trial"].to_numpy(int)
    bound = subject.descriptor.bounds.get(name)
    order = np.argsort(value)
    signed = curves[0][4]
    for label, role, marker, values, _ in curves:
        ax.plot(value[order], values[order], marker=marker, markersize=3, zorder=3, label=label,
                **static.line_style(theme, role))  # fmt: skip
    if signed:
        ax.axhline(0.0, color=theme.roles["bounds"], linewidth=theme.line_width, zorder=2)
    groups: list[list[int]] = []
    for i in order:
        if groups and np.log10(value[i] / value[groups[-1][-1]]) < CROWDED:
            groups[-1].append(i)
        else:
            groups.append([i])
    for group in groups:
        first, last = number[group].min(), number[group].max()
        top = max(curve[3][group].max() for curve in curves)
        ax.annotate(f"{first}-{last}" if first != last else str(first),
                    (value[group].mean(), top), xytext=(0, 3), textcoords="offset points",
                    ha="center", va="bottom", **static.text_style(theme))  # fmt: skip
    if signed:
        brackets = [
            (
                curve[1],
                "Final bracket, " + curve[0].rpartition(", ")[2],
                final_bracket(value, curve[3]),
            )
            for curve in curves
        ]
    else:
        brackets = [("band", "Final bracket", final_bracket(value, curves[0][3] - curves[1][3]))]
    for role, label, bracket in brackets:
        if bracket is not None:
            ax.axvspan(*bracket, facecolor=theme.roles[role], alpha=0.3 if signed else 1.0,
                       edgecolor=theme.roles["bounds"], linewidth=theme.line_width, zorder=1,
                       label=label)  # fmt: skip
    phase = rows["phase"].iloc[0]
    best, widths = phase_returned(subject, phase)
    cost = rows["cost"].to_numpy(float)
    shown = rows["trial"] == (best.trial if best is not None else -1)
    threshold = acceptable_cost(
        best, widths, float(cost[shown.to_numpy()][0]) if shown.any() else None
    )
    ring_acceptable(ax, value, [c[3] for c in curves], cost, threshold, theme)
    lines = []
    if signed:
        for label, _, _, values, _ in curves:
            side = label.rpartition(", ")[2].removesuffix(" bound")
            lines.append(_reading(f"{side}: ", f"{name}*_{side}", value, values))
    else:
        lines.append(_reading("", f"{name}*", value, curves[0][3] - curves[1][3]))
    if best is None or best.trial not in set(number):
        lines.append("The returned trial is not among the trials drawn")
    elif name in best.parameters:
        ax.axvline(best.parameters[name], color=theme.roles["best"], linewidth=theme.line_width,
                   linestyle="--", zorder=2, label="Returned value")  # fmt: skip
        lines.append(f"Returned {name} = {best.parameters[name]:.4g}")
    static.note(ax, "\n".join(lines), theme, loc="upper left")
    ax.set_xscale("log")
    ax.set_yscale("symlog", linthresh=SYMLOG_FLOOR)
    reach = 10.0 * max(np.abs(curve[3]).max() for curve in curves)
    ax.set_ylim(-reach if signed else 0, reach)
    ax.set_xlabel(axis_label(name, bound.units if bound is not None else None))
    ax.set_ylabel(
        f"Signed gap {DISTANCES[0][0]} - {DISTANCES[1][0]} ({unit_text('m')})" if signed
        else f"Mean downslope distance ({unit_text('m')})"
    )  # fmt: skip
    static.style_axes(ax, theme)
    static.legend(ax, theme)
