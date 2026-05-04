"""2D map renderers for comparison visuals."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np

from hydromodpy.analysis.comparison.visuals_payloads import (
    CaseConfigurationPayload,
    DifferencePayload,
    MapPayload,
)
from hydromodpy.analysis.comparison.visuals_style import (
    _LABEL_FONT_SIZE,
    _PANEL_TITLE_FONT_SIZE,
    _TICK_FONT_SIZE,
    _TITLE_FONT_SIZE,
    _finite_limits,
    _mask_nodata,
    _pretty_label,
    _robust_limits,
    _robust_symmetric_limit,
    _style_map_axes,
    _simulation_panel_title,
)

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.collections import PolyCollection  # noqa: E402

try:
    import rasterio
    from rasterio.transform import from_origin
except Exception:  # pragma: no cover - optional at runtime
    rasterio = None


def _render_map_subplot(
    ax: Any,
    payload: MapPayload,
    *,
    cmap: str,
    vmin: float,
    vmax: float,
) -> Any:
    if payload.geometry_kind == "scatter":
        plot_values = _mask_nodata(payload.values)
        marker_size = max(8.0, min(48.0, 24000.0 / max(1, payload.values.size)))
        artist = ax.scatter(
            payload.x,
            payload.y,
            c=plot_values,
            cmap=cmap,
            vmin=vmin,
            vmax=vmax,
            s=marker_size,
            marker="s",
            linewidths=0.0,
        )
        ax.set_aspect("equal", adjustable="box")
        _style_map_axes(ax)
        return artist

    image = _mask_nodata(np.asarray(payload.values, dtype=float)).reshape(
        payload.structured_shape
    )
    imshow_kwargs: dict[str, Any] = {
        "origin": "lower",
        "cmap": cmap,
        "vmin": vmin,
        "vmax": vmax,
        "aspect": "auto",
    }
    if payload.extent is not None:
        imshow_kwargs["extent"] = payload.extent
        imshow_kwargs["aspect"] = "equal"
    artist = ax.imshow(
        image,
        **imshow_kwargs,
    )
    _style_map_axes(ax)
    return artist


def _render_difference_subplot(
    ax: Any,
    payload: DifferencePayload,
    *,
    cmap: str,
    vmax: float,
) -> Any:
    if payload.geometry_kind == "scatter":
        plot_values = _mask_nodata(payload.values)
        marker_size = max(8.0, min(48.0, 24000.0 / max(1, payload.values.size)))
        artist = ax.scatter(
            payload.x,
            payload.y,
            c=plot_values,
            cmap=cmap,
            vmin=-vmax,
            vmax=vmax,
            s=marker_size,
            marker="s",
            linewidths=0.0,
        )
        ax.set_aspect("equal", adjustable="box")
        _style_map_axes(ax)
        return artist

    image = _mask_nodata(np.asarray(payload.values, dtype=float)).reshape(
        payload.structured_shape
    )
    imshow_kwargs: dict[str, Any] = {
        "origin": "lower",
        "cmap": cmap,
        "vmin": -vmax,
        "vmax": vmax,
        "aspect": "auto",
    }
    if payload.extent is not None:
        imshow_kwargs["extent"] = payload.extent
        imshow_kwargs["aspect"] = "equal"
    artist = ax.imshow(
        image,
        **imshow_kwargs,
    )
    _style_map_axes(ax)
    return artist


def _boundary_edges_by_side(
    vertices: np.ndarray,
    faces: np.ndarray,
) -> dict[str, list[np.ndarray]]:
    edges: dict[tuple[int, int], int] = {}
    for face in np.asarray(faces, dtype=int):
        face = face[(face >= 0) & (face < vertices.shape[0])]
        if face.size < 3:
            continue
        for left, right in zip(face, np.roll(face, -1), strict=False):
            key = tuple(sorted((int(left), int(right))))
            edges[key] = edges.get(key, 0) + 1
    boundary = [edge for edge, count in edges.items() if count == 1]
    if not boundary:
        return {}
    xy = np.asarray(vertices[:, :2], dtype=float)
    xmin, ymin = np.nanmin(xy, axis=0)
    xmax, ymax = np.nanmax(xy, axis=0)
    span_x = max(float(xmax - xmin), 1.0)
    span_y = max(float(ymax - ymin), 1.0)
    tol_x = span_x * 0.03
    tol_y = span_y * 0.03
    result: dict[str, list[np.ndarray]] = {
        "west": [],
        "east": [],
        "south": [],
        "north": [],
    }
    for edge in boundary:
        segment = xy[np.asarray(edge, dtype=int)]
        midpoint = segment.mean(axis=0)
        if abs(float(midpoint[0]) - float(xmin)) <= tol_x:
            result["west"].append(segment)
        elif abs(float(midpoint[0]) - float(xmax)) <= tol_x:
            result["east"].append(segment)
        elif abs(float(midpoint[1]) - float(ymin)) <= tol_y:
            result["south"].append(segment)
        elif abs(float(midpoint[1]) - float(ymax)) <= tol_y:
            result["north"].append(segment)
    return result


def _write_case_configuration_figure(
    *,
    path: Path,
    payload: CaseConfigurationPayload,
) -> bool:
    has_mesh = (
        payload.vertices is not None
        and payload.faces is not None
        and payload.vertices.size > 0
        and payload.faces.size > 0
    ) or (
        payload.centroid_x is not None
        and payload.centroid_y is not None
        and payload.centroid_x.size > 0
    )
    if not has_mesh and payload.recharge_values is None:
        return False

    figure, axes = plt.subplots(2, 2, figsize=(12.6, 8.4), squeeze=False)
    mesh_ax, recharge_ax, meta_ax, semantics_ax = np.asarray(axes, dtype=object).ravel()

    if (
        payload.vertices is not None
        and payload.faces is not None
        and payload.vertices.size
    ):
        polygons: list[np.ndarray] = []
        colors: list[float] = []
        surface = payload.surface_top
        for index, face in enumerate(np.asarray(payload.faces, dtype=int)):
            face = face[(face >= 0) & (face < payload.vertices.shape[0])]
            if face.size < 3:
                continue
            polygons.append(np.asarray(payload.vertices[face, :2], dtype=float))
            if (
                surface is not None
                and index < surface.size
                and math.isfinite(float(surface[index]))
            ):
                colors.append(float(surface[index]))
            else:
                colors.append(float(index))
        if polygons:
            collection = PolyCollection(
                polygons,
                array=np.asarray(colors, dtype=float),
                cmap="terrain",
                edgecolors=(0.12, 0.16, 0.20, 0.22),
                linewidths=0.25,
            )
            mesh_ax.add_collection(collection)
            mesh_ax.autoscale_view()
            colorbar = figure.colorbar(collection, ax=mesh_ax, fraction=0.046, pad=0.02)
            colorbar.set_label(
                "surface top [m]" if payload.surface_top is not None else "cell",
                fontsize=_LABEL_FONT_SIZE,
            )
            colorbar.ax.tick_params(labelsize=_TICK_FONT_SIZE)
            boundary_edges = _boundary_edges_by_side(payload.vertices, payload.faces)
            side_colors = {
                "west": "#2563eb",
                "east": "#dc2626",
                "south": "#059669",
                "north": "#7c3aed",
            }
            for side, label in payload.boundary_sides:
                for segment in boundary_edges.get(side, []):
                    mesh_ax.plot(
                        segment[:, 0],
                        segment[:, 1],
                        color=side_colors.get(side, "#111827"),
                        linewidth=2.1,
                        solid_capstyle="round",
                    )
                mesh_ax.plot(
                    [],
                    [],
                    color=side_colors.get(side, "#111827"),
                    linewidth=2.1,
                    label=label,
                )
    elif payload.centroid_x is not None and payload.centroid_y is not None:
        values = np.arange(payload.centroid_x.size, dtype=float)
        mesh_ax.scatter(
            payload.centroid_x, payload.centroid_y, c=values, s=22, cmap="viridis"
        )

    for x, y, label in payload.observable_points:
        mesh_ax.scatter(
            [x],
            [y],
            s=34,
            c="#111827",
            marker="o",
            edgecolors="white",
            linewidths=0.8,
        )
        mesh_ax.text(x, y, f" {label}", fontsize=7, color="#111827", va="center")
    mesh_ax.set_title(
        "Spatial support, topography, boundaries", fontsize=_TITLE_FONT_SIZE
    )
    mesh_ax.set_aspect("equal", adjustable="box")
    mesh_ax.tick_params(labelsize=_TICK_FONT_SIZE)
    if payload.boundary_sides:
        mesh_ax.legend(loc="upper right", fontsize=7, frameon=True)

    if payload.recharge_values is not None and payload.recharge_values.size > 0:
        values = np.asarray(payload.recharge_values, dtype=float).reshape(-1)
        recharge_ax.step(
            np.arange(values.size), values, where="post", color="#0f766e", linewidth=1.8
        )
        recharge_ax.fill_between(
            np.arange(values.size),
            values,
            step="post",
            color="#99f6e4",
            alpha=0.45,
        )
        recharge_ax.set_ylabel(
            payload.recharge_unit or "recharge", fontsize=_LABEL_FONT_SIZE
        )
        recharge_ax.set_xlabel("forcing record", fontsize=_LABEL_FONT_SIZE)
    else:
        recharge_ax.text(
            0.5, 0.5, "No recharge forcing found", ha="center", va="center"
        )
    recharge_ax.set_title("Recharge forcing", fontsize=_TITLE_FONT_SIZE)
    recharge_ax.grid(True, alpha=0.18, linewidth=0.6)
    recharge_ax.tick_params(labelsize=_TICK_FONT_SIZE)

    meta_ax.axis("off")
    meta_text = "\n".join(
        [*payload.metadata_lines, "", "simulations:", *payload.simulation_lines]
    )
    meta_ax.text(
        0.02,
        0.98,
        meta_text,
        ha="left",
        va="top",
        fontsize=9,
        family="monospace",
        linespacing=1.35,
    )
    meta_ax.set_title("Case metadata", fontsize=_TITLE_FONT_SIZE, loc="left")

    semantics_ax.axis("off")
    boundary_text = "\n".join(
        f"- {label} ({side})" for side, label in payload.boundary_sides
    )
    if not boundary_text:
        boundary_text = "- no side Dirichlet boundary detected"
    semantics = (
        "Interpretation notes\n\n"
        "Boundary conditions:\n"
        f"{boundary_text}\n\n"
        "For MF6/Boussinesq comparisons, inspect budgets before judging head differences:\n"
        "- fixed-head support can change effective recharge support,\n"
        "- Boussinesq reports prescribed-head outflow explicitly,\n"
        "- metrics are aligned on physical elapsed time."
    )
    semantics_ax.text(
        0.02,
        0.98,
        semantics,
        ha="left",
        va="top",
        fontsize=9,
        linespacing=1.35,
    )
    semantics_ax.set_title(
        "Comparison semantics", fontsize=_TITLE_FONT_SIZE, loc="left"
    )

    figure.suptitle(
        f"Comparison case configuration: {payload.comparison_id}", fontsize=13, y=0.985
    )
    figure.subplots_adjust(
        left=0.06, right=0.98, top=0.92, bottom=0.07, hspace=0.32, wspace=0.2
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return True


def _write_map_comparison_figure(
    *,
    path: Path,
    observable_name: str,
    payloads: list[MapPayload],
) -> None:
    limits = _robust_limits(payload.values for payload in payloads)
    if limits is None:
        limits = _finite_limits(payload.values for payload in payloads)
    if limits is None:
        return
    vmin, vmax = limits
    if math.isclose(vmin, vmax):
        delta = abs(vmin) * 0.05 or 1.0
        vmin -= delta
        vmax += delta

    ncols = min(2, len(payloads))
    nrows = int(math.ceil(len(payloads) / float(ncols)))
    figure, axes = plt.subplots(
        nrows,
        ncols,
        figsize=(4.6 * ncols, 4.1 * nrows + 0.7),
        squeeze=False,
    )
    axes_array = np.asarray(axes, dtype=object).ravel()
    artist = None
    used_axes = axes_array[: len(payloads)].tolist()
    for ax, payload in zip(used_axes, payloads, strict=False):
        artist = _render_map_subplot(ax, payload, cmap="viridis", vmin=vmin, vmax=vmax)
        ax.set_title(
            _simulation_panel_title(
                simulation_id=payload.simulation_id,
                simulation_label=payload.simulation_label,
                solver=payload.solver or payload.mesh_mode,
            ),
            fontsize=_PANEL_TITLE_FONT_SIZE,
            pad=6,
        )
    for ax in axes_array[len(payloads) :]:
        ax.set_visible(False)
    if artist is not None:
        colorbar = figure.colorbar(
            artist,
            ax=used_axes,
            orientation="horizontal",
            pad=0.06,
            fraction=0.05,
            aspect=40,
        )
        colorbar.set_label(
            payloads[0].unit or "value",
            fontsize=_LABEL_FONT_SIZE,
            labelpad=4,
        )
        colorbar.ax.tick_params(labelsize=_TICK_FONT_SIZE)
    figure.suptitle(
        f"{_pretty_label(observable_name)} [{payloads[0].unit or 'native'}]  {payloads[0].time_label}",
        fontsize=_TITLE_FONT_SIZE,
        y=0.97,
    )
    figure.subplots_adjust(
        left=0.03,
        right=0.98,
        top=0.84,
        bottom=0.14,
        wspace=0.05,
        hspace=0.12,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)


def _write_difference_figure(
    *,
    path: Path,
    payload: DifferencePayload,
) -> None:
    vmax = _robust_symmetric_limit([payload.values])
    if vmax is None:
        limits = _finite_limits([payload.values])
        if limits is None:
            return
        vmax = max(abs(limits[0]), abs(limits[1]))
    if not math.isfinite(vmax) or math.isclose(vmax, 0.0):
        vmax = 1.0

    figure, ax = plt.subplots(1, 1, figsize=(5.3, 4.8))
    artist = _render_difference_subplot(ax, payload, cmap="coolwarm", vmax=vmax)
    ax.set_title(
        f"{payload.candidate_simulation} minus {payload.reference_simulation}",
        fontsize=_PANEL_TITLE_FONT_SIZE,
        pad=6,
    )
    colorbar = figure.colorbar(
        artist,
        ax=ax,
        orientation="horizontal",
        pad=0.08,
        fraction=0.06,
        aspect=40,
    )
    colorbar.set_label(
        payload.unit or "difference", fontsize=_LABEL_FONT_SIZE, labelpad=4
    )
    colorbar.ax.tick_params(labelsize=_TICK_FONT_SIZE)
    figure.suptitle(
        f"{_pretty_label(payload.observable_name)} difference",
        fontsize=_TITLE_FONT_SIZE,
        y=0.96,
    )
    figure.subplots_adjust(left=0.04, right=0.98, top=0.84, bottom=0.16)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)


def _write_map_triptych_figure(
    *,
    path: Path,
    reference: MapPayload,
    candidate: MapPayload,
    difference: DifferencePayload,
) -> bool:
    limits = _robust_limits([reference.values, candidate.values])
    if limits is None:
        limits = _finite_limits([reference.values, candidate.values])
    if limits is None:
        return False
    vmin, vmax = limits
    if math.isclose(vmin, vmax):
        delta = abs(vmin) * 0.05 or 1.0
        vmin -= delta
        vmax += delta

    diff_vmax = _robust_symmetric_limit([difference.values])
    if diff_vmax is None:
        diff_limits = _finite_limits([difference.values])
        if diff_limits is None:
            return False
        diff_vmax = max(abs(diff_limits[0]), abs(diff_limits[1]))
    if not math.isfinite(diff_vmax) or math.isclose(diff_vmax, 0.0):
        diff_vmax = 1.0

    figure, axes = plt.subplots(1, 3, figsize=(13.8, 4.9), squeeze=False)
    ref_ax, cand_ax, diff_ax = np.asarray(axes, dtype=object).ravel().tolist()
    ref_artist = _render_map_subplot(
        ref_ax, reference, cmap="viridis", vmin=vmin, vmax=vmax
    )
    _render_map_subplot(cand_ax, candidate, cmap="viridis", vmin=vmin, vmax=vmax)
    diff_artist = _render_difference_subplot(
        diff_ax,
        difference,
        cmap="coolwarm",
        vmax=diff_vmax,
    )
    ref_ax.set_title(
        _simulation_panel_title(
            simulation_id=reference.simulation_id,
            simulation_label=reference.simulation_label,
            solver=reference.solver or reference.mesh_mode,
        ),
        fontsize=_PANEL_TITLE_FONT_SIZE,
        pad=6,
    )
    cand_ax.set_title(
        _simulation_panel_title(
            simulation_id=candidate.simulation_id,
            simulation_label=candidate.simulation_label,
            solver=candidate.solver or candidate.mesh_mode,
        ),
        fontsize=_PANEL_TITLE_FONT_SIZE,
        pad=6,
    )
    diff_ax.set_title(
        f"{candidate.simulation_id} minus {reference.simulation_id}",
        fontsize=_PANEL_TITLE_FONT_SIZE,
        pad=6,
    )
    value_colorbar = figure.colorbar(
        ref_artist,
        ax=[ref_ax, cand_ax],
        orientation="horizontal",
        pad=0.08,
        fraction=0.055,
        aspect=38,
    )
    value_colorbar.set_label(
        reference.unit or "value", fontsize=_LABEL_FONT_SIZE, labelpad=4
    )
    value_colorbar.ax.tick_params(labelsize=_TICK_FONT_SIZE)
    diff_colorbar = figure.colorbar(
        diff_artist,
        ax=diff_ax,
        orientation="horizontal",
        pad=0.08,
        fraction=0.055,
        aspect=28,
    )
    diff_colorbar.set_label(
        reference.unit or "difference", fontsize=_LABEL_FONT_SIZE, labelpad=4
    )
    diff_colorbar.ax.tick_params(labelsize=_TICK_FONT_SIZE)
    figure.suptitle(
        f"{_pretty_label(reference.observable_name)} [{reference.unit or 'native'}]  "
        f"{reference.time_label}",
        fontsize=_TITLE_FONT_SIZE,
        y=0.97,
    )
    figure.subplots_adjust(left=0.03, right=0.98, top=0.84, bottom=0.18, wspace=0.08)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return True


def _write_regridded_map_figure(
    *,
    path: Path,
    observable_name: str,
    arrays: list[tuple[MapPayload, np.ndarray]],
    extent: tuple[float, float, float, float],
) -> bool:
    limits = _robust_limits(array for _, array in arrays)
    if limits is None:
        limits = _finite_limits(array for _, array in arrays)
    if limits is None:
        return False
    vmin, vmax = limits
    if math.isclose(vmin, vmax):
        delta = abs(vmin) * 0.05 or 1.0
        vmin -= delta
        vmax += delta
    ncols = min(2, len(arrays))
    nrows = int(math.ceil(len(arrays) / float(ncols)))
    figure, axes = plt.subplots(
        nrows, ncols, figsize=(4.8 * ncols, 4.1 * nrows + 0.7), squeeze=False
    )
    axes_array = np.asarray(axes, dtype=object).ravel()
    artist = None
    for ax, (payload, array) in zip(axes_array, arrays, strict=False):
        artist = ax.imshow(
            array,
            origin="lower",
            extent=extent,
            cmap="viridis",
            vmin=vmin,
            vmax=vmax,
            aspect="equal",
        )
        _style_map_axes(ax)
        ax.set_title(
            _simulation_panel_title(
                simulation_id=payload.simulation_id,
                simulation_label=payload.simulation_label,
                solver=payload.solver or payload.mesh_mode,
            ),
            fontsize=_PANEL_TITLE_FONT_SIZE,
            pad=6,
        )
    for ax in axes_array[len(arrays) :]:
        ax.set_visible(False)
    if artist is not None:
        colorbar = figure.colorbar(
            artist,
            ax=axes_array[: len(arrays)].tolist(),
            orientation="horizontal",
            pad=0.06,
            fraction=0.05,
            aspect=40,
        )
        colorbar.set_label(
            arrays[0][0].unit or "value", fontsize=_LABEL_FONT_SIZE, labelpad=4
        )
        colorbar.ax.tick_params(labelsize=_TICK_FONT_SIZE)
    figure.suptitle(
        f"{_pretty_label(observable_name)} on fine raster",
        fontsize=_TITLE_FONT_SIZE,
        y=0.97,
    )
    figure.subplots_adjust(
        left=0.03, right=0.98, top=0.84, bottom=0.14, wspace=0.05, hspace=0.12
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return True


def _write_regridded_difference_figure(
    *,
    path: Path,
    observable_name: str,
    candidate_simulation: str,
    reference_simulation: str,
    array: np.ndarray,
    unit: str,
    extent: tuple[float, float, float, float],
) -> bool:
    vmax = _robust_symmetric_limit([array])
    if vmax is None:
        limits = _finite_limits([array])
        if limits is None:
            return False
        vmax = max(abs(limits[0]), abs(limits[1]))
    if not math.isfinite(vmax) or math.isclose(vmax, 0.0):
        vmax = 1.0
    figure, ax = plt.subplots(1, 1, figsize=(5.4, 4.8))
    artist = ax.imshow(
        array,
        origin="lower",
        extent=extent,
        cmap="coolwarm",
        vmin=-vmax,
        vmax=vmax,
        aspect="equal",
    )
    _style_map_axes(ax)
    ax.set_title(
        f"{candidate_simulation} minus {reference_simulation}",
        fontsize=_PANEL_TITLE_FONT_SIZE,
        pad=6,
    )
    colorbar = figure.colorbar(
        artist,
        ax=ax,
        orientation="horizontal",
        pad=0.08,
        fraction=0.06,
        aspect=40,
    )
    colorbar.set_label(unit or "difference", fontsize=_LABEL_FONT_SIZE, labelpad=4)
    colorbar.ax.tick_params(labelsize=_TICK_FONT_SIZE)
    figure.suptitle(
        f"{_pretty_label(observable_name)} fine-raster difference",
        fontsize=_TITLE_FONT_SIZE,
        y=0.96,
    )
    figure.subplots_adjust(left=0.04, right=0.98, top=0.84, bottom=0.16)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return True


def _write_regridded_triptych_figure(
    *,
    path: Path,
    observable_name: str,
    reference_payload: MapPayload,
    candidate_payload: MapPayload,
    reference_array: np.ndarray,
    candidate_array: np.ndarray,
    extent: tuple[float, float, float, float],
) -> bool:
    limits = _robust_limits([reference_array, candidate_array])
    if limits is None:
        limits = _finite_limits([reference_array, candidate_array])
    if limits is None:
        return False
    vmin, vmax = limits
    if math.isclose(vmin, vmax):
        delta = abs(vmin) * 0.05 or 1.0
        vmin -= delta
        vmax += delta

    difference_array = np.asarray(candidate_array - reference_array, dtype=float)
    diff_vmax = _robust_symmetric_limit([difference_array])
    if diff_vmax is None:
        diff_limits = _finite_limits([difference_array])
        if diff_limits is None:
            return False
        diff_vmax = max(abs(diff_limits[0]), abs(diff_limits[1]))
    if not math.isfinite(diff_vmax) or math.isclose(diff_vmax, 0.0):
        diff_vmax = 1.0

    figure, axes = plt.subplots(1, 3, figsize=(13.8, 4.9), squeeze=False)
    ref_ax, cand_ax, diff_ax = np.asarray(axes, dtype=object).ravel().tolist()
    ref_artist = ref_ax.imshow(
        reference_array,
        origin="lower",
        extent=extent,
        cmap="viridis",
        vmin=vmin,
        vmax=vmax,
        aspect="equal",
    )
    cand_ax.imshow(
        candidate_array,
        origin="lower",
        extent=extent,
        cmap="viridis",
        vmin=vmin,
        vmax=vmax,
        aspect="equal",
    )
    diff_artist = diff_ax.imshow(
        difference_array,
        origin="lower",
        extent=extent,
        cmap="coolwarm",
        vmin=-diff_vmax,
        vmax=diff_vmax,
        aspect="equal",
    )
    for ax in (ref_ax, cand_ax, diff_ax):
        _style_map_axes(ax)
    ref_ax.set_title(
        _simulation_panel_title(
            simulation_id=reference_payload.simulation_id,
            simulation_label=reference_payload.simulation_label,
            solver=reference_payload.solver or reference_payload.mesh_mode,
        ),
        fontsize=_PANEL_TITLE_FONT_SIZE,
        pad=6,
    )
    cand_ax.set_title(
        _simulation_panel_title(
            simulation_id=candidate_payload.simulation_id,
            simulation_label=candidate_payload.simulation_label,
            solver=candidate_payload.solver or candidate_payload.mesh_mode,
        ),
        fontsize=_PANEL_TITLE_FONT_SIZE,
        pad=6,
    )
    diff_ax.set_title(
        f"{candidate_payload.simulation_id} minus {reference_payload.simulation_id}",
        fontsize=_PANEL_TITLE_FONT_SIZE,
        pad=6,
    )
    value_colorbar = figure.colorbar(
        ref_artist,
        ax=[ref_ax, cand_ax],
        orientation="horizontal",
        pad=0.08,
        fraction=0.055,
        aspect=38,
    )
    value_colorbar.set_label(
        reference_payload.unit or "value",
        fontsize=_LABEL_FONT_SIZE,
        labelpad=4,
    )
    value_colorbar.ax.tick_params(labelsize=_TICK_FONT_SIZE)
    diff_colorbar = figure.colorbar(
        diff_artist,
        ax=diff_ax,
        orientation="horizontal",
        pad=0.08,
        fraction=0.055,
        aspect=28,
    )
    diff_colorbar.set_label(
        reference_payload.unit or "difference",
        fontsize=_LABEL_FONT_SIZE,
        labelpad=4,
    )
    diff_colorbar.ax.tick_params(labelsize=_TICK_FONT_SIZE)
    figure.suptitle(
        f"{_pretty_label(observable_name)} on fine raster [{reference_payload.unit or 'native'}]",
        fontsize=_TITLE_FONT_SIZE,
        y=0.97,
    )
    figure.subplots_adjust(left=0.03, right=0.98, top=0.84, bottom=0.18, wspace=0.08)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return True


def _write_geotiff(
    *,
    path: Path,
    array: np.ndarray,
    extent: tuple[float, float, float, float],
) -> bool:
    if rasterio is None:
        return False
    xmin, xmax, ymin, ymax = extent
    height, width = array.shape
    if height <= 0 or width <= 0:
        return False
    resolution_x = (xmax - xmin) / float(width)
    resolution_y = (ymax - ymin) / float(height)
    if resolution_x <= 0.0 or resolution_y <= 0.0:
        return False
    data = np.asarray(array, dtype="float32")
    nodata_value = np.float32(-9999.0)
    data_to_write = np.where(np.isfinite(data), data, nodata_value)
    transform = from_origin(xmin, ymax, resolution_x, resolution_y)
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="float32",
        transform=transform,
        crs="EPSG:2154",
        nodata=float(nodata_value),
    ) as dataset:
        dataset.write(data_to_write, 1)
    return True
