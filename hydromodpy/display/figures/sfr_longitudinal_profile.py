"""Longitudinal profile of one SFR quantity against the distance to the outlet."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

import numpy as np

from hydromodpy.display.figure import BaseFigure, FigureNotApplicable, FigureSpec, run_suffix
from hydromodpy.display.figure_options import Opt
from hydromodpy.display.figure_registry import register
from hydromodpy.display.figures._instant import instant_label
from hydromodpy.display.figures.sfr_reach_timeseries import (
    STATE_UNITS,
    no_reach_series_reason,
    sfr_reach_stations,
)
from hydromodpy.results.run.sfr import sfr_reach_links

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from pandas import DataFrame

    from hydromodpy.results.run import Run


def distance_to_outlet(links: DataFrame) -> dict[tuple[str, int], float]:
    """Return the distance from the middle of each reach to the outlet of its network.

    The path follows, at each fork, the downstream reach that takes the larger
    share of the flow (``ustrf``, the lower ``ifno`` on a tie). Reach numbers
    increase downstream, so one pass from the last reach to the first is enough.
    The distance is in the unit of ``rlen`` (metres).
    """
    distances: dict[tuple[str, int], float] = {}
    for network, rows in links.groupby("network_id", sort=False):
        length = dict(zip(rows["ifno"].astype(int), rows["rlen"].astype(float), strict=True))
        share = dict(zip(rows["ifno"].astype(int), rows["ustrf"].astype(float), strict=True))
        main_next: dict[int, int | None] = {}
        for ifno, downstream in zip(rows["ifno"].astype(int), rows["downstream"], strict=True):
            known = [int(down) for down in downstream if int(down) in length]
            main_next[ifno] = min(known, key=lambda down: (-share[down], down)) if known else None
        to_end: dict[int, float] = {}
        for ifno in sorted(length, reverse=True):
            following = main_next[ifno]
            to_end[ifno] = length[ifno] + (0.0 if following is None else to_end[following])
            distances[(str(network), ifno)] = to_end[ifno] - 0.5 * length[ifno]
    return distances


@register
class SfrLongitudinalProfile(BaseFigure):
    """One SFR quantity per reach at a chosen time step (default: the last).

    The x axis is the distance from the middle of each reach to the outlet,
    along the main path, with the outlet on the right. Each branch of a
    branched network is drawn as its own line, from its head to the reach it
    joins, so the flow that accumulates downstream reads as one rising curve
    per tributary. A fork is followed to the reach that takes the larger share
    of the flow.
    """

    spec = FigureSpec(
        name="sfr_longitudinal_profile",
        title="SFR longitudinal profile",
        kind="timeseries",
        required_tables=("timeseries",),
        default_figsize=(8.0, 4.5),
    )

    def unavailable_reason(self, sim: Run) -> str | None:
        """Require the stream-reach series, which ``spec`` cannot declare."""
        return super().unavailable_reason(sim) or no_reach_series_reason(sim)

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        variable: Annotated[
            str,
            Opt(
                'Stream-reach series to draw: "downstream_flow" (the default), '
                '"stage", "depth" or another series the SFR package wrote.'
            ),
        ] = "downstream_flow",
        timestep: Annotated[
            int,
            Opt(
                'The instant drawn: a date ("2002-10-15"), "first" or "last". The '
                "figure draws the stress period that holds the date. Left out, the last."
            ),
        ] = -1,
        **_,
    ) -> Axes:
        triples = sfr_reach_stations(sim, variable)
        if not triples:
            raise KeyError(
                f"sfr_longitudinal_profile: no SFR '{variable}' series for sim {sim.sim_id}"
            )
        try:
            links = sfr_reach_links(sim)
        except KeyError as exc:
            # The run was sealed before the reach table stored its connectivity.
            raise FigureNotApplicable(str(exc.args[0])) from exc
        distance = distance_to_outlet(links)
        value: dict[tuple[str, int], float] = {}
        stamp = None
        for network, ifno, station in triples:
            series = sim.timeseries(variable, station=station)
            value[(network, ifno)] = float(series.iloc[timestep])
            stamp = series.index[timestep]
        points = sorted(key for key in value if key in distance)
        if not points:
            raise KeyError(f"sfr_longitudinal_profile: no reach of sim {sim.sim_id} has a position")
        downstream = {
            (str(row.network_id), int(row.ifno)): [int(down) for down in row.downstream]
            for row in links.itertuples()
        }
        segments = [
            [(distance[key], value[key]), (distance[(key[0], down)], value[(key[0], down)])]
            for key in points
            for down in downstream[key]
            if (key[0], down) in value and (key[0], down) in distance
        ]
        if segments:
            from matplotlib.collections import LineCollection

            ax.add_collection(LineCollection(segments, colors="steelblue", linewidths=1.2))
        positions = np.array([distance[key] for key in points])
        ax.plot(
            positions,
            [value[key] for key in points],
            ls="none",
            color="steelblue",
            marker="o",
            ms=3,
        )
        ax.autoscale_view()
        ax.invert_xaxis()
        networks = ", ".join(dict.fromkeys(key[0] for key in points))
        ax.set_xlabel("distance to the outlet, along the main path (m)")
        ax.set_ylabel(f"{variable} ({STATE_UNITS.get(variable, 'm³/s')})")
        when = instant_label(sim, timestep) or (f"{stamp:%Y-%m-%d}" if stamp is not None else "")
        ax.set_title(
            f"SFR {variable} profile{run_suffix(sim)} @ {networks}" + (f" ({when})" if when else "")
        )
        ax.grid(True, ls=":", lw=0.4)
        return ax
