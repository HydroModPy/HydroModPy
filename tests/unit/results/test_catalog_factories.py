"""Factory entry points on :class:`SimulationCatalog` and :class:`Run`.

S05-10 introduces ``from_toml`` / ``from_json`` / ``from_dict`` so a single
:class:`HydroModPyConfig` source spawns either a :class:`Project`, a
:class:`SimulationCatalog`, or a :class:`Run` view.
"""

from __future__ import annotations

import json
from pathlib import Path

from hydromodpy.results.catalog import SimulationCatalog
from hydromodpy.results.run import Run

_CATALOG_TOML = """\
workflow = "simulation"

[workspace]
root = "{root}"
project_root = "{root}"

[geographic]
source_mode = "synthetic"
"""


def _write_minimal_toml(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(_CATALOG_TOML.format(root=tmp_path.as_posix()), encoding="utf-8")
    return path


def _build_payload(tmp_path: Path) -> dict:
    return {
        "workflow": "simulation",
        "workspace": {
            "project_root": str(tmp_path),
            "root": str(tmp_path),
        },
        "geographic": {"source_mode": "synthetic"},
    }


def test_simulation_catalog_from_toml_opens_workspace(tmp_path: Path) -> None:
    config_path = _write_minimal_toml(tmp_path)
    cat = SimulationCatalog.from_toml(config_path)
    try:
        assert cat.workspace_path == tmp_path.resolve()
    finally:
        cat.close()


def test_simulation_catalog_from_dict_opens_workspace(tmp_path: Path) -> None:
    payload = _build_payload(tmp_path)
    cat = SimulationCatalog.from_dict(payload)
    try:
        assert cat.workspace_path == tmp_path.resolve()
    finally:
        cat.close()


def test_simulation_catalog_from_json_opens_workspace(tmp_path: Path) -> None:
    payload = json.dumps(_build_payload(tmp_path))
    cat = SimulationCatalog.from_json(payload)
    try:
        assert cat.workspace_path == tmp_path.resolve()
    finally:
        cat.close()


def test_run_from_toml_returns_view(tmp_path: Path) -> None:
    config_path = _write_minimal_toml(tmp_path)
    run = Run.from_toml(config_path, sim_id="missing-sim")
    try:
        assert run.sim_id == "missing-sim"
        assert run._catalog.workspace_path == tmp_path.resolve()
    finally:
        run._catalog.close()


def test_run_from_dict_returns_view(tmp_path: Path) -> None:
    payload = _build_payload(tmp_path)
    run = Run.from_dict(payload, sim_id="missing-sim")
    try:
        assert run.sim_id == "missing-sim"
        assert run._catalog.workspace_path == tmp_path.resolve()
    finally:
        run._catalog.close()


def test_run_from_json_returns_view(tmp_path: Path) -> None:
    payload = json.dumps(_build_payload(tmp_path))
    run = Run.from_json(payload, sim_id="missing-sim")
    try:
        assert run.sim_id == "missing-sim"
        assert run._catalog.workspace_path == tmp_path.resolve()
    finally:
        run._catalog.close()
