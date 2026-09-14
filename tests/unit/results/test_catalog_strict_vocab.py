"""Strict v2 vocabulary checks for solver codes and mesh topologies.

The catalog accepts only the canonical ``solvers.code`` values seeded in
``catalog/migrations/versions/0001_initial_v2_schema.sql``. Legacy aliases
like ``modflow6gwt`` and ``modflownwt`` are rejected eagerly.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from hydromodpy.results.catalog.constants import (
    VALID_SOLVER_CODES,
    validate_solver_code,
)
from hydromodpy.results.catalog.facade import Catalog
from tests._helpers.fixtures_catalog import simulation_catalog


@pytest.fixture
def catalog(tmp_path: Path):
    with simulation_catalog(tmp_path) as cat:
        yield cat


def test_validate_solver_code_accepts_canonical_codes() -> None:
    for code in VALID_SOLVER_CODES:
        assert validate_solver_code(code) == code


def test_validate_solver_code_strips_and_lowercases() -> None:
    assert validate_solver_code("  MODFLOW6  ") == "modflow6"
    assert validate_solver_code("MODFLOW_NWT") == "modflow_nwt"


def test_validate_solver_code_rejects_modflownwt_alias() -> None:
    with pytest.raises(ValueError, match="Unknown solver code"):
        validate_solver_code("modflownwt")


def test_validate_solver_code_rejects_modflow6gwt_alias() -> None:
    with pytest.raises(ValueError, match="Unknown solver code"):
        validate_solver_code("modflow6gwt")


def test_validate_solver_code_lists_known_codes() -> None:
    with pytest.raises(ValueError) as excinfo:
        validate_solver_code("not_a_solver")
    msg = str(excinfo.value)
    for known in VALID_SOLVER_CODES:
        assert known in msg


def test_register_simulation_rejects_legacy_solver_name(catalog) -> None:
    sid = str(uuid.uuid4())
    with pytest.raises(ValueError, match="Unknown solver code"):
        catalog.register_simulation(sid, project="test", solver="modflow6gwt")


def test_register_simulation_rejects_modflownwt_alias(catalog) -> None:
    sid = str(uuid.uuid4())
    with pytest.raises(ValueError, match="Unknown solver code"):
        catalog.register_simulation(sid, project="test", solver="modflownwt")


def test_register_simulation_accepts_canonical_modflow_nwt(catalog) -> None:
    sid = str(uuid.uuid4())
    reg = catalog.register_simulation(sid, project="test", solver="modflow_nwt")
    if reg.zarr is not None:
        reg.zarr.close()
