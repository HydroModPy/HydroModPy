"""Factory entry points on :class:`Catalog`.

``from_toml`` / ``from_json`` / ``from_dict`` open the index of the project a
configuration names, so one :class:`HydroModPyConfig` source spawns either a
:class:`Project` or a :class:`Catalog`. A :class:`Run` view is then created
with ``Catalog(...)`` + ``Run(sim_id, catalog)``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.results.catalog import Catalog, rebuild_index
from hydromodpy.results.run import Run
from tests._helpers.sealed_runs import make_project, seal_run

_CATALOG_TOML = """\
[workflow]
mode = "simulation"

[workspace]
root = "{root}"

[geographic]
source_mode = "synthetic"
"""


@pytest.fixture
def project(tmp_path: Path) -> tuple[Path, str]:
    root = make_project(tmp_path / "demo")
    sid = seal_run(root, "alpha", site=None)
    rebuild_index(root)
    return root, sid


def _write_minimal_toml(root: Path) -> Path:
    path = root / "config.toml"
    path.write_text(_CATALOG_TOML.format(root=root.as_posix()), encoding="utf-8")
    return path


def _build_payload(root: Path) -> dict:
    return {
        "workflow": {"mode": "simulation"},
        "workspace": {"root": str(root)},
        "geographic": {"source_mode": "synthetic"},
    }


def test_catalog_from_toml_opens_the_project_index(project) -> None:
    root, sid = project
    cat = Catalog.from_toml(_write_minimal_toml(root))
    try:
        assert cat.workspace_path == root.resolve()
        assert cat.resolve("alpha") == sid
    finally:
        cat.close()


def test_catalog_from_dict_opens_the_project_index(project, monkeypatch) -> None:
    root, sid = project
    monkeypatch.chdir(root)
    cat = Catalog.from_dict(_build_payload(root))
    try:
        assert cat.resolve("alpha") == sid
    finally:
        cat.close()


def test_catalog_from_json_opens_the_project_index(project, monkeypatch) -> None:
    root, sid = project
    monkeypatch.chdir(root)
    cat = Catalog.from_json(json.dumps(_build_payload(root)))
    try:
        assert cat.resolve("alpha") == sid
    finally:
        cat.close()


def test_run_from_toml_returns_a_view(project) -> None:
    root, sid = project
    cat = Catalog.from_toml(_write_minimal_toml(root))
    try:
        run = Run(sid, cat)
        assert run.name == "alpha"
        assert run.status == "completed"
    finally:
        cat.close()
