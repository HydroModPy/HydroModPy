"""Native-mesh export helpers (NPZ / CSV / VTU / PNG)."""

from __future__ import annotations

import csv
import os
from collections.abc import Mapping
from pathlib import Path

import numpy as np

from hydromodpy.core.io import filesystem
from hydromodpy.core.logging import get_logger
from hydromodpy.solver.modflow_common.options import ModflowPostprocessOptions

from ._models import NODATA, FlowPostprocessModel

logger = get_logger(__name__)


def _windows_extended_length_path(path: Path) -> str:
    if os.name != "nt":
        return str(path)
    normalized = str(path.resolve())
    if normalized.startswith("\\\\?\\"):
        return normalized
    if normalized.startswith("\\\\"):
        return "\\\\?\\UNC\\" + normalized.lstrip("\\")
    return "\\\\?\\" + normalized


def native_mesh_exports_enabled(options: ModflowPostprocessOptions) -> bool:
    """Return True when one native mesh export format is enabled."""
    return bool(
        getattr(options, "native_mesh_npz", False)
        or getattr(options, "native_mesh_csv", False)
        or getattr(options, "native_mesh_vtu", False)
        or getattr(options, "native_mesh_png", False)
    )


def native_cell_series_payload(
    model: FlowPostprocessModel,
    *,
    datasets: Mapping[str, Mapping[int, np.ndarray]],
) -> dict[str, np.ndarray]:
    """Normalize time-indexed cell datasets to stacked `(ntime, ncpl)` arrays."""
    payload: dict[str, np.ndarray] = {}
    for name, data_by_time in datasets.items():
        if not data_by_time:
            continue
        stacked_rows: list[np.ndarray] = []
        for _, values in sorted(data_by_time.items(), key=lambda item: int(item[0])):
            flat = np.asarray(
                model.solver_mesh.flatten_from_grid(np.asarray(values)),
                dtype=float,
            ).reshape(-1)
            if flat.size != int(model.ncpl):
                continue
            stacked_rows.append(flat)
        if stacked_rows:
            payload[str(name)] = np.vstack(stacked_rows).astype(float, copy=False)
    return payload


def export_native_mesh_outputs(
    model: FlowPostprocessModel,
    *,
    options: ModflowPostprocessOptions,
    times: list[float] | tuple[float, ...],
    datasets: Mapping[str, Mapping[int, np.ndarray]],
    prefix: str,
) -> None:
    """Write native mesh exports (NPZ, CSV, VTU, PNG) for cell-based outputs."""
    if not native_mesh_exports_enabled(options):
        return

    cell_series = native_cell_series_payload(model, datasets=datasets)
    if not cell_series:
        return

    mesh_dir = os.path.join(model.save_file, "_mesh")
    filesystem.create_folder(mesh_dir)
    time_index = np.arange(len(times), dtype=int)
    times_array = np.asarray(times, dtype=float)
    cell_ids = np.arange(int(model.ncpl), dtype=int)

    if getattr(options, "native_mesh_npz", False):
        _write_npz(mesh_dir, prefix, cell_series, time_index, times_array, cell_ids)

    if getattr(options, "native_mesh_csv", False):
        _write_csv(mesh_dir, prefix, cell_series, times_array)

    if getattr(options, "native_mesh_vtu", False):
        _write_vtu(model, mesh_dir, prefix, cell_series, cell_ids, times_array)

    if getattr(options, "native_mesh_png", False):
        _write_png(model, prefix, cell_series, times_array)


def _write_npz(
    mesh_dir: str,
    prefix: str,
    cell_series: dict[str, np.ndarray],
    time_index: np.ndarray,
    times_array: np.ndarray,
    cell_ids: np.ndarray,
) -> None:
    for name, values in cell_series.items():
        np.savez_compressed(
            os.path.join(mesh_dir, f"{prefix}_{name}.npz"),
            time_index=time_index,
            times=times_array,
            cell_ids=cell_ids,
            values=values,
        )


