"""Station object for single-station hydrometric time series operations."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple, Union

import pandas as pd


class Station:
    """Single station series with station-level operations."""

    def __init__(
        self,
        *,
        station_id: str,
        variable: str,
        data: Optional[pd.DataFrame] = None,
        metadata: Optional[Mapping[str, Any]] = None,
        station_position: Optional[Mapping[str, Any]] = None,
        georeferencing: Optional[Mapping[str, Any]] = None,
    ):
        self.station_id = str(station_id)
        self.variable = str(variable)
        self.metadata = dict(metadata) if metadata else {}
        inferred_position, inferred_georef = self.infer_spatial_info(self.metadata)
        self.station_position = dict(station_position) if station_position is not None else inferred_position
        self.georeferencing = dict(georeferencing) if georeferencing is not None else inferred_georef
        self.data = pd.DataFrame() if data is None else data.copy()
        if not self.data.empty:
            self.data = self._sanitize_loaded_data(self.data)

    @staticmethod
    def infer_spatial_info(metadata: Mapping[str, Any]) -> Tuple[dict, dict]:
        """Infer station coordinates and georeferencing flags from metadata."""
        x_wgs84 = Station._as_float_or_none(
            metadata.get("x_wgs84", metadata.get("longitude_station", metadata.get("lon")))
        )
        y_wgs84 = Station._as_float_or_none(
            metadata.get("y_wgs84", metadata.get("latitude_station", metadata.get("lat")))
        )
        x_l93 = Station._as_float_or_none(
            metadata.get("x_l93", metadata.get("coordonnee_x_station"))
        )
        y_l93 = Station._as_float_or_none(
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
    def _sanitize_loaded_data(df: pd.DataFrame) -> pd.DataFrame:
        """Ensure standard dtypes and required columns for loaded station data."""
        out = df.copy()
        if "date_obs_elab" in out.columns:
            out["date_obs_elab"] = pd.to_datetime(out["date_obs_elab"], errors="coerce")
        if "resultat_obs_elab" in out.columns:
            out["resultat_obs_elab"] = pd.to_numeric(out["resultat_obs_elab"], errors="coerce")
        return out

    @staticmethod
    def filter_by_date_range(
        df: pd.DataFrame,
        date_start: Optional[datetime] = None,
        date_end: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """Filter station dataframe using date range when possible."""
        if "date_obs_elab" not in df.columns:
            return df

        out = df.copy()
        out["date_obs_elab"] = pd.to_datetime(out["date_obs_elab"], errors="coerce")
        out = out.dropna(subset=["date_obs_elab"])
        if date_start is not None:
            out = out[out["date_obs_elab"] >= date_start]
        if date_end is not None:
            out = out[out["date_obs_elab"] <= date_end]
        return out

    @staticmethod
    def process_api_dataframe(
        df: pd.DataFrame,
        *,
        variable: str,
        station_id: str,
        watershed_area: Optional[float] = None,
    ) -> pd.DataFrame:
        """Process and clean raw API dataframe for one station."""
        base_columns = [
            "date_obs_elab",
            "resultat_obs_elab",
            "grandeur_hydro_elab",
            "libelle_qualification",
        ]
        available_columns = [col for col in base_columns if col in df.columns]
        out = df[available_columns].copy()

        if variable in ["QmnJ", "QmM", "QINM", "QINnJ", "QixM", "QIXnJ"]:
            out["resultat_obs_elab"] = pd.to_numeric(out["resultat_obs_elab"], errors="coerce") / 1000.0
            if watershed_area and pd.notna(watershed_area) and watershed_area > 0:
                out["specific_discharge"] = out["resultat_obs_elab"] / float(watershed_area)
        elif variable in ["HIXM", "HIXnJ"]:
            out["resultat_obs_elab"] = pd.to_numeric(out["resultat_obs_elab"], errors="coerce") / 1000.0

        out["date_obs_elab"] = pd.to_datetime(out["date_obs_elab"], errors="coerce")
        out["station_id"] = str(station_id)
        out = out.dropna(subset=["date_obs_elab", "resultat_obs_elab"])
        return out

    @staticmethod
    def compute_missing_data(
        df: pd.DataFrame,
        *,
        start_date: datetime,
        end_date: datetime,
        station_id: str,
        verbose: bool = True,
    ) -> dict:
        """Compute missing data summary for one station within a date range."""
        sid = str(station_id)
        if start_date is None or end_date is None:
            return {
                "station_id": sid,
                "expected_days": 0,
                "actual_days": 0,
                "missing_days": 0,
                "completeness_pct": 0.0,
                "first_date": None,
                "last_date": None,
                "gaps_detected": 0,
            }

        if df.empty or "date_obs_elab" not in df.columns:
            total_expected = (end_date - start_date).days + 1
            return {
                "station_id": sid,
                "expected_days": total_expected,
                "actual_days": 0,
                "missing_days": total_expected,
                "completeness_pct": 0.0,
                "first_date": None,
                "last_date": None,
                "gaps_detected": 0,
            }

        work = df.copy()
        work["date_obs_elab"] = pd.to_datetime(work["date_obs_elab"], errors="coerce")
        work = work.dropna(subset=["date_obs_elab"])

        expected_dates = pd.date_range(start=start_date, end=end_date, freq="D")
        actual_dates = work["date_obs_elab"].dt.normalize().unique()
        missing_dates = set(expected_dates) - set(pd.to_datetime(actual_dates))

        if missing_dates:
            missing_sorted = sorted(missing_dates)
            gaps = 1
            for idx in range(1, len(missing_sorted)):
                if (missing_sorted[idx] - missing_sorted[idx - 1]).days > 1:
                    gaps += 1
        else:
            gaps = 0

        missing_info = {
            "station_id": sid,
            "expected_days": len(expected_dates),
            "actual_days": len(actual_dates),
            "missing_days": len(missing_dates),
            "completeness_pct": (len(actual_dates) / len(expected_dates)) * 100 if len(expected_dates) else 0.0,
            "first_date": work["date_obs_elab"].min() if not work.empty else None,
            "last_date": work["date_obs_elab"].max() if not work.empty else None,
            "gaps_detected": gaps,
        }

        if verbose:
            if len(missing_dates) > 0:
                print(
                    f"  Missing data: {len(missing_dates)} days "
                    f"({missing_info['completeness_pct']:.1f}% complete)"
                )
                print(f"  Gaps detected: {gaps}")
            else:
                print(f"  Complete data: 100% ({len(actual_dates)} days)")

        return missing_info

    def completeness(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        verbose: bool = True,
    ) -> dict:
        """Compute completeness summary for this station."""
        start = start_date
        end = end_date

        if start is None:
            start = self.metadata.get("start_date")
        if end is None:
            end = self.metadata.get("end_date")
        start = self._to_datetime_or_none(start)
        end = self._to_datetime_or_none(end)

        if (start is None or end is None) and not self.data.empty and "date_obs_elab" in self.data.columns:
            dates = pd.to_datetime(self.data["date_obs_elab"], errors="coerce").dropna()
            if not dates.empty:
                if start is None:
                    start = dates.min().to_pydatetime()
                if end is None:
                    end = dates.max().to_pydatetime()

        if start is None or end is None:
            return {
                "station_id": self.station_id,
                "expected_days": 0,
                "actual_days": 0,
                "missing_days": 0,
                "completeness_pct": 0.0,
                "first_date": None,
                "last_date": None,
                "gaps_detected": 0,
            }

        return self.compute_missing_data(
            self.data,
            start_date=start,
            end_date=end,
            station_id=self.station_id,
            verbose=verbose,
        )

    @staticmethod
    def _to_datetime_or_none(value: Any) -> Optional[datetime]:
        """Convert input to datetime when possible."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed.to_pydatetime() if hasattr(parsed, "to_pydatetime") else parsed

    @staticmethod
    def _as_float_or_none(value: Any) -> Optional[float]:
        """Convert numeric-like values to float; return None when unavailable."""
        if value is None:
            return None
        try:
            parsed = pd.to_numeric(value, errors="coerce")
        except Exception:
            return None
        if pd.isna(parsed):
            return None
        return float(parsed)

    def build_label(self) -> str:
        """Build display label from station id and optional station name."""
        station_name = self.metadata.get("station_name")
        if station_name and pd.notna(station_name):
            return f"{self.station_id} - {station_name}"
        return self.station_id

    def plot(
        self,
        output_path: Optional[Union[str, Path]] = None,
        show: bool = True,
        block: bool = True,
        figsize: tuple = (12, 4),
    ):
        """Plot this single-station series."""
        if self.data.empty:
            raise ValueError(f"No loaded station data available for station {self.station_id}.")

        try:
            import matplotlib.pyplot as plt
        except ImportError as exc:
            raise ImportError(
                "Matplotlib is required to plot station data. "
                "Install with: pip install matplotlib"
            ) from exc

        if "date_obs_elab" not in self.data.columns or "resultat_obs_elab" not in self.data.columns:
            raise ValueError(
                "Expected columns 'date_obs_elab' and 'resultat_obs_elab' are missing "
                "from loaded station data."
            )

        plot_df = self.data.copy()
        plot_df["date_obs_elab"] = pd.to_datetime(plot_df["date_obs_elab"], errors="coerce")
        plot_df["resultat_obs_elab"] = pd.to_numeric(plot_df["resultat_obs_elab"], errors="coerce")
        plot_df = plot_df.dropna(subset=["date_obs_elab", "resultat_obs_elab"]).sort_values("date_obs_elab")
        if plot_df.empty:
            raise ValueError(f"No valid station points available for station {self.station_id}.")

        fig, ax = plt.subplots(1, 1, figsize=figsize, dpi=140)
        ax.plot(
            plot_df["date_obs_elab"].to_numpy(),
            plot_df["resultat_obs_elab"].to_numpy(dtype=float),
            linewidth=1.2,
            label=self.build_label(),
        )

        y_label = "Observed value"
        if self.variable in ["QmnJ", "QmM", "QINM", "QINnJ", "QixM", "QIXnJ"]:
            y_label = "Discharge [m3/s]"
        elif self.variable in ["HIXM", "HIXnJ"]:
            y_label = "Water level [m]"

        ax.set_title(f"Loaded station series - {self.variable}")
        ax.set_xlabel("Date")
        ax.set_ylabel(y_label)
        ax.grid(True, alpha=0.3)
        ax.legend(loc="best", fontsize=9)
        fig.tight_layout()

        if output_path is not None:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(output_path, bbox_inches="tight")
            print(f"Station figure exported to: {output_path}")

        backend = plt.get_backend().lower()
        if show:
            if "agg" in backend:
                print("Figure backend is non-interactive (Agg): closing figure without display.")
                plt.close(fig)
            else:
                plt.show(block=bool(block))
        else:
            plt.close(fig)

        return fig, ax
