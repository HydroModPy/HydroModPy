"""A key retired by the outputs and orchestration target is refused by name.

A section that only a pre-release of 2.0 wrote is refused in a file by the list of
``prerelease_forms.txt``, with the way out. The model still says what replaces it, which
a Python caller and a sealed snapshot read.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from hydromodpy.config.hydromodpy_config import HydroModPyConfig

SYNTHETIC = {"geographic": {"source_mode": "synthetic"}}


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "project.toml"
    path.write_text('[geographic]\nsource_mode = "synthetic"\n\n' + text, encoding="utf-8")
    return path


def test_the_mesh_catchment_batch_section_stays_refused() -> None:
    with pytest.raises(ValidationError, match="no replacement"):
        HydroModPyConfig.model_validate({**SYNTHETIC, "mesh_catchment_batch": {}})
