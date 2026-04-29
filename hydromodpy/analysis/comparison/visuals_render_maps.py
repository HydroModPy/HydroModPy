"""2D map renderers for comparison visuals."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np

from hydromodpy.analysis.comparison.visuals_payloads import DifferencePayload, MapPayload
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
    _variant_panel_title,
)

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

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

    image = _mask_nodata(np.asarray(payload.values, dtype=float)).reshape(payload.structured_shape)
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

    image = _mask_nodata(np.asarray(payload.values, dtype=float)).reshape(payload.structured_shape)
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
            _variant_panel_title(
                variant_id=payload.variant_id,
                variant_label=payload.variant_label,
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
        f"{payload.candidate_variant} minus {payload.reference_variant}",
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
    colorbar.set_label(payload.unit or "difference", fontsize=_LABEL_FONT_SIZE, labelpad=4)
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
            _variant_panel_title(
                variant_id=payload.variant_id,
                variant_label=payload.variant_label,
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
        colorbar.set_label(arrays[0][0].unit or "value", fontsize=_LABEL_FONT_SIZE, labelpad=4)
        colorbar.ax.tick_params(labelsize=_TICK_FONT_SIZE)
    figure.suptitle(
        f"{_pretty_label(observable_name)} on fine raster",
        fontsize=_TITLE_FONT_SIZE,
        y=0.97,
    )
    figure.subplots_adjust(left=0.03, right=0.98, top=0.84, bottom=0.14, wspace=0.05, hspace=0.12)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return True


def _write_regridded_difference_figure(
    *,
    path: Path,
    observable_name: str,
    candidate_variant: str,
    reference_variant: str,
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
        f"{candidate_variant} minus {reference_variant}",
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
