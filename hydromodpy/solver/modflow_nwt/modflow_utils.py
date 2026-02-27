# -*- coding: utf-8 -*-
"""
Utilities for MODFLOW-NWT property mapping from Flow/Domain objects.
"""

import copy

import numpy as np

from hydromodpy.tools import get_logger
from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_fieldparam_discretization import (
    discretize_fieldparam_on_sgrid,
)

logger = get_logger(__name__)


def _coerce_geology_field(zone_obj):
    """Return a geology field object exposing `on_mesh(...)`."""
    if zone_obj is None:
        raise ValueError("Missing geology zone object in domain")

    if not hasattr(zone_obj, "on_mesh"):
        raise TypeError(
            "Domain geology zone must expose 'on_mesh(...)'. "
            "Expected a GeologyField-compatible object."
        )
    if not hasattr(zone_obj, "identifier"):
        raise TypeError(
            "Domain geology zone must expose 'identifier'. "
            "Expected a GeologyField-compatible object."
        )
    return zone_obj


def _build_property_from_flow_domain(
    *,
    model,
    sgrid,
    flow_param_candidates,
    target_3d_attr: str,
    target_surface_attr: str,
    property_label: str,
) -> None:
    """Map one Flow parameter to one MODFLOW property array on SGrid.

    Design intent
    -------------
    Keep the call site compact, while keeping behavior explicit:
    - one helper call per property (K, Sy, Ss),
    - deterministic output arrays (`target_3d_attr`, `target_surface_attr`),
    - strict contract (no fallback, no silent skip).

    Practical examples
    ------------------
    Example A (hydraulic conductivity):
    - input aliases: `("K", "k")`
    - output attrs: `target_3d_attr="hk"`, `target_surface_attr="hk_value"`
    - expected result:
      `model.hk.shape == (nlay, nrow, ncol)` and
      `model.hk_value.shape == (nrow, ncol)`

    Example B (specific yield):
    - input aliases: `("Sy", "SY", "sy", "S", "s")`
    - output attrs: `target_3d_attr="sy"`, `target_surface_attr="sy_value"`

    Strict behavior (important)
    ---------------------------
    If one prerequisite is missing (parameter, geology zone, spatial-id
    compatibility), this method raises immediately. In mapping mode, there
    is intentionally no historical fallback.
    """
    # 1) Validate object contracts early (fail fast, explicit error message).
    if model.flow is None or not hasattr(model.flow, "parameters"):
        raise ValueError("Missing flow object or flow.parameters for property mapping")
    if model.domain is None or not hasattr(model.domain, "zones"):
        raise ValueError("Missing domain object or domain.zones for property mapping")

    # 2) Read the Flow parameter registry and pick the first matching alias.
    #    Example: with aliases ("K", "k"), prefer "K" if both exist.
    parameters = getattr(model.flow, "parameters", {})
    if not isinstance(parameters, dict):
        raise TypeError("flow.parameters must be a dictionary")

    param_obj = None
    selected_name = None
    for candidate in flow_param_candidates:
        if candidate in parameters:
            param_obj = parameters.get(candidate)
            selected_name = str(candidate)
            break
    if param_obj is None:
        aliases = ", ".join([str(v) for v in flow_param_candidates])
        raise ValueError(
            f"Cannot map {property_label}: missing flow parameter among ({aliases})"
        )
    if not hasattr(param_obj, "to_mesh_field"):
        raise TypeError(
            f"Cannot map {property_label}: selected parameter '{selected_name}' "
            "does not expose to_mesh_field(...)"
        )

    # 3) Resolve geology support from Domain.
    #    This must expose at least:
    #    - identifier (for heterogeneous consistency checks),
    #    - on_mesh(...) (for zone-fraction projection on the 2D support).
    zones = getattr(model.domain, "zones", {})
    if not isinstance(zones, dict):
        raise TypeError("domain.zones must be a dictionary")
    geology_zone = zones.get("geology")
    if geology_zone is None:
        raise ValueError("Cannot map property: domain.zones['geology'] is missing")
    geology_field = _coerce_geology_field(geology_zone)

    # 4) For heterogeneous parameters, enforce field spatial-id consistency.
    #    Example:
    #    - param_obj.field_spatial_id == "field_geology"
    #    - geology_field.identifier == "field_geology"
    #    If they differ, mapping is refused to avoid mixing unrelated supports.
    if getattr(param_obj, "is_heterogeneous", False):
        required_field_id = str(getattr(param_obj, "field_spatial_id", "")).strip()
        geology_field_id = str(getattr(geology_field, "identifier", "")).strip()
        if required_field_id and geology_field_id and required_field_id != geology_field_id:
            raise ValueError(
                f"Cannot map {property_label}: field_spatial_id mismatch "
                f"('{required_field_id}' != '{geology_field_id}')"
            )

    # 5) Core discretization call:
    #    - geology_field.on_mesh(...) creates the planar support;
    #    - field_param.to_mesh_field(..., depth=...) is evaluated over layers;
    #    - returned object contains both surface map and full 3D tensor.
    discretized = discretize_fieldparam_on_sgrid(
        geology_field=geology_field,
        field_param=param_obj,
        sgrid=sgrid,
        cell_samples_per_axis=None,
        depth=0.0,
        strict_field_spatial_id_match=True,
    )

    # 6) Persist outputs on MODFLOW instance:
    #    - solver-ready 3D tensor (`hk`, `sy`, `ss`),
    #    - surface 2D view kept for legacy logs/plots.
    setattr(model, target_3d_attr, np.asarray(discretized.values_3d, dtype=float))
    setattr(model, target_surface_attr, np.asarray(discretized.values_2d, dtype=float))

    logger.info(
        "%s mapped from flow.%s on domain geology",
        property_label,
        selected_name,
    )


