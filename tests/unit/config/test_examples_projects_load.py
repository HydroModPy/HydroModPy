"""Validate bundled example projects against the root config schema."""

import tomllib
from pathlib import Path

from hydromodpy.config import HydroModPyConfig
from hydromodpy.config.config_migration import migrate_config_doc


def test_examples_projects_load() -> None:
    project_files = sorted(Path("examples/projects").glob("*/project.toml"))
    assert project_files
    supported_workflows = {
        "simulation",
        "calibration",
        "batch",
        "overview",
        "mesh",
        "comparison",
        "testbed",
    }
    validated_files: list[Path] = []

    for project_file in project_files:
        with project_file.open("rb") as stream:
            payload = tomllib.load(stream)
        workflow = payload.get("workflow")
        if not isinstance(workflow, dict) or workflow.get("mode") not in supported_workflows:
            continue
        # Mirror on-disk loading: migrate legacy [simulation] keys before validating.
        migrate_config_doc(payload)
        HydroModPyConfig.model_validate(payload, context={"validation_context": "api"})
        validated_files.append(project_file)

    assert validated_files
