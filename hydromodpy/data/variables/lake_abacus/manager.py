"""Lake-abacus manager: stage-volume-area tables from the user's files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.data.contracts.table import TableRecord
from hydromodpy.data.managers.base_manager_file import BaseFileManager


class LakeAbacusManager(BaseFileManager):
    VARIABLE_NAME = "lake_abacus"
    RECORD_KIND = "tables"

    def read_custom(self, source_cfg: Any, *, derived_dir: Path | None) -> list[TableRecord]:
        """Read a CSV or Parquet abacus."""
        from hydromodpy.data.variables.lake_abacus.custom import load_custom_abacus

        return load_custom_abacus(source_cfg, derived_dir=derived_dir)

    def index_fields(self, record: TableRecord) -> dict[str, Any]:
        return {"station_id": record.table_id, "unit": record.unit}
