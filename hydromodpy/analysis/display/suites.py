"""High-level orchestration — test-facing entry points.

This module mirrors :mod:`hydromodpy.analysis.display.orchestration` but is the
target that unit tests import and monkeypatch.  Keeping it separate
from orchestration avoids accidental import-path breakage in tests.
"""
from __future__ import annotations

from pathlib import Path
import shutil

import numpy as np
import pandas as pd

from hydromodpy.solver.boussinesq.history_contract import (
    step_end_elapsed_seconds_from_payload,
    step_history_from_history,
)
from hydromodpy.analysis.display.common import (
    _extract_recharge_series_m_per_day,
    resolve_flow_base_raster,
    resolve_model_figure_dir,
)
from hydromodpy.analysis.display.flow_payloads import (
    FlowSpatialFigurePayload,
    build_flow_cumulative_payload,
    build_flow_spatial_payload_from_model,
)
from hydromodpy.analysis.display.figures.animation import build_gif, build_plotly_slider
from hydromodpy.analysis.display.figures.boussinesq import (
    plot_boussinesq_diagnostics,
    plot_boussinesq_edge_flux_map,
    plot_boussinesq_state,
)
from hydromodpy.analysis.display.figures.cross_section import plot_cross_section
from hydromodpy.analysis.display.figures.flow_diagnostics import (
    plot_flow_mass_balance,
    plot_flow_probe_timeseries,
)
from hydromodpy.analysis.display.figures.flow_synthesis import (
    FLOW_SPATIAL_FIELD_SPECS,
    plot_flow_recharge_discharge_cumulative,
    plot_flow_spatial_field,
    plot_flow_state_triptych,
)
from hydromodpy.analysis.display.figures.maps import plot_pathlines_map
from hydromodpy.analysis.display.figures.timeseries import plot_discharge, plot_piezometry
from hydromodpy.analysis.display.options import DisplayOptions
from hydromodpy.analysis.display.transport_plots import plot_concentration_frames


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _resolve_flow_model(result):
    """Return the configured flow model using explicit solver lookup."""
    flow_model = result.get_model_for_solver("modflownwt")
    if flow_model is None:
        flow_model = result.get_model_for_solver("modflow6")
    return flow_model


def _resolve_boussinesq_model(result):
    """Return the configured Boussinesq flow model when present."""
    return result.get_model_for_solver("boussinesq")


def _is_unstructured_flow_model(flow_model) -> bool:
    """Return True when the active flow model uses an irregular planar mesh."""
    solver_mesh = getattr(flow_model, "solver_mesh", None)
    return bool(solver_mesh is not None and not getattr(solver_mesh, "is_structured", True))


def _native_mesh_figure_dir(model) -> Path | None:
    """Return the solver-native mesh figure directory when present."""
    full_path = getattr(model, "full_path", None)
    if full_path is None:
        return None
    figure_dir = Path(full_path) / "_postprocess" / "_figures" / "native_mesh"
    if not figure_dir.is_dir():
        return None
    return figure_dir


def _copy_latest_native_mesh_figures(
    native_dir: Path | None,
    output_dir: Path,
    *,
    mapping: list[tuple[str, str]],
) -> list[Path]:
    """Copy the latest native-mesh figures to the standard display directory."""
    if native_dir is None:
        return []
    copied: list[Path] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    for pattern, target_name in mapping:
        candidates = sorted(native_dir.glob(pattern))
        if not candidates:
            continue
        source = candidates[-1]
        target = output_dir / target_name
        shutil.copyfile(source, target)
        copied.append(target)
    return copied


def _resolve_boussinesq_triangles(mesh) -> np.ndarray:
    """Map mesh cell node ids to positional triangle indices."""
    return np.asarray(
        [
            [int(mesh.node_index_by_id[int(node_id)]) for node_id in node_ids]
            for node_ids in mesh.cell_node_ids
        ],
        dtype=int,
    )


