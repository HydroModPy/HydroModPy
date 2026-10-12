"""Every per-cell term an extractor writes, and every virtual field, has a descriptor.

A term without a descriptor is stored but never listed, exported or read: the
registry is the gate of ``run.array.list_fields``, ``hmp export --list`` and
``[[export]] variables = "all"``.

The list of terms is the canonical map, so it cannot see a record that map does
not name: ``canonical_budget_component`` passes such a record through as its
lower-cased name, and that term lands in the store without a descriptor. The
record names the MODFLOW builders emit are listed below and checked against the
map; an unmapped record a future package emits is not caught here.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.field_routing import STREAM_CONSTANT_HEAD_BUDGET
from hydromodpy.results import field_registry
from hydromodpy.results.derive.virtual_fields import VIRTUAL_FIELDS, field_descriptor
from hydromodpy.solver.boussinesq.extractors.flow import BoussinesqOutputAdapter
from hydromodpy.solver.modflow_common.budget_components import (
    CANONICAL_BUDGET_TERMS,
    canonical_budget_component,
)

N_CELLS = 3

VIRTUAL_FIELD_NAMES = (
    "watertable_elevation",
    "watertable_depth",
    "seepage_mask",
    "outflow_drain",
    "release_flux",
    "fluxes_from_budget",
    "accumulation_flux",
    "release_accumulation_flux",
    "concentration_seepage",
    "mass_seepage",
    "mass_accumulated",
    "simulated_active_network",
)
"""Every name ``available_virtual_fields`` or the network reader can list."""


MODFLOW_6_RECORDS = (
    "DRN",
    "DRN-TO-MVR",
    "RCHA",
    "CHD",
    "WEL",
    "EVTA",
    "STO-SS",
    "STO-SY",
    "SFR",
    "LAK",
)
MODFLOW_NWT_RECORDS = (
    "DRAINS",
    "RECHARGE",
    "ET",
    "WELLS",
    "CONSTANT HEAD",
    "STORAGE",
    "STREAM LEAKAGE",
    "LAKE SEEPAGE",
)


def _boussinesq_terms() -> set[str]:
    """Return the components the Boussinesq extractor writes, given every history."""
    ones = np.ones((2, N_CELLS))
    payload = {
        "recharge_rate_history_m_s": ones,
        "drainage_flux_history_m3_s": ones,
        "well_flux_history_m3_s": ones,
        "saturation_excess_history_m_s": ones,
        "prescribed_head_flux_history_m3_s": ones,
    }
    components = BoussinesqOutputAdapter._budget_components(
        payload, n_timesteps=2, n_cells=N_CELLS, cell_area_m2=np.ones(N_CELLS)
    )
    return set(components)


def _written_terms() -> list[str]:
    terms = {*CANONICAL_BUDGET_TERMS, STREAM_CONSTANT_HEAD_BUDGET, *_boussinesq_terms()}
    return sorted(terms)


def test_the_boussinesq_extractor_writes_five_terms() -> None:
    assert _boussinesq_terms() == {"recharge", "drain", "well", "surface_excess", "constant_head"}


@pytest.mark.parametrize("term", _written_terms())
def test_a_written_budget_term_is_in_the_registry_under_budget(term: str) -> None:
    descriptor = field_registry.get(term)
    assert descriptor.zarr_path == f"budget/{term}"
    assert descriptor.units == "m3 s-1"
    assert descriptor.derived_by == "solver"


@pytest.mark.parametrize("record", [*MODFLOW_6_RECORDS, *MODFLOW_NWT_RECORDS])
def test_a_record_the_builders_emit_maps_to_a_canonical_term(record: str) -> None:
    assert canonical_budget_component(record) in CANONICAL_BUDGET_TERMS


def test_every_unknown_name_of_a_cell_budget_file_stays_out_of_the_registry() -> None:
    assert not field_registry.has("cell_budget")


@pytest.mark.parametrize("name", VIRTUAL_FIELD_NAMES)
def test_a_virtual_field_has_a_descriptor(name: str) -> None:
    descriptor = field_descriptor(name)
    assert descriptor.public_name == name
    assert descriptor.zarr_path == f"derived/{name}"


def test_the_virtual_field_table_names_nothing_outside_the_list() -> None:
    assert set(VIRTUAL_FIELDS) <= set(VIRTUAL_FIELD_NAMES)
