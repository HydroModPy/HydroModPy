"""Intermittency manager: custom flow-state chronicles and Hub'Eau ONDE."""

from __future__ import annotations

from pathlib import Path

from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.managers.base_manager_variable import BaseVariableManager
from hydromodpy.data.variables.intermittency.apis import hubeau
from hydromodpy.data.variables.intermittency.config import IntermittencySourceConfig


class IntermittencyManager(BaseVariableManager):
    """Observed flow states of streams, from the user's files or Hub'Eau ONDE."""

    VARIABLE_NAME = "intermittency"
    """Name of the data type, as ``[data.intermittency]`` writes it."""

    INTERNAL_UNIT = "code"
    """Unit of the stored values: a flow-state code from 1 to 5, not a quantity."""

    RECORD_VARIABLE = "flow_state"
    """Variable name the records are stored under."""

    SOURCES = {"hubeau": hubeau.fetch_for_config}
    """Sources other than ``custom``: ``hubeau`` reads the ONDE campaigns of Hub'Eau."""

    def load_custom(self, source_cfg: IntermittencySourceConfig) -> list[PointRecord]:
        """Load observed flow states: codes 1 to 5, irregular dates, never expanded."""
        from hydromodpy.data.ingest.custom_points import load_custom_points

        records = load_custom_points(
            data_dir=Path(source_cfg.path),
            variable_name=self.VARIABLE_NAME,
            internal_unit=self.INTERNAL_UNIT,
            project_period=self.project_period,
            col_id=source_cfg.col_id,
            col_x=source_cfg.col_x,
            col_y=source_cfg.col_y,
            col_crs=source_cfg.col_crs,
            default_crs=source_cfg.default_crs,
            col_datetime=source_cfg.col_datetime,
            col_value=source_cfg.col_value,
            station_ids=source_cfg.station_ids,
            clamp_values=(1, 5),
            default_frequency="irregular",
            expand_constants=False,
            record_variable=self.RECORD_VARIABLE,
            source_unit_override=source_cfg.source_unit,
        )
        return self._apply_mask(records, source_cfg)
