"""Classifier and canonical naming for MODFLOW budget records.

MODFLOW-NWT and MODFLOW 6 name the same physical flux differently
(``RECHARGE`` vs ``RCHA``, ``DRAINS`` vs ``DRN``, ``WELLS`` vs ``WEL``).
:func:`canonical_budget_component` maps both vocabularies onto the public
names declared in :mod:`hydromodpy.results.field_registry`, so the stored
spatial fields under ``budget/`` are backend-agnostic and figures can read
``recharge`` or ``drain`` whatever solved the model.
"""

from __future__ import annotations

# Records that are NOT scalar volumetric stress/storage fluxes. FLOW-JA-FACE and
# the directional FACE flows are antisymmetric intercell fluxes that net to ~0
# (they belong to the vector flow field, not a budget total). DATA-SPDIS is the
# specific-discharge velocity (m/s) and DATA-SAT is the dimensionless cell
# saturation fraction; neither is a volumetric flux, so they must never be
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
        # cell saturation fraction (dimensionless), not a flux
        "DATA-SAT",
    }
)

# MODFLOW record name (normalized upper-case, single-spaced) -> public field
# name. Anything absent keeps its own lower-case name, so a package we do not
# model explicitly still lands in the store under a predictable key.
_CANONICAL_BUDGET_NAMES: dict[str, str] = {
    # recharge
    "RECHARGE": "recharge",
    "RCHA": "recharge",
    "RCH": "recharge",
    # hillslope drainage
    "DRAINS": "drain",
    "DRAIN": "drain",
    "DRN": "drain",
    "DRAINS (DRT)": "drain",
    # Drain flux handed to the water mover (route_drainage): a distinct
    # record, kept distinct, because it leaves the DRN package for SFR/LAK.
    "DRN-TO-MVR": "drain_to_mover",
    "LAK-TO-MVR": "lake_to_mover",
    "SFR-TO-MVR": "stream_to_mover",
    # pumping / injection wells
    "WELLS": "well",
    "WEL": "well",
    # river leakage
    "RIVER LEAKAGE": "river",
    "RIV": "river",
    # constant head
    "CONSTANT HEAD": "constant_head",
    "CHD": "constant_head",
    # evapotranspiration
    "ET": "evapotranspiration",
    "EVT": "evapotranspiration",
    "EVTA": "evapotranspiration",
    # general-head boundary
    "HEAD DEP BOUNDS": "general_head",
    "GHB": "general_head",
    # storage
    "STORAGE": "storage",
    "STO-SS": "storage_ss",
    "STO-SY": "storage_sy",
    # advanced packages
    "LAK": "lake",
    "SFR": "stream",
    "MVR": "mover",
}


def _normalize(record_name: str) -> str:
    """Return the record name upper-cased with collapsed inner whitespace."""
    return " ".join(str(record_name).strip().upper().split())


def is_scalar_budget_component(record_name: str) -> bool:
    """Return True when a budget record is a real scalar stress/storage flux.

    Surviving terms (DRN, RCHA, WEL, CHD, STO-SS, STO-SY, ...) are volumetric
    fluxes in length^3 per time unit. Returns False for intercell face flows and
    for the specific-discharge velocity, which would corrupt a scalar budget.
    """
    return _normalize(record_name) not in _EXCLUDED_BUDGET_COMPONENTS


def canonical_budget_component(record_name: str) -> str:
    """Map one MODFLOW budget record name onto its public field name.

    Unknown records fall back to their lower-cased, single-spaced name so no
    package is silently dropped from the store.
    """
    normalized = _normalize(record_name)
    return _CANONICAL_BUDGET_NAMES.get(normalized, normalized.lower())


__all__ = [
    "canonical_budget_component",
    "is_scalar_budget_component",
]
