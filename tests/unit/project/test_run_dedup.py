"""A plain ``hmp run`` skips a re-run identical to a completed run, read from the manifests.

Covers :func:`hydromodpy.project.dispatch.workflow.completed_identical_run`
and :func:`hydromodpy.results.catalog.registration.run_identity_hash`, the
``identity.config_hash`` a run seals. No index is opened: the manifests under
``runs/`` are the record.
"""

from __future__ import annotations

import copy
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated

from pydantic import BaseModel

from hydromodpy.core.state.paths import run_dir_rel
from hydromodpy.core.tracking.input_file import InputFile
from hydromodpy.project.dispatch.workflow import completed_identical_run
from hydromodpy.results.catalog.registration import input_file_digests, run_identity_hash
from hydromodpy.results.manifest import ManifestConfig, ManifestRun
from tests._helpers.sealed_runs import write_attempt
from tests.unit.results._run_record_factory import make_identity, make_record


def _stub_config(config: dict, root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        model_dump=lambda *, mode="json": config,
        workspace=SimpleNamespace(project_root=str(root)),
    )


def _seal(root: Path, config: dict, *, name: str = "demo") -> str:
    """Seal a run of *config* under ``runs/<name>`` and return its ``sim_id``."""
    sid = str(uuid.uuid4())
    config_hash = run_identity_hash(config)
    stem = name.split(".v")[0]
    version = int(name.rsplit(".v", 1)[1]) if ".v" in name else 1
    base = make_record()
    record = base.model_copy(
        update={
            "run": ManifestRun(
                sim_id=sid,
                name=name,
                name_stem=stem,
                version=version,
                status="completed",
                project="p",
                case_id=stem,
                rel_dir=run_dir_rel(name),
                attempt=1,
                attempt_id="a" * 32,
                solver="modflow6",
                created_at=base.run.created_at,
            ),
            "site": None,
            "config": ManifestConfig(file="config.toml", hash=config_hash, source="project.toml"),
            "identity": make_identity(
                site=None,
                site_fingerprint=None,
                case_id=stem,
                sim_id=sid,
                attempt_id="a" * 32,
                config_hash=config_hash,
                mesh_hash=None,
            ),
            "geometry": base.geometry.model_copy(update={"mesh_hash": None}),
            "provenance": base.provenance.model_copy(update={"sim_id": sid}),
        }
    )
    run_dir = root / "runs" / name
    run_dir.mkdir(parents=True)
    (run_dir / "config.toml").write_text("[flow]\n", encoding="utf-8")
    record.write(run_dir)
    return sid


def _config(sy: float = 0.001, scratch: str = "/p/.hmp/scratch/demo.p111") -> dict:
    return {
        "flow": {"sy": sy},
        "simulation": {"name": "demo"},
        "workspace": {"project_root": "/p", "solver_scratch_folder": scratch},
    }


