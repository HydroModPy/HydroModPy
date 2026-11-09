"""Intermittency manager: custom flow-state chronicles and Hub'Eau ONDE."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.managers.base_manager_variable import BaseVariableManager
from hydromodpy.data.variables.intermittency.config import IntermittencySourceConfig

if TYPE_CHECKING:
    from hydromodpy.data.source.port import FetchRequest


class IntermittencyManager(BaseVariableManager):
    """Observed flow states of streams, from the user's files or Hub'Eau ONDE."""

    VARIABLE_NAME = "intermittency"
    """Name of the data type, as ``[data.intermittency]`` writes it."""

    INTERNAL_UNIT = "code"
    """Unit of the stored values: a flow-state code from 1 to 5, not a quantity."""

    RECORD_VARIABLE = "flow_state"
    """Variable name the records are stored under."""

    def load_file(self, source_cfg: IntermittencySourceConfig) -> list[PointRecord]:
        """Load observed flow states: codes 1 to 5, irregular dates, never expanded."""
        from hydromodpy.data.ingest.custom_points import load_file_points

        records = load_file_points(
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

    def _station_request(
        self,
        source_cfg: IntermittencySourceConfig,
        out_dir: Path,
        station_ids: Sequence[str],
        bbox: tuple[float, float, float, float] | None,
        start: datetime | None,
        end: datetime | None,
    ) -> FetchRequest:
        from hydromodpy.catchment.administrative.france import bbox_for_departments
        from hydromodpy.data.source.port import Extent, FetchRequest, Period

        station_ids = list(station_ids or ())
        period = Period(start=start, end=end) if start is not None and end is not None else None
        if station_ids:
            return FetchRequest(out_dir=out_dir, station_ids=tuple(station_ids), period=period)

        code_dept = getattr(source_cfg, "code_departement", None)
        if bbox is None and code_dept:
            dept_bbox_2154 = bbox_for_departments(code_dept)
            extent = Extent(*dept_bbox_2154, crs="EPSG:2154").to_crs("EPSG:4326")
            return FetchRequest(out_dir=out_dir, extent=extent, period=period)

        return super()._station_request(
            source_cfg,
            out_dir=out_dir,
            station_ids=station_ids,
            bbox=bbox,
            start=start,
            end=end,
        )
