from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.cli.commands.run import _infer_workflow_from_sections
from hydromodpy.project.dispatch import workflow as project_workflow
from hydromodpy.workflow.dispatch import KNOWN_WORKFLOWS, resolve_workflow


@pytest.mark.fast
def test_site_selection_is_registered_workflow(tmp_path: Path):
    config_path = tmp_path / "selection.toml"
    config_path.write_text(
        "\n".join(
            [
                "[workflow]",
                'mode = "site_selection"',
                "",
                "[site_selection]",
                'selection_id = "demo"',
                'output_root = "out"',
            ]
        ),
        encoding="utf-8",
    )

    assert "site_selection" in KNOWN_WORKFLOWS
    assert "site_selection" in project_workflow.DISPATCH
    assert resolve_workflow(config_path, cli_workflow=None, require_toml_field=True) == (
        "site_selection"
    )


@pytest.mark.fast
def test_site_selection_dry_run_inference():
    assert _infer_workflow_from_sections({"site_selection": {}}) == "site_selection"


@pytest.mark.fast
def test_workflow_resolution_accepts_utf8_bom(tmp_path: Path):
    config_path = tmp_path / "selection_bom.toml"
    config_path.write_text(
        '[workflow]\nmode = "site_selection"\n',
        encoding="utf-8-sig",
    )

    assert resolve_workflow(config_path, cli_workflow=None, require_toml_field=True) == (
        "site_selection"
    )
