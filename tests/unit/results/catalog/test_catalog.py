"""The Catalog reader opens a project index, looks runs up and refuses to write.

A catalog is opened on a project root or on the workspace a config names. It reaches the
index through the DuckDB backend port, and its public surface stays bounded.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigError, ReadOnlyError
from hydromodpy.results.catalog.discovery import SimulationNotFoundError
from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.run.view import Run
from tests._helpers.run_builders import runs
from tests._helpers.sealed_runs import make_project, seal_run

__all__ = ["runs"]

# Ceiling, not an exact count: the surface may shrink but must not grow back into a god-object.
MAX_PUBLIC_FUNCTIONS = 50
# Verbs a reader cannot have: the run writes its store, the verbs move directories.
WRITER_VERBS = ("register_simulation", "finalize", "trash", "restore", "delete", "add_tag")

CONFIG_TOML = """\
[workflow]
mode = "simulation"

[workspace]
root = "{root}"

[geographic]
source_mode = "synthetic"
"""


class Validated(BaseModel):
    marker: str = "sealed"


def alpha_project(tmp_path: Path) -> tuple[Path, str]:
    root = make_project(tmp_path / "demo")
    sim_id = seal_run(root, "alpha", site=None)
    rebuild_index(root)
    return root, sim_id


def public_functions() -> list[str]:
    members = inspect.getmembers(Catalog, predicate=inspect.isfunction)
    return [name for name, _ in members if not name.startswith("_")]


def test_open_on_the_workspace_of_a_config(tmp_path):
    root, sim_id = alpha_project(tmp_path)
    (root / "config.toml").write_text(CONFIG_TOML.format(root=root.as_posix()), encoding="utf-8")
    config = HydroModPyConfig.from_toml(root / "config.toml")

    with Catalog.from_workspace(config.workspace) as catalog:
        assert catalog.workspace_path == root.resolve()
        assert catalog.resolve("alpha") == sim_id


def test_run_view_keeps_its_index_reads(tmp_path):
    root, sim_id = alpha_project(tmp_path)
    workspace = SimpleNamespace(project_root=root)

    with Catalog.from_workspace(workspace) as catalog:
        run = Run(sim_id, catalog)
        assert run.name == "alpha"
        assert run.status == "completed"


def test_run_reads_the_config_function_of_its_catalog(tmp_path):
    root, sim_id = alpha_project(tmp_path)
    seen: list[Any] = []

    def read_config(snapshot: Any) -> BaseModel:
        seen.append(snapshot)
        return Validated()

    with Catalog(root, read_config=read_config) as catalog:
        run = Run(sim_id, catalog)
        assert run.hydromodpy_config == Validated()
        assert seen, "the sealed snapshot was not read"
        assert run.config_snapshot is not None


def test_catalog_without_read_config_refuses(tmp_path):
    root, sim_id = alpha_project(tmp_path)

    with Catalog(root) as catalog:
        run = Run(sim_id, catalog)
        with pytest.raises(ConfigError, match="hmp.open"):
            _ = run.hydromodpy_config
        assert run.config_snapshot is not None


def test_backend_of_a_reader_refuses_writes(tmp_path):
    root, _ = alpha_project(tmp_path)

    with Catalog(root) as catalog, pytest.raises(ReadOnlyError):
        catalog.backend.execute("DELETE FROM simulations")


def test_public_surface_is_bounded():
    assert len(public_functions()) <= MAX_PUBLIC_FUNCTIONS


def test_reader_has_no_writer_verb():
    names = set(public_functions())
    assert not set(WRITER_VERBS) & names
    assert not any(name.startswith("write_") for name in names)


def test_simulations_property(runs):
    runs.open(project="a")
    runs.open(project="b")
    assert len(runs.catalog().simulations) == 2


def test_find_by_tags(runs):
    runs.open(tags=["transient", "test"])
    runs.open(tags=["steady"])
    assert runs.catalog().find(tags="transient").count == 1


def test_latest(runs):
    runs.open(project="p1")
    runs.catalog()
    second = runs.open(project="p1").sim_id
    assert runs.catalog().latest("p1").sim_id == second


LOOKUP_REFUSALS = [
    pytest.param(
        "__getitem__", ("nonexistent",), {}, SimulationNotFoundError, None, id="unknown name"
    ),
    pytest.param(
        "find", (), {"nonexistent_field": "x"}, ValueError, "Unknown filter", id="unknown filter"
    ),
    pytest.param("latest", ("nonexistent",), {}, KeyError, None, id="latest of an unknown project"),
    pytest.param(
        "best", ("nonexistent",), {"metric": "nse"}, KeyError, None, id="best of an unknown project"
    ),
]


@pytest.mark.parametrize(("method", "args", "kwargs", "error", "message"), LOOKUP_REFUSALS)
def test_refusals(runs, method, args, kwargs, error, message):
    runs.open(project="p1")
    lookup = getattr(runs.catalog(), method)
    with pytest.raises(error, match=message):
        lookup(*args, **kwargs)
