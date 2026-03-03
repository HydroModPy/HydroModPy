"""
WaterQuality object for individual water-quality site or sample series.

This is analogous to :class:`Piezometer` but data fields will be adapted to the
Hub'Eau quality endpoints (river / piezometer).  The implementation here is a
starting point; you will need to update ``process_api_dataframe`` and other
helpers to match the actual JSON attributes returned by the chosen endpoint.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple, Union

import pandas as pd

try:
    from ..common.base_station import BaseStation
except ImportError:  # pragma: no cover
    import sys

    _manager_root = Path(__file__).resolve().parents[1]
    if str(_manager_root) not in sys.path:
        sys.path.insert(0, str(_manager_root))
    from common.base_station import BaseStation


class WaterQuality(BaseStation):
    """Single water‑quality series with site‑level operations."""

    def __init__(
        self,
        *,
        site_id: str,
        data: Optional[pd.DataFrame] = None,
        metadata: Optional[Mapping[str, Any]] = None,
        site_position: Optional[Mapping[str, Any]] = None,
        georeferencing: Optional[Mapping[str, Any]] = None,
    ):
        self.site_id = str(site_id)
        self.metadata = dict(metadata) if metadata else {}
        inferred_position, inferred_georef = self.infer_spatial_info(self.metadata)
        self.site_position = dict(site_position) if site_position is not None else inferred_position
        self.georeferencing = dict(georeferencing) if georeferencing is not None else inferred_georef
        self.data = pd.DataFrame() if data is None else data.copy()
        if not self.data.empty:
            self.data = self._sanitize_loaded_data(self.data)

    @staticmethod
    def infer_spatial_info(metadata: Mapping[str, Any]) -> Tuple[dict, dict]:
        return BaseStation.infer_spatial_info(metadata)

    @staticmethod
    def _sanitize_loaded_data(df: pd.DataFrame) -> pd.DataFrame:
        # the set of expected columns should be adapted for water quality;
        # here we assume at least a datetime column named 'date_measure' and
        # one or more parameters.
        return BaseStation.sanitize_dataframe(
            df,
            date_columns=["date_measure"],
            numeric_columns=None,  # parameters will be converted later
        )

    @staticmethod
    def _parse_datetime_column(series: pd.Series) -> pd.Series:
        # reuse same logic as Piezometer
        numeric = pd.to_numeric(series, errors="coerce")
        if numeric.notna().any():
            dt_ms = pd.to_datetime(numeric, unit="ms", errors="coerce")
            dt_s = pd.to_datetime(numeric, unit="s", errors="coerce")
            out = dt_ms.where(dt_ms.notna(), dt_s)
            return out.where(out.notna(), pd.to_datetime(series, errors="coerce"))
        return pd.to_datetime(series, errors="coerce")

    @staticmethod
    def process_api_dataframe(
        df: pd.DataFrame,
        *,
        site_id: str,
        parameters: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """Convert raw API output into standard format.

        This must be updated to match the JSON fields returned by
        ``qualite_rivieres`` / ``qualite_nappes`` endpoints; the code below is
        only illustrative.
        """
        out = pd.DataFrame()
        # example: both endpoints often use 'date_prelevement' or similar
        if "date_prelevement" in df.columns:
            out["date_measure"] = df["date_prelevement"]
        elif "date" in df.columns:
            out["date_measure"] = df["date"]
        else:
            out["date_measure"] = pd.NaT

        out["date_measure"] = WaterQuality._parse_datetime_column(out["date_measure"])
        out["site_id"] = str(site_id)

        # bring in all other columns as-is; parameter filtering may happen later
        for col in df.columns:
            if col not in ("date_prelevement", "date", "site_id"):
                out[col] = df[col]

        # optionally drop unwanted parameters
        if parameters is not None:
            keep = ["date_measure", "site_id"] + parameters
            out = out.loc[:, out.columns.intersection(keep)]

        return out.sort_values("date_measure").reset_index(drop=True)

    # additional helpers (completeness, filter_by_date_range, plot, etc.) may be
    # reimplemented or copied from :class:`Piezometer` as needed.


# end of water_quality.py
