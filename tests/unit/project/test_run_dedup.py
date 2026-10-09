"""A plain ``hmp run`` skips a re-run identical to a completed run.

Covers :func:`hydromodpy.project.dispatch.workflow.completed_identical_run`
and :func:`hydromodpy.results.catalog.registration.run_identity_hash`, the
``config_hash`` the catalog records at registration.
"""

from __future__ import annotations

import copy
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated

from pydantic import BaseModel

from hydromodpy.core.tracking.input_file import InputFile
from hydromodpy.project.dispatch.workflow import completed_identical_run
from hydromodpy.results.catalog.registration import input_file_digests, run_identity_hash
from tests._helpers.fixtures_catalog import simulation_catalog


def _stub_config(config: dict, root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        model_dump=lambda *, mode="json": config,
        workspace=SimpleNamespace(project_root=str(root)),
    )


def _register(root: Path, config: dict, *, name: str = "demo", status: str = "completed") -> str:
    sid = str(uuid.uuid4())
    with simulation_catalog(root) as cat:
        cat.register_simulation(sid, project="p", solver="modflow6", name=name, config=config)
        cat._backend.execute(
            "UPDATE simulations SET status_id = "
            "(SELECT id FROM statuses WHERE code = ?), "
            "ended_at = current_timestamp WHERE sim_id = ?",
            [status, sid],
        )
    return sid


def _config(sy: float = 0.001, scratch: str = "/p/.hmp/scratch/demo.p111") -> dict:
    return {
        "flow": {"sy": sy},
        "simulation": {"name": "demo"},
        "workspace": {"project_root": "/p", "solver_scratch_folder": scratch},
    }


def test_identical_config_matches_and_change_discriminates(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    sid = _register(root, _config())

    found = completed_identical_run(_stub_config(_config(), root), name="demo")
    assert found == ("demo", sid)

    # Any changed parameter flips the hash, so the run is not a duplicate.
    assert completed_identical_run(_stub_config(_config(sy=0.01), root), name="demo") is None


def test_the_scratch_folder_of_the_process_does_not_count(tmp_path: Path) -> None:
    """Two processes name two scratch folders; the run is the same run."""
    root = tmp_path / "ws"
    sid = _register(root, _config(scratch="/p/.hmp/scratch/demo.p111"))

    other_process = _config(scratch="/p/.hmp/scratch")
    found = completed_identical_run(_stub_config(other_process, root), name="demo")
    assert found is not None
    assert found[1] == sid


def test_another_name_is_another_run(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    _register(root, _config())
    assert completed_identical_run(_stub_config(_config(), root), name="other") is None


def test_non_completed_and_trashed_runs_do_not_trigger_skip(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    _register(root, _config(), status="running")
    _register(root, _config(), status="trashed")
    assert completed_identical_run(_stub_config(_config(), root), name="demo") is None


def test_missing_catalog_is_fail_open(tmp_path: Path) -> None:
    config = _stub_config(_config(), tmp_path / "absent")
    assert completed_identical_run(config, name="demo") is None


def test_identity_hash_reads_overrides_not_name() -> None:
    config = _config()
    base = run_identity_hash(config)
    assert base == run_identity_hash(copy.deepcopy(config))
    # The name lives in its own column, so a rename does not leave it stale.
    renamed = copy.deepcopy(config)
    renamed["simulation"]["name"] = "demo_k"
    assert base == run_identity_hash(renamed)
    assert base != run_identity_hash(config, overrides={"K": 1e-5})
    # The caller's dict is not touched.
    assert config["workspace"]["solver_scratch_folder"].endswith("demo.p111")
    assert config["simulation"]["name"] == "demo"
    # An override that does not serialise never matches anything.
    odd = {"properties": object()}
    assert run_identity_hash(config, overrides=odd) != run_identity_hash(config, overrides=odd)


def test_another_release_is_another_run(monkeypatch) -> None:
    config = _config()
    base = run_identity_hash(config)
    monkeypatch.setattr("hydromodpy.core.version.__version__", "0.0.0+other")
    assert run_identity_hash(config) != base


class _Workspace(BaseModel):
    project_root: str


class _ForcedConfig(BaseModel):
    """The smallest configuration that names a forcing file."""

    workspace: _Workspace
    simulation: dict
    recharge: Annotated[Path | None, InputFile(role="recharge", category="data")] = None


def _forced_project(tmp_path: Path) -> _ForcedConfig:
    root = tmp_path / "ws"
    forcing = root / "data" / "recharge.csv"
    forcing.parent.mkdir(parents=True)
    forcing.write_text("date,value\n2020-01-01,1.0\n")
    return _ForcedConfig(
        workspace=_Workspace(project_root=str(root)),
        simulation={"name": "demo"},
        recharge=Path("data/recharge.csv"),
    )


def _register_as_a_run(config: _ForcedConfig, *, name: str = "demo") -> str:
    """Register ``config`` with the hash the pipeline records."""
    sid = str(uuid.uuid4())
    dump = config.model_dump(mode="json")
    config_hash = run_identity_hash(dump, inputs=input_file_digests(config))
    with simulation_catalog(Path(config.workspace.project_root)) as cat:
        cat.register_simulation(
            sid, project="p", solver="modflow6", name=name, config=dump, config_hash=config_hash
        )
        cat._backend.execute(
            "UPDATE simulations SET status_id = "
            "(SELECT id FROM statuses WHERE code = 'completed') WHERE sim_id = ?",
            [sid],
        )
    return sid


def test_an_edited_forcing_file_is_another_run(tmp_path: Path) -> None:
    config = _forced_project(tmp_path)
    sid = _register_as_a_run(config)
    assert completed_identical_run(config, name="demo") == ("demo", sid)

    forcing = Path(config.workspace.project_root) / "data" / "recharge.csv"
    forcing.write_text("date,value\n2020-01-01,2.0\n")
    assert completed_identical_run(config, name="demo") is None


def test_a_renamed_run_no_longer_answers_to_its_old_name(tmp_path: Path) -> None:
    config = _forced_project(tmp_path)
    sid = _register_as_a_run(config, name="baseline")
    assert completed_identical_run(config, name="baseline") == ("baseline", sid)

    with simulation_catalog(Path(config.workspace.project_root)) as cat:
        cat.rename_simulation(sid, "baseline_ref")
    assert completed_identical_run(config, name="baseline") is None
    assert completed_identical_run(config, name="baseline_ref") == ("baseline_ref", sid)


def test_a_version_of_the_name_still_matches(tmp_path: Path) -> None:
    """``if_exists = "replace"`` leaves the live run under ``name.v2``."""
    config = _forced_project(tmp_path)
    sid = _register_as_a_run(config, name="demo.v2")
    assert completed_identical_run(config, name="demo") == ("demo.v2", sid)


def test_inputs_that_cannot_be_walked_never_match(monkeypatch, tmp_path: Path) -> None:
    """The run goes on, and errs on the side of computing."""

    def broken(*_args, **_kwargs):
        raise RuntimeError("walker failed")

    monkeypatch.setattr("hydromodpy.core.tracking.collect_input_files", broken)
    config = _forced_project(tmp_path)
    assert input_file_digests(config) != input_file_digests(config)
