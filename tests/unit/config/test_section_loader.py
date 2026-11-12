"""Loading one TOML section into its model, with the paths of its files resolved from the project root.

A bare file name is refused, and the refusal names where the former workspace
fallback would have found the file, under the role of the field.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import pytest
from pydantic import BaseModel

from hydromodpy.config.section_loader import load_standard_section
from hydromodpy.core.toml_io.paths import BareInputNameError
from hydromodpy.core.tracking.input_file import InputFile


class Piezometry(BaseModel):
    file: Annotated[Path | None, InputFile(role="piezometry", category="data")] = None


def test_a_bare_name_is_refused_with_its_former_place(tmp_path: Path) -> None:
    former = tmp_path / "data" / "piezometry" / "heads.csv"
    former.parent.mkdir(parents=True)
    former.touch()

    with pytest.raises(BareInputNameError, match=f"for example '{former}'"):
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
