"""``resolve_restart_source``: a ``[flow] restart_from`` reference becomes a field store and a ``sim_id``."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.model.flow_config import RestartReference
from hydromodpy.results.storage.contract import FIELDS_STORE_NAME
from hydromodpy.workflow.steps.prepare_solver.restart import resolve_restart_source
from tests._helpers.sealed_runs import make_project, seal_run
from tests.unit.workflow.steps.prepare_solver._helpers import sealed_run

# A restart reference (run name, with or without its version, ``sim_id`` or path) resolves to the
# field store the solver reads and to the ``sim_id`` of the sealed run that holds it.


def test_name_sim_id_and_path_resolve_to_one_run(tmp_path: Path) -> None:
    project = make_project(tmp_path / "demo")
    sid = sealed_run(project, "spinup")
    sealed_run(project, "spinup.v2")
    expected = project / "runs" / "spinup" / FIELDS_STORE_NAME

    assert resolve_restart_source(project, "spinup").path != expected, "the bare name is v2"
    assert resolve_restart_source(project, "runs/spinup").path == expected
    assert resolve_restart_source(project, sid).sim_id == sid
    assert resolve_restart_source(project, sid[:12]).path == expected
    assert resolve_restart_source(project, f"runs/spinup/{FIELDS_STORE_NAME}").sim_id == sid
    assert resolve_restart_source(project, str(expected)).rel_dir == "runs/spinup"


def test_unknown_reference(tmp_path: Path) -> None:
    project = make_project(tmp_path / "demo")
    with pytest.raises(ConfigError, match="nowhere"):
        resolve_restart_source(project, "nowhere")


def test_unsealed_run_without_store(tmp_path: Path) -> None:
    project = make_project(tmp_path / "demo")
    seal_run(project, "spinup", site=None)
    with pytest.raises(ConfigError, match=FIELDS_STORE_NAME):
        resolve_restart_source(project, "spinup")


def test_table_form_finds_sim_id_first(tmp_path: Path) -> None:
    project = make_project(tmp_path / "demo")
    sid = sealed_run(project, "spinup")
    sealed_run(project, "spinup.v2")

    source = resolve_restart_source(
        project, RestartReference(sim_id=sid, path="runs/spinup.v2/fields.zarr")
    )

    assert source.sim_id == sid
    assert source.path == project / "runs" / "spinup" / FIELDS_STORE_NAME


def test_table_form_falls_back_to_path(tmp_path: Path) -> None:
    project = make_project(tmp_path / "demo")
    loose = project / "inputs" / FIELDS_STORE_NAME
    loose.mkdir(parents=True)

    source = resolve_restart_source(
        project, RestartReference(sim_id="0" * 32, path=f"inputs/{FIELDS_STORE_NAME}")
    )

    assert source.path == loose
    assert source.sim_id == "0" * 32
    with pytest.raises(ConfigError, match="no sealed run of this project has that sim_id"):
        resolve_restart_source(project, RestartReference(sim_id="1" * 32, path="missing"))


def test_reference_needs_sim_id_or_path() -> None:

    with pytest.raises(ValidationError, match="names a sim_id, a path, or both"):
        RestartReference()
    assert RestartReference.model_validate({"path": "runs/a"}).sim_id is None
