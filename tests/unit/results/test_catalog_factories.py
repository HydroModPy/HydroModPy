"""A catalog is opened on a project root, or on the workspace a config names.

``from_workspace`` opens the index of the project a ``[workspace]`` section
names, so a loaded :class:`HydroModPyConfig` still reaches either a
:class:`Project` or a :class:`Catalog`. The ``read_config`` function a catalog
carries is handed to its runs and validates a sealed snapshot.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.run.view import Run
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


class _Validated(BaseModel):
    marker: str = "sealed"


def test_catalog_from_workspace_opens_the_project_index_of_a_loaded_config(project) -> None:
    root, sid = project
    cfg = HydroModPyConfig.from_toml(_write_minimal_toml(root))
    cat = Catalog.from_workspace(cfg.workspace)
    try:
        assert cat.workspace_path == root.resolve()
        assert cat.resolve("alpha") == sid
    finally:
        cat.close()


def test_a_run_made_by_a_catalog_reads_the_config_function_of_its_catalog(project) -> None:
    root, sid = project
    seen: list[Any] = []

    def read_config(snapshot: Any) -> BaseModel:
        seen.append(snapshot)
        return _Validated()

    cat = Catalog(root, read_config=read_config)
    try:
        run = Run(sid, cat)
        assert run.hydromodpy_config == _Validated()
        assert seen, "the sealed snapshot was not read"
        assert run.config_snapshot is not None
    finally:
        cat.close()


def test_a_catalog_without_read_config_refuses_hydromodpy_config(project) -> None:
    root, sid = project
    cat = Catalog(root)
    try:
        run = Run(sid, cat)
        with pytest.raises(ConfigError, match="hmp.open"):
            _ = run.hydromodpy_config
        assert run.config_snapshot is not None
    finally:
        cat.close()


def test_a_run_view_on_a_catalog_keeps_its_index_reads(project) -> None:
    root, sid = project
    cat = Catalog.from_workspace(_workspace_of(root))
    try:
        run = Run(sid, cat)
        assert run.name == "alpha"
        assert run.status == "completed"
    finally:
        cat.close()


def _workspace_of(root: Path) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(project_root=root)
