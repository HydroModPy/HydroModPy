"""The maximal and minimal mapped networks against the simulated extents of a run.

A mapped network is a classification by flow duration: the complete network
holds every reach a cartographer saw flowing, the permanent network the reaches
flowing all year. What a transient run is compared to is therefore not one
state but two extents counted over its years, the ones the two-bound mode of
the network criterion scores: the cells flowing at least ``N_max`` timesteps
of a year, and the cells flowing at every timestep but at most ``N_min``, kept
when they meet the rule in ``year_quorum`` of the complete years.

This map draws both, outside any calibration, over the two maps the run
stored: the simulated extents filled, the mapped networks outlined, the way the
figure 4f of the HydroModPy technical note (EGUsphere 2026) sets the minimum
and maximum simulated extents beside the permanent and complete maps. Asked
for one bound, it draws the valid, excess and missing cells of that bound
instead, the partition the criterion scores for it.

Nothing is scored here: the counts on the page are cells, and the distances
belong to a calibration trial.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import numpy as np

from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.figures._memo import RunMemo
from hydromodpy.display.figures._stream_comparison import (
    AGREEMENT_COLORS,
    CASING_COLOR,
    CELL_WEIGHT_PT,
    GROUND_COLOR,
    MapExtentName,
    cell_count,
    checked_cells,
    class_label,
    draw_cells,
    flowing_words,
    map_extent,
    map_legend,
    select_cells,
)
from hydromodpy.display.maps.axes import overlay_watershed_contour, style_map_axes
from hydromodpy.display.maps.mesh_geometry import face_polygons
from hydromodpy.results.derive.network_criterion_settings import (
    NetworkCriterionSettings,
    network_criterion_settings,
)
from hydromodpy.results.derive.stream_extent import (
    FLOW_FIELD,
    NetworkExtents,
    network_extents_from_run,
    scored_cells,
    unavailable_reason_for_extents,
)
from hydromodpy.results.derive.stream_network import (
    AGREEMENT_EXCESS,
    AGREEMENT_MISSING,
    AGREEMENT_VALID,
)

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.patches import Patch

    from hydromodpy.results.run import Run

BoundChoice = Literal["both", "minimal", "maximal"]

SIMULATED_MINIMAL_COLOR = "#2166AC"
"""Fill of the minimal simulated extent: the cells flowing all year."""

SIMULATED_MAXIMAL_COLOR = "#A6CEE3"
"""Fill of the cells the maximal extent adds to the minimal one."""

OBSERVED_MINIMAL_COLOR = "#1A1A1A"
"""Outline of the minimal (permanent) mapped network."""

OBSERVED_MAXIMAL_COLOR = "#E66100"
"""Outline of the reaches the maximal (complete) map adds to the minimal one."""

_OUTLINE_WEIGHT_PT = 1.3
"""Stroke of a mapped cell: an outline has to read over a filled one."""

_FLAT_WEIGHT_PT = 0.0

_EXTENTS_MEMO = RunMemo()


@register
class NetworkExtentBoundsMap(BaseFigure):
    """Maximal and minimal simulated extents beside the maximal and minimal maps.

    Drawn from a transient run that stored both maps: the complete network as
    ``reference`` and the permanent one as ``reference_permanent``. A steady
    run, or a run with one map only, gets a sentence instead of a figure.

    Options
    -------
    ``bound``
        ``"both"`` (default) draws the two extents and the two maps; ``"minimal"``
        or ``"maximal"`` draws the valid, excess and missing cells of that bound.
    ``year``
        One complete calendar year to draw instead of the climatological extents.
    ``maximal_flowing_steps``, ``minimal_dry_steps``, ``year_quorum``, ``visible_flow``
        The rules of ``[calibration.outputs.<n>.extent]``. Left out, the rules
        the run's sealed network output scored with, or the defaults of that
        table when it sealed none.
    ``tau_specific_ratio``, ``diagonal_neighbors``
        The criterion's seepage threshold and neighbour graph. Left out, the
        run's sealed network output, or the criterion's defaults. The
        rasterisation of the maps, the weighting and the positional accuracy
        always come from there, the snap from ``[geographic.snap_streams]``
        and the years counted from ``[calibration] scoring_window``.
    ``output``
        The calibration output to read the settings of, when the run sealed
        several network outputs; the first one otherwise.
    ``extent``
        ``"catchment"`` crops to the delineated watershed, ``"mesh"`` keeps the
        whole domain.
    """

    spec = FigureSpec(
        name="network_extent_bounds_map",
        title="Network extent bounds",
        kind="comparison",
        required_fields=(FLOW_FIELD,),
        default_figsize=(7.0, 6.8),
    )

    def unavailable_reason(self, sim: Run) -> str | None:
        """Return why this run holds no two extents to draw, or None when it does."""
        reason = super().unavailable_reason(sim)
        if reason is not None:
            return reason
        try:
            settings = network_criterion_settings(sim)
        except ValueError as exc:
            return f"its sealed network output cannot be read: {exc}"
        return unavailable_reason_for_extents(
            sim,
            tau_specific_ratio=settings.tau_specific_ratio,
            scoring_window=settings.scoring_window,
        )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        bound: BoundChoice = "both",
        year: int | str | None = None,
        maximal_flowing_steps: int | None = None,
        minimal_dry_steps: int | None = None,
        year_quorum: float | None = None,
        visible_flow: str | None = None,
        tau_specific_ratio: float | None = None,
        diagonal_neighbors: bool | None = None,
        output: str | None = None,
        extent: MapExtentName = "catchment",
        **_,
    ) -> Axes:
        if bound not in ("both", "minimal", "maximal"):
            raise ValueError(f"bound must be 'both', 'minimal' or 'maximal', got {bound!r}.")
        settings = network_criterion_settings(sim, output=output)
        tau = float(
            settings.tau_specific_ratio if tau_specific_ratio is None else tau_specific_ratio
        )
        reason = unavailable_reason_for_extents(
            sim, tau_specific_ratio=tau, scoring_window=settings.scoring_window
        )
        if reason is not None:
            raise ValueError(f"{self.spec.name} unavailable for {sim.sim_id}: {reason}")
        extents = extents_from_run(
            sim,
            settings,
            maximal_flowing_steps=maximal_flowing_steps,
            minimal_dry_steps=minimal_dry_steps,
            year_quorum=year_quorum,
            visible_flow=visible_flow,
            tau_specific_ratio=tau,
            diagonal_neighbors=diagonal_neighbors,
        )
        chosen_year = _chosen_year(extents, year, figure=self.spec.name)
        polygons = face_polygons(sim)
        scope = scored_cells(extents.geometry) if extent == "catchment" else None
        if bound == "both":
            handles = _draw_both(ax, polygons, extents, chosen_year, scope)
        else:
            handles = _draw_one(ax, polygons, extents, bound, chosen_year)

        ax.set_facecolor(GROUND_COLOR)
        style_map_axes(ax)
        overlay_watershed_contour(ax, sim, color="#404040", linewidth=0.9, alpha=0.7)
        what = "both bounds" if bound == "both" else f"{bound} bound"
        ax.set_title(
            f"{self.spec.title} - {sim.name or sim.sim_id}\n{what}, {_window(extents, chosen_year)}"
        )
        window = map_extent(sim, polygons, extent=extent)
        note = "\n".join(
            [*extent_notes(extents, chosen_year), settings.note(), f"frame: {window.name}"]
        )
        map_legend(ax, handles, note=note, ncols=2)
        window.apply(ax)
        return ax


def extents_from_run(
    sim: Run,
    settings: NetworkCriterionSettings,
    *,
    maximal_flowing_steps: int | None = None,
    minimal_dry_steps: int | None = None,
    year_quorum: float | None = None,
    visible_flow: str | None = None,
    tau_specific_ratio: float | None = None,
    diagonal_neighbors: bool | None = None,
) -> NetworkExtents:
    """Return the extents of a run, memoised on the run and the rules.

    A rule left None is the one ``settings`` carries: the run's sealed extent
    table, or its defaults. The years counted are those of the run's sealed
    scoring window.
    """
    rules = settings.extent_rules
    knobs = {
        "maximal_flowing_steps": int(
            rules.maximal_flowing_steps if maximal_flowing_steps is None else maximal_flowing_steps
        ),
        "minimal_dry_steps": int(
            rules.minimal_dry_steps if minimal_dry_steps is None else minimal_dry_steps
        ),
        "year_quorum": float(rules.year_quorum if year_quorum is None else year_quorum),
        "visible_flow": str(rules.visible_flow if visible_flow is None else visible_flow),
        "tau_specific_ratio": float(
            settings.tau_specific_ratio if tau_specific_ratio is None else tau_specific_ratio
        ),
        "diagonal_neighbors": bool(
            settings.diagonal_neighbors if diagonal_neighbors is None else diagonal_neighbors
        ),
        "observed_rasterization": settings.observed_rasterization,
        "weighting": settings.weighting,
        "observed_position_accuracy_m": settings.observed_position_accuracy_m,
        "scoring_window": settings.scoring_window,
    }
    return _EXTENTS_MEMO.get_or_build(
        sim,
        tuple(sorted(knobs.items())),
        lambda: network_extents_from_run(sim, **knobs),
    )


def extent_notes(extents: NetworkExtents, year: int | None) -> list[str]:
    """Return the lines naming the rules the extents were cut by, and the counts."""
    years = extents.years.years
    rule = (
        f"maximal: flowing >= {extents.maximal_flowing_steps} timestep(s) of a year; "
        f"minimal: dry <= {extents.minimal_dry_steps} timestep(s)"
    )
    if year is None:
        rule += (
            f"; kept in >= {extents.masks.n_years_required} of {len(years)} complete "
            f"year(s) ({years[0]}-{years[-1]}, quorum {extents.year_quorum:g})"
        )
    if extents.years.outside_window:
        left_out = ", ".join(str(item) for item in extents.years.outside_window)
        rule += f"; outside the scoring window: {left_out}"
    lines = [rule, flowing_words(extents.tau_specific_ratio, extents.visible_flow)]
    for bound in ("minimal", "maximal"):
        if bound == "minimal" and extents.minimal_observed is None:
            continue
        counts = extents.supports(bound, year=year).counts
        lines.append(
            f"{bound}: {int(counts['n_valid'])} valid, {int(counts['n_excess'])} excess, "
            f"{int(counts['n_missing'])} missing scored cell(s)"
        )
    if np.isfinite(extents.frac_minimal_outside_maximal):
        lines.append(
            f"minimal map outside the maximal map: {extents.frac_minimal_outside_maximal:.1%}"
        )
    return lines


def _chosen_year(extents: NetworkExtents, year: int | str | None, *, figure: str) -> int | None:
    """Return the year asked for, checked against the complete years, or None."""
    if year is None:
        return None
    try:
        value = int(year)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{figure}: year must be a calendar year, got {year!r}.") from exc
    if value not in extents.years.years:
        complete = ", ".join(str(item) for item in extents.years.years)
        raise ValueError(f"{figure}: {value} is not a complete year of this run ({complete}).")
    return value


def _window(extents: NetworkExtents, year: int | None) -> str:
    """Return what the extents on the page were counted over."""
    if year is not None:
        return f"year {year}"
    years = extents.years.years
    span = str(years[0]) if len(years) == 1 else f"{years[0]}-{years[-1]}"
    return f"climatological extents over {span}"


def _draw_both(
    ax: Axes,
    polygons,
    extents: NetworkExtents,
    year: int | None,
    scope: np.ndarray | None = None,
) -> list[Patch]:
    """Fill the two simulated extents and outline the two maps.

    ``scope`` restricts the legend counts to the declared frame (the scored
    cells of the catchment); ``None`` counts every cell of the mesh. Drawing
    stays over the whole mesh regardless, since the map is cropped visually
    by the window, not by this mask.
    """
    from matplotlib.patches import Patch

    n_cells = len(polygons)
    sim_min = checked_cells(extents.simulated("minimal", year=year), n_cells, "minimal extent")
    sim_max = checked_cells(extents.simulated("maximal", year=year), n_cells, "maximal extent")
    obs_max = checked_cells(extents.observed("maximal"), n_cells, "maximal map")
    obs_min = checked_cells(extents.observed("minimal"), n_cells, "minimal map")
    sim_added = sim_max & ~sim_min
    obs_added = obs_max & ~obs_min
    keep = np.ones(n_cells, dtype=bool) if scope is None else np.asarray(scope, dtype=bool)

    draw_cells(
        ax,
        select_cells(polygons, sim_max),
        color=CASING_COLOR,
        label="_extent casing",
        zorder=2,
        weight_pt=CELL_WEIGHT_PT,
    )
    draw_cells(
        ax,
        select_cells(polygons, sim_added),
        color=SIMULATED_MAXIMAL_COLOR,
        label="simulated maximal extent",
        zorder=3,
        weight_pt=_FLAT_WEIGHT_PT,
    )
    draw_cells(
        ax,
        select_cells(polygons, sim_min),
        color=SIMULATED_MINIMAL_COLOR,
        label="simulated minimal extent",
        zorder=4,
        weight_pt=_FLAT_WEIGHT_PT,
    )
    draw_cells(
        ax,
        select_cells(polygons, obs_added),
        color="none",
        edgecolor=OBSERVED_MAXIMAL_COLOR,
        label="maximal map",
        zorder=5,
        weight_pt=_OUTLINE_WEIGHT_PT,
    )
    draw_cells(
        ax,
        select_cells(polygons, obs_min),
        color="none",
        edgecolor=OBSERVED_MINIMAL_COLOR,
        label="minimal map",
        zorder=6,
        weight_pt=_OUTLINE_WEIGHT_PT,
    )
    return [
        Patch(
            facecolor=SIMULATED_MINIMAL_COLOR,
            edgecolor=CASING_COLOR,
            label=f"simulated minimal extent ({cell_count(sim_min & keep)})",
        ),
        Patch(
            facecolor=SIMULATED_MAXIMAL_COLOR,
            edgecolor=CASING_COLOR,
            label=f"maximal extent beyond it ({cell_count(sim_added & keep)})",
        ),
        Patch(
            facecolor="none",
            edgecolor=OBSERVED_MINIMAL_COLOR,
            linewidth=_OUTLINE_WEIGHT_PT,
            label=f"minimal map ({cell_count(obs_min & keep)})",
        ),
        Patch(
            facecolor="none",
            edgecolor=OBSERVED_MAXIMAL_COLOR,
            linewidth=_OUTLINE_WEIGHT_PT,
            label=f"maximal map beyond it ({cell_count(obs_added & keep)})",
        ),
    ]


def _draw_one(
    ax: Axes,
    polygons,
    extents: NetworkExtents,
    bound: Literal["minimal", "maximal"],
    year: int | None,
) -> list[Patch]:
    """Draw the valid, excess and missing cells of one bound."""
    from matplotlib.patches import Patch

    supports = extents.supports(bound, year=year)
    n_cells = len(polygons)
    classes = {
        AGREEMENT_VALID: checked_cells(supports.valid, n_cells, "valid cells"),
        AGREEMENT_EXCESS: checked_cells(supports.excess, n_cells, "excess cells"),
        AGREEMENT_MISSING: checked_cells(supports.missing, n_cells, "missing cells"),
    }
    union = np.zeros(n_cells, dtype=bool)
    for mask in classes.values():
        union |= mask
    draw_cells(
        ax,
        select_cells(polygons, union),
        color=CASING_COLOR,
        label="_network casing",
        zorder=2,
        weight_pt=CELL_WEIGHT_PT,
    )
    handles: list[Patch] = []
    for zorder, (value, mask) in enumerate(classes.items(), start=3):
        draw_cells(
            ax,
            select_cells(polygons, mask),
            color=AGREEMENT_COLORS[value],
            label=class_label(value),
            zorder=zorder,
            weight_pt=_FLAT_WEIGHT_PT,
        )
        handles.append(
            Patch(
                facecolor=AGREEMENT_COLORS[value],
                edgecolor=CASING_COLOR,
                label=f"{class_label(value)} ({cell_count(mask)})",
            )
        )
    return handles


__all__ = ["NetworkExtentBoundsMap", "extent_notes", "extents_from_run"]
