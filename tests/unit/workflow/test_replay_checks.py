"""What a replay reads of the run it repeats: its inputs, its drift, its producer.

The directories are written here, so each case is the record it names. The real
replay, with a solver and a moved default, is in
``tests/integration/workflow/test_a_sealed_run_is_replayed.py``.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import FrozenDataError
from hydromodpy.results.record.manifest import InputEntry, TrackedInput
from hydromodpy.results.record.record import RunProvenance
from hydromodpy.results.storage.contract import PUBLICATION_FILENAME
from hydromodpy.schema.lineage import ProducerSide
from hydromodpy.workflow import replay_checks
from tests._helpers.run_records import make_record


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _workspace(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Return ``(project, run, input file)`` of a workspace holding one sealed run."""
    workspace = tmp_path / "workspace"
    (workspace / "workspace.toml").parent.mkdir(parents=True, exist_ok=True)
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
    replay_checks.check_replay_inputs(run_dir, project_root=project)


def _with_sealed_mesh(run_dir: Path) -> None:
    """Add the ``mesh`` row a seal writes for the mesh it copied under ``mesh/``."""
    import json

    path = run_dir / "inputs.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["inputs"].append(
        {
            "variable": "mesh",
            "provider": "store",
            "product": "mesh",
            "path": "mesh",
            "sha256": "f" * 64,
        }
    )
    path.write_text(json.dumps(document), encoding="utf-8")


def test_a_run_with_a_sealed_mesh_still_has_its_api_inputs_intact(tmp_path: Path) -> None:
    project, run_dir, _forcing = _workspace(tmp_path)
    _with_sealed_mesh(run_dir)

    assert replay_checks.api_inputs_intact(run_dir, project)
    replay_checks.check_replay_inputs(run_dir, project_root=project)


def test_a_changed_input_is_refused_naming_the_file_and_both_digests(tmp_path: Path) -> None:
    project, run_dir, forcing = _workspace(tmp_path)
    sealed = _sha(forcing.read_bytes())
    forcing.write_bytes(b"date,value\n2020-01-01,1\n")

    with pytest.raises(FrozenDataError) as refusal:
        replay_checks.check_replay_inputs(run_dir, project_root=project)

    text = str(refusal.value)
    assert "recharge:rate (data/recharge/rate.csv)" in text
    assert sealed in text
    assert _sha(forcing.read_bytes()) in text


def test_a_missing_input_is_refused_naming_where_it_was_looked_for(tmp_path: Path) -> None:
    project, run_dir, forcing = _workspace(tmp_path)
    forcing.unlink()

    with pytest.raises(FrozenDataError, match=r"missing from .*rate\.csv"):
        replay_checks.check_replay_inputs(run_dir, project_root=project)


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
    replay_checks.check_replay_inputs(run_dir, project_root=project)

    forcing.write_bytes(b"other bytes")
    with pytest.raises(FrozenDataError, match=r"recharge:rate"):
        replay_checks.check_replay_inputs(run_dir, project_root=project)

    shutil.rmtree(folder)
    with pytest.raises(FrozenDataError, match=r"recharge \(data/recharge\)"):
        replay_checks.check_replay_inputs(run_dir, project_root=project)


def _locked(tmp_path: Path, input_entry: InputEntry) -> tuple[Path, object]:
    """Write a run whose record holds *input_entry*, and read its pins."""
    project, run_dir, _forcing = _workspace(tmp_path)
    make_record(inputs=[input_entry]).write(run_dir)
    pins = replay_checks.locked_inputs_of(
        run_dir, project_root=project, data_dir=project.parent.parent / "data"
    )
    return run_dir, pins


def test_a_user_file_is_pinned_at_its_path_under_the_project(tmp_path: Path) -> None:
    _project, run_dir, forcing = _workspace(tmp_path)
    pins = replay_checks.locked_inputs_of(
        run_dir, project_root=run_dir.parent.parent, data_dir=run_dir.parent.parent.parent / "data"
    )
    assert pins is not None
    assert [pin.source for pin in pins.inputs] == ["file"]
    assert pins.inputs[0].variable == "recharge"
    assert pins.inputs[0].sha256 == _sha(forcing.read_bytes())