def _load_boussinesq_state_payload(model) -> dict[str, np.ndarray]:
    """Load available Boussinesq state arrays from memory and optional disk."""
    payload: dict[str, np.ndarray] = {}
    state = getattr(model, "state", None)
    state_mapping = {
        "head_m": "final_head_m",
        "recharge_rate_m_s": "final_recharge_rate_m_s",
        "well_flux_m3_s": "final_well_flux_m3_s",
        "saturation_excess_rate_m_s": "final_saturation_excess_rate_m_s",
        "head_history_m": "head_history_m",
        "saturated_thickness_history_m": "saturated_thickness_history_m",
        "saturation_excess_history_m_s": "saturation_excess_history_m_s",
        "recharge_rate_history_m_s": "recharge_rate_history_m_s",
        "well_flux_history_m3_s": "well_flux_history_m3_s",
        "internal_edge_flux_m3_s": "internal_edge_flux_m3_s",
        "internal_edge_flux_history_m3_s": "internal_edge_flux_history_m3_s",
        "prescribed_head_flux_m3_s": "prescribed_head_flux_m3_s",
        "prescribed_head_flux_history_m3_s": "prescribed_head_flux_history_m3_s",
        "prescribed_head_m_by_cell": "prescribed_head_m_by_cell",
        "prescribed_head_history_m_by_cell": "prescribed_head_history_m_by_cell",
        "boundary_edge_flux_m3_s": "boundary_edge_flux_m3_s",
        "boundary_edge_flux_history_m3_s": "boundary_edge_flux_history_m3_s",
        "drainage_flux_m3_s": "drainage_flux_m3_s",
        "drainage_flux_history_m3_s": "drainage_flux_history_m3_s",
        "period_lengths_seconds": "period_lengths_seconds",
    }
    if state is not None:
        for attr_name, key in state_mapping.items():
            values = getattr(state, attr_name, None)
            if values is None:
                continue
            array = np.asarray(values, dtype=float)
            if array.size == 0:
                continue
            payload[key] = array.copy()

    full_path = getattr(model, "full_path", None)
    if full_path is None:
        return payload

    state_history_path = Path(full_path) / "_boussinesq_state_history.npz"
    if not state_history_path.exists():
        return payload

    with np.load(state_history_path) as npz_payload:
        for key in npz_payload.files:
            if key in payload:
                continue
            array = np.asarray(npz_payload[key], dtype=float)
            if array.size == 0:
                continue
            payload[key] = array
    return payload


def _resolve_boussinesq_head(model) -> np.ndarray | None:
    """Return the final Boussinesq head array from memory or disk."""
    payload = _load_boussinesq_state_payload(model)
    head = payload.get("final_head_m")
    if head is None:
        return None
    return np.asarray(head, dtype=float).reshape(-1)


def _resolve_boussinesq_edge_node_indices(mesh) -> tuple[np.ndarray, np.ndarray]:
    """Return edge endpoint indices aligned with node coordinate arrays."""
    return (
        np.asarray(
            [int(mesh.node_index_by_id[int(node_id)]) for node_id in mesh.edge_node_a],
            dtype=int,
        ),
        np.asarray(
            [int(mesh.node_index_by_id[int(node_id)]) for node_id in mesh.edge_node_b],
            dtype=int,
        ),
    )


def _boussinesq_time_axis_days(period_lengths_seconds: np.ndarray) -> np.ndarray:
    """Return the cumulative time at the end of each stress period in days."""
    payload = {"period_lengths_seconds": np.asarray(period_lengths_seconds, dtype=float)}
    elapsed_seconds = step_end_elapsed_seconds_from_payload(payload)
    if elapsed_seconds is None:
        return np.asarray([], dtype=float)
    return np.asarray(elapsed_seconds / 86_400.0, dtype=float)


def _align_boussinesq_step_history(values: np.ndarray | None, *, n_steps: int) -> np.ndarray | None:
    """Align one history array to one row per solved stress period."""
    if values is None:
        return None
    array = np.asarray(values, dtype=float)
    if array.size == 0:
        return None
    try:
        return step_history_from_history(
            array,
            n_steps=int(n_steps),
            name="boussinesq_step_history",
        )
    except ValueError:
        if array.ndim == 1:
            array = array.reshape(1, -1)
        if array.shape[0] > int(n_steps):
            return np.asarray(array[-int(n_steps) :], dtype=float)
        return None


