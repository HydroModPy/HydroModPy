"""Vocabulary of solver codes.

The index seeds ``solvers.code`` from ``index_schema.py``. A name typed by a
user is checked by :func:`validate_solver_code`, which refuses legacy aliases
like ``modflow6gwt`` and ``modflownwt``. A seal naming a code the table does not
hold is indexed all the same, and the code is added: a later 2.x may write one.
"""

from __future__ import annotations

import pytest

from hydromodpy.results.catalog import Catalog, rebuild_index
from hydromodpy.results.catalog.constants import (
    VALID_SOLVER_CODES,
    validate_solver_code,
)
from tests._helpers.sealed_runs import make_project, seal_run


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


def test_a_seal_naming_a_solver_outside_the_vocabulary_is_still_indexed(tmp_path):
    root = make_project(tmp_path / "demo")
    seal_run(root, "canonical", solver="modflow_nwt")
    seal_run(root, "later", solver="a_later_solver")

    report = rebuild_index(root)

    assert not report.skipped
    with Catalog(root) as catalog:
        assert sorted(catalog.list_simulations()["name"]) == ["canonical", "later"]
