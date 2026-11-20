"""The two shared fixtures documented for the integration tier still work.

``tests/README.md`` and ``docs/source/contribute/architecture/how-to/add-a-test.rst``
point new integration tests at ``tmp_workspace`` and ``minimal_config``. Both
promise a specific downstream capability, so this file asserts the promise
rather than the fixture body: a workspace whose projects ``hmp.open`` reads
once indexed, and a config that survives a full TOML round-trip. Without that, a required field
added to any sub-config would rot the fixture silently and only surface in the
next test someone tried to write with it.
"""

from __future__ import annotations

from pathlib import Path

import hydromodpy as hmp
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.results.catalog.indexer import rebuild_index
from tests._helpers.sealed_runs import make_project


def test_tmp_workspace_is_openable_as_a_catalog(tmp_workspace: Path) -> None:
    assert (tmp_workspace / "data").is_dir()
    assert (tmp_workspace / "projects").is_dir()

    project = make_project(tmp_workspace / "projects" / "demo")
    rebuild_index(project)
    with hmp.open(project).store as catalog:
        simulations = catalog.list_simulations()

    assert simulations.empty
    assert "sim_id" in simulations.columns


def test_minimal_config_survives_a_toml_round_trip(
    minimal_config: HydroModPyConfig, tmp_path: Path
) -> None:
    destination = tmp_path / "minimal.toml"
    minimal_config.to_toml(destination)

    reloaded = HydroModPyConfig.from_toml(destination)

    assert reloaded.geographic.source_mode == minimal_config.geographic.source_mode
    # The project root is where the file is read, never a key of the file.
    assert Path(reloaded.workspace.project_root) == destination.parent.resolve()
    assert reloaded.workflow.mode == minimal_config.workflow.mode
