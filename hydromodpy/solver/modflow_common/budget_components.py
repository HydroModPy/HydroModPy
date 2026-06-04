"""Classifier for MODFLOW budget records that map to a scalar stress/storage flux."""

from __future__ import annotations

# Records that are NOT scalar volumetric stress/storage fluxes. FLOW-JA-FACE and
# the directional FACE flows are antisymmetric intercell fluxes that net to ~0
# (they belong to the vector flow field, not a budget total). DATA-SPDIS is the
# specific-discharge velocity (m/s), not a volumetric flux, and must never be
# summed or reduced into a scalar budget term.
_EXCLUDED_BUDGET_COMPONENTS: frozenset[str] = frozenset(
    {
        # intercell / face flows (vector field, handled elsewhere)
        "FLOW-JA-FACE",
        "FLOW RIGHT FACE",
        "FLOW FRONT FACE",
        "FLOW LOWER FACE",
        # specific-discharge velocity vector (m/s)
        "DATA-SPDIS",
    }
)


def is_scalar_budget_component(record_name: str) -> bool:
    """Return True when a budget record is a real scalar stress/storage flux.

    Surviving terms (DRN, RCHA, WEL, CHD, STO-SS, STO-SY, ...) are volumetric
    fluxes in length^3 per time unit. Returns False for intercell face flows and
    for the specific-discharge velocity, which would corrupt a scalar budget.
    """
    normalized = " ".join(str(record_name).strip().upper().split())
    return normalized not in _EXCLUDED_BUDGET_COMPONENTS


__all__ = ["is_scalar_budget_component"]
