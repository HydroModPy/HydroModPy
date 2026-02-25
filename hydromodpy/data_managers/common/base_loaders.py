"""Shared helpers for API/local data loaders."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Mapping, Optional, Sequence

import pandas as pd


DEFAULT_STATUS_MESSAGES = {
    200: "Success: All results present in the response",
    206: "Partial content: Some results may be missing",
    400: "Bad request: Check your request parameters",
    401: "Unauthorized: Check your credentials",
    403: "Forbidden: Check your permissions",
    404: "Not found: Check your URL",
    500: "Internal server error: Try again later",
}


class BaseApiLoader:
    """Base helpers reused by API loaders."""

    STATUS_MESSAGES = DEFAULT_STATUS_MESSAGES

    @classmethod
    def _check_status_code(cls, status_code: int) -> bool:
        """Validate Hub'Eau status code and print a readable diagnostic."""
        message = cls.STATUS_MESSAGES.get(
            status_code, f"Unknown error {status_code}: Check the API documentation"
        )
        is_success = status_code in (200, 206)
        if not is_success:
            print(f"Error {status_code}: {message}")
        return is_success

    @staticmethod
    def _to_datetime_or_none(value):
        """Parse datetime-like value and return ``None`` on failure."""
        if value is None or pd.isna(value):
            return None
        if isinstance(value, datetime):
            return value
        try:
            parsed = pd.to_datetime(value, errors="coerce")
        except Exception:
            return None
        if pd.isna(parsed):
            return None
        return parsed.to_pydatetime() if hasattr(parsed, "to_pydatetime") else parsed


class BaseLocalLoader:
    """Base helpers reused by local file loaders."""

    @staticmethod
    def _to_datetime_or_none(value):
        """Parse datetime-like value and return ``None`` on failure."""
        if value is None or pd.isna(value):
            return None
        if isinstance(value, datetime):
            return value
        try:
            parsed = pd.to_datetime(value, errors="coerce")
        except Exception:
            return None
        if pd.isna(parsed):
            return None
        return parsed.to_pydatetime() if hasattr(parsed, "to_pydatetime") else parsed

    @staticmethod
    def _filter_reference_by_station_id(
        df: pd.DataFrame,
        station_col: str,
        station_ids: Sequence[str],
    ) -> pd.DataFrame:
        """Filter a reference dataframe to requested station identifiers."""
        if df.empty or station_col not in df.columns:
            return df
        return df[df[station_col].astype(str).isin([str(v) for v in station_ids])].copy()

    @staticmethod
    def _read_optional_csv(path: Path) -> pd.DataFrame:
        """Read one optional CSV file and return empty dataframe when missing."""
        return pd.read_csv(path) if path.exists() else pd.DataFrame()

    @staticmethod
    def _first_matching_metadata_row(
        *,
        metadata_df: pd.DataFrame,
        candidate_id_columns: Sequence[str],
        entity_id: str,
    ) -> Optional[Mapping[str, object]]:
        """Return first metadata row matching one candidate id column."""
        if metadata_df.empty:
            return None
        for column in candidate_id_columns:
            if column not in metadata_df.columns:
                continue
            match = metadata_df[metadata_df[column].astype(str) == str(entity_id)]
            if not match.empty:
                return match.iloc[0].to_dict()
        return None
