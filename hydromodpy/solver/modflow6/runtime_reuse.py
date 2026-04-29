"""Calibration runtime-reuse helpers for MODFLOW 6 flow models."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from hydromodpy.solver.modflow6.builders import build_drain_stress_period_data
from hydromodpy.solver.modflow6.property_mapping import (
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
    model.hk = model.solver_mesh.flatten_from_grid(flow_params["hk"])
    model.sy = model.solver_mesh.flatten_from_grid(flow_params["sy"])
    model.ss = model.solver_mesh.flatten_from_grid(flow_params["ss"])

    updated_packages: list[str] = []
    if getattr(model, "npf", None) is not None:
        model.npf.k.set_data(model.hk)
        model.npf.k33.set_data(
            model.hk
            / max(
                float(
                    getattr(
                        getattr(model.modflow_config, "process_specific", object()),
                        "vka",
                        1.0,
                    )
                ),
                1e-12,
            )
        )
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

    return tuple(updated_packages)


__all__ = [
    "calibration_runtime_reuse_enabled",
    "can_refresh_runtime_reuse",
    "refresh_reused_runtime_property_packages",
    "runtime_reuse_signature",
]
