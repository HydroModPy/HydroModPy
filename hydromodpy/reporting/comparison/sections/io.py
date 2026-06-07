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
    recharge_text = "chronique mensuelle"
    if recharge_values:
        mean_recharge = sum(recharge_values) / len(recharge_values)
        recharge_text = (
            f"{len(recharge_values)} mois; moyenne {mean_recharge:.2g} mm/j; "
            f"min {min(recharge_values):.2g}; max {max(recharge_values):.2g}"
        )
    length_x = _format_value(grid.get("length_x"), default="5025 m")
    length_y = _format_value(grid.get("length_y"), default="5025 m")
    rows = [
        (
            "Geometrie",
            f"domaine carre {length_x} x {length_y}, grille source "
            f"{_format_value(grid.get('nx'), default='67')} x "
            f"{_format_value(grid.get('ny'), default='67')}, CRS "
            f"{_format_value(grid.get('crs'), default='EPSG:2154')}",
        ),
        (
            "Topographie",
            f"plan incline, altitude de base {_format_value(topography.get('base_elevation'), default='20')} m, denivele lateral {_format_value(topography.get('right_to_left_amplitude'), default='20')} m",
        ),
        (
            "Epaisseur",
            f"substratum a epaisseur constante {_format_value(depth_model.get('thickness'), default='80 m')}",
        ),
        (
            "Conductivite K",
            _format_mapping_values(
                k_values, default="heterogene: ouest 1e-5, centre 8e-5, est 3e-5 m/s"
            ),
        ),
        (
            "Stockage",
            f"Sy {_format_mapping_values(sy_values, default='heterogene')}; Ss {_format_value(ss_value, default='1e-5 m-1')}",
        ),
        ("Recharge", recharge_text),
        ("Conditions limites", _boundary_condition_text(flow)),
    ]
    return rows


def _initial_condition_text(flow: Mapping[str, Any]) -> str:
    ic = _mapping(flow.get("ic"))
    ic_type = str(ic.get("type", "")).strip()
    if ic_type == "steady_state":
        backend = str(flow.get("runtime_backend", "")).strip().lower()
        surface = str(flow.get("surface_interaction_model", "")).strip().lower()
        if backend == "petsc" and surface == "vi_obstacle":
            return (
                "charge initiale issue d'un calcul permanent auxiliaire avec "
                "la recharge moyenne; pour Boussinesq, le permanent et le "
                "transitoire utilisent PETSc SNESVI avec la fermeture "
                "vi_obstacle directe"
            )
        if backend == "petsc" and surface == "ts_vi_obstacle":
            return (
                "charge initiale issue d'un calcul permanent auxiliaire avec "
                "la recharge moyenne; pour Boussinesq, ce permanent utilise "
                "PETSc SNESVI avec la fermeture vi_obstacle avant le "
                "transitoire PETSc TS/SNESVI"
            )
        return (
            "charge initiale issue d'un calcul permanent auxiliaire avec la "
            "recharge moyenne de la chronique, appliquee ensuite au transitoire"
        )
    if ic_type == "top_offset":
        return f"charge initiale egale au toit moins {_format_value(ic.get('value'), default='un offset')}"
    return f"type {_format_value(ic_type, default='non documente')}"


def _recharge_text(flow: Mapping[str, Any]) -> str:
    sinks_sources = _mapping(flow.get("sinks_sources"))
    recharge = _mapping(sinks_sources.get("recharge"))
    first_clim = _format_value(recharge.get("first_clim"), default="mean")
    negative_to_evt = _format_value(recharge.get("negative_to_evt"), default="false")
    return (
        "chronique mensuelle lue depuis la configuration de donnees; "
        f"premiere periode first_clim={first_clim}; "
        f"negative_to_evt={negative_to_evt}"
    )


def _boundary_condition_text(flow: Mapping[str, Any], *, solver: str = "") -> str:
    active_bc = flow.get("active_bc")
    active = [str(item) for item in active_bc] if isinstance(active_bc, list) else []
    if "east_side" in active:
        return "ancienne configuration avec charge imposee sur le bord est"
    if "drainage" in active:
        bc = _mapping(flow.get("bc"))
        drainage = _mapping(_mapping(bc.get("cauchy")).get("drainage"))
        if not drainage:
            drainage = _mapping(_mapping(bc.get("robin")).get("drainage"))
        value = _format_value(drainage.get("value"))
        if _quantity_is_zero(drainage.get("value")):
            if solver.strip().lower() == "boussinesq":
                return (
                    "pas de charge laterale imposee; drainage Cauchy declare "
                    "mais desactive par conductance nulle; obstacle libre "
                    "strict h <= z_top conserve"
                )
            return "drainage declare mais desactive par conductance nulle"
        suffix = f", conductance {value}" if value else ""
        return f"pas de charge laterale imposee; drainage de surface actif sur le toit{suffix}"
    if not active:
        if solver.strip().lower() == "boussinesq":
            return "aucune condition limite active; obstacle libre strict h <= z_top"
        return "aucune condition limite active, hors recharge"
    return ", ".join(active)


def _boussinesq_method_text(flow: Mapping[str, Any]) -> str:
    backend = str(flow.get("runtime_backend", "") or "").strip().lower()
    surface = str(flow.get("surface_interaction_model", "") or "").strip().lower()
    if backend == "petsc" and surface == "vi_obstacle":
        retry_text = (
            "; retry adaptatif active"
            if bool(flow.get("vi_substep_on_failure", False))
            else "; retry adaptatif desactive"
        )
        return (
            "modele 2D non lineaire en nappe libre sur le meme maillage; "
            "backend PETSc complet; surface_interaction_model=vi_obstacle; "
            "solveur PETSc SNESVI direct; "
            f"{_format_value(flow.get('vi_substeps_per_period'), default='4')} sous-pas par periode"
            f"{retry_text}; "
            f"tolerance residu={_format_value(flow.get('runtime_tol_residual_inf'), default='')}"
        )
    if backend == "petsc" and surface == "ts_vi_obstacle":
        return (
            "modele 2D non lineaire en nappe libre sur le meme maillage; "
            "backend PETSc complet; surface_interaction_model=ts_vi_obstacle; "
            f"PETSc TS {_format_value(flow.get('ts_vi_type'), default='beuler')}; "
            f"SNESVI {_format_value(flow.get('ts_vi_snes_type'), default='vinewtonrsls')}; "
            f"{_format_value(flow.get('ts_vi_steps_per_period'), default='4')} sous-pas TS par periode; "
            f"tolerance residu={_format_value(flow.get('runtime_tol_residual_inf'), default='')}"
        )
    return (
        "modele 2D non lineaire en nappe libre sur le meme maillage; "
        f"backend {_format_value(flow.get('runtime_backend'), default='scipy_sparse')}; "
        f"iterations max={_format_value(flow.get('runtime_max_iterations'), default='')}; "
        f"tolerance residu={_format_value(flow.get('runtime_tol_residual_inf'), default='')}"
    )


def _has_head_error_metrics(ctx: ComparisonWebContext) -> bool:
    return any(
        str(row.get("observable", "")).startswith("head")
        and _float_or_none(row.get("rmse_normalized_percent")) is not None
        for row in ctx.metrics_rows
    )