def _select_boussinesq_probe_indices(mesh, *, max_probes: int = 5) -> np.ndarray:
    """Pick a few representative cells spanning the x-extent of the mesh."""
    x = np.asarray(mesh.cell_centroid_x_m, dtype=float).reshape(-1)
    y = np.asarray(mesh.cell_centroid_y_m, dtype=float).reshape(-1)
    n_cells = int(x.size)
    if n_cells == 0:
        return np.asarray([], dtype=int)
    n_probes = min(int(max_probes), n_cells)
    x_targets = np.linspace(float(np.min(x)), float(np.max(x)), n_probes)
    y_mid = 0.5 * (float(np.min(y)) + float(np.max(y)))
    chosen: list[int] = []
    for target_x in x_targets.tolist():
        distance = ((x - float(target_x)) ** 2) + ((y - y_mid) ** 2)
        for candidate in np.argsort(distance).tolist():
            if int(candidate) not in chosen:
                chosen.append(int(candidate))
                break
    return np.asarray(chosen, dtype=int)


def _build_boussinesq_probe_series(mesh, payload: dict[str, np.ndarray]) -> tuple[np.ndarray, dict[str, np.ndarray]] | None:
    """Build a compact set of representative probe head series."""
    period_lengths = np.asarray(payload.get("period_lengths_seconds", []), dtype=float).reshape(-1)
    head_history = payload.get("head_history_m")
    if head_history is None:
        return None
    history = np.asarray(head_history, dtype=float)
    if history.ndim == 1:
        history = history.reshape(1, -1)
    if history.shape[0] <= 1:
        return None

    probe_indices = _select_boussinesq_probe_indices(mesh)
    if probe_indices.size == 0:
        return None
    time_days = _boussinesq_time_axis_days(period_lengths)
    if time_days.size == 0 or history.shape[0] != int(time_days.size) + 1:
        time_days = np.arange(1, int(history.shape[0]), dtype=float)

    series_by_label: dict[str, np.ndarray] = {}
    x_values = np.asarray(mesh.cell_centroid_x_m, dtype=float).reshape(-1)
    y_values = np.asarray(mesh.cell_centroid_y_m, dtype=float).reshape(-1)
    for probe_index in probe_indices.tolist():
        series_by_label[
            f"Cell {int(mesh.cell_ids[probe_index])} (x={x_values[probe_index]:.0f}, y={y_values[probe_index]:.0f})"
        ] = np.asarray(history[1:, probe_index], dtype=float)
    return time_days, series_by_label


def _build_boussinesq_mass_balance(mesh, payload: dict[str, np.ndarray]):
    """Build signed mass-balance components for one transient Boussinesq run."""
    period_lengths = np.asarray(payload.get("period_lengths_seconds", []), dtype=float).reshape(-1)
    n_steps = int(period_lengths.size)
    if n_steps == 0:
        return None

    required_keys = (
        "head_history_m",
        "recharge_rate_history_m_s",
        "saturation_excess_history_m_s",
        "drainage_flux_history_m3_s",
    )
    if any(key not in payload for key in required_keys):
        return None
    if (
        "prescribed_head_flux_history_m3_s" not in payload
        and "boundary_edge_flux_history_m3_s" not in payload
    ):
        return None

    head_history = np.asarray(payload["head_history_m"], dtype=float)
    if head_history.ndim == 1:
        head_history = head_history.reshape(1, -1)
    if head_history.shape[0] < n_steps + 1:
        return None

    recharge_history = _align_boussinesq_step_history(
        payload.get("recharge_rate_history_m_s"),
        n_steps=n_steps,
    )
    saturation_excess_history = _align_boussinesq_step_history(
        payload.get("saturation_excess_history_m_s"),
        n_steps=n_steps,
    )
    well_history = _align_boussinesq_step_history(
        payload.get("well_flux_history_m3_s"),
        n_steps=n_steps,
    )
    boundary_head_history = _align_boussinesq_step_history(
        payload.get("prescribed_head_flux_history_m3_s"),
        n_steps=n_steps,
    )
    if boundary_head_history is None:
        boundary_head_history = _align_boussinesq_step_history(
            payload.get("boundary_edge_flux_history_m3_s"),
            n_steps=n_steps,
        )
    drainage_history = _align_boussinesq_step_history(
        payload.get("drainage_flux_history_m3_s"),
        n_steps=n_steps,
    )
    if (
        recharge_history is None
        or saturation_excess_history is None
        or boundary_head_history is None
        or drainage_history is None
    ):
        return None

    cell_area = np.asarray(mesh.cell_area_m2, dtype=float).reshape(1, -1)
    storage = (
        cell_area
        * np.asarray(mesh.storage_coefficient, dtype=float).reshape(1, -1)
        * (head_history[1 : n_steps + 1] - head_history[:n_steps])
        / period_lengths.reshape(-1, 1)
    ).sum(axis=1)
    recharge = (recharge_history * cell_area).sum(axis=1)
    saturation_excess = -(saturation_excess_history * cell_area).sum(axis=1)
    drainage = -np.asarray(drainage_history, dtype=float).sum(axis=1)
    boundary_head = -np.asarray(boundary_head_history, dtype=float).sum(axis=1)

    components = {
        "Recharge": recharge,
        "Head BC": boundary_head,
        "Drainage": drainage,
        "Sat. excess": saturation_excess,
        "Storage": -storage,
    }
    if well_history is not None:
        well_signed = np.asarray(well_history, dtype=float).sum(axis=1)
        if np.any(np.abs(well_signed) > 0.0):
            components["Wells"] = well_signed

    filtered_components = {
        name: series
        for name, series in components.items()
        if np.any(np.abs(np.asarray(series, dtype=float)) > 0.0)
    }
    if not filtered_components:
        return None
    net = np.zeros(n_steps, dtype=float)
    for series in filtered_components.values():
        net = net + np.asarray(series, dtype=float)
    return _boussinesq_time_axis_days(period_lengths), filtered_components, net


