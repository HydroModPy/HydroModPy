"""Lake-abacus variable: stage-volume-area tables from the user's files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.data.contracts.table import TableRecord
from hydromodpy.data.families.files import FileVariable


class LakeAbacusVariable(FileVariable):
    VARIABLE_NAME = "lake_abacus"
    RECORD_KIND = "tables"

    def read_file_source(self, source_cfg: Any, *, derived_dir: Path | None) -> list[TableRecord]:
        """Read a CSV or Parquet abacus."""
        from hydromodpy.data.variables.lake_abacus.custom import load_custom_abacus

        return load_custom_abacus(source_cfg, derived_dir=derived_dir)
