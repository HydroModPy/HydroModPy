"""A configuration a run stored with an earlier version still loads.

The fixtures under ``fixtures/stored_e611edf79`` were written by the code of
commit e611edf79, before the root ``[persistence]`` table was refused and
before ``solver.backend`` followed the flow process. The config is a minimal
MODFLOW-NWT run: its dump holds ``[persistence]`` and a ``solver.backend`` of
``modflow6``, the old default, next to a flow process that names
``modflow_nwt``. A user file holding the same keys is still refused.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.config.stored_config_migration import migrate_stored_config
from hydromodpy.core.exceptions import ConfigValidationError, ResumeError
from hydromodpy.workflow.internals.manifest import (
    SCHEMA_VERSION,
    ResolvedRunManifest,
    resolved_config_path,
)
from hydromodpy.workflow.internals.state import PipelineState

_FIXTURES = Path(__file__).parent / "fixtures" / "stored_e611edf79"
# sha256 of the resolved config the e611edf79 manifest signed.
_E611_CONFIG_SHA256 = "cb49f1c47afd4895750baa9f4fffae198b3fb3d4017abeda22063a08e8db85ff"


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _sealed_run_config(tmp_path: Path) -> Path:
    run_dir = tmp_path / "proj" / "runs" / "frozen_nwt"
    run_dir.mkdir(parents=True)
    target = run_dir / "config.toml"
    shutil.copy(_FIXTURES / "config_modflow_nwt.toml", target)
    return target


def test_the_snapshot_reloads_and_runs_the_solver_of_the_process(
    caplog: pytest.LogCaptureFixture,
) -> None:
    snapshot = _fixture("snapshot_modflow_nwt.json")
    assert "persistence" in snapshot
    assert snapshot["solver"]["backend"] == {"backend": "modflow6"}

    with caplog.at_level("INFO", logger="hydromodpy"):
        cfg = HydroModPyConfig.from_snapshot(snapshot)

    assert cfg.solver.backend_name == "modflow_nwt"
    migrated = [record.getMessage() for record in caplog.records if "migrated" in record.msg]
    assert len(migrated) == 1
    assert "persistence dropped" in migrated[0]
    assert "solver.backend 'modflow6' dropped" in migrated[0]


def test_an_override_of_the_flow_solver_applies_to_the_snapshot() -> None:
    snapshot = _fixture("snapshot_modflow_nwt.json")
    process = [{"id": "flow_main", "type": "flow", "solvers": ["boussinesq"]}]

    cfg = HydroModPyConfig.from_snapshot(snapshot, simulation={"process": process})

    assert cfg.solver.backend_name == "boussinesq"


def test_the_frozen_run_config_reloads(tmp_path: Path) -> None:
    cfg = HydroModPyConfig.from_toml(_sealed_run_config(tmp_path))

    assert cfg.solver.backend_name == "modflow_nwt"


def test_the_same_file_written_by_a_user_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "project.toml"
    shutil.copy(_FIXTURES / "config_modflow_nwt.toml", path)

    with pytest.raises(ConfigValidationError, match=r"\[persistence\] is not read"):
        HydroModPyConfig.from_toml(path)


def test_the_checkpoint_of_the_earlier_version_still_resumes(tmp_path: Path) -> None:
    workspace = tmp_path / "proj"
    cfg = HydroModPyConfig.from_toml(_sealed_run_config(tmp_path))
    checkpoint = resolved_config_path(workspace, "frozen_nwt")
    checkpoint.parent.mkdir(parents=True)
    shutil.copy(_FIXTURES / "resolved_config_modflow_nwt.json", checkpoint)
    manifest = ResolvedRunManifest(
        schema_version=SCHEMA_VERSION,
        run_id="frozen_nwt",
        config_sha256=_E611_CONFIG_SHA256,
        config_path=None,
        workspace=str(workspace),
        steps=(),
        step_index=3,
        step_name="setup",
        created_at="2026-10-05T00:00:00+00:00",
        updated_at="2026-10-05T00:00:00+00:00",
    )
    state = PipelineState(run_id="frozen_nwt", data={"cfg": cfg})

    manifest.verify_state(state, (), workspace=workspace)

    changed = cfg.model_copy(deep=True)
    changed.simulation.description = "another run"
    with pytest.raises(ResumeError, match="Resolved configuration changed"):
        manifest.verify_state(
            PipelineState(run_id="frozen_nwt", data={"cfg": changed}), (), workspace=workspace
        )


def test_the_site_selection_keys_move_where_they_were_read() -> None:
    snapshot = _fixture("snapshot_site_selection.json")
    observations = snapshot["site_selection"]["criteria"]["observations"]
    assert observations["flow_station_max_distance_km"] == 3.0

    cfg = HydroModPyConfig.from_snapshot(snapshot)

    flow_station = cfg.site_selection.criteria.observations.flow_station
    assert flow_station.max_station_to_outlet_distance_km == 3.0


def test_a_flat_flow_station_mode_fills_a_default_mode() -> None:
    stored = migrate_stored_config(
        {
            "site_selection": {
                "criteria": {
                    "observations": {
                        "flow_station_mode": "score",
                        "flow_station": {"mode": "report_only"},
                    }
                }
            }
        }
    )

    observations = stored["site_selection"]["criteria"]["observations"]
    assert observations == {"flow_station": {"mode": "score"}}


def test_the_null_cell_id_and_the_abacus_name_are_dropped() -> None:
    stored = migrate_stored_config(
        {
            "calibration": {"outputs": {"h1": {"support": "cell", "cell_id": None, "row": 1}}},
            "data": {"lake_abacus": {"id": "lake_abacus", "sources": []}},
        }
    )

    assert stored["calibration"]["outputs"]["h1"] == {"support": "cell", "row": 1}
    assert stored["data"]["lake_abacus"] == {"sources": []}


def test_a_cell_id_with_a_value_is_left_for_the_model_to_refuse() -> None:
    stored = migrate_stored_config(
        {"calibration": {"outputs": {"h1": {"support": "cell", "cell_id": 4}}}}
    )

    assert stored["calibration"]["outputs"]["h1"]["cell_id"] == 4
