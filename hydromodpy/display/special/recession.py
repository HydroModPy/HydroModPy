"""Recession rate against discharge on the Brutsaert-Nieber plane, at one station.

A draining aquifer sets how fast its own baseflow falls, so ``-dQ/dt`` against ``Q``
puts every falling limb of the record on one cloud whose slope is the drainage law,
``-dQ/dt = a Q^b``. The rate is the step difference taken only where the discharge
falls. The line of each cloud is the fit of ``results.derive.recession`` and its
exponent is written in the legend. The slopes of a linear reservoir (``b = 1``) and of
the late-time Boussinesq solution (``b = 3/2``) pass through the median of the
simulated cloud. When the run stores the conductivity, the specific yield, the area
of the catchment and a stream network, the Boussinesq line of those properties is
drawn too, with its coefficient, since the offset of the cloud to it is what a
hydrogeologist reads. Otherwise a note names what is missing. The coefficient of that line is
written for a reach drained from both banks (``sides = 2``) and its unit is on the
figure. The legend gives the number of falling steps of each fit. The station is the one
the run scored, unless one is asked. The discharge is read as ``run.timeseries`` gives it.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from hydromodpy.core.units.quantities import SECONDS_PER_DAY
from hydromodpy.display import static, variables
from hydromodpy.display.special.records import scored_station
from hydromodpy.display.subject import (
    FigureNotApplicable,
    read_field,
    read_mesh,
    read_network,
    read_observed,
)
from hydromodpy.display.theme import Theme, unit_text
from hydromodpy.results.derive.recession import (
    MIN_FIT_POINTS,
    brutsaert_nieber_coefficient,
    fit_recession,
    recession_cloud,
)

VARIABLE = "discharge"
REFERENCES = ((1.0, ":", "b = 1 (linear reservoir)"), (1.5, "--", "b = 3/2 (Boussinesq)"))
NETWORK_ROLES = ("generated", "reference")
"""Networks tried in turn for the length of the stream that drains the aquifer."""


A_UNIT = r"$\mathregular{m^{-3/2}\,d^{-1/2}}$"
"""Unit of ``a`` of the Boussinesq law, for a discharge in m3 per day and a time in days."""


def _cloud(record: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(Q, -dQ/dt)`` of the falling limbs, Q in display unit and time in days."""
    return recession_cloud(_shown(record))


def _in_display(coefficient: float, per_display: float) -> float:
    """Return ``a`` for a discharge in the display unit, ``per_display`` of it per m3/s.

    A rate in m3 per day squared becomes ``per_display / 86400`` times larger and a discharge
    ``86400 / per_display`` times smaller, so ``a`` is scaled by ``sqrt(86400 / per_display)``.
    """
    return coefficient * float(np.sqrt(SECONDS_PER_DAY / per_display))


def _read(run: Any, station: str | None) -> pd.Series:
    """Return the simulated discharge of the station on the time axis of ``run.timeseries``."""
    try:
        return run.timeseries(VARIABLE, station=station)
    except (KeyError, ValueError) as error:
        raise FigureNotApplicable(
            f"Run {run.name!r} stores no {VARIABLE!r} series at station {station!r} "
            f"(a steady run has none): {error}"
        ) from error


def _shown(record: pd.Series) -> pd.Series:
    return pd.Series(variables.to_display(VARIABLE, record.to_numpy()), index=record.index)


def _catchment_mean(run: Any, name: str) -> float:
    """Return the mean of the field ``name`` over the cells of the catchment."""
    values = read_field(run, name)[read_mesh(run).zones["catchment"]]
    if not np.isfinite(values).any():
        raise FigureNotApplicable(
            f"Run {run.name!r}: the field {name!r} is empty on the catchment."
        )
    return float(np.nanmean(values))


def _catchment_area(run: Any) -> float:
    """Return the area in m2 of the cells of the catchment."""
    mesh = read_mesh(run)
    return float(mesh.areas[mesh.zones["catchment"]].sum())