def _load_observed_streamflow(result) -> pd.DataFrame | None:
    """Load observed discharge from PointRecords."""
    from hydromodpy.analysis.display.adapters import observed_discharge_series

    hydrometry = getattr(result.loaded_data, "hydrometry", None)
    if not hydrometry:
        return None
    records = getattr(hydrometry, "points", hydrometry)
    if not records:
        return None
    area_m2 = float(result.setup.geographic.catch_area) * 1_000_000
    return observed_discharge_series(records, freq="ME", area_m2=area_m2)


def _load_flow_timeseries(result) -> pd.DataFrame | None:
    """Load the simulated flow time series exported by post-processing."""
    run_id = _resolve_flow_model(result).model_name
    smod_path = (
        result.setup.workspace.simulations_folder
        / run_id
        / "_postprocess"
        / "_timeseries"
        / "_simulated_timeseries.csv"
    )
    if not smod_path.exists():
        return None
    return pd.read_csv(smod_path, sep=";", index_col=0, parse_dates=True)


def _extract_cross_section_data(
    dem_path: Path,
    wt_path: Path,
    x_index: int | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Extract 1-D cross-section arrays from DEM and water-table files."""
    import rasterio

    watertable = np.load(wt_path, allow_pickle=True).item()
    with rasterio.open(dem_path) as dem_src:
        dem_data = dem_src.read(1)
        nodata = dem_src.nodata
        row_spacing = abs(float(dem_src.transform.e)) if dem_src.transform.e else 1.0

    wt = watertable[2].astype(float)
    dem = dem_data.astype(float)
    if nodata is not None:
        dem[np.isclose(dem, float(nodata))] = np.nan
    else:
        dem[dem < 0] = np.nan
    wt[wt < 0] = np.nan

    if x_index is None:
        x_index = dem.shape[1] // 2
    x_index = int(np.clip(x_index, 0, max(dem.shape[1] - 1, 0)))

    x_coords = np.arange(dem.shape[0], dtype=float) * row_spacing
    return dem[:, x_index], wt[:, x_index], x_coords


def _prepare_streamflow_series(
    simulated_timeseries: pd.DataFrame,
    factor: int = 30,
) -> tuple[pd.Series, pd.Series]:
    """Convert raw simulated timeseries to plotting-ready Series."""
    recharge = simulated_timeseries["recharge"] * factor * 1000
    outflow = (
        simulated_timeseries["outflow_drain"] + simulated_timeseries["runoff"]
    ) * factor * 1000
    return outflow, recharge


def _plot_common_flow_spatial_outputs(
    payload: FlowSpatialFigurePayload | None,
    *,
    options: DisplayOptions,
    output_dir: Path,
) -> bool:
    """Render generic flow spatial figures from the common payload."""
    if payload is None:
        return False

    has_dynamic_fields = any(
        getattr(payload, attr_name) is not None
        for attr_name in (
            "watertable_elevation_m",
            "watertable_depth_m",
            "seepage_areas_m_per_day",
            "outflow_drain_m_per_day",
            "accumulation_flux_m_per_day",
        )
    )

    if options.flow.is_enabled("state_triptych", default=True):
        plot_flow_state_triptych(
            payload=payload,
            options=options,
            save_path=output_dir / "flow_state_triptych.png",
        )

    if options.flow.is_enabled("watertable_map", default=True):
        for field_name, spec in FLOW_SPATIAL_FIELD_SPECS.items():
            if field_name == "top_elevation":
                continue
            values = getattr(payload, spec.attr_name)
            if values is None:
                continue
            plot_flow_spatial_field(
                payload=payload,
                field_name=field_name,
                options=options,
                save_path=output_dir / f"{field_name}.png",
            )

    return has_dynamic_fields


# ------------------------------------------------------------------
# Suites
# ------------------------------------------------------------------

def plot_flow_suite(result, options: DisplayOptions) -> None:
    """Run all enabled flow figures for one completed simulation result."""
    if not options.should_render():
        return

    flow_model = _resolve_flow_model(result)
    run_id = flow_model.model_name
    output_dir = resolve_model_figure_dir(result.setup.workspace, run_id)
    is_unstructured = _is_unstructured_flow_model(flow_model)
    need_simulated_timeseries = any(
        [
            options.flow.is_enabled("streamflow", default=True),
            options.flow.is_enabled("piezometry", default=True),
            options.flow.is_enabled("recharge_discharge_cumulative", default=True),
        ]
    )
    simulated_timeseries = (
        _load_flow_timeseries(result) if need_simulated_timeseries else None
    )
    observed_streamflow = (
        _load_observed_streamflow(result)
        if options.flow.is_enabled("streamflow", default=True)
        else None
    )
    spatial_payload = build_flow_spatial_payload_from_model(flow_model)
    cumulative_payload = (
        build_flow_cumulative_payload(simulated_timeseries, run_id=run_id)
        if simulated_timeseries is not None
        else None
    )

    rendered_common_spatial = _plot_common_flow_spatial_outputs(
        spatial_payload,
        options=options,
        output_dir=output_dir,
    )

    if cumulative_payload is not None and options.flow.is_enabled(
        "recharge_discharge_cumulative",
        default=True,
    ):
        plot_flow_recharge_discharge_cumulative(
            payload=cumulative_payload,
            options=options,
            save_path=output_dir / "recharge_discharge_cumulative.png",
        )

    if is_unstructured:
        _copy_latest_native_mesh_figures(
            _native_mesh_figure_dir(flow_model),
            output_dir,
            mapping=[
                ("flow_support_overview.png", "flow_support_overview.png"),
            ],
        )
        if not rendered_common_spatial:
            _copy_latest_native_mesh_figures(
                _native_mesh_figure_dir(flow_model),
                output_dir,
                mapping=[
                    ("flow_watertable_depth_t(*).png", "watertable_depth.png"),
                    ("flow_watertable_elevation_t(*).png", "watertable_elevation.png"),
                    ("flow_seepage_areas_t(*).png", "seepage_areas.png"),
                    ("flow_outflow_drain_t(*).png", "outflow_drain.png"),
                    ("flow_accumulation_flux_t(*).png", "accumulation_flux.png"),
                ],
            )

    if options.flow.is_enabled("cross_section", default=True) and not is_unstructured:
        base_raster = resolve_flow_base_raster(flow_model, result.setup.geographic)
        wt_path = (
            result.setup.workspace.simulations_folder
            / run_id
            / "_postprocess"
            / "watertable_elevation.npy"
        )
        dem_section, wt_section, x_coords = _extract_cross_section_data(
            base_raster, wt_path,
        )
        plot_cross_section(
            dem_section=dem_section,
            wt_section=wt_section,
            x_coords=x_coords,
            options=options,
            save_path=output_dir / "cross_section.png",
        )

    if (
        options.flow.is_enabled("streamflow", default=True)
        and observed_streamflow is not None
        and simulated_timeseries is not None
    ):
        outflow, recharge = _prepare_streamflow_series(simulated_timeseries)
        plot_discharge(
            observed_df=observed_streamflow,
            simulated_series=outflow,
            recharge_series=recharge,
            model_label=run_id.upper(),
            ylabel="Q / A [mm/month]",
            options=options,
            save_path=output_dir / "streamflow.png",
        )

    if options.flow.is_enabled("piezometry", default=True) and simulated_timeseries is not None:
        from hydromodpy.analysis.display.adapters import observed_piezometry_series

        obs_piezo = None
        piezometry = getattr(result.loaded_data, "piezometry", None)
        if piezometry:
            obs_piezo = observed_piezometry_series(piezometry, freq="ME")

        _, recharge = _prepare_streamflow_series(simulated_timeseries)
        wt_depth = simulated_timeseries["watertable_depth"]
        plot_piezometry(
            observed_df=obs_piezo,
            simulated_series=wt_depth,
            recharge_series=recharge,
            model_label=run_id.upper(),
            options=options,
            save_path=output_dir / "piezometry.png",
        )


def plot_boussinesq_flow_suite(result, options: DisplayOptions) -> None:
    """Render the Boussinesq-specific launcher display figures."""
    if not options.should_render() or not options.flow.enabled:
        return

    model = _resolve_boussinesq_model(result)
    if model is None:
        return

    mesh = getattr(model, "mesh", None)
    payload = _load_boussinesq_state_payload(model)
    head_m = _resolve_boussinesq_head(model)
    if mesh is None or head_m is None:
        return

    run_id = str(getattr(model, "model_name", "")).strip() or "boussinesq"
    output_dir = resolve_model_figure_dir(result.setup.workspace, run_id)
    triangles = _resolve_boussinesq_triangles(mesh)
    node_x = np.asarray(mesh.node_x_m, dtype=float)
    node_y = np.asarray(mesh.node_y_m, dtype=float)
    cell_top = np.asarray(mesh.z_top_m, dtype=float)
    cell_bottom = np.asarray(mesh.z_bottom_m, dtype=float)
    raw_cell_area = getattr(mesh, "cell_area_m2", None)
    cell_area = None if raw_cell_area is None else np.asarray(raw_cell_area, dtype=float)
    generic_payload = build_flow_spatial_payload_from_model(model)

    if generic_payload is not None and options.flow.is_enabled("state_triptych", default=True):
        plot_flow_state_triptych(
            payload=generic_payload,
            options=options,
            save_path=output_dir / "flow_state_triptych.png",
        )

    if options.flow.is_enabled("boussinesq_state", default=True):
        plot_boussinesq_state(
            node_x_m=node_x,
            node_y_m=node_y,
            triangles=triangles,
            cell_head_m=head_m,
            cell_centroid_x_m=np.asarray(mesh.cell_centroid_x_m, dtype=float),
            cell_z_top_m=cell_top,
            cell_z_bottom_m=cell_bottom,
            options=options,
            save_path=output_dir / "boussinesq_state.png",
        )

    if options.flow.is_enabled("boussinesq_diagnostics", default=True):
        plot_boussinesq_diagnostics(
            node_x_m=node_x,
            node_y_m=node_y,
            triangles=triangles,
            cell_head_m=head_m,
            cell_z_top_m=cell_top,
            cell_z_bottom_m=cell_bottom,
            cell_area_m2=cell_area,
            cell_saturation_excess_rate_m_s=payload.get("final_saturation_excess_rate_m_s"),
            cell_drainage_flux_m3_s=payload.get("drainage_flux_m3_s"),
            options=options,
            save_path=output_dir / "boussinesq_diagnostics.png",
        )

    if options.flow.is_enabled("boussinesq_edge_flux", default=True):
        internal_flux = payload.get("internal_edge_flux_m3_s")
        if (
            internal_flux is not None
            and hasattr(mesh, "edge_node_a")
            and hasattr(mesh, "edge_node_b")
            and hasattr(mesh, "boundary_edge_mask")
        ):
            edge_node_a, edge_node_b = _resolve_boussinesq_edge_node_indices(mesh)
            plot_boussinesq_edge_flux_map(
                node_x_m=node_x,
                node_y_m=node_y,
                edge_node_a_indices=edge_node_a,
                edge_node_b_indices=edge_node_b,
                boundary_edge_mask=np.asarray(mesh.boundary_edge_mask, dtype=bool),
                internal_edge_flux_m3_s=internal_flux,
                boundary_edge_flux_m3_s=payload.get("boundary_edge_flux_m3_s"),
                options=options,
                save_path=output_dir / "boussinesq_edge_flux.png",
            )

    if options.flow.is_enabled("boussinesq_mass_balance", default=True):
        balance_payload = _build_boussinesq_mass_balance(mesh, payload)
        if balance_payload is not None:
            time_days, components, net = balance_payload
            plot_flow_mass_balance(
                time_values=time_days,
                components_by_name=components,
                net_series=net,
                title="Boussinesq Mass Balance",
                options=options,
                save_path=output_dir / "boussinesq_mass_balance.png",
            )

    if options.flow.is_enabled("boussinesq_probes", default=True):
        probe_payload = _build_boussinesq_probe_series(mesh, payload)
        if probe_payload is not None:
            time_days, series_by_label = probe_payload
            plot_flow_probe_timeseries(
                time_values=time_days,
                series_by_label=series_by_label,
                title="Boussinesq Probe Heads",
                ylabel="Head [m]",
                options=options,
                save_path=output_dir / "boussinesq_probe_heads.png",
            )


def plot_particles_suite(result, options: DisplayOptions) -> None:
    """Run all enabled particle-tracking outputs for one simulation result."""
    if not options.should_render():
        return

    flow_model = _resolve_flow_model(result)
    run_id = flow_model.model_name
    output_dir = resolve_model_figure_dir(result.setup.workspace, run_id)
    particles_dir = (
        result.setup.workspace.simulations_folder
        / run_id
        / "_postprocess"
        / "_particles"
    )

    if not options.particles.is_enabled("pathlines", default=False):
        return

    import geopandas as gpd

    pathlines_gdf = gpd.read_file(particles_dir / "pathlines_weighted.shp")
    endpoints_gdf = gpd.read_file(particles_dir / "starting_weighted.shp")

    plot_pathlines_map(
        dem_path=resolve_flow_base_raster(flow_model, result.setup.geographic),
        watershed_shp=result.setup.geographic.watershed_shp,
        pathlines_gdf=pathlines_gdf,
        endpoints_gdf=endpoints_gdf,
        options=options,
        save_path=output_dir / "pathlines.png",
    )


def plot_transport_suite(result, options: DisplayOptions) -> None:
    """Run transport concentration exports and derived animations."""
    if not options.should_render():
        return

    flow_model = _resolve_flow_model(result)
    transport_model = result.get_model_for_solver("mt3dms")
    if transport_model is None:
        transport_model = result.get_model_for_solver("modflow6gwt")
    if transport_model is None:
        return

    run_concentration = options.transport.is_enabled("concentration", default=False)
    run_gif = options.transport.is_enabled("gif", default=False)
    run_web_animation = options.transport.is_enabled("web_animation", default=False)
    if not any([run_concentration, run_gif, run_web_animation]):
        return

    run_id = flow_model.model_name
    output_dir = resolve_model_figure_dir(result.setup.workspace, run_id) / "transport"
    if _is_unstructured_flow_model(flow_model):
        _copy_latest_native_mesh_figures(
            _native_mesh_figure_dir(flow_model),
            output_dir,
            mapping=[
                ("transport_concentration_seepage_t(*).png", "concentration_seepage.png"),
                ("transport_mass_seepage_t(*).png", "mass_seepage.png"),
                ("transport_mass_accumulated_t(*).png", "mass_accumulated.png"),
            ],
        )
        return

    save_frame_files = options.save or run_gif or run_web_animation
    show_last_frame = run_concentration and options.show

    frame_paths = plot_concentration_frames(
        model_transport=transport_model,
        model_modflow=flow_model,
        geographic=result.setup.geographic,
        hydrography=result.loaded_data.hydrography,
        recharge_series=_extract_recharge_series_m_per_day(result.loaded_data.recharge),
        base_raster_path=resolve_flow_base_raster(flow_model, result.setup.geographic),
        output_dir=output_dir,
        prefix="concentration",
        dpi=options.dpi,
        save_frames=save_frame_files,
        show_last_frame=show_last_frame,
    )

    if run_gif:
        build_gif(
            frame_paths=frame_paths,
            gif_path=output_dir / "concentration.gif",
        )

    if run_web_animation:
        html_path = output_dir / "concentration_slider.html" if options.save else None
        build_plotly_slider(
            frame_paths=frame_paths,
            html_path=html_path,
            show_in_browser=options.show,
        )


__all__ = [
    "plot_boussinesq_flow_suite",
    "plot_flow_suite",
    "plot_particles_suite",
    "plot_transport_suite",
]
