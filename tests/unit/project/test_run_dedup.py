"""A plain ``hmp run`` skips a re-run whose resolved config already completed.

Covers :func:`hydromodpy.project.dispatch.workflow._completed_run_with_same_config`,
which mirrors the ``config_hash`` the catalog records at registration.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

from hydromodpy.project.dispatch.workflow import _completed_run_with_same_config
from tests._helpers.fixtures_catalog import simulation_catalog


def _stub_project(config: dict, root: Path) -> SimpleNamespace:
    cfg = SimpleNamespace(
        model_dump=lambda *, mode="json": config,
        workspace=SimpleNamespace(project_root=str(root)),
    )
    return SimpleNamespace(config=cfg)


def _register_completed(root: Path, config: dict) -> str:
    sid = str(uuid.uuid4())
    with simulation_catalog(root) as cat:
        cat.register_simulation(sid, project="p", solver="modflow6", name="demo", config=config)
        cat._backend.execute(
            "UPDATE simulations SET status_id = "
            "(SELECT id FROM statuses WHERE code = 'completed'), "
            "ended_at = current_timestamp WHERE sim_id = ?",
            [sid],
        )
    return sid


def test_identical_config_matches_and_change_discriminates(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    config = {"flow": {"sy": 0.001}, "simulation": {"name": "demo"}}
    sid = _register_completed(root, config)

    found = _completed_run_with_same_config(_stub_project(config, root))
    assert found is not None
    assert found[1] == sid

    # Any changed parameter flips the hash, so the run is not a duplicate.
    changed = {"flow": {"sy": 0.01}, "simulation": {"name": "demo"}}
    assert _completed_run_with_same_config(_stub_project(changed, root)) is None


def test_non_completed_run_does_not_trigger_skip(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    config = {"flow": {"sy": 0.001}}
    sid = str(uuid.uuid4())
    with simulation_catalog(root) as cat:
        # Registered but left non-completed (default status).
        cat.register_simulation(sid, project="p", solver="modflow6", name="demo", config=config)

    assert _completed_run_with_same_config(_stub_project(config, root)) is None


def test_missing_catalog_is_fail_open(tmp_path: Path) -> None:
    config = {"flow": {"sy": 0.001}}
    assert _completed_run_with_same_config(_stub_project(config, tmp_path / "absent")) is None