def _stream_length(run: Any) -> float:
    """Return the length in m of the generated network, else of the mapped one."""
    for role in NETWORK_ROLES:
        try:
            return float(read_network(run, role).geometry.length.sum())
        except FigureNotApplicable:
            continue
    raise FigureNotApplicable(f"Run {run.name!r} stores no stream network.")


def _boussinesq(run: Any) -> tuple[float | None, list[str]]:
    """Return ``a`` of the Boussinesq law in m3 and days, and the facts the run does not store."""
    facts = (
        ("hydraulic conductivity", lambda: _catchment_mean(run, "hydraulic_conductivity")),
        ("specific yield", lambda: _catchment_mean(run, "specific_yield")),
        ("catchment area", lambda: _catchment_area(run)),
        ("stream network", lambda: _stream_length(run)),
    )  # fmt: skip
    found, missing = [], []
    for name, read in facts:
        try:
            found.append(read())
        except FigureNotApplicable:
            missing.append(name)
    if missing:
        return None, missing
    k, porosity, area, length = found
    return brutsaert_nieber_coefficient(
        k=k * SECONDS_PER_DAY, porosity=porosity, stream_length=length, area=area
    ), []


def draw(subject: Any, ax: Any, theme: Theme, *, station: str | None = None) -> None:
    """Draw the simulated and observed clouds with their fits and the reference slopes."""
    station = scored_station(subject, VARIABLE, station)
    simulated = _read(subject, station)
    try:
        record = read_observed(subject, VARIABLE, station=station)
        observed = pd.Series(record.to_numpy(), index=simulated.index) if len(record) == len(simulated) else None  # fmt: skip
    except FigureNotApplicable:
        observed = None
    records = [("simulated", simulated)]
    if observed is not None:
        records.insert(0, ("observed", observed))
    clouds = [(role, record, *_cloud(record)) for role, record in records]
    if clouds[-1][2].size < MIN_FIT_POINTS:
        raise FigureNotApplicable(
            f"Run {subject.name!r}: the simulated {VARIABLE} at station {station!r} has fewer "
            f"than {MIN_FIT_POINTS} falling steps, so no recession can be fitted."
        )
    for role, record, flow, rate in clouds:
        color = static.line_style(theme, role)["color"]
        ax.scatter(flow, rate, s=6, color=color, alpha=0.6, linewidths=0, zorder=3)
        law = fit_recession(_shown(record))
        if law is None:
            continue
        label = f"{role}, fitted b = {law[1]:.2f}, {flow.size} steps"
        own = np.geomspace(flow.min(), flow.max(), 20)
        ax.plot(
            own, law[0] * own ** law[1], label=label, zorder=4,
            **static.line_style(theme, role),
        )  # fmt: skip
    flow, rate = clouds[-1][2:]
    anchor, level = np.median(flow), np.median(rate)
    grid = np.geomspace(flow.min(), flow.max(), 20)
    for exponent, dashes, text in REFERENCES:
        ax.plot(
            grid, level * (grid / anchor) ** exponent, linestyle=dashes, label=text, zorder=2,
            color=theme.roles["bounds"], linewidth=theme.line_width,
        )  # fmt: skip
    coefficient, missing = _boussinesq(subject)
    if coefficient is None:
        static.note(
            ax, f"No Boussinesq line: the run stores no {', no '.join(missing)}.", theme,
            loc="upper left",
        )  # fmt: skip
    else:
        per_display = float(variables.to_display(VARIABLE, np.array([1.0]))[0])
        line = _in_display(coefficient, per_display)
        ax.plot(
            grid, line * grid**1.5, zorder=2,
            label=f"Boussinesq, both banks (sides = 2), a = {coefficient:.3g} {A_UNIT}",
            linestyle="-.", **static.line_style(theme, "reference_law"),
        )  # fmt: skip
    ax.set_xscale("log")
    ax.set_yscale("log")
    head, unit = variables.label_parts(VARIABLE)
    ax.set_xlabel(variables.join_unit(head, unit))
    ax.set_ylabel(variables.join_unit("Recession rate, -dQ/dt", unit_text("m3 s-1 d-1")))
    static.style_axes(ax, theme)
    ax.tick_params(which="minor", labelsize=theme.small, labelcolor=theme.ink)
    static.legend(ax, theme)