def test_identical_config_matches_and_change_discriminates(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    sid = _seal(root, _config())

    found = completed_identical_run(_stub_config(_config(), root), name="demo")
    assert found == ("demo", sid)

    # Any changed parameter flips the hash, so the run is not a duplicate.
    assert completed_identical_run(_stub_config(_config(sy=0.01), root), name="demo") is None


def test_the_scratch_folder_of_the_process_does_not_count(tmp_path: Path) -> None:
    """Two processes name two scratch folders; the run is the same run."""
    root = tmp_path / "ws"
    sid = _seal(root, _config(scratch="/p/.hmp/scratch/demo.p111"))

    other_process = _config(scratch="/p/.hmp/scratch")
    found = completed_identical_run(_stub_config(other_process, root), name="demo")
    assert found is not None
    assert found[1] == sid


def test_a_version_of_the_name_answers_too(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    _seal(root, _config(sy=0.5), name="demo")
    sid = _seal(root, _config(), name="demo.v2")

    assert completed_identical_run(_stub_config(_config(), root), name="demo") == ("demo.v2", sid)


def test_another_name_is_another_run(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    _seal(root, _config())
    assert completed_identical_run(_stub_config(_config(), root), name="other") is None


def test_an_unsealed_directory_never_matches(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    write_attempt(root, "runs/demo", status="failed")
    write_attempt(root, "runs/demo.v2", status="running")
    assert completed_identical_run(_stub_config(_config(), root), name="demo") is None


def test_an_unreadable_manifest_never_matches_and_never_blocks(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    broken = root / "runs" / "demo"
    broken.mkdir(parents=True)
    (broken / "manifest.json").write_text("{not json", encoding="utf-8")
    assert completed_identical_run(_stub_config(_config(), root), name="demo") is None


def test_the_newest_version_answers_first(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    _seal(root, _config(), name="demo")
    sid = _seal(root, _config(), name="demo.v3")
    _seal(root, _config(sy=0.5), name="demo.v2")

    assert completed_identical_run(_stub_config(_config(), root), name="demo") == ("demo.v3", sid)


def test_a_project_without_runs_matches_nothing(tmp_path: Path) -> None:
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


def _seal_as_a_run(config: _ForcedConfig, *, name: str = "demo") -> str:
    """Seal ``config`` with the hash the pipeline records, inputs included."""
    root = Path(config.workspace.project_root)
    dump = config.model_dump(mode="json")
    sid = _seal(root, dump, name=name)
    # The seal hashes the input files too: rewrite the hash the way the run does.
    from hydromodpy.results.record import RunRecord

    record = RunRecord.read(root / "runs" / name)
    config_hash = run_identity_hash(dump, inputs=input_file_digests(config))
    record = record.model_copy(
        update={
            "config": record.config.model_copy(update={"hash": config_hash}),
            "identity": record.identity.model_copy(update={"config_hash": config_hash}),
        }
    )
    record.write(root / "runs" / name)
    return sid


def test_an_edited_forcing_file_is_another_run(tmp_path: Path) -> None:
    config = _forced_project(tmp_path)
    sid = _seal_as_a_run(config)
    assert completed_identical_run(config, name="demo") == ("demo", sid)

    forcing = Path(config.workspace.project_root) / "data" / "recharge.csv"
    forcing.write_text("date,value\n2020-01-01,2.0\n")
    assert completed_identical_run(config, name="demo") is None


def test_a_renamed_run_no_longer_answers_to_its_old_name(tmp_path: Path) -> None:
    config = _forced_project(tmp_path)
    sid = _seal_as_a_run(config, name="baseline")
    assert completed_identical_run(config, name="baseline") == ("baseline", sid)

    root = Path(config.workspace.project_root)
    (root / "runs" / "baseline").rename(root / "runs" / "renamed")
    assert completed_identical_run(config, name="baseline") is None
    assert completed_identical_run(config, name="renamed") == ("renamed", sid)


class _Workflow(BaseModel):
    mode: str = "simulation"


class _FolderConfig(BaseModel):
    """A configuration that names a folder of station files, as ``[data.recharge]`` does."""

    workspace: _Workspace
    workflow: _Workflow = _Workflow()
    simulation: dict
    recharge: Annotated[Path | None, InputFile(role="recharge", category="data")] = None


def test_two_identical_hmp_run_calls_give_the_same_run(monkeypatch, tmp_path: Path) -> None:
    """The first run writes the sidecar of a station file it read: the second still matches."""
    import hydromodpy as hmp
    from tests._helpers.api_doubles import make_capturing_project

    root = tmp_path / "ws"
    station = root / "data" / "recharge" / "recharge_custom_NANCON_20000101_20021231_M.csv"
    station.parent.mkdir(parents=True)
    station.write_text("datetime,value\n2000-01-31,1.0\n", encoding="utf-8")
    config = _FolderConfig(
        workspace=_Workspace(project_root=str(root)),
        simulation={"name": "demo"},
        recharge=Path("data/recharge"),
    )
    sid = _seal_as_a_run(config)  # hashed before the run, as the run does
    station.with_name(station.name + ".json").write_text('{"source": "custom"}', encoding="utf-8")

    captured: dict = {}
    monkeypatch.setattr(
        "hydromodpy.project.Project",
        make_capturing_project(
            captured, result=SimpleNamespace(name="demo.v2", sim_id="new"), verb="simulate"
        ),
    )
    monkeypatch.setattr(
        "hydromodpy._api._open_run", lambda root, run_dir: ("opened", Path(run_dir).name)
    )

    assert hmp.run(config, name="demo") == ("opened", "demo")
    assert hmp.run(config, name="demo") == ("opened", "demo")
    assert "verb_kwargs" not in captured
    assert completed_identical_run(config, name="demo") == ("demo", sid)
