"""``provenance.json`` must name the engine that solved, not the one on disk.

A MODFLOW 6 run driven through ``libmf6`` never opens the ``mf6`` executable.
Recording the executable would publish a sha256 and a version describing an
unrelated file, and would hide which dispatch produced the numbers.
"""

from __future__ import annotations

import json

import pytest

from hydromodpy.core.state.paths import catalog_path_for
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.reindex import rebuild_index
from hydromodpy.results.manifest import build_provenance
from hydromodpy.results.storage.contract import RUN_CONFIG_FILENAME

SID = "00000000-0000-4000-8000-0000000eeeee"


def _register(catalog: Catalog) -> None:
    reg = catalog.register_simulation(
        SID,
        project="engine",
        solver="modflow6",
        name="engine_run",
        n_cells=8,
        n_layers=1,
    )
    if reg.zarr is not None:
        reg.zarr.close()


@pytest.fixture
def library_run(tmp_path):
    """A run whose engine is the shared library, sealed on disk."""
    lib = tmp_path / "libmf6.so"
    lib.write_bytes(b"pretend shared library")
    project_root = tmp_path / "project"
    with Catalog(project_root) as catalog:
        _register(catalog)
        catalog.write_run_environment(
            SID,
            solver_name="modflow6",
            solver_binary_path=lib,
            solver_engine="library",
            solver_execution_mode="api",
            solver_version_text="6.6.3",
        )
        (catalog.run_dir_for(SID) / RUN_CONFIG_FILENAME).write_text("[flow]\n")
        catalog.finalize(SID, status="completed", duration_s=1.0)
        yield catalog, lib, project_root


def test_provenance_names_the_library_and_the_api_mode(library_run) -> None:
    catalog, lib, _ = library_run
    solver = build_provenance(catalog, SID)["solver"]

    assert solver["engine"] == "library"
    assert solver["execution_mode"] == "api"
    assert solver["version"] == "6.6.3"
    assert solver["binary_path"] == str(lib)
    assert solver["binary_sha256"], "the library must be fingerprinted like an executable"


def test_a_library_engine_survives_the_post_run_executable_refinement(library_run) -> None:
    """The model still exposes ``exe``; refining from it would rewrite history."""
    catalog, lib, _ = library_run
    before = build_provenance(catalog, SID)["solver"]

    catalog.update_run_environment_solver_binary(SID, solver_binary_path="/somewhere/mf6")

    assert build_provenance(catalog, SID)["solver"] == before
    assert before["binary_path"] == str(lib)


def test_an_executable_engine_still_accepts_the_refinement(tmp_path) -> None:
    exe = tmp_path / "mf6_custom"
    exe.write_bytes(b"pretend executable")
    with Catalog(tmp_path / "project") as catalog:
        _register(catalog)
        catalog.write_run_environment(
            SID,
            solver_name="modflow6",
            solver_engine="executable",
            solver_execution_mode="subprocess",
        )
        catalog.update_run_environment_solver_binary(SID, solver_binary_path=exe)
        solver = build_provenance(catalog, SID)["solver"]

    assert solver["binary_path"] == str(exe)
    assert solver["engine"] == "executable"


def test_the_engine_block_survives_an_index_rebuild(library_run) -> None:
    """The index is rebuildable, so the engine must live in the run directory."""
    catalog, _, project_root = library_run
    expected = build_provenance(catalog, SID)["solver"]
    catalog.close()

    catalog_path_for(project_root).unlink()
    rebuild_index(project_root)

    with Catalog(project_root) as rebuilt:
        rebuilt_solver = build_provenance(rebuilt, SID)["solver"]

    assert rebuilt_solver["engine"] == expected["engine"]
    assert rebuilt_solver["execution_mode"] == expected["execution_mode"]
    assert rebuilt_solver["version"] == expected["version"]


def test_provenance_json_on_disk_carries_the_engine(library_run) -> None:
    catalog, _, _root = library_run
    payload = json.loads((catalog.run_dir_for(SID) / "provenance.json").read_text(encoding="utf-8"))

    assert payload["solver"]["engine"] == "library"
    assert payload["solver"]["execution_mode"] == "api"
