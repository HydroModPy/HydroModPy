"""``[flow] restart_from`` names a run; the step resolves it to a store and links by id.

A run name, with or without its version, a ``sim_id`` or a path: each resolves
to the field store the solver reads, and to the ``sim_id`` of the sealed run
that holds it. The step binds the resolved path on the flow configuration,
so the frozen ``config.toml`` writes it relative to the project, and the
lineage of the run names its source by id.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.results.storage.contract import FIELDS_STORE_NAME
from hydromodpy.workflow.steps.prepare_solver.dispatch import _bind_restart_source
from hydromodpy.workflow.steps.prepare_solver.restart import resolve_restart_source
from tests._helpers.run_stores import open_run_store
from tests._helpers.sealed_runs import make_project, seal_run


def _sealed(project: Path, name: str) -> str:
    sid = seal_run(project, name, site=None)
    (project / "runs" / name / FIELDS_STORE_NAME).mkdir()
    return sid


def test_a_run_name_resolves_to_its_latest_version(tmp_path: Path) -> None:
    project = make_project(tmp_path / "demo")
    _sealed(project, "spinup")
    sid_v2 = _sealed(project, "spinup.v2")

    source = resolve_restart_source(project, "spinup")

    assert source.sim_id == sid_v2
    assert source.path == project / "runs" / "spinup.v2" / FIELDS_STORE_NAME
    assert source.rel_dir == "runs/spinup.v2"


def test_a_versioned_name_a_sim_id_and_a_path_resolve_to_the_same_run(tmp_path: Path) -> None:
    project = make_project(tmp_path / "demo")
    sid = _sealed(project, "spinup")
    _sealed(project, "spinup.v2")
    expected = project / "runs" / "spinup" / FIELDS_STORE_NAME

    assert resolve_restart_source(project, "spinup").path != expected, "the bare name is v2"
    assert resolve_restart_source(project, "runs/spinup").path == expected
    assert resolve_restart_source(project, sid).sim_id == sid
    assert resolve_restart_source(project, sid[:12]).path == expected
    assert resolve_restart_source(project, f"runs/spinup/{FIELDS_STORE_NAME}").sim_id == sid
    assert resolve_restart_source(project, str(expected)).rel_dir == "runs/spinup"


def test_a_store_outside_any_seal_resolves_without_an_id(tmp_path: Path) -> None:
    loose = tmp_path / "elsewhere" / FIELDS_STORE_NAME
    loose.mkdir(parents=True)

    source = resolve_restart_source(make_project(tmp_path / "demo"), str(loose))

    assert source.sim_id is None and source.path == loose and source.rel_dir is None


def test_an_unknown_reference_is_refused_by_name(tmp_path: Path) -> None:
    project = make_project(tmp_path / "demo")
    with pytest.raises(ConfigError, match="nowhere"):
        resolve_restart_source(project, "nowhere")


def test_an_unsealed_run_without_store_is_refused(tmp_path: Path) -> None:
    project = make_project(tmp_path / "demo")
    seal_run(project, "spinup", site=None)
    with pytest.raises(ConfigError, match=FIELDS_STORE_NAME):
        resolve_restart_source(project, "spinup")


def test_the_step_binds_the_resolved_path_and_links_the_lineage_by_id(tmp_path: Path) -> None:
    project = make_project(tmp_path / "demo")
    sid = _sealed(project, "spinup")
    store = open_run_store(project, "production", n_cells=4)
    flow = SimpleNamespace(restart_from="spinup")
    ctx = SimpleNamespace(cfg=SimpleNamespace(flow=flow), lineage=None)

    _bind_restart_source(ctx, store=store)

    assert flow.restart_from == str(project / "runs" / "spinup" / FIELDS_STORE_NAME)
    assert store.facts.lineage.parent_sim_id == sid
    assert store.facts.lineage.parent_hint == "runs/spinup"
    assert ctx.lineage == store.facts.lineage
    store.close()


def test_without_a_reference_the_step_touches_nothing(tmp_path: Path) -> None:
    project = make_project(tmp_path / "demo")
    store = open_run_store(project, "production", n_cells=4)
    flow = SimpleNamespace(restart_from=None)
    ctx = SimpleNamespace(cfg=SimpleNamespace(flow=flow), lineage=None)

    _bind_restart_source(ctx, store=store)

    assert flow.restart_from is None
    assert store.facts.lineage.parent_sim_id is None
    store.close()


def test_the_table_form_finds_its_run_by_sim_id_first(tmp_path: Path) -> None:
    from hydromodpy.physics.flow.flow_config import RestartReference

    project = make_project(tmp_path / "demo")
    sid = _sealed(project, "spinup")
    _sealed(project, "spinup.v2")

    source = resolve_restart_source(
        project, RestartReference(sim_id=sid, path="runs/spinup.v2/fields.zarr")
    )

    assert source.sim_id == sid
    assert source.path == project / "runs" / "spinup" / FIELDS_STORE_NAME


def test_the_table_form_falls_back_to_its_path_in_another_project(tmp_path: Path) -> None:
    from hydromodpy.physics.flow.flow_config import RestartReference

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


def test_a_restart_reference_names_a_sim_id_or_a_path() -> None:
    from pydantic import ValidationError

    from hydromodpy.physics.flow.flow_config import RestartReference

    with pytest.raises(ValidationError, match="names a sim_id, a path, or both"):
        RestartReference()
    assert RestartReference.model_validate({"path": "runs/a"}).sim_id is None


def test_the_step_returns_the_sim_id_the_frozen_config_writes(tmp_path: Path) -> None:
    from hydromodpy.physics.flow.flow_config import RestartReference

    project = make_project(tmp_path / "demo")
    sid = _sealed(project, "spinup")
    store = open_run_store(project, "production", n_cells=4)
    flow = SimpleNamespace(restart_from=RestartReference(sim_id=sid))
    ctx = SimpleNamespace(cfg=SimpleNamespace(flow=flow), lineage=None)

    returned = _bind_restart_source(ctx, store=store)

    assert returned == sid
    assert flow.restart_from == str(project / "runs" / "spinup" / FIELDS_STORE_NAME)
    store.close()
