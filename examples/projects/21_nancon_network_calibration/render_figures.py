"""Render the figures of the two-stage calibration of the Nancon.

Two families.

Read straight from the run: the crossing of the two distances, the trace of the
bisection, the cost profile of the storage phase and the two-stage card.

Rebuilt here: the criterion's per-cell supports. It builds them during a trial
and nothing persists them, so this script recomputes them from the promoted run
and hands them to the map figures. That is what makes the network comparison
possible at all.

    python examples/projects/21_nancon_network_calibration/render_figures.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from hydromodpy.calibration.observations.simulated_network import (
    downstream_closure,
    specific_seepage_threshold,
)
from hydromodpy.core.depression_filling import fill_depressions_on_graph
from hydromodpy.core.field_routing import cell_adjacency_from_face_connectivity
from hydromodpy.core.topographic_distance import (
    build_downslope_metric,
    downslope_distance_to_mask,
)
from hydromodpy.display.figure_registry import get as get_figure
from hydromodpy.results.calibration_trials import calibration_trials
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.run import Run
from hydromodpy.spatial.mesh.ops.vector_cell_mask import cell_polygons, vector_cell_mask

PROJECT = Path(__file__).resolve().parent
DATA = PROJECT.parents[1] / "data"
FIGURES = PROJECT / "figures" / "calibration"

NETWORK = DATA / "hydrography" / "nancon_stream_network.gpkg"
DISCHARGE = DATA / "hydrometry" / "hydrometry_custom_NANCON_19820201_20220125_D.csv"

FROM_THE_RUN = (
    "downslope_distance_crossing",
    "bisection_bracket_trace",
    "parameter_cost_profile",
    "abherve_two_stage_card",
)


def _save(figure, ax, name: str) -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    path = FIGURES / f"{name}.png"
    figure.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(figure)
    print(f"  {name}: {path.relative_to(PROJECT)}")


def _render(name: str, run, **opts) -> None:
    factory = get_figure(name)
    fig_obj = factory() if isinstance(factory, type) else factory
    if not opts:
        reason = fig_obj.unavailable_reason(run)
        if reason:
            print(f"  {name}: skipped, {reason}")
            return
    figure, ax = plt.subplots(figsize=fig_obj.spec.default_figsize)
    try:
        fig_obj.render(run, ax, **opts)
    except Exception as exc:  # noqa: BLE001 - one bad figure must not stop the rest
        plt.close(figure)
        print(f"  {name}: failed, {type(exc).__name__}: {exc}")
        return
    _save(figure, ax, name)


def _runs_by_name(catalog) -> dict[str, str]:
    sims = catalog.simulations
    return {str(n): str(s) for n, s in zip(sims["name"], sims["sim_id"], strict=False)}


def criterion_supports(run) -> dict[str, np.ndarray] | None:
    """Rebuild the three per-cell masks the criterion balances.

    The same construction the criterion runs: seepage above a specific
    threshold, closed downslope, both supports cut to the delineated catchment,
    and the descent measured on a surface whose depressions are resolved on the
    mesh graph itself.
    """
    if not NETWORK.exists():
        print(f"  supports: no mapped network at {NETWORK}")
        return None
    watershed = PROJECT / f"runs/{run.name}/tables.parquet/geographic_watershed.parquet"
    if not watershed.exists():
        print("  supports: this run kept no watershed table")
        return None

    mesh = run.mesh
    faces = np.asarray(mesh.face_node_connectivity)
    verts = np.asarray(mesh.vertices)
    topo = np.asarray(mesh.topography).reshape(-1)
    polys = cell_polygons(verts, faces)

    net = gpd.read_file(NETWORK)
    observed = np.asarray(
        vector_cell_mask(polys, list(net.geometry), mesh_crs=mesh.crs, geometry_crs=net.crs),
        dtype=bool,
    )
    ws = gpd.read_parquet(watershed)
    catchment = np.asarray(
        vector_cell_mask(polys, list(ws.geometry), mesh_crs=mesh.crs, geometry_crs=ws.crs),
        dtype=bool,
    )

    adjacency = cell_adjacency_from_face_connectivity(faces, n_cells=topo.size)
    outlet = int(np.argmin(np.where(catchment, topo, np.inf)))
    seeds = np.zeros(topo.size, dtype=bool)
    seeds[outlet] = True
    conditioned = fill_depressions_on_graph(topo, adjacency, seeds).surface
    metric = build_downslope_metric(conditioned, faces, vertices=verts)

    try:
        release = np.asarray(run.field("release_flux", timestep=-1)).reshape(-1)
    except Exception as exc:  # noqa: BLE001
        print(f"  supports: this run persisted no release_flux ({type(exc).__name__})")
        return None

    areas = np.asarray(run.mesh_cell_areas()) if hasattr(run, "mesh_cell_areas") else None
    if areas is None:
        areas = np.full(topo.size, 2500.0)
    threshold = specific_seepage_threshold(areas, _mean_recharge(run), ratio=1.0e-4)
    seepage = np.asarray(release, dtype=float) > np.asarray(threshold, dtype=float)
    simulated = downstream_closure(metric, seepage) & catchment
    observed_in = observed & catchment

    return {
        "simulated": simulated,
        "observed": observed_in,
        "valid": simulated & observed_in,
        "excess": simulated & ~observed_in,
        "missing": observed_in & ~simulated,
        "distance": downslope_distance_to_mask(metric, observed_in | seeds),
        "catchment": catchment,
    }


def _mean_recharge(run) -> float:
    """Mean recharge of the run, in m/s, from its own budget."""
    try:
        budget = run.budget()
        rows = budget[budget["component"] == "recharge"]
        flux = float(rows["flux_in"].mean())
        area = 64.68e6
        return flux / area
    except Exception:  # noqa: BLE001
        return 8.0e-9


def main() -> int:
    catalog = Catalog(PROJECT)
    by_name = _runs_by_name(catalog)
    if not by_name:
        print("No run in this project. Run the calibration first:")
        print("  hmp calibrate examples/projects/21_nancon_network_calibration/"
              "calibration_two_stage.toml")
        return 1

    # One session per stage, and each figure reads the stage it belongs to: the
    # crossing and the bracket are the root search, the cost profile is the
    # storage grid. Handed the wrong one they refuse, naming the diagnostic the
    # session never published.
    def _run_named(prefix: str):
        # Newest first: a promoted run re-run with more fields written keeps the
        # same name with a version suffix, and that one is the useful one.
        for name in sorted((n for n in by_name if n.startswith(prefix)), reverse=True):
            run = Run(by_name[name], catalog)
            if run.has_table("calibration_iterations"):
                return run
        return None

    def _run_with_field(prefix: str, field: str):
        for name in sorted((n for n in by_name if n.startswith(prefix)), reverse=True):
            run = Run(by_name[name], catalog)
            try:
                run.field(field, timestep=-1)
            except Exception:  # noqa: BLE001
                continue
            return run
        return None

    root_search = _run_named("bisection_iter")
    storage = _run_named("grid_iter")

    if root_search is not None:
        print(f"Root search, from run {root_search.name}: "
              f"{len(calibration_trials(root_search))} trials")
        for name in ("downslope_distance_crossing", "bisection_bracket_trace"):
            _render(name, root_search)
        _render("abherve_two_stage_card", root_search)
    if storage is not None:
        print(f"Storage grid, from run {storage.name}: "
              f"{len(calibration_trials(storage))} trials")
        _render("parameter_cost_profile", storage)
    if root_search is None and storage is None:
        print("No run carries calibration trials; skipping the session figures.")

    steady = _run_with_field("bisection_iter", "release_flux") or root_search
    if steady is not None:
        print(f"\nNetwork comparison, from run {steady.name}:")
        supports = criterion_supports(steady)
        if supports is not None:
            _render(
                "seepage_network_reference_overlay",
                steady,
                simulated=supports["simulated"],
                observed=supports["observed"],
            )
            _render(
                "seepage_network_confusion_map",
                steady,
                valid=supports["valid"],
                excess=supports["excess"],
                missing=supports["missing"],
            )
            _render(
                "downslope_distance_map",
                steady,
                distance=supports["distance"],
                support=supports["observed"],
            )

    transient = next(
        (Run(s, catalog) for n, s in by_name.items() if "grid_iter" in n or "transient" in n),
        None,
    )
    if transient is not None:
        print(f"\nDischarge, from run {transient.name}:")
        observed = pd.read_csv(DISCHARGE, parse_dates=["datetime"]).set_index("datetime")["value"]
        # The score and the window are calibration notions: display may not
        # import calibration, so the caller that ran the calibration passes them.
        best = calibration_trials(transient).sort_values("objective_value").head(1)
        cost = float(best["objective_value"].iloc[0]) if not best.empty else None
        _render(
            "hydrograph_log_nse",
            transient,
            observed=observed,
            nse_log=None if cost is None else 1.0 - cost,
            scoring_window=(pd.Timestamp("2001-01-01"), pd.Timestamp("2009-12-31")),
        )
    else:
        print("\nNo transient run promoted; skipping the hydrograph.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
