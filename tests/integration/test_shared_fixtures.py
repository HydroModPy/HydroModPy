"""The two shared fixtures documented for the integration tier still work.

``tests/README.md`` and ``docs/source/architecture/how-to/add-a-test.rst``
point new integration tests at ``tmp_workspace`` and ``minimal_config``. Both
promise a specific downstream capability, so this file asserts the promise
rather than the fixture body: a workspace that ``hmp.open`` accepts, and a
config that survives a full TOML round-trip. Without that, a required field
added to any sub-config would rot the fixture silently and only surface in the
next test someone tried to write with it.
"""

from __future__ import annotations

from pathlib import Path

import hydromodpy as hmp
from hydromodpy.config import HydroModPyConfig


def test_tmp_workspace_is_openable_as_a_catalog(tmp_workspace: Path) -> None:
    assert (tmp_workspace / "data").is_dir()
    assert (tmp_workspace / "projects").is_dir()

    with hmp.open(tmp_workspace, create=True) as catalog:
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
    assert reloaded.workspace.project_root == minimal_config.workspace.project_root
    assert reloaded.workflow.mode == minimal_config.workflow.mode