def build_flow_domain_property_snapshot(
    *,
    model,
    sgrid,
    mapping_specs,
    strict: bool = False,
):
    """Compute Flow/Domain-mapped properties and restore model state afterwards.

    Parameters
    ----------
    model : object
        Modflow instance carrying ``flow`` and ``domain``.
    sgrid : object
        FloPy StructuredGrid used for discretization.
    mapping_specs : list[tuple]
        Tuples with ``(aliases, target_3d_attr, target_surface_attr, label)``.
    strict : bool, optional
        If True, raise on first mapping error. If False, log warning and continue.

    Returns
    -------
    dict
        Snapshot dictionary keyed by target attribute names.
        Example keys: ``"hk"``, ``"hk_value"``, ``"sy"``, ``"sy_value"``.
    """
    snapshot = {}
    attrs_to_restore = set()
    for _, target_3d_attr, target_surface_attr, _ in mapping_specs:
        attrs_to_restore.add(str(target_3d_attr))
        attrs_to_restore.add(str(target_surface_attr))

    had_attr = {attr: hasattr(model, attr) for attr in attrs_to_restore}
    original_values = {
        attr: copy.deepcopy(getattr(model, attr))
        for attr in attrs_to_restore
        if had_attr[attr]
    }

    try:
        for aliases, target_3d_attr, target_surface_attr, label in mapping_specs:
            try:
                _build_property_from_flow_domain(
                    model=model,
                    sgrid=sgrid,
                    flow_param_candidates=aliases,
                    target_3d_attr=target_3d_attr,
                    target_surface_attr=target_surface_attr,
                    property_label=label,
                )
                snapshot[target_3d_attr] = np.asarray(
                    getattr(model, target_3d_attr), dtype=float
                ).copy()
                snapshot[target_surface_attr] = np.asarray(
                    getattr(model, target_surface_attr), dtype=float
                ).copy()
            except Exception as exc:
                if strict:
                    raise
                logger.warning("Flow/Domain mapping skipped for %s: %s", label, exc)
    finally:
        for attr, value in original_values.items():
            setattr(model, attr, value)
        for attr, existed in had_attr.items():
            if not existed and hasattr(model, attr):
                delattr(model, attr)

    return snapshot


def compare_and_log_property_arrays(
    *,
    property_label: str,
    historical_3d,
    mapped_3d,
):
    """Compare historical vs Flow/Domain arrays and emit a console report."""
    hist = np.asarray(historical_3d, dtype=float)
    mapped = np.asarray(mapped_3d, dtype=float)

    if hist.shape != mapped.shape:
        report = (
            f"[{property_label}] historical vs mapped comparison\n"
            f"  shape mismatch: historical={hist.shape}, mapped={mapped.shape}"
        )
        logger.info(report)
        return {
            "property": property_label,
            "status": "shape_mismatch",
            "historical_shape": tuple(hist.shape),
            "mapped_shape": tuple(mapped.shape),
            "report": report,
        }

    valid = np.isfinite(hist) & np.isfinite(mapped)
    n_total = int(hist.size)
    n_valid = int(np.count_nonzero(valid))
    if n_valid == 0:
        report = (
            f"[{property_label}] historical vs mapped comparison\n"
            f"  no finite values in common (n_total={n_total})"
        )
        logger.info(report)
        return {
            "property": property_label,
            "status": "no_finite_overlap",
            "n_total": n_total,
            "n_valid": n_valid,
            "report": report,
        }

    h = hist[valid]
    m = mapped[valid]
    abs_diff = np.abs(h - m)
    scale = np.maximum(np.abs(h), np.abs(m))
    rel_diff = np.zeros_like(abs_diff)
    nonzero = scale > 0.0
    rel_diff[nonzero] = abs_diff[nonzero] / scale[nonzero]

    summary = {
        "property": property_label,
        "status": "ok",
        "shape": tuple(hist.shape),
        "n_total": n_total,
        "n_valid": n_valid,
        "historical_min": float(np.min(h)),
        "historical_max": float(np.max(h)),
        "mapped_min": float(np.min(m)),
        "mapped_max": float(np.max(m)),
        "abs_diff_mean": float(np.mean(abs_diff)),
        "abs_diff_max": float(np.max(abs_diff)),
        "abs_diff_p95": float(np.percentile(abs_diff, 95.0)),
        "rel_diff_mean": float(np.mean(rel_diff)),
        "rel_diff_max": float(np.max(rel_diff)),
        "rel_diff_p95": float(np.percentile(rel_diff, 95.0)),
    }

    report = (
        f"[{property_label}] historical vs Flow/Domain mapping comparison\n"
        f"  shape={summary['shape']}, n_valid={summary['n_valid']}/{summary['n_total']}\n"
        f"  historical: min={summary['historical_min']:.6e}, max={summary['historical_max']:.6e}\n"
        f"  mapped    : min={summary['mapped_min']:.6e}, max={summary['mapped_max']:.6e}\n"
        f"  abs diff  : mean={summary['abs_diff_mean']:.6e}, p95={summary['abs_diff_p95']:.6e}, max={summary['abs_diff_max']:.6e}\n"
        f"  rel diff  : mean={summary['rel_diff_mean']:.6e}, p95={summary['rel_diff_p95']:.6e}, max={summary['rel_diff_max']:.6e}"
    )
    summary["report"] = report
    logger.info(report)
    return summary
