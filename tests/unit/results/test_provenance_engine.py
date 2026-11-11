"""``provenance.json`` must name the engine that solved, not the one on disk.

A MODFLOW 6 run driven through ``libmf6`` never opens the ``mf6`` executable.
Recording the executable would publish a sha256 and a version describing an
unrelated file, and would hide which dispatch produced the numbers.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hydromodpy.core.state.layout import catalog_path_for
from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.storage.contract import RUN_CONFIG_FILENAME
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.results.storage.sealing import build_provenance, seal_completed
from tests._helpers.run_stores import open_run_store

ENDED_AT = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)


def _solver(store: RunStore) -> dict:
    return dict(build_provenance(store.facts, ended_at=ENDED_AT).solver)


def _engine_of_index(project_root: Path, sim_id: str) -> tuple:
    with Catalog(project_root) as catalog:
        return catalog.connection.execute(
            "SELECT solver_engine, solver_execution_mode, solver_version_text "
            "FROM runs_environment WHERE sim_id = ?",
            [sim_id],
        ).fetchone()


@pytest.fixture
def library_run(tmp_path) -> Iterator[tuple[RunStore, Path, Path]]:
    """A run whose engine is the shared library, still open."""
    lib = tmp_path / "libmf6.so"
    lib.write_bytes(b"pretend shared library")
    project_root = tmp_path / "project"
    store = open_run_store(project_root, "engine_run", n_cells=8, n_layers=1)
    store.write_run_environment(
        store.sim_id,
        solver_name="modflow6",
        solver_binary_path=lib,
        solver_engine="library",
        solver_execution_mode="api",
        solver_version_text="6.6.3",
    )
    (store.run_dir / RUN_CONFIG_FILENAME).write_text("[flow]\n")
    yield store, lib, project_root
    store.close()


def test_provenance_names_the_library_and_the_api_mode(library_run) -> None:
    store, lib, _ = library_run
    solver = _solver(store)

    assert solver["engine"] == "library"
    assert solver["execution_mode"] == "api"
    assert solver["version"] == "6.6.3"
    assert solver["binary_path"] == str(lib)
    assert solver["binary_sha256"], "the library must be fingerprinted like an executable"


def test_a_library_engine_survives_the_post_run_executable_refinement(library_run) -> None:
    """The model still exposes ``exe``; refining from it would rewrite history."""
    store, lib, _ = library_run
    before = _solver(store)

    store.update_run_environment_solver_binary(store.sim_id, solver_binary_path="/somewhere/mf6")

    assert _solver(store) == before
    assert before["binary_path"] == str(lib)


def test_an_executable_engine_still_accepts_the_refinement(tmp_path) -> None:
    exe = tmp_path / "mf6_custom"
    exe.write_bytes(b"pretend executable")
    with open_run_store(tmp_path / "project", "engine_run", n_cells=8, n_layers=1) as store:
        store.write_run_environment(
            store.sim_id,
            solver_name="modflow6",
            solver_engine="executable",
            solver_execution_mode="subprocess",
        )
        store.update_run_environment_solver_binary(store.sim_id, solver_binary_path=exe)
        solver = _solver(store)

    assert solver["binary_path"] == str(exe)
    assert solver["engine"] == "executable"


def test_the_engine_block_survives_an_index_rebuild(library_run) -> None:
    """The index is rebuildable, so the engine must live in the run directory."""
    store, _, project_root = library_run
    sid = store.sim_id
    seal_completed(store)
    rebuild_index(project_root)
    expected = _engine_of_index(project_root, sid)

    catalog_path_for(project_root).unlink()
    rebuild_index(project_root)

    assert expected == ("library", "api", "6.6.3")
    assert _engine_of_index(project_root, sid) == expected


def test_provenance_json_on_disk_carries_the_engine(library_run) -> None:
    store, _, _root = library_run
    run_dir = store.run_dir
    seal_completed(store)
    payload = json.loads((run_dir / "provenance.json").read_text(encoding="utf-8"))

    assert payload["solver"]["engine"] == "library"
    assert payload["solver"]["execution_mode"] == "api"


@pytest.mark.parametrize(
    ("image", "expected"),
    [
        ({}, None),
        ({"tag": "2.1.0"}, {"tag": "2.1.0"}),
        (
            {"tag": "2.1.0", "digest": "sha256:" + "ab" * 32},
            {"tag": "2.1.0", "digest": "sha256:" + "ab" * 32},
        ),
        (
            {"tag": "2.1.0", "digest": "sha256:typo"},
            {"tag": "2.1.0", "digest_refused": "sha256:typo"},
        ),
    ],
)
def test_the_image_is_sealed_only_inside_an_image(
    library_run, monkeypatch, image, expected
) -> None:
    store, _, _ = library_run
    monkeypatch.setenv("HMP_IMAGE_TAG", image.get("tag", ""))
    if "digest" in image:
        monkeypatch.setenv("HMP_IMAGE_DIGEST", image["digest"])
    else:
        monkeypatch.delenv("HMP_IMAGE_DIGEST", raising=False)
    store.write_run_environment(store.sim_id, solver_name="modflow6")

    environment = build_provenance(store.facts, ended_at=ENDED_AT).environment

    assert environment.get("image") == expected
    assert ("image" in environment) is bool(expected)
