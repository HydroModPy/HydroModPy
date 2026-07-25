"""Storage-contract constants that every layer must agree on.

The catalog filename, the project marker filename and the workspace TOML
filename live in :mod:`hydromodpy.core.state.paths`. Every consumer (cli,
results, data) must import them from there - no duplicate string literals.
``project.toml`` plays one single role: it is both the project configuration
and the marker anchoring the project root.
"""

from __future__ import annotations

from hydromodpy.core.state.paths import (
    CATALOG_FILENAME,
    INDEX_FILENAME,
    INTERNAL_DIRNAME,
    PROJECT_MARKER_FILENAME,
    RUNS_DIRNAME,
    SHARE_DIRNAME,
    WORKSPACE_TOML_FILENAME,
    catalog_path_for,
    runs_dir_for,
    share_dir_for,
)


def test_catalog_filename_is_canonical():
    assert CATALOG_FILENAME == "index.duckdb"


def test_project_directory_names_are_canonical():
    assert PROJECT_MARKER_FILENAME == "project.toml"
    assert RUNS_DIRNAME == "runs"
    assert SHARE_DIRNAME == "share"
    assert INTERNAL_DIRNAME == ".hmp"


def test_project_path_helpers_build_the_runs_first_tree(tmp_path):
    assert catalog_path_for(tmp_path) == tmp_path / ".hmp" / "index.duckdb"
    assert runs_dir_for(tmp_path) == tmp_path / "runs"
    assert share_dir_for(tmp_path) == tmp_path / "share"


def test_workspace_toml_filename_is_canonical():
    assert WORKSPACE_TOML_FILENAME == "workspace.toml"


def test_index_filename_is_canonical():
    assert INDEX_FILENAME == "index.duckdb"


def test_storage_contract_module_does_not_redefine_catalog_filename():
    """``results.storage.contract`` must reuse the core constant verbatim."""
    from hydromodpy.results.storage import contract

    assert contract.CATALOG_FILENAME is CATALOG_FILENAME


def test_no_legacy_hydromodpy_duckdb_in_filename_constants():
    for name in (CATALOG_FILENAME, WORKSPACE_TOML_FILENAME):
        assert name != "hydromodpy.duckdb"
        assert name != PROJECT_MARKER_FILENAME
