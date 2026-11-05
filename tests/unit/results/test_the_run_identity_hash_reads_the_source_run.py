"""The run identity hash reads the source run a configuration points at by its sim_id.

``[flow] restart_from`` and the ``run`` of a ``[[mesh.refinement_zone]]`` name an
earlier run, and a bare name is its latest version. The frozen ``config.toml``
writes the sim_id instead. Hashing the text as written made the original and
its frozen copy hash apart, so ``hmp run --resume`` of an interrupted run
started over, and made two runs that read two versions of one source run hash
alike, so the second was skipped as identical.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hydromodpy.results.catalog.registration import run_identity_hash
from hydromodpy.results.source_runs import resolve_source_runs, source_run_id
from hydromodpy.results.storage.contract import FIELDS_STORE_NAME
from tests._helpers.sealed_runs import make_project, seal_run

ZONE = {"where": "watertable_depth", "below": 0.5, "cell_size": 25.0}


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return make_project(tmp_path / "demo")


def _sealed(project: Path, name: str) -> str:
    sim_id = seal_run(project, name, site=None)
    (project / "runs" / name / FIELDS_STORE_NAME).mkdir()
    return sim_id


def _config(project: Path, *, zone_run: str | None = None, restart: Any = None) -> dict:
    config: dict[str, Any] = {"workspace": {"project_root": str(project)}, "flow": {}}
    if zone_run is not None:
        config["mesh"] = {"engine": "voronoi", "refinement_zone": [{**ZONE, "run": zone_run}]}
    if restart is not None:
        config["flow"]["restart_from"] = restart
    return config


def _hash(project: Path, **kwargs: Any) -> str | None:
    return run_identity_hash(_config(project, **kwargs))


def test_a_reference_resolves_to_the_sim_id_of_a_sealed_run(project: Path) -> None:
    first = _sealed(project, "spinup")
    second = _sealed(project, "spinup.v2")

    assert source_run_id(project, "spinup") == second, "a bare name is the latest version"
    assert source_run_id(project, "spinup.v2") == second
    assert source_run_id(project, "runs/spinup") == first
    assert source_run_id(project, f"runs/spinup/{FIELDS_STORE_NAME}") == first
    assert source_run_id(project, str(project / "runs" / "spinup")) == first
    assert source_run_id(project, first) == first
    assert source_run_id(project, first[:10]) == first


def test_a_reference_that_names_no_sealed_run_has_no_sim_id(project: Path) -> None:
    sealed = _sealed(project, "spinup")
    (project / "runs" / "open").mkdir()

    assert source_run_id(project, "nowhere") is None
    assert source_run_id(project, "open") is None
    assert source_run_id(project, "") is None
    assert source_run_id(project, sealed[:4]) is None, "a prefix needs eight characters"
    assert source_run_id(project, "0" * 32) is None


def test_a_prefix_that_matches_two_runs_names_none(project: Path) -> None:
    seal_run(project, "first", site=None, sim_id="ab" * 16)
    seal_run(project, "second", site=None, sim_id="ab" * 8 + "cd" * 8)

    assert source_run_id(project, "ab" * 4) is None
    assert source_run_id(project, "ab" * 8 + "cd") == "ab" * 8 + "cd" * 8


def test_the_references_of_a_payload_are_written_as_sim_ids(project: Path) -> None:
    sim_id = _sealed(project, "spinup")
    payload = _config(project, zone_run="spinup", restart="spinup")

    resolve_source_runs(payload, project)

    assert payload["mesh"]["refinement_zone"][0]["run"] == sim_id
    assert payload["flow"]["restart_from"] == sim_id


def test_a_reference_to_nothing_is_left_as_written(project: Path) -> None:
    payload = _config(project, zone_run="nowhere", restart="elsewhere")

    resolve_source_runs(payload, project)

    assert payload["mesh"]["refinement_zone"][0]["run"] == "nowhere"
    assert payload["flow"]["restart_from"] == "elsewhere"


def test_a_zone_hashes_alike_by_name_and_by_sim_id(project: Path) -> None:
    sim_id = _sealed(project, "coarse")

    assert _hash(project, zone_run="coarse") == _hash(project, zone_run=sim_id)
    assert _hash(project, zone_run="coarse") == _hash(project, zone_run="coarse")


def test_a_later_version_of_the_source_changes_the_hash_of_a_new_run(project: Path) -> None:
    first = _sealed(project, "coarse")
    before = _hash(project, zone_run="coarse")

    second = _sealed(project, "coarse.v2")

    assert _hash(project, zone_run="coarse") != before, "the bare name now reads the .v2"
    assert _hash(project, zone_run="coarse") == _hash(project, zone_run=second)
    assert _hash(project, zone_run=first) == before, "the sim_id of the first run still does not"


def test_a_zone_on_a_run_that_does_not_exist_still_hashes(project: Path) -> None:
    assert _hash(project, zone_run="nowhere") != _hash(project, zone_run="elsewhere")


def test_a_hotstart_hashes_alike_in_every_form_that_names_one_run(project: Path) -> None:
    from hydromodpy.core.state.result_dirs import run_dir_rel

    sim_id = _sealed(project, "spinup")
    store = f"{run_dir_rel('spinup')}/{FIELDS_STORE_NAME}"
    table = {"sim_id": sim_id, "path": store}
    forms = ["spinup", sim_id, store, str(project / store), table]

    assert len({_hash(project, restart=form) for form in forms}) == 1
    assert _hash(project, restart="spinup") != _hash(project, restart=None)


def test_a_table_of_a_run_outside_this_project_hashes_by_its_sim_id(project: Path) -> None:
    sim_id = "c" * 32

    table = {"sim_id": sim_id, "path": "runs/gone/fields.zarr"}

    assert _hash(project, restart=table) == _hash(project, restart=sim_id)


def test_a_later_version_of_the_hotstart_source_changes_the_hash(project: Path) -> None:
    first = _sealed(project, "spinup")
    before = _hash(project, restart="spinup")

    second = _sealed(project, "spinup.v2")

    assert _hash(project, restart="spinup") != before
    assert _hash(project, restart="spinup") == _hash(project, restart=second)
    assert _hash(project, restart={"sim_id": first, "path": "runs/spinup/fields.zarr"}) == before


def test_a_configuration_without_a_project_root_hashes_as_written() -> None:
    config = {"mesh": {"engine": "voronoi", "refinement_zone": [{**ZONE, "run": "coarse"}]}}

    assert run_identity_hash(config) == run_identity_hash(
        {"mesh": {"engine": "voronoi", "refinement_zone": [{**ZONE, "run": "coarse"}]}}
    )
    assert run_identity_hash(config) != run_identity_hash(
        {"mesh": {"engine": "voronoi", "refinement_zone": [{**ZONE, "run": "other"}]}}
    )
