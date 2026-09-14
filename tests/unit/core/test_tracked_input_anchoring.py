"""Where a tracked input path is looked for.

A bare filename in a configuration resolves under ``<workspace>/data/<family>/``
everywhere the pipeline reads it. The tracking walker resolved it against the
shell's working directory instead, so the same project tracked its files or lost
them depending on where the command was launched from, and reported the loss as
a warning naming a path nobody wrote.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import pytest
from pydantic import BaseModel, ConfigDict

from hydromodpy.core.tracking import collect_input_files
from hydromodpy.core.tracking.input_file import InputFile


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    geometry: Annotated[
        Path | None,
        InputFile(role="stream_enforcement_geometry", category="geometry"),
    ] = None


@pytest.fixture
def project(tmp_path: Path) -> Path:
    target = tmp_path / "data" / "hydrography" / "streams.gpkg"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"only its location matters here")
    return tmp_path


def test_a_relative_path_is_anchored_on_the_project(project: Path) -> None:
    config = _Config(geometry=Path("data/hydrography/streams.gpkg"))

    entries = collect_input_files(config, base=project)

    assert len(entries) == 1
    assert entries[0].canonical_path == (project / "data/hydrography/streams.gpkg").resolve()


def test_an_absolute_path_is_left_alone(project: Path) -> None:
    absolute = (project / "data/hydrography/streams.gpkg").resolve()
    config = _Config(geometry=absolute)

    entries = collect_input_files(config, base=Path("/elsewhere"))

    assert entries[0].canonical_path == absolute


def test_without_a_base_the_old_behaviour_stands(project: Path) -> None:
    # No anchor to use: the walker can only resolve against the process cwd,
    # which is what every caller that has no project does.
    config = _Config(geometry=Path("data/hydrography/streams.gpkg"))

    entries = collect_input_files(config)

    assert entries[0].canonical_path == Path("data/hydrography/streams.gpkg").resolve()


def test_a_path_that_the_anchor_does_not_hold_falls_back(project: Path) -> None:
    # The anchor is a hint, not a rewrite: a file that is not under the project
    # keeps resolving the way it did, so a configuration pointing outside the
    # project is not silently repointed inside it.
    config = _Config(geometry=Path("nowhere/streams.gpkg"))

    entries = collect_input_files(config, base=project)

    assert entries[0].canonical_path == Path("nowhere/streams.gpkg").resolve()


def test_an_unset_path_is_not_tracked() -> None:
    assert collect_input_files(_Config(), base=Path.cwd()) == []
