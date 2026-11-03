"""What a replay reads of the run it repeats: its digests and its solver binary.

The directories are written here, so each case is the record it names. The real
replay, with a solver and a moved default, is in
``tests/integration/workflow/test_a_sealed_run_is_replayed.py``.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.exceptions import FrozenDataError
from hydromodpy.project import replay_checks
from hydromodpy.results.manifest import InputEntry, TrackedInput
from hydromodpy.results.record import RunProvenance
from tests.unit.results._run_record_factory import make_record


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _workspace(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Return ``(project, run, input file)`` of a workspace holding one sealed run."""
    workspace = tmp_path / "workspace"
    (workspace / "workspace.toml").parent.mkdir(parents=True)
    (workspace / "workspace.toml").write_text("", encoding="utf-8")
    project = workspace / "projects" / "demo"
    run_dir = project / "runs" / "probe"
    run_dir.mkdir(parents=True)
    (project / "project.toml").write_text("", encoding="utf-8")
    forcing = workspace / "data" / "recharge" / "rate.csv"
    forcing.parent.mkdir(parents=True)
    forcing.write_bytes(b"date,value\n")
    (run_dir / "config.toml").write_text("", encoding="utf-8")
    _write_record(run_dir, forcing.read_bytes())
    return project, run_dir, forcing


def _write_record(run_dir: Path, data: bytes, *, declared: tuple[TrackedInput, ...] = ()) -> None:
    make_record(
        inputs=[
            InputEntry(
                variable="recharge:rate",
                provider="custom",
                path="data/recharge/rate.csv",
                sha256=_sha(data),
                bytes=len(data),
            )
        ],
        tracked_inputs=list(declared),
    ).write(run_dir)


@pytest.mark.parametrize(
    ("name", "found"),
    [
        ("config.toml", True),
        ("run_demo.toml", False),
    ],
)
def test_a_frozen_file_is_a_run_when_its_record_sits_beside_it(
    tmp_path: Path, name: str, found: bool
) -> None:
    _project, run_dir, _forcing = _workspace(tmp_path)
    assert (replay_checks.sealed_run_of(run_dir / name) == run_dir) is found


def test_a_config_toml_without_a_record_is_no_run(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text("", encoding="utf-8")
    assert replay_checks.sealed_run_of(tmp_path / "config.toml") is None


def test_unchanged_inputs_pass(tmp_path: Path) -> None:
    project, run_dir, _forcing = _workspace(tmp_path)
    replay_checks.refuse_changed_inputs(run_dir, project)


def test_a_changed_input_is_refused_naming_the_file_and_both_digests(tmp_path: Path) -> None:
    project, run_dir, forcing = _workspace(tmp_path)
    sealed = _sha(forcing.read_bytes())
    forcing.write_bytes(b"date,value\n2020-01-01,1\n")

    with pytest.raises(FrozenDataError) as refusal:
        replay_checks.refuse_changed_inputs(run_dir, project)

    text = str(refusal.value)
    assert "recharge:rate (data/recharge/rate.csv)" in text
    assert sealed in text
    assert _sha(forcing.read_bytes()) in text


def test_a_missing_input_is_refused_naming_where_it_was_looked_for(tmp_path: Path) -> None:
    project, run_dir, forcing = _workspace(tmp_path)
    forcing.unlink()

    with pytest.raises(FrozenDataError, match=r"missing from .*rate\.csv"):
        replay_checks.refuse_changed_inputs(run_dir, project)


def test_a_file_added_beside_an_input_is_no_other_input_and_a_gone_folder_is_refused(
    tmp_path: Path,
) -> None:
    from hydromodpy.results.storage.digests import sha256_directory

    project, run_dir, forcing = _workspace(tmp_path)
    folder = forcing.parent
    _write_record(
        run_dir,
        forcing.read_bytes(),
        declared=(
            TrackedInput(
                role="recharge",
                category="data",
                path="data/recharge",
                declared_path="recharge",
                sha256=sha256_directory(folder),
                portable=True,
            ),
        ),
    )
    (folder / "another_station.csv").write_text("a\n", encoding="utf-8")
    replay_checks.refuse_changed_inputs(run_dir, project)

    forcing.write_bytes(b"other bytes")
    with pytest.raises(FrozenDataError, match=r"recharge:rate"):
        replay_checks.refuse_changed_inputs(run_dir, project)

    shutil.rmtree(folder)
    with pytest.raises(FrozenDataError, match=r"recharge \(data/recharge\)"):
        replay_checks.refuse_changed_inputs(run_dir, project)


def test_a_file_read_by_the_replay_alone_is_named_and_a_same_digest_elsewhere_is_not(
    tmp_path: Path,
) -> None:
    _project, run_dir, forcing = _workspace(tmp_path)
    same = tmp_path / "replay_same"
    same.mkdir()
    _write_record(same, forcing.read_bytes())
    assert replay_checks.replay_differences(run_dir, same) == []

    other = tmp_path / "replay_other"
    other.mkdir()
    _write_record(other, b"other")
    lines = replay_checks.replay_differences(run_dir, other)
    assert lines == [
        f"recharge:rate (data/recharge/rate.csv): read here with sha256 {_sha(b'other')}, "
        "the source run did not"
    ]


def _provenance(run_dir: Path, sha256: str | None, version: str = "mf6: 6.6.3") -> None:
    (run_dir / "provenance.json").write_text(
        RunProvenance(
            sim_id="s",
            solver={
                "name": "modflow6",
                "execution_mode": "subprocess",
                "version": version,
                "binary_sha256": sha256,
            },
        ).model_dump_json(),
        encoding="utf-8",
    )


@pytest.fixture
def local_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A solver binary on this machine: sha256 ``here``, version ``mf6: 6.7.0``."""
    monkeypatch.setattr(
        "hydromodpy.solver.modflow_common.binaries.resolve_solver_engine",
        lambda solver, execution_mode="subprocess": SimpleNamespace(
            path=tmp_path / "mf6", version="mf6: 6.7.0"
        ),
    )
    monkeypatch.setattr(
        "hydromodpy.results.run.environment.solver_binary_identity",
        lambda path: ("here", "mf6: 6.7.0"),
    )


def test_another_solver_binary_is_named_with_both_versions(
    tmp_path: Path, local_binary: None
) -> None:
    _provenance(tmp_path, "sealed")
    warning = replay_checks.solver_binary_warning(tmp_path)
    assert warning is not None
    assert "mf6: 6.6.3" in warning and "mf6: 6.7.0" in warning
    assert "sealed" in warning and "here" in warning


@pytest.mark.parametrize("sha256", ["here", None])
def test_the_same_binary_or_no_record_says_nothing(
    tmp_path: Path, local_binary: None, sha256: str | None
) -> None:
    _provenance(tmp_path, sha256)
    assert replay_checks.solver_binary_warning(tmp_path) is None
