"""Outflow-drain map grid and DEM-context map figures."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from hydromodpy.calibration.observations.network_transient_truth import (
    mesh_cell_geometry,
)
from hydromodpy.calibration.reporting.network_transient import io as _nt_io
from hydromodpy.calibration.reporting.network_transient import state as _state
from hydromodpy.calibration.reporting.network_transient.figures_watershed import _open_first_run
from hydromodpy.calibration.reporting.network_transient.geometry import (
    _drain_facecolors,
    _first_non_truth_candidate,
    _mesh_context_from_truth_package,
    _mesh_polygons,
    _plot_geographic_lines,
    _plot_topography,
    _polygon_bounds,
    _relative_gdf_bounds,
    _relative_origin,
    _relative_polygons,
    _safe_geographic,
    _score_catalog_path,
    _score_file_path,
    _topography_context,
    _watershed_clip_patch,
)
from hydromodpy.results.catalog import Catalog

_read_json = _nt_io.read_json


def _save_outflow_map_grid(
    truth_dir: Path | None, score_rows: list[dict[str, str]], path: Path
) -> None:
    if truth_dir is None:
        return
    candidate = _first_non_truth_candidate(score_rows)
    if candidate is None:
        return

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.cm import ScalarMappable
    from matplotlib.collections import PolyCollection
    from matplotlib.colors import LogNorm, Normalize

    from hydromodpy.calibration.metrics.network import active_network_mask

    d_ref = np.load(truth_dir / "steady_network_drain_by_cell.npz")["outflow_drain"]
    normalization = _read_json(truth_dir / "normalization.json")
    threshold = float(normalization.get("tau_network", 0.0))

    fallback_context = _mesh_context_from_truth_package(truth_dir)
    origin = None if fallback_context is None else fallback_context["origin"]
    polygons = None if fallback_context is None else fallback_context["polygons"]
    cell_topography = None if fallback_context is None else fallback_context["cell_topography"]
    topo = None
    watershed = None
    watershed_contour = None
    river_network = None

    if _state.report_facade().REFERENCE_RUN_ROOT.is_dir():
        try:
            catalog, run = _open_first_run(_state.report_facade().REFERENCE_RUN_ROOT)
        except Exception:
            catalog = None
        if catalog is not None:
            try:
                try:
                    centroids, _ = mesh_cell_geometry(
                        run.mesh.vertices, run.mesh.face_node_connectivity
                    )
                    origin = _relative_origin(run, centroids)
                    polygons = _relative_polygons(_mesh_polygons(run), origin)
                    cell_topography = None
                except Exception:
                    pass
                if origin is not None:
                    topo = _topography_context(run, origin)
                    watershed = _safe_geographic(run, "watershed")
                    watershed_contour = _safe_geographic(run, "watershed_contour")
                    river_network = _safe_geographic(run, "hydrographic_network_generated")
            finally:
                catalog.close()

    if origin is None or polygons is None or len(polygons) != d_ref.size:
        return

    d_sim = _steady_drain_from_score_row(candidate)
    if d_sim is None or d_sim.size != d_ref.size:
        return
    ref_mask = active_network_mask(d_ref, threshold=threshold)
    sim_mask = active_network_mask(d_sim, threshold=threshold)
    true_positive = ref_mask & sim_mask
    false_negative = ref_mask & ~sim_mask
    false_positive = ~ref_mask & sim_mask

    positive_values = np.concatenate((d_ref[d_ref > threshold], d_sim[d_sim > threshold]))
    if positive_values.size:
        vmin = max(float(np.nanmin(positive_values)) * 0.5, 1.0e-12)
        vmax = float(np.nanmax(positive_values))
    else:
        vmin, vmax = 1.0e-12, 1.0
    norm = LogNorm(vmin=vmin, vmax=max(vmax, vmin * 10.0))
    cmap = plt.get_cmap("magma")

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(13.0, 6.0), dpi=150, sharex=True, sharey=True)
    panels = (
        ("Objectif cible", d_ref, ref_mask),
        (
            f"Meilleur candidat: {candidate.get('candidate_id', 'candidat')}",
            d_sim,
            sim_mask,
        ),
    )
    mappable = None
    bounds = _relative_gdf_bounds(watershed, origin) if watershed is not None else None
    if bounds is None:
        bounds = _polygon_bounds(polygons)
    for ax, (title, drain, mask) in zip(axes, panels, strict=False):
        clip_patch = _watershed_clip_patch(watershed, origin, ax) if watershed is not None else None
        image = _plot_topography(ax, topo, clip_patch=clip_patch)
        del image
        if topo is None and cell_topography is not None:
            topo_values = np.asarray(cell_topography, dtype=float)
            topo_finite = topo_values[np.isfinite(topo_values)]
            if topo_finite.size:
                topo_coll = PolyCollection(
                    polygons,
                    array=topo_values,
                    cmap="terrain",
                    norm=Normalize(
                        vmin=float(np.nanmin(topo_finite)),
                        vmax=float(np.nanmax(topo_finite)),
                    ),
                    edgecolors="none",
                    alpha=0.34,
                    zorder=0,
                )
                ax.add_collection(topo_coll)
        facecolors = _drain_facecolors(drain, threshold=threshold, cmap=cmap, norm=norm)
        coll = PolyCollection(
            polygons,
            facecolors=facecolors,
            edgecolors=(0.25, 0.28, 0.32, 0.18),
            linewidths=0.18,
        )
        if clip_patch is not None:
            coll.set_clip_path(clip_patch)
        ax.add_collection(coll)
        mappable = ScalarMappable(norm=norm, cmap=cmap)
        _plot_geographic_lines(ax, river_network, origin, color="#3c78a8", lw=0.8, alpha=0.32)
        _plot_geographic_lines(ax, watershed_contour, origin, color="#17202a", lw=1.7, alpha=0.58)
        ax.scatter([0.0], [0.0], s=34, color="#17202a", edgecolors="white", linewidths=0.6)
        if bounds is not None:
            ax.set_xlim(bounds[0], bounds[2])
            ax.set_ylim(bounds[1], bounds[3])
        else:
            ax.autoscale_view()
        ax.set_aspect("equal", adjustable="box")
        ax.set_title(
            f"{title}\ncellules actives={int(mask.sum())}",
            fontsize=11,
        )
        ax.set_xlabel("X relatif a l'exutoire (km)")
        ax.set_ylabel("Y relatif a l'exutoire (km)")
        ax.grid(True, ls=":", lw=0.35, color="#cfd8df")
    if mappable is not None:
        fig.colorbar(
            mappable,
            ax=axes.ravel().tolist(),
            fraction=0.035,
            pad=0.025,
            label="outflow_drain actif (m3/s, log)",
        )
    summary = (
        f"commun={int(true_positive.sum())}, "
        f"manques={int(false_negative.sum())}, exces={int(false_positive.sum())}"
    )
    source_label = _network_map_source_label(candidate)
    fig.suptitle(
        f"Drainage utilise par l'objectif spatial ({source_label}), clippe au bassin ({summary})"
    )
    fig.subplots_adjust(left=0.07, right=0.88, bottom=0.12, top=0.84, wspace=0.08)
    fig.savefig(path)
    plt.close(fig)


def _save_dem_context_map(truth_dir: Path | None, reference_root: Path, path: Path) -> None:
    if truth_dir is None:
        return

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection
    from matplotlib.colors import Normalize

    fallback_context = _mesh_context_from_truth_package(truth_dir)
    origin = None if fallback_context is None else fallback_context["origin"]
    polygons = None if fallback_context is None else fallback_context["polygons"]
    cell_topography = None if fallback_context is None else fallback_context["cell_topography"]
    topo = None
    source_label = "z_top_mean du maillage"
    watershed = None
    watershed_contour = None
    river_network = None

    if reference_root.is_dir():
        try:
            catalog, run = _open_first_run(reference_root)
        except Exception:
            catalog = None
        if catalog is not None:
            try:
                if origin is None:
                    try:
                        centroids, _ = mesh_cell_geometry(
                            run.mesh.vertices, run.mesh.face_node_connectivity
                        )
                        origin = _relative_origin(run, centroids)
                        polygons = _relative_polygons(_mesh_polygons(run), origin)
                        cell_topography = None
                    except Exception:
                        pass
                if origin is not None:
                    topo = _topography_context(run, origin)
                    if topo is not None:
                        source_label = "raster DEM watershed_dem"
                    watershed = _safe_geographic(run, "watershed")
                    watershed_contour = _safe_geographic(run, "watershed_contour")
                    river_network = _safe_geographic(run, "hydrographic_network_generated")
            finally:
                catalog.close()

    if origin is None or polygons is None:
        return

    bounds = _relative_gdf_bounds(watershed, origin) if watershed is not None else None
    if bounds is None:
        bounds = _polygon_bounds(polygons)

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8.8, 6.6), dpi=150)
    clip_patch = _watershed_clip_patch(watershed, origin, ax) if watershed is not None else None
    image = _plot_topography(ax, topo, clip_patch=clip_patch)
    mappable = image
    if topo is None and cell_topography is not None:
        topo_values = np.asarray(cell_topography, dtype=float)
        finite = topo_values[np.isfinite(topo_values)]
        if finite.size:
            coll = PolyCollection(
                polygons,
                array=topo_values,
                cmap="terrain",
                norm=Normalize(vmin=float(finite.min()), vmax=float(finite.max())),
                edgecolors=(0.18, 0.22, 0.27, 0.18),
                linewidths=0.15,
                alpha=0.82,
            )
            ax.add_collection(coll)
            mappable = coll
    else:
        mesh_overlay = PolyCollection(
            polygons,
            facecolors=(1.0, 1.0, 1.0, 0.0),
            edgecolors=(0.12, 0.16, 0.20, 0.14),
            linewidths=0.15,
        )
        ax.add_collection(mesh_overlay)

    _plot_geographic_lines(ax, river_network, origin, color="#276f93", lw=0.9, alpha=0.45)
    _plot_geographic_lines(ax, watershed_contour, origin, color="#17202a", lw=1.8, alpha=0.65)
    ax.scatter([0.0], [0.0], s=36, color="#17202a", edgecolors="white", linewidths=0.7)
    if bounds is not None:
        ax.set_xlim(bounds[0], bounds[2])
        ax.set_ylim(bounds[1], bounds[3])
    else:
        ax.autoscale_view()
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("X relatif a l'exutoire (km)")
    ax.set_ylabel("Y relatif a l'exutoire (km)")
    ax.grid(True, ls=":", lw=0.35, color="#cfd8df")
    ax.set_title(f"Contexte topographique ({source_label})")
    if mappable is not None:
        fig.colorbar(mappable, ax=ax, fraction=0.035, pad=0.025, label="Elevation (m)")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _steady_drain_from_score_row(row: dict[str, str]) -> np.ndarray | None:
    source = str(row.get("network_map_source", "steady")).strip().lower()
    if source.startswith("transient"):
        transient_artifact = _score_file_path(row.get("transient_network_npz", ""))
        transient_drain = _outflow_drain_from_npz(transient_artifact)
        if transient_drain is not None:
            return transient_drain

    artifact = _score_file_path(row.get("steady_drain_npz", ""))
    steady_drain = _outflow_drain_from_npz(artifact)
    if steady_drain is not None:
        return steady_drain

    catalog_path = _score_catalog_path(row.get("steady_catalog", ""))
    if catalog_path is None or not catalog_path.is_dir():
        return None
    try:
        with Catalog(catalog_path) as catalog:
            run = catalog[catalog.resolve(row.get("steady_ref", "run_0001"))]
            return np.asarray(run.field("outflow_drain", timestep=-1), dtype=float).reshape(-1)
    except Exception:
        return None


def _outflow_drain_from_npz(artifact: Path | None) -> np.ndarray | None:
    if artifact is None or not artifact.is_file():
        return None
    try:
        with np.load(artifact) as data:
            return np.asarray(data["outflow_drain"], dtype=float).reshape(-1)
    except Exception:
        return None


def _network_map_source_label(row: dict[str, str]) -> str:
    source = str(row.get("network_map_source", "steady")).strip().lower()
    if source == "transient_last":
        return "dernier pas transitoire"
    if source == "transient_mean":
        return "moyenne transitoire"
    return "permanent"
