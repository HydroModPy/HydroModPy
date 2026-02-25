"""Common station-level utilities shared by hydrometry and piezometry."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional, Sequence, Tuple

import pandas as pd


class BaseStation:
    """Reusable operations for single-station time-series objects.

    Domain-specific classes (for example ``Station`` and ``Piezometer``)
    inherit this class and provide their own domain mappings/plot logic while
    reusing:
    - coordinate/georeferencing inference,
    - dataframe dtype normalization,
    - date-range filtering,
    - completeness (missing-data) computation,
    - robust numeric/datetime parsing helpers.
    """

    @staticmethod
    def infer_spatial_info(metadata: Mapping[str, Any]) -> Tuple[dict, dict]:
        """Infer station coordinates and georeferencing flags from metadata."""
        x_wgs84 = BaseStation._as_float_or_none(
            metadata.get("x_wgs84", metadata.get("longitude_station", metadata.get("lon")))
        )
        y_wgs84 = BaseStation._as_float_or_none(
            metadata.get("y_wgs84", metadata.get("latitude_station", metadata.get("lat")))
        )
        x_l93 = BaseStation._as_float_or_none(
            metadata.get("x_l93", metadata.get("coordonnee_x_station"))
        )
        y_l93 = BaseStation._as_float_or_none(
            metadata.get("y_l93", metadata.get("coordonnee_y_station"))
        )

        available_crs = []
        if x_wgs84 is not None and y_wgs84 is not None:
            available_crs.append("EPSG:4326")
        if x_l93 is not None and y_l93 is not None:
            available_crs.append("EPSG:2154")

        georeferencing = {
            "is_georeferenced": bool(available_crs),
            "available_crs": available_crs,
            "preferred_crs": (
                "EPSG:4326"
                if "EPSG:4326" in available_crs
                else "EPSG:2154" if "EPSG:2154" in available_crs else None
            ),
        }

        station_position = {
            "wgs84": {"x": x_wgs84, "y": y_wgs84},
            "l93": {"x": x_l93, "y": y_l93},
        }
        return station_position, georeferencing

    @staticmethod
    def sanitize_dataframe(
        df: pd.DataFrame,
        *,
        date_columns: Sequence[str],
        numeric_columns: Sequence[str],
    ) -> pd.DataFrame:
        """Apply common datetime/numeric casting rules to loaded tables."""
        out = df.copy()
        for column in date_columns:
            if column in out.columns:
                out[column] = pd.to_datetime(out[column], errors="coerce")
        for column in numeric_columns:
            if column in out.columns:
                out[column] = pd.to_numeric(out[column], errors="coerce")
        return out

    @staticmethod
    def filter_by_date_range(
        df: pd.DataFrame,
        *,
        date_column: str,
        date_start: Optional[datetime] = None,
        date_end: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """Filter dataframe rows within an optional date interval."""
        if date_column not in df.columns:
            return df

        out = df.copy()
        out[date_column] = pd.to_datetime(out[date_column], errors="coerce")
        out = out.dropna(subset=[date_column])
        if date_start is not None:
            out = out[out[date_column] >= date_start]
        if date_end is not None:
            out = out[out[date_column] <= date_end]
        return out

    @staticmethod
    def _empty_completeness_payload(*, id_field: str, id_value: str, expected_days: int = 0) -> dict:
        """Build a canonical empty completeness payload."""
        return {
            id_field: str(id_value),
            "expected_days": int(expected_days),
            "actual_days": 0,
            "missing_days": int(expected_days),
            "completeness_pct": 0.0,
            "first_date": None,
            "last_date": None,
            "gaps_detected": 0,
        }

    @staticmethod
    def compute_missing_data(
        df: pd.DataFrame,
        *,
        date_column: str,
        start_date: Optional[datetime],
        end_date: Optional[datetime],
        id_field: str,
        id_value: str,
        verbose: bool = True,
    ) -> dict:
        """Compute missing-data diagnostics for one station timeseries."""
        station_id = str(id_value)
        if start_date is None or end_date is None:
            return BaseStation._empty_completeness_payload(
                id_field=id_field,
                id_value=station_id,
                expected_days=0,
            )

        if df.empty or date_column not in df.columns:
            total_expected = (end_date - start_date).days + 1
            return BaseStation._empty_completeness_payload(
                id_field=id_field,
                id_value=station_id,
                expected_days=total_expected,
            )

        work = df.copy()
        work[date_column] = pd.to_datetime(work[date_column], errors="coerce")
        work = work.dropna(subset=[date_column])

        expected_dates = pd.date_range(start=start_date, end=end_date, freq="D")
        actual_dates = work[date_column].dt.normalize().unique()
        missing_dates = set(expected_dates) - set(pd.to_datetime(actual_dates))

        if missing_dates:
            missing_sorted = sorted(missing_dates)
            gaps = 1
            for idx in range(1, len(missing_sorted)):
                if (missing_sorted[idx] - missing_sorted[idx - 1]).days > 1:
                    gaps += 1
        else:
            gaps = 0

        expected_count = len(expected_dates)
        actual_count = len(actual_dates)
        payload = {
            id_field: station_id,
            "expected_days": expected_count,
            "actual_days": actual_count,
            "missing_days": len(missing_dates),
            "completeness_pct": (actual_count / expected_count) * 100 if expected_count else 0.0,
            "first_date": work[date_column].min() if not work.empty else None,
            "last_date": work[date_column].max() if not work.empty else None,
            "gaps_detected": gaps,
        }

        if verbose:
            if missing_dates:
                print(
                    f"  Missing data: {len(missing_dates)} days "
                    f"({payload['completeness_pct']:.1f}% complete)"
                )
                print(f"  Gaps detected: {gaps}")
            else:
                print(f"  Complete data: 100% ({actual_count} days)")

        return payload

    @staticmethod
    def _as_float_or_none(value: Any) -> Optional[float]:
        """Convert numeric-like values to ``float``; return ``None`` when missing."""
        if value is None:
            return None
        if isinstance(value, str) and value.strip() == "":
            return None
        try:
            parsed = pd.to_numeric(value, errors="coerce")
        except Exception:
            return None
        if pd.isna(parsed):
            return None
        return float(parsed)

    @staticmethod
    def _to_datetime_or_none(value: Any) -> Optional[datetime]:
        """Parse datetime-like values and return ``None`` on failure."""
        if value is None:
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
