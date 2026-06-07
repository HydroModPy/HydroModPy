"""Shared major-ion meq/L conversion helper for hydrochem diagram tests.

The diagram builders consume meq/L data (see each module docstring). The
mg/L -> meq/L conversion is upstream science: meq/L = (mg/L) / equiv_weight,
with equiv_weight = molar_mass / |valence|. These tests do the conversion
explicitly, feed meq/L to the real builders, and assert geometry.
"""

from __future__ import annotations

# Equivalent weights in mg/meq = molar mass / |valence|.
EQUIV_WEIGHT = {
    "Ca": 40.078 / 2,
    "Mg": 24.305 / 2,
    "Na": 22.990 / 1,
    "K": 39.098 / 1,
    "Cl": 35.453 / 1,
    "SO4": 96.06 / 2,
    "HCO3": 61.016 / 1,
}


def mg_to_meq(sample_mg: dict[str, float]) -> dict[str, float]:
    """Convert one major-ion sample from mg/L to meq/L."""
    return {ion: value / EQUIV_WEIGHT[ion] for ion, value in sample_mg.items()}
