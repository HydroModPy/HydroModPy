"""Summary helpers for the reference 2D geology-on-Gmsh case."""

from __future__ import annotations

from typing import Any

import numpy as np


def normalize_zone_key(raw: object) -> str:
    """Return one stable string key used in summaries and legends."""

    if isinstance(raw, (int, np.integer)):
        return str(int(raw))
    if isinstance(raw, (float, np.floating)):
        value = float(raw)
        if np.isfinite(value) and value.is_integer():
            return str(int(value))
        return str(value)
    return str(raw).strip()


def dominant_zone_indices(
    field_discretization,
) -> tuple[np.ndarray, tuple[str, ...], int, int]:
    """Return dominant-zone indices and QA counters on the planar mesh."""

    zone_keys_raw, fractions_by_zone = field_discretization.weighted_components()
    zone_keys = tuple(normalize_zone_key(key) for key in zone_keys_raw)
    stack = np.vstack(
        [
            np.asarray(
                field_discretization.mesh.to_cell_values(fractions_by_zone[key]),
                dtype=float,
            ).reshape(-1)
            for key in zone_keys_raw
        ]
    )
    max_fraction = np.nanmax(stack, axis=0)
    dominant_idx = np.argmax(stack, axis=0).astype(float)
    valid = np.isfinite(max_fraction) & (max_fraction > 0.0)
    dominant_idx[~valid] = np.nan
    mixed = int(np.count_nonzero(valid & (max_fraction < 0.999999)))
    undefined = int(np.count_nonzero(~valid))
    return dominant_idx, zone_keys, mixed, undefined


def build_reference_case_summary(
    *,
    mesh,
    geology_field,
    field_param,
    field_discretization,
    mesh_values,
) -> dict[str, Any]:
    """Build the stable JSON summary used by tests and manual review."""

    dominant_idx, zone_keys, mixed_count, undefined_count = dominant_zone_indices(
        field_discretization
    )
    valid_mask = np.isfinite(dominant_idx)
    dominant_counts: dict[str, int] = {}
    for idx, zone_key in enumerate(zone_keys):
        dominant_counts[zone_key] = int(
            np.count_nonzero(dominant_idx[valid_mask] == float(idx))
        )

    values = np.asarray(
        mesh.to_cell_values(mesh_values.cell_values), dtype=float
    ).reshape(-1)
    return {
        "mesh_kind": str(mesh.kind),
        "cell_type": str(mesh.cell_type),
        "n_nodes": int(mesh.n_nodes),
        "n_cells": int(mesh.n_cells),
        "bounds": [float(v) for v in mesh.bounds],
        "field_id": str(geology_field.identifier),
        "field_param_id": str(field_param.identifier),
        "field_param_kind": str(field_param.kind),
        "n_zone_keys": int(len(zone_keys)),
        "zone_keys": [str(v) for v in zone_keys],
        "mixed_cell_count": int(mixed_count),
        "undefined_cell_count": int(undefined_count),
        "dominant_zone_counts": dominant_counts,
        "value_min": round(float(np.nanmin(values)), 12),
        "value_max": round(float(np.nanmax(values)), 12),
        "value_mean": round(float(np.nanmean(values)), 12),
        "value_sum": round(float(np.nansum(values)), 12),
        "value_signature_head": [round(float(v), 12) for v in values[:8]],
    }


__all__ = [
    "build_reference_case_summary",
    "dominant_zone_indices",
    "normalize_zone_key",
]