def _write_csv(
    mesh_dir: str,
    prefix: str,
    cell_series: dict[str, np.ndarray],
    times_array: np.ndarray,
) -> None:
    for name, values in cell_series.items():
        csv_path = os.path.join(mesh_dir, f"{prefix}_{name}.csv")
        with open(csv_path, "w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["time_index", "time", "cell_id", "value"])
            for tidx, time_value in enumerate(times_array.tolist()):
                for cell_id, cell_value in enumerate(values[tidx].tolist()):
                    writer.writerow([int(tidx), float(time_value), int(cell_id), float(cell_value)])


def _write_vtu(
    model: FlowPostprocessModel,
    mesh_dir: str,
    prefix: str,
    cell_series: dict[str, np.ndarray],
    cell_ids: np.ndarray,
    times_array: np.ndarray,
) -> None:
    try:
        from hydromodpy.spatial.mesh.io import write_vtu

        for tidx, _time_value in enumerate(times_array.tolist()):
            cell_fields: dict[str, np.ndarray] = {
                "cell_id": cell_ids.astype(float, copy=False),
                "top_elevation": np.asarray(model.solver_mesh.top, dtype=float).reshape(-1),
            }
            for name, values in cell_series.items():
                cell_fields[str(name)] = np.asarray(values[tidx], dtype=float).reshape(-1)
            mesh_with_data = model.solver_mesh.planar_mesh.with_cell_data(**cell_fields)
            write_vtu(
                os.path.join(mesh_dir, f"{prefix}_t({int(tidx)}).vtu"),
                mesh_with_data,
            )
    except ImportError as exc:
        logger.warning("Skipping native mesh VTU export: %s", exc)


def _write_png(
    model: FlowPostprocessModel,
    prefix: str,
    cell_series: dict[str, np.ndarray],
    times_array: np.ndarray,
) -> None:
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    from matplotlib.ticker import ScalarFormatter
    from mpl_toolkits.axes_grid1 import make_axes_locatable

    from hydromodpy.spatial.mesh.plotting import plot_cell_values

    figure_dir = os.path.join(model.save_file, "_figures", "native_mesh")
    filesystem.create_folder(figure_dir)
    field_styles = {
        "watertable_elevation": ("Hydraulic head", "Head [m]", "viridis"),
        "watertable_depth": ("Water-table depth", "Top - h [m]", "Blues"),
        "seepage_areas": ("Seepage areas", "Seepage [m/day]", "Reds"),
        "outflow_drain": ("Drain discharge", "Discharge [m/day]", "magma"),
        "accumulation_flux": ("Accumulation flux", "Accumulated flow [m/day]", "plasma"),
        "concentration_seepage": ("Seepage concentration", "Concentration [-]", "viridis"),
        "mass_seepage": ("Seepage mass", "Mass [-]", "cividis"),
        "mass_accumulated": ("Accumulated mass", "Accumulated mass [-]", "inferno"),
    }

    for name, values in cell_series.items():
        for tidx, time_value in enumerate(times_array.tolist()):
            flat = np.asarray(values[tidx], dtype=float).reshape(-1).copy()
            flat[~np.isfinite(flat)] = np.nan
            flat[flat <= float(NODATA)] = np.nan
            finite = flat[np.isfinite(flat)]
            if finite.size == 0:
                continue

            vmin = float(np.nanmin(finite))
            vmax = float(np.nanmax(finite))
            if np.isclose(vmin, vmax):
                vmax = vmin + 1.0

            field_title, colorbar_label, cmap = field_styles.get(
                str(name),
                (str(name).replace("_", " ").title(), str(name).replace("_", " "), "viridis"),
            )
            fig, ax = plt.subplots(figsize=(7.2, 6.0), dpi=220)
            mappable = plot_cell_values(
                ax,
                model.solver_mesh.planar_mesh,
                flat,
                cmap=cmap,
                show_mesh=True,
                vmin=vmin,
                vmax=vmax,
            )
            ax.set_title(
                f"{field_title} | t={float(time_value):.12g} s",
                fontsize=10.5,
                loc="left",
                pad=5.0,
            )
            ax.set_xlabel("x (m)", fontsize=9)
            ax.set_ylabel("y (m)", fontsize=9)
            ax.ticklabel_format(style="plain", axis="both", useOffset=False)
            ax.tick_params(axis="both", labelsize=8, length=3.0, pad=2.0)

            divider = make_axes_locatable(ax)
            cax = divider.append_axes("right", size="3.8%", pad=0.06)
            cbar = fig.colorbar(mappable, cax=cax)
            cbar.set_label(colorbar_label, fontsize=8.5, labelpad=6.0)
            cbar.ax.tick_params(labelsize=7.5, length=2.5, pad=1.5)
            formatter = ScalarFormatter(useMathText=True)
            formatter.set_powerlimits((-2, 3))
            cbar.formatter = formatter
            cbar.update_ticks()

            fig.subplots_adjust(left=0.08, right=0.94, bottom=0.11, top=0.9)
            output_path = (
                Path(model.save_file)
                / "_figures"
                / "native_mesh"
                / f"{prefix}_{name}_t({int(tidx)}).png"
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(_windows_extended_length_path(output_path), bbox_inches="tight")
            plt.close(fig)