def test_a_cache_row_is_pinned_by_its_path_under_the_data_folder(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    row = workspace / "data" / "hydro" / "J1.parquet"
    row.parent.mkdir(parents=True)
    row.write_bytes(b"q")
    run_dir, pins = _locked(
        tmp_path,
        InputEntry(
            variable="discharge:q",
            provider="hubeau",
            product="hydrometrie",
            request={"station": "J1"},
            path="data/hydro/J1.parquet",
            sha256=_sha(b"q"),
            bytes=1,
        ),
    )
    assert pins is not None
    assert [(pin.source, pin.path, pin.station_id) for pin in pins.inputs] == [
        ("hubeau", "hydro/J1.parquet", "J1")
    ]
    assert pins.path == run_dir / "inputs.json"


def test_a_published_copy_pins_nothing_and_an_unreadable_record_pins_nothing(
    tmp_path: Path,
) -> None:
    _project, run_dir, _forcing = _workspace(tmp_path)
    project, data = run_dir.parent.parent, run_dir.parent.parent.parent / "data"
    (run_dir / PUBLICATION_FILENAME).write_text("{}", encoding="utf-8")
    assert replay_checks.locked_inputs_of(run_dir, project_root=project, data_dir=data) is None

    (run_dir / PUBLICATION_FILENAME).unlink()
    (run_dir / "inputs.json").write_text("{not json", encoding="utf-8")
    assert replay_checks.locked_inputs_of(run_dir, project_root=project, data_dir=data) is None


def test_no_source_run_records_no_drift() -> None:
    assert replay_checks.warn_config_drift(None, None) == {}


def _provenance(
    run_dir: Path,
    *,
    tool: str = "2.0.0a5",
    solver: str = "mf6: 6.6.3",
    sha256: str = "sealed",
    packages: dict[str, str] | None = None,
) -> RunProvenance:
    provenance = RunProvenance(
        sim_id="s",
        tool={"name": "hydromodpy", "version": tool},
        solver={
            "name": "modflow6",
            "execution_mode": "subprocess",
            "version": solver,
            "binary_sha256": sha256,
        },
        packages={} if packages is None else packages,
    )
    (run_dir / "provenance.json").write_text(provenance.model_dump_json(), encoding="utf-8")
    return provenance


def test_the_same_producer_says_nothing(tmp_path: Path) -> None:
    sealed = _provenance(tmp_path)
    assert replay_checks.producer_differences(tmp_path, sealed) == {}


def test_another_solver_binary_is_named_with_both_versions(tmp_path: Path) -> None:
    _provenance(tmp_path)
    found = RunProvenance(
        sim_id="r",
        tool={"version": "2.0.0a5"},
        solver={"version": "mf6: 6.7.0", "binary_sha256": "here"},
    )
    differences = replay_checks.producer_differences(tmp_path, found)
    assert set(differences) == {"solver.version", "solver.binary_sha256"}
    assert differences["solver.version"] == ProducerSide(sealed="mf6: 6.6.3", found="mf6: 6.7.0")
    assert differences["solver.binary_sha256"] == ProducerSide(sealed="sealed", found="here")


def test_a_package_or_the_tool_at_another_version_is_named_by_its_dotted_path(
    tmp_path: Path,
) -> None:
    _provenance(tmp_path, packages={"numpy": "2.1.0"})
    found = RunProvenance(
        sim_id="r",
        tool={"version": "2.1.0"},
        solver={"version": "mf6: 6.6.3", "binary_sha256": "sealed"},
        packages={"numpy": "2.2.0"},
    )
    differences = replay_checks.producer_differences(tmp_path, found)
    assert set(differences) == {"tool.version", "packages.numpy"}


def test_the_warning_names_the_keys_and_says_the_numbers_can_differ(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    differences = {
        "solver.version": ProducerSide(sealed="mf6: 6.6.3", found="mf6: 6.7.0"),
    }
    with caplog.at_level(logging.WARNING):
        replay_checks.warn_producer_differences(tmp_path / "probe", differences)
    text = caplog.text
    assert "solver.version" in text
    assert "The numbers can differ." in text


def test_an_identical_producer_warns_about_nothing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        replay_checks.warn_producer_differences(tmp_path / "probe", {})
    assert caplog.text == ""
