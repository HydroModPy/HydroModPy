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

from hydromodpy.core.tracking.input_file import InputFile
from hydromodpy.core.tracking.walker import collect_input_files


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    geometry: Annotated[
        Path | None,
        InputFile(role="network_map", category="geometry"),
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
