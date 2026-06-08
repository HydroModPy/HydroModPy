"""Calibration runtime-reuse helpers for MODFLOW 6 flow models."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

from hydromodpy.solver.modflow6.builders import build_drain_stress_period_data
from hydromodpy.solver.modflow6.property_mapping import (
    fill_missing_flow_properties_from_mesh_support,
    resolve_flow_property_arrays,
    resolve_required_flow_properties,
)
from hydromodpy.solver.modflow_common import ModflowPreprocessOptions


def calibration_runtime_reuse_enabled(
    flow_runtime_overrides: Mapping[str, object] | None,
) -> bool:
    """Return ``True`` when calibration asks for one reusable MF6 runtime."""
    return bool(
        isinstance(flow_runtime_overrides, Mapping)
        and flow_runtime_overrides.get("reuse_solver_model", False)
    )


def runtime_reuse_signature(
    model,
    *,
    flow: object,
    domain: object,
    options: ModflowPreprocessOptions,
    mesh_planar: object | None,
    mesh_support: object | None,
) -> tuple[object, ...]:
    """Capture the static runtime structure that must remain stable."""
    time_grid = getattr(options, "time_grid", None)
    return (
        id(flow),
        id(domain),
        id(mesh_planar),
        id(mesh_support),
        id(time_grid),
        str(model.flow_regime or ""),
    )


def can_refresh_runtime_reuse(
    model,
    *,
    flow: object,
    domain: object,
    options: ModflowPreprocessOptions,
    mesh_planar: object | None,
    mesh_support: object | None,
    flow_runtime_overrides: Mapping[str, object] | None,
) -> bool:
    """Return ``True`` when a cached runtime can be refreshed in place."""
    if not calibration_runtime_reuse_enabled(flow_runtime_overrides):
        return False
    if getattr(model, "sim", None) is None or getattr(model, "gwf", None) is None:
        return False
    signature = runtime_reuse_signature(
        model,
        flow=flow,
        domain=domain,
        options=options,
        mesh_planar=mesh_planar,
        mesh_support=mesh_support,
    )
    return signature == getattr(model, "_calibration_runtime_reuse_signature", None)


def refresh_reused_runtime_property_packages(
    model,
    *,
    flow_runtime_overrides: Mapping[str, object] | None,
) -> tuple[str, ...]:
    """Update only runtime-varying hydraulic packages on a reused MF6 object."""
    flow_params = resolve_flow_property_arrays(
        flow=model.flow,
        domain=model.domain,
        solver_mesh=model.solver_mesh,
        planar_mesh=model.runtime_mesh_planar,
        required_properties=resolve_required_flow_properties(flow_regime=model.flow_regime),
        optional_fill_values={"Sy": 0.0, "Ss": 0.0},
        runtime_property_overrides=flow_runtime_overrides,
    )
    flow_params = fill_missing_flow_properties_from_mesh_support(
        flow_params,
        mesh_support=model.runtime_mesh_support,
        solver_mesh=model.solver_mesh,
    )
    model.hk = model.solver_mesh.flatten_from_grid(flow_params["hk"])
    model.sy = model.solver_mesh.flatten_from_grid(flow_params["sy"])
    model.ss = model.solver_mesh.flatten_from_grid(flow_params["ss"])

    updated_packages: list[str] = []
    if getattr(model, "npf", None) is not None:
        model.npf.k.set_data(model.hk)
        # k33 = k / vka (vka = kh/kv vertical anisotropy ratio, > 0).
        model.npf.k33.set_data(model.hk / float(model.modflow_config.process_specific.vka))
        updated_packages.append("npf")
    if getattr(model, "sto", None) is not None:
        model.sto.sy.set_data(model.sy)
        model.sto.ss.set_data(model.ss)
        updated_packages.append("sto")

    drainage_cond_series = getattr(model, "_drainage_cond_series", None)
    if (
        getattr(model, "drn", None) is not None
        and drainage_cond_series is not None
        and bool(getattr(model, "_drainage_uses_hk", False))
    ):
        drn_spd = build_drain_stress_period_data(
            model,
            solver_mesh=model.solver_mesh,
            drainage_cond_series=drainage_cond_series,
            ocean_support_mask=np.asarray(
                getattr(model, "_ocean_support_mask", np.zeros(int(model.ncpl), dtype=bool)),
                dtype=bool,
            ),
            stream_support_mask=np.asarray(
                getattr(model, "_stream_support_mask", np.zeros(int(model.ncpl), dtype=bool)),
                dtype=bool,
            ),
        )
        model.drn.stress_period_data.set_data(drn_spd)
        updated_packages.append("drn")

    if refresh_reused_lak_bedleak(model, flow_runtime_overrides=flow_runtime_overrides):
        updated_packages.append("lak")

    return tuple(updated_packages)


def refresh_reused_lak_bedleak(
    model,
    *,
    flow_runtime_overrides: Mapping[str, object] | None,
) -> bool:
    """Refresh the LAK ``bedleak`` (calibration parameter) in place.

    ``bedleak`` is the lake-bed leakance (1/T) on every LAK connection, the
    under-dam leakage calibration parameter. Like npf/sto, the lake grid
    and connection geometry are static under reuse, so we only rewrite the
    ``bedleak`` column of ``connectiondata`` (per 0-based lake index ``ifno``) and
    keep the cached MF6 object. Returns ``True`` when the LAK package was touched.

    The new value comes from a ``bedleak`` override (a scalar applied to every
    lake, or a ``{lake_id: value}`` mapping in 1/s) and falls back to the current
    per-lake ``bedleak`` declared on ``model.flow``. The override values are SI
    (1/s) like the hk/sy/ss overrides.
    """
    from hydromodpy.solver.modflow6.builders.lake import (
        convert_bedleak_to_per_s,
        lake_definitions_for_bedleak,
    )

    lak = getattr(model, "lak", None)
    if lak is None:
        return False

    # Per-lake bedleak (1/s) declared on the current model.flow, in LAK
    # packagedata (ifno) order, plus the optional calibration override.
    lake_ids: list[str] = []
    base_bedleak: dict[int, float] = {}
    for lake_index, (lake_id, definition) in enumerate(lake_definitions_for_bedleak(model).items()):
        lake_ids.append(str(lake_id))
        bedleak = definition.get("bedleak")
        if bedleak is None:
            continue
        unit = definition.get("bedleak_unit")
        base_bedleak[lake_index] = convert_bedleak_to_per_s(
            bedleak,
            lake_id=lake_id,
            unit=str(unit) if unit is not None else None,
        )

    targets = _merge_bedleak_targets(
        base_bedleak,
        lake_ids,
        _bedleak_override(flow_runtime_overrides),
    )
    if not targets:
        return False

    connectiondata = lak.connectiondata.get_data()
    names = getattr(getattr(connectiondata, "dtype", None), "names", None) or ()
    if connectiondata is None or "bedleak" not in names:
        return False
    updated = np.array(connectiondata, copy=True)
    bedleak_col = np.asarray(updated["bedleak"], dtype=float)
    ifno = np.asarray(updated["ifno"], dtype=int)
    changed = False
    for lake_index, value in targets.items():
        mask = ifno == int(lake_index)
        if mask.any():
            bedleak_col[mask] = float(value)
            changed = True
    if not changed:
        return False
    updated["bedleak"] = bedleak_col
    lak.connectiondata.set_data(updated)
    return True


def _bedleak_override(
    flow_runtime_overrides: Mapping[str, object] | None,
) -> Mapping[str, object] | float | None:
    """Return the ``bedleak`` calibration override (scalar or per-lake mapping)."""
    if not isinstance(flow_runtime_overrides, Mapping):
        return None
    override = flow_runtime_overrides.get("bedleak")
    if isinstance(override, Mapping):
        return {str(lake_id): value for lake_id, value in override.items()}
    if isinstance(override, (int, float)) and not isinstance(override, bool):
        return float(override)
    return None


def _merge_bedleak_targets(
    base_bedleak: Mapping[int, float],
    lake_ids: Sequence[str],
    override: Mapping[str, object] | float | None,
) -> dict[int, float]:
    """Combine the declared per-lake bedleak with the calibration override.

    A scalar override applies to every lake; a per-lake mapping overrides only the
    named lakes (matched against the LAK packagedata order in ``lake_ids``).
    """
    targets: dict[int, float] = dict(base_bedleak)
    if isinstance(override, (int, float)) and not isinstance(override, bool):
        indices = range(len(lake_ids)) if lake_ids else [0]
        for lake_index in indices:
            targets[lake_index] = float(override)
    elif isinstance(override, Mapping):
        for lake_id, value in override.items():
            if str(lake_id) in lake_ids:
                targets[lake_ids.index(str(lake_id))] = float(value)  # type: ignore[arg-type]
    return targets


__all__ = [
    "calibration_runtime_reuse_enabled",
    "can_refresh_runtime_reuse",
    "refresh_reused_lak_bedleak",
    "refresh_reused_runtime_property_packages",
    "runtime_reuse_signature",
]
