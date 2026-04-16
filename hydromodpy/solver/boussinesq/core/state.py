"""Normalized in-memory solver state for the Boussinesq backend."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class BoussinesqState:
    """Normalized flow state carried by the Boussinesq runtime.

    The state stores both the current solution and, when available, the short
    histories needed by validation and post-processing helpers.
    """

    head_m: np.ndarray
    saturated_thickness_m: np.ndarray
    recharge_rate_m_s: np.ndarray | None = None
    well_flux_m3_s: np.ndarray | None = None
    saturation_excess_rate_m_s: np.ndarray | None = None
    recharge_rate_history_m_s: np.ndarray | None = None
    well_flux_history_m3_s: np.ndarray | None = None
    head_history_m: np.ndarray | None = None
    saturated_thickness_history_m: np.ndarray | None = None
    saturation_excess_history_m_s: np.ndarray | None = None
    internal_edge_flux_m3_s: np.ndarray | None = None
    internal_edge_flux_history_m3_s: np.ndarray | None = None
    imposed_head_edge_flux_m3_s: np.ndarray | None = None
    imposed_head_edge_flux_history_m3_s: np.ndarray | None = None
    prescribed_head_flux_m3_s: np.ndarray | None = None
    prescribed_head_flux_history_m3_s: np.ndarray | None = None
    prescribed_head_m_by_cell: np.ndarray | None = None
    prescribed_head_history_m_by_cell: np.ndarray | None = None
    drainage_flux_m3_s: np.ndarray | None = None
    drainage_flux_history_m3_s: np.ndarray | None = None
    period_lengths_seconds: tuple[float, ...] = ()
    nonlinear_iterations: tuple[int, ...] = ()
    converged_by_period: tuple[bool, ...] = ()

    @classmethod
    def initial(
        cls,
        *,
        head_m: np.ndarray,
        saturated_thickness_m: np.ndarray,
    ) -> BoussinesqState:
        """Create the minimal state used before any nonlinear runtime call."""
        return cls(
            head_m=np.asarray(head_m, dtype=float).copy(),
            saturated_thickness_m=np.asarray(saturated_thickness_m, dtype=float).copy(),
        )

    @classmethod
    def from_runtime(
        cls,
        **kwargs: Any,
    ) -> BoussinesqState:
        """Create one normalized runtime state with consistent array coercion."""
        array_fields = {
            "head_m",
            "saturated_thickness_m",
            "recharge_rate_m_s",
            "well_flux_m3_s",
            "saturation_excess_rate_m_s",
            "recharge_rate_history_m_s",
            "well_flux_history_m3_s",
            "head_history_m",
            "saturated_thickness_history_m",
            "saturation_excess_history_m_s",
            "internal_edge_flux_m3_s",
            "internal_edge_flux_history_m3_s",
            "imposed_head_edge_flux_m3_s",
            "imposed_head_edge_flux_history_m3_s",
            "prescribed_head_flux_m3_s",
            "prescribed_head_flux_history_m3_s",
            "prescribed_head_m_by_cell",
            "prescribed_head_history_m_by_cell",
            "drainage_flux_m3_s",
            "drainage_flux_history_m3_s",
        }
        normalized = dict(kwargs)
        for field_name in array_fields:
            value = normalized.get(field_name)
            if value is not None:
                normalized[field_name] = np.asarray(value, dtype=float).copy()
        if "period_lengths_seconds" in normalized:
            normalized["period_lengths_seconds"] = tuple(
                float(value) for value in normalized["period_lengths_seconds"]
            )
        if "nonlinear_iterations" in normalized:
            normalized["nonlinear_iterations"] = tuple(
                int(value) for value in normalized["nonlinear_iterations"]
            )
        if "converged_by_period" in normalized:
            normalized["converged_by_period"] = tuple(
                bool(value) for value in normalized["converged_by_period"]
            )
        return cls(**normalized)


__all__ = ["BoussinesqState"]
