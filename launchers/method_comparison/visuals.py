"""Visual comparison outputs for method-comparison runs."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import matplotlib
import numpy as np

from launchers.method_comparison.config import (
    MethodComparisonConfig,
    MethodComparisonObservableSchema,
    MethodComparisonVariantSchema,
)
from launchers.method_comparison.runtime import (
    CellCentroidTable,
    VariableSeries,
    load_variable_series,
    mask_depth_series_from_head_nodata,
    resolve_bundle_cells,
    resolve_structured_shape_from_config,
    resolve_structured_shape_from_run_folder,
    select_time_slices,
)

matplotlib.use("Agg")
import matplotlib.pyplot as plt


@dataclass(frozen=True, slots=True)
class MapPayload:
    """One rendered map payload for one observable and one variant."""

    variant_id: str
    variant_label: str
    solver: str
    mesh_mode: str
    observable_name: str
    resolved_variable: str
    unit: str
    time_label: str
    values: np.ndarray
    geometry_kind: str
    structured_shape: tuple[int, int] | None = None
    cell_ids: np.ndarray | None = None
    x: np.ndarray | None = None
    y: np.ndarray | None = None


@dataclass(frozen=True, slots=True)
class DifferencePayload:
    """One difference map aligned on a reference geometry."""

    reference_variant: str
    candidate_variant: str
    observable_name: str
    unit: str
    values: np.ndarray
    geometry_kind: str
    structured_shape: tuple[int, int] | None = None
    cell_ids: np.ndarray | None = None
    x: np.ndarray | None = None
    y: np.ndarray | None = None


_TITLE_FONT_SIZE = 10
_PANEL_TITLE_FONT_SIZE = 8
_LABEL_FONT_SIZE = 8
_TICK_FONT_SIZE = 7
_LEGEND_FONT_SIZE = 7


def _slug(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", str(value).strip().lower())
    return text.strip("_") or "item"


def _pretty_label(value: str) -> str:
    text = re.sub(r"[_]+", " ", str(value).strip())
    text = re.sub(r"\s+", " ", text).strip()
    return text[:1].upper() + text[1:] if text else "Value"


def _display_variant_label(*, variant_id: str, variant_label: str) -> str:
    text = variant_label.strip() or variant_id.strip()
    if len(text) <= 26:
        return text
    return variant_id.strip() or text


def _variant_panel_title(*, variant_id: str, variant_label: str, solver: str) -> str:
    label = _display_variant_label(variant_id=variant_id, variant_label=variant_label)
    solver_text = str(solver).strip().lower()
    if not solver_text:
        return label
    return f"{label}\n{solver_text}"


def _style_map_axes(ax: Any) -> None:
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_xlabel("")
    ax.set_ylabel("")
    for spine in ax.spines.values():
        spine.set_linewidth(0.6)
        spine.set_color("#9ca3af")


def _legend_ncols(n_items: int) -> int:
    if n_items <= 1:
        return 1
    if n_items <= 4:
        return 2
    return 3


def _safe_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        number = float(value)
    except Exception:
        return None
    if not math.isfinite(number):
        return None
    return number


def _mask_nodata(values: np.ndarray) -> np.ndarray:
    masked = np.asarray(values, dtype=float).copy()
    if masked.size == 0:
        return masked
    for sentinel in (-9999.0, -99999.0, -999999.0):
        masked[np.isclose(masked, sentinel, rtol=0.0, atol=1.0e-6)] = np.nan
    return masked


def _finite_limits(values: Iterable[np.ndarray]) -> tuple[float, float] | None:
    arrays = [
        _mask_nodata(np.asarray(item, dtype=float)).ravel()
        for item in values
        if np.asarray(item, dtype=float).size > 0
    ]
    if not arrays:
        return None
    stacked = np.concatenate(arrays)
    finite = stacked[np.isfinite(stacked)]
    if finite.size == 0:
        return None
    return float(np.nanmin(finite)), float(np.nanmax(finite))


def _choose_map_slice(
    *,
    series: VariableSeries,
    observable: MethodComparisonObservableSchema,
) -> tuple[np.ndarray, str] | None:
    slices = select_time_slices(series, observable)
    if not slices:
        return None
    if len(slices) == 1:
        chosen = slices[0]
    elif observable.time_reducer is not None:
        reducer_key = str(observable.time_reducer).strip().lower()
        if reducer_key == "first":
            chosen = slices[0]
        elif reducer_key == "last":
            chosen = slices[-1]
        else:
            return None
    else:
        return None
    return np.asarray(chosen.values, dtype=float).ravel(), str(chosen.time_key)


def _build_map_payload(
    *,
    cfg: MethodComparisonConfig,
    variant: MethodComparisonVariantSchema,
    summary: dict[str, Any],
    observable: MethodComparisonObservableSchema,
    rows: list[dict[str, Any]],
) -> MapPayload | None:
    reducer_key = str(observable.reducer or "identity").strip().lower()
    if reducer_key not in {"", "identity"}:
        return None
    run_folder = summary.get("run_folder")
    if not run_folder:
        return None
    run_folder_path = Path(str(run_folder))
    series = load_variable_series(run_folder=run_folder_path, variable=observable.variable)
    series = mask_depth_series_from_head_nodata(run_folder=run_folder_path, series=series)
    selected = _choose_map_slice(series=series, observable=observable)
    if selected is None:
        return None
    values, time_label = selected
    if values.size == 0:
        return None

    unit = next(
        (
            str(row.get("unit", ""))
            for row in rows
            if str(row.get("variant_id", "")) == variant.id
            and str(row.get("observable", "")) == observable.name
            and str(row.get("unit", "")) != ""
        ),
        observable.unit or "",
    )

    cells = resolve_bundle_cells(run_folder_path)
    if cells is not None and cells.cell_ids.size == values.size:
        return MapPayload(
            variant_id=variant.id,
            variant_label=variant.label or variant.id,
            solver=variant.solver or "",
            mesh_mode=variant.mesh_mode,
            observable_name=observable.name,
            resolved_variable=series.variable_name,
            unit=unit,
            time_label=time_label,
            values=values,
            geometry_kind="scatter",
            cell_ids=np.asarray(cells.cell_ids, dtype=int),
            x=np.asarray(cells.x, dtype=float),
            y=np.asarray(cells.y, dtype=float),
        )

    config_path_raw = summary.get("config_path")
    config_path = None if config_path_raw in ("", None) else Path(str(config_path_raw))
    if config_path is None:
        config_path = cfg.resolve_variant_config_path(variant)
    structured_shape = (
        None
        if config_path is None or not config_path.exists()
        else resolve_structured_shape_from_config(
            config_path,
            solver_name=variant.solver,
        )
    )
    if structured_shape is None:
        structured_shape = resolve_structured_shape_from_run_folder(run_folder_path)
    if structured_shape is None:
        return None
    if values.size != structured_shape[0] * structured_shape[1]:
        return None
    return MapPayload(
        variant_id=variant.id,
        variant_label=variant.label or variant.id,
        solver=variant.solver or "",
        mesh_mode=variant.mesh_mode,
        observable_name=observable.name,
        resolved_variable=series.variable_name,
        unit=unit,
        time_label=time_label,
        values=values,
        geometry_kind="structured",
        structured_shape=structured_shape,
    )


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
    artist = ax.imshow(
        image,
        origin="lower",
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        aspect="auto",
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
    artist = ax.imshow(
        image,
        origin="lower",
        cmap=cmap,
        vmin=-vmax,
        vmax=vmax,
        aspect="auto",
    )
    _style_map_axes(ax)
    return artist


def _build_difference_payload(
    *,
    reference: MapPayload,
    candidate: MapPayload,
) -> DifferencePayload | None:
    if reference.unit != candidate.unit:
        return None

    if (
        reference.geometry_kind == "scatter"
        and candidate.geometry_kind == "scatter"
        and reference.cell_ids is not None
        and candidate.cell_ids is not None
    ):
        if reference.cell_ids.size != candidate.cell_ids.size:
            return None
        candidate_positions = {
            int(cell_id): index for index, cell_id in enumerate(candidate.cell_ids.tolist())
        }
        if any(int(cell_id) not in candidate_positions for cell_id in reference.cell_ids.tolist()):
            return None
        ordered = np.asarray(
            [candidate.values[candidate_positions[int(cell_id)]] for cell_id in reference.cell_ids],
            dtype=float,
        )
        reference_values = _mask_nodata(reference.values)
        candidate_values = _mask_nodata(ordered)
        return DifferencePayload(
            reference_variant=reference.variant_id,
            candidate_variant=candidate.variant_id,
            observable_name=reference.observable_name,
            unit=reference.unit,
            values=candidate_values - reference_values,
            geometry_kind="scatter",
            cell_ids=np.asarray(reference.cell_ids, dtype=int),
            x=np.asarray(reference.x, dtype=float),
            y=np.asarray(reference.y, dtype=float),
        )

    if (
        reference.geometry_kind == "structured"
        and candidate.geometry_kind == "structured"
        and reference.structured_shape == candidate.structured_shape
    ):
        reference_values = _mask_nodata(reference.values)
        candidate_values = _mask_nodata(candidate.values)
        return DifferencePayload(
            reference_variant=reference.variant_id,
            candidate_variant=candidate.variant_id,
            observable_name=reference.observable_name,
            unit=reference.unit,
            values=np.asarray(candidate_values - reference_values, dtype=float),
            geometry_kind="structured",
            structured_shape=reference.structured_shape,
        )
    return None


def _write_map_comparison_figure(
    *,
    path: Path,
    observable_name: str,
    payloads: list[MapPayload],
) -> None:
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
    for ax, payload in zip(used_axes, payloads):
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


def _write_timeseries_figure(
    *,
    path: Path,
    observable_name: str,
    unit: str,
    grouped_rows: list[dict[str, Any]],
) -> bool:
    variant_keys = {
        str(row.get("variant_id", ""))
        for row in grouped_rows
        if str(row.get("variant_id", "")) != ""
    }
    if len(variant_keys) < 2:
        return False

    use_elapsed_seconds = all(
        _safe_float(row.get("elapsed_seconds")) is not None for row in grouped_rows
    )
    x_label = "Elapsed time [s]" if use_elapsed_seconds else "Time index"

    series_payloads: dict[tuple[str, str, int], list[tuple[float, float]]] = {}
    for row in grouped_rows:
        value = _safe_float(row.get("value"))
        if value is None:
            continue
        x_value = (
            _safe_float(row.get("elapsed_seconds"))
            if use_elapsed_seconds
            else _safe_float(row.get("time_index"))
        )
        if x_value is None:
            continue
        key = (
            str(row.get("variant_id", "")),
            str(row.get("variant_label", row.get("variant_id", ""))),
            int(row.get("value_index", 0)),
        )
        series_payloads.setdefault(key, []).append((x_value, value))

    if not any(len(points) >= 2 for points in series_payloads.values()):
        return False

    figure, ax = plt.subplots(1, 1, figsize=(6.8, 3.9))
    for (variant_id, variant_label, value_index), points in sorted(series_payloads.items()):
        ordered = sorted(points, key=lambda item: item[0])
        if len(ordered) < 2:
            continue
        x_values = [item[0] for item in ordered]
        y_values = [item[1] for item in ordered]
        label = _display_variant_label(
            variant_id=variant_id,
            variant_label=variant_label or variant_id,
        )
        if any(
            other_value_index != value_index
            and other_variant_id == variant_id
            for (other_variant_id, _, other_value_index) in series_payloads
        ):
            label = f"{label} [{value_index}]"
        ax.plot(
            x_values,
            y_values,
            marker="o",
            linewidth=1.5,
            markersize=3.2,
            label=label,
        )

    if not ax.lines:
        plt.close(figure)
        return False
    ax.set_xlabel(x_label, fontsize=_LABEL_FONT_SIZE)
    ax.set_ylabel(unit or "value", fontsize=_LABEL_FONT_SIZE)
    ax.set_title(_pretty_label(observable_name), fontsize=_TITLE_FONT_SIZE, pad=8)
    ax.tick_params(labelsize=_TICK_FONT_SIZE)
    ax.grid(True, alpha=0.22, linewidth=0.6)
    ax.margins(x=0.03, y=0.08)
    legend = ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.21),
        ncol=_legend_ncols(len(ax.lines)),
        frameon=False,
        fontsize=_LEGEND_FONT_SIZE,
        handlelength=1.8,
        columnspacing=1.1,
        borderaxespad=0.0,
    )
    for line in legend.get_lines():
        line.set_linewidth(1.5)
    figure.subplots_adjust(left=0.11, right=0.98, top=0.86, bottom=0.29)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return True


def generate_comparison_figures(
    *,
    cfg: MethodComparisonConfig,
    variant_summaries: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    reference_variant: str | None,
    comparison_root: Path,
) -> list[dict[str, Any]]:
    """Generate best-effort PNG comparisons from extracted observables."""
    figure_root = comparison_root / "comparison_figures"
    figure_root.mkdir(parents=True, exist_ok=True)
    for existing_path in figure_root.glob("*"):
        if existing_path.is_file():
            try:
                existing_path.unlink()
            except OSError:
                pass

    completed_summaries = {
        str(summary.get("id", "")): summary
        for summary in variant_summaries
        if summary.get("status") in {"completed", "reused"}
    }
    variants = {
        variant.id: variant for variant in cfg.method_comparison.variant if variant.enabled
    }

    artifacts: list[dict[str, Any]] = []

    for observable in cfg.method_comparison.observable:
        if observable.support != "map":
            continue
        payloads: list[MapPayload] = []
        for variant_id, variant in variants.items():
            summary = completed_summaries.get(variant_id)
            if summary is None:
                continue
            try:
                payload = _build_map_payload(
                    cfg=cfg,
                    variant=variant,
                    summary=summary,
                    observable=observable,
                    rows=rows,
                )
            except Exception:
                payload = None
            if payload is not None:
                payloads.append(payload)

        if len(payloads) >= 2:
            map_path = figure_root / f"{_slug(observable.name)}__map_comparison.png"
            _write_map_comparison_figure(
                path=map_path,
                observable_name=observable.name,
                payloads=payloads,
            )
            if map_path.exists():
                artifacts.append(
                    {
                        "kind": "map_comparison",
                        "observable": observable.name,
                        "path": str(map_path),
                    }
                )

        if reference_variant is None:
            continue
        reference_payload = next(
            (payload for payload in payloads if payload.variant_id == reference_variant),
            None,
        )
        if reference_payload is None:
            continue
        for candidate in payloads:
            if candidate.variant_id == reference_variant:
                continue
            difference = _build_difference_payload(
                reference=reference_payload,
                candidate=candidate,
            )
            if difference is None:
                continue
            diff_path = figure_root / (
                f"{_slug(observable.name)}__difference__"
                f"{_slug(reference_variant)}__vs__{_slug(candidate.variant_id)}.png"
            )
            _write_difference_figure(path=diff_path, payload=difference)
            if diff_path.exists():
                artifacts.append(
                    {
                        "kind": "difference_map",
                        "observable": observable.name,
                        "reference_variant": reference_variant,
                        "candidate_variant": candidate.variant_id,
                        "path": str(diff_path),
                    }
                )

    grouped_rows: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        if str(row.get("support", "")) == "map":
            continue
        if str(row.get("comparison_time_key", "")) == "reduced":
            continue
        key = (str(row.get("observable", "")), str(row.get("unit", "")))
        grouped_rows.setdefault(key, []).append(row)

    for (observable_name, unit), grouped in sorted(grouped_rows.items()):
        series_path = figure_root / f"{_slug(observable_name)}__timeseries.png"
        if _write_timeseries_figure(
            path=series_path,
            observable_name=observable_name,
            unit=unit,
            grouped_rows=grouped,
        ):
            artifacts.append(
                {
                    "kind": "timeseries",
                    "observable": observable_name,
                    "unit": unit,
                    "path": str(series_path),
                }
            )

    return artifacts


__all__ = ("generate_comparison_figures",)
