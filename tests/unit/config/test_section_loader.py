"""Loading one TOML section into its model, with the paths of its files resolved from the project root.

A workspace name is read in the folder of the role of the field, under the
workspace data folder. A bare file name is refused, and the refusal gives the
workspace name to write when the file is in that folder.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import pytest
from pydantic import BaseModel

from hydromodpy.config.section_loader import load_standard_section
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.toml_io.paths import BareInputNameError
from hydromodpy.core.tracking.input_file import InputFile


class Piezometry(BaseModel):
    file: Annotated[Path | None, InputFile(role="piezometry", category="data")] = None
    mask: Path | None = None


def test_a_bare_name_is_refused_with_its_workspace_name(tmp_path: Path) -> None:
    former = tmp_path / "data" / "piezometry" / "heads.csv"
    former.parent.mkdir(parents=True)
    former.touch()

    with pytest.raises(BareInputNameError, match="Write 'workspace:heads.csv'"):
        load_standard_section(
            {"file": "heads.csv"},
            Piezometry,
            tmp_path / "project",
            workspace_data_dir=tmp_path / "data",
        )


def test_a_bare_name_without_a_former_place_gets_a_suggestion(tmp_path: Path) -> None:
    with pytest.raises(BareInputNameError, match="for example 'inputs/heads.csv'"):
        load_standard_section({"file": "heads.csv"}, Piezometry, tmp_path)


def test_a_path_is_resolved_from_the_project_root(tmp_path: Path) -> None:
    section = load_standard_section({"file": "inputs/heads.csv"}, Piezometry, tmp_path)

    assert section.file == (tmp_path / "inputs" / "heads.csv").resolve()


def test_a_workspace_name_is_read_in_the_folder_of_the_role(tmp_path: Path) -> None:
    section = load_standard_section(
        {"file": "workspace:heads.csv"},
        Piezometry,
        tmp_path / "project",
        workspace_data_dir=tmp_path / "data",
    )

    assert section.file == tmp_path / "data" / "piezometry" / "heads.csv"


def test_a_workspace_name_on_a_key_with_no_role_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="this key is not one"):
        load_standard_section(
            {"mask": "workspace:mask.gpkg"},
            Piezometry,
            tmp_path / "project",
            workspace_data_dir=tmp_path / "data",
        )
