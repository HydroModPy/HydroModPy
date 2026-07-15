"""Storage-contract constants that every layer must agree on.

The catalog filename, project TOML filename, and workspace TOML filename
live in :mod:`hydromodpy.core.state.paths`. Every consumer (cli, results,
data) must import them from there - no duplicate string literals.
"""

from __future__ import annotations

from hydromodpy.core.state.paths import (
    CATALOG_FILENAME,
    INDEX_FILENAME,
    PROJECT_TOML_FILENAME,
    WORKSPACE_TOML_FILENAME,
)


def test_catalog_filename_is_canonical():
    assert CATALOG_FILENAME == "catalog.duckdb"


def test_project_toml_filename_is_canonical():
    assert PROJECT_TOML_FILENAME == "hydromodpy.toml"


def test_workspace_toml_filename_is_canonical():
    assert WORKSPACE_TOML_FILENAME == "workspace.toml"


def test_index_filename_is_canonical():
    assert INDEX_FILENAME == "index.duckdb"


def test_storage_contract_module_does_not_redefine_catalog_filename():
    """``results.storage.contract`` must reuse the core constant verbatim."""
    from hydromodpy.results.storage import contract

    assert contract.CATALOG_FILENAME is CATALOG_FILENAME


def test_no_legacy_hydromodpy_duckdb_in_filename_constants():
    for name in (CATALOG_FILENAME, PROJECT_TOML_FILENAME, WORKSPACE_TOML_FILENAME):
        assert name != "hydromodpy.duckdb"
        assert name != "project.toml"
