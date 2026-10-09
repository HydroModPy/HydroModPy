"""Config payload loaders and physical-context text helpers."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hydromodpy.core.toml_io.loader import load_toml_with_base_config
from hydromodpy.reporting.comparison.context import ComparisonWebContext

from .templates import (
    _float_or_none,
    _format_value,
    _mapping,
    _quantity_is_zero,
)


def _base_config_payload(ctx: ComparisonWebContext) -> dict[str, Any]:
    raw_path = ctx.manifest.get("base_simulation_config")
    if raw_path in (None, ""):
        return {}
    config_path = _existing_config_path(Path(str(raw_path)), ctx=ctx)
    if config_path is None:
        return {}
    try:
        payload = load_toml_with_base_config(config_path)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _simulation_config_payloads(
    ctx: ComparisonWebContext,
) -> list[tuple[Mapping[str, Any], dict[str, Any]]]:
    payloads: list[tuple[Mapping[str, Any], dict[str, Any]]] = []
    for simulation in ctx.simulations:
        raw_path = simulation.get("config_path")
        if raw_path in (None, ""):
            continue
        config_path = _existing_config_path(Path(str(raw_path)), ctx=ctx)
        if config_path is None:
            continue
        try:
            payload = load_toml_with_base_config(config_path)
        except Exception:
            continue
        if isinstance(payload, dict):
            payloads.append((simulation, payload))
    return payloads


def _flow_payload_for_solver(
    simulation_payloads: list[tuple[Mapping[str, Any], dict[str, Any]]],
    solver: str,
) -> Mapping[str, Any] | None:
    solver_key = solver.strip().lower()
    for simulation, payload in simulation_payloads:
        if str(simulation.get("solver", "")).strip().lower() == solver_key:
            flow = _mapping(payload.get("flow"))
            if flow:
                return flow
    return None


def _existing_config_path(path: Path, *, ctx: ComparisonWebContext) -> Path | None:
    """Return an existing local path for a manifest config path."""
    candidates = [path]
    text = str(path).replace("\\", "/")
    if text.startswith("/mnt/") and len(text) > 6 and text[6] == "/":
        drive = text[5].upper()
        candidates.append(Path(f"{drive}:/" + text[7:]))
    if not path.is_absolute():
        candidates.append((ctx.root / path).resolve())
        candidates.append((ctx.root.parent / path).resolve())
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _is_synthetic_patchy(ctx: ComparisonWebContext) -> bool:
    comparison_id = str(ctx.manifest.get("comparison_id", "")).lower()
    return "synthetic_patchy" in comparison_id


def _recharge_values(payload: Mapping[str, Any]) -> list[float]:
    data = _mapping(payload.get("data"))
    recharge = _mapping(data.get("recharge"))
    sources = recharge.get("sources")
    if not isinstance(sources, list):
        return []
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        values = source.get("values")
        if isinstance(values, list):
            out: list[float] = []
            for item in values:
                try:
                    out.append(float(item))
                except Exception:
                    return []
            return out
    return []


def _depth_model_text(depth_model: Mapping[str, Any]) -> str:
    """Describe the substratum the way the declared depth model places it."""
    kind = depth_model.get("kind", "constant_thickness")
    if kind == "flat_substratum":
        elevation = _format_value(depth_model.get("substratum_elevation"), default="0 m")
        return f"flat substratum at elevation {elevation}"
    if kind in ("raster_substratum", "raster_thickness"):
        read = "thickness" if kind == "raster_thickness" else "elevation"
        offset = _format_value(depth_model.get("offset"), default="0 m")
        return f"substratum read from [data.substratum] ({read}), offset {offset}"
    thickness = _format_value(depth_model.get("thickness"), default="80 m")
    return f"substratum of constant thickness {thickness}"


def _synthetic_context_rows(payload: Mapping[str, Any]) -> list[tuple[str, str]]:
    from .templates import _format_mapping_values

    geographic = _mapping(payload.get("geographic"))
    synthetic = _mapping(geographic.get("synthetic"))
    grid = _mapping(synthetic.get("grid"))
    topography = _mapping(synthetic.get("topography"))
    domain = _mapping(payload.get("domain"))
    depth_model = _mapping(domain.get("depth_model"))
    flow = _mapping(payload.get("flow"))
    param = _mapping(flow.get("param"))
    k_values = _mapping(_mapping(param.get("K")).get("field_heterogeneous")).get("values", {})
    sy_values = _mapping(_mapping(param.get("Sy")).get("field_heterogeneous")).get("values", {})
    ss_value = _mapping(_mapping(param.get("Ss")).get("field_homogeneous")).get("value")
    recharge_values = _recharge_values(payload)
    recharge_text = "monthly series"
    if recharge_values:
        mean_recharge = sum(recharge_values) / len(recharge_values)
        recharge_text = (
            f"{len(recharge_values)} months; mean {mean_recharge:.2g} mm/d; "
            f"min {min(recharge_values):.2g}; max {max(recharge_values):.2g}"
        )
    length_x = _format_value(grid.get("length_x"), default="5025 m")
    length_y = _format_value(grid.get("length_y"), default="5025 m")
    rows = [
        (
            "Geometry",
            f"square domain {length_x} x {length_y}, source grid "
            f"{_format_value(grid.get('nx'), default='67')} x "
            f"{_format_value(grid.get('ny'), default='67')}, CRS "
            f"{_format_value(grid.get('crs'), default='EPSG:2154')}",
        ),
        (
            "Topography",
            f"tilted plane, base elevation {_format_value(topography.get('base_elevation'), default='20')} m, lateral drop {_format_value(topography.get('right_to_left_amplitude'), default='20')} m",
        ),
        ("Thickness", _depth_model_text(depth_model)),
        (
            "Hydraulic conductivity K",
            _format_mapping_values(
                k_values, default="heterogeneous: west 1e-5, centre 8e-5, east 3e-5 m/s"
            ),
        ),
        (
            "Storage",
            f"Sy {_format_mapping_values(sy_values, default='heterogeneous')}; Ss {_format_value(ss_value, default='1e-5 m-1')}",
        ),
        ("Recharge", recharge_text),
        ("Boundary conditions", _boundary_condition_text(flow)),
    ]
    return rows


_MM_PER_YEAR_PER_M_PER_S = 1000.0 * 365.25 * 86400.0


def _steady_forcing_text(ic: Mapping[str, Any]) -> str:
    """Return what the auxiliary steady solve was held at."""
    if str(ic.get("source", "")).strip() != "prescribed":
        return "the mean recharge of the series"
    rate = ic.get("rate")
    if rate is None:
        return "a prescribed recharge"
    return f"a prescribed recharge of {float(rate) * _MM_PER_YEAR_PER_M_PER_S:.0f} mm/yr"


def _initial_condition_text(flow: Mapping[str, Any]) -> str:
    ic = _mapping(flow.get("ic"))
    ic_type = str(ic.get("type", "")).strip()
    if ic_type == "steady_state":
        forcing = _steady_forcing_text(ic)
        backend = str(flow.get("runtime_backend", "")).strip().lower()
        surface = str(flow.get("surface_interaction_model", "")).strip().lower()
        if backend == "petsc" and surface == "vi_obstacle":
            return (
                f"initial head from an auxiliary steady-state solve with {forcing}; "
                "for Boussinesq, the steady and the transient solves use PETSc SNESVI "
                "with the direct vi_obstacle closure"
            )
        if backend == "petsc" and surface == "ts_vi_obstacle":
            return (
                f"initial head from an auxiliary steady-state solve with {forcing}; "
                "for Boussinesq, this steady solve uses PETSc SNESVI with the "
                "vi_obstacle closure before the PETSc TS/SNESVI transient"
            )
        return (
            f"initial head from an auxiliary steady-state solve with {forcing}, "
            "then applied to the transient run"
        )
    if ic_type == "top_offset":
        return f"initial head equal to the top minus {_format_value(ic.get('value'), default='an offset')}"
    return f"type {_format_value(ic_type, default='not documented')}"


def _recharge_text(flow: Mapping[str, Any]) -> str:
    sinks_sources = _mapping(flow.get("sinks_sources"))
    recharge = _mapping(sinks_sources.get("recharge"))
    first_clim = _format_value(recharge.get("first_clim"), default="mean")
    negative_to_evt = _format_value(recharge.get("negative_to_evt"), default="false")
    return (
        "monthly series read from the data configuration; "
        f"first period first_clim={first_clim}; "
        f"negative_to_evt={negative_to_evt}"
    )


def _boundary_condition_text(flow: Mapping[str, Any], *, solver: str = "") -> str:
    active_bc = flow.get("active_bc")
    active = [str(item) for item in active_bc] if isinstance(active_bc, list) else []
    if "east_side" in active:
        return "legacy configuration with a prescribed head on the east edge"
    if "drainage" in active:
        # A boundary is keyed by what it is; its kind is a field of it.
        drainage = _mapping(_mapping(flow.get("bc")).get("drainage"))
        value = _format_value(drainage.get("value"))
        if _quantity_is_zero(drainage.get("value")):
            if solver.strip().lower() == "boussinesq":
                return (
                    "no lateral prescribed head; Cauchy drainage declared "
                    "but disabled by zero conductance; strict free "
                    "obstacle h <= z_top kept"
                )
            return "drainage declared but disabled by zero conductance"
        suffix = f", conductance {value}" if value else ""
        return f"no lateral prescribed head; surface drainage active on the top{suffix}"
    if not active:
        if solver.strip().lower() == "boussinesq":
            return "no active boundary condition; strict free obstacle h <= z_top"
        return "no active boundary condition, recharge aside"
    return ", ".join(active)


def _boussinesq_method_text(flow: Mapping[str, Any]) -> str:
    backend = str(flow.get("runtime_backend", "") or "").strip().lower()
    surface = str(flow.get("surface_interaction_model", "") or "").strip().lower()
    if backend == "petsc" and surface == "vi_obstacle":
        retry_text = (
            "; adaptive retry enabled"
            if bool(flow.get("vi_substep_on_failure", False))
            else "; adaptive retry disabled"
        )
        return (
            "nonlinear 2D unconfined-aquifer model on the same mesh; "
            "full PETSc backend; surface_interaction_model=vi_obstacle; "
            "direct PETSc SNESVI solver; "
            f"{_format_value(flow.get('vi_substeps_per_period'), default='4')} substeps per period"
            f"{retry_text}; "
            f"residual tolerance={_format_value(flow.get('runtime_tol_residual_inf'), default='')}"
        )
    if backend == "petsc" and surface == "ts_vi_obstacle":
        return (
            "nonlinear 2D unconfined-aquifer model on the same mesh; "
            "full PETSc backend; surface_interaction_model=ts_vi_obstacle; "
            f"PETSc TS {_format_value(flow.get('ts_vi_type'), default='beuler')}; "
            f"SNESVI {_format_value(flow.get('ts_vi_snes_type'), default='vinewtonrsls')}; "
            f"{_format_value(flow.get('ts_vi_steps_per_period'), default='4')} TS substeps per period; "
            f"residual tolerance={_format_value(flow.get('runtime_tol_residual_inf'), default='')}"
        )
    return (
        "nonlinear 2D unconfined-aquifer model on the same mesh; "
        f"backend {_format_value(flow.get('runtime_backend'), default='scipy_sparse')}; "
        f"max iterations={_format_value(flow.get('runtime_max_iterations'), default='')}; "
        f"residual tolerance={_format_value(flow.get('runtime_tol_residual_inf'), default='')}"
    )


def _has_head_error_metrics(ctx: ComparisonWebContext) -> bool:
    return any(
        str(row.get("observable", "")).startswith("head")
        and _float_or_none(row.get("rmse_normalized_percent")) is not None
        for row in ctx.metrics_rows
    )
