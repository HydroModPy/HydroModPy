# -*- coding: utf-8 -*-
"""Intermittency support from ONDE-like observations.

This module handles a simple, explicit workflow for stream intermittency:

1. clip a national ONDE shapefile to the watershed polygon,
2. extract station metadata (codes, labels, coordinates, date bounds),
3. convert textual flow labels to numeric classes,
4. export one diagnostic plot per station,
5. build one aggregated time-indexed table (`self.flowing`).

The class is intentionally report-oriented: it prepares observation summaries
used by diagnostics and calibration support, not solver boundary conditions.
"""

from __future__ import annotations

import os

import geopandas as gpd
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import whitebox

from hydromodpy.tools import get_logger

logger = get_logger(__name__)
WBT = whitebox.WhiteboxTools()
WBT.verbose = False


def _normalize_col_token(value: object) -> str:
    """Normalize a column name token for tolerant ONDE schema matching."""
    text = str(value).strip().lower()
    return "".join(ch for ch in text if ch.isalnum())


def _resolve_required_column(
    available_columns: list[str],
    *,
    role: str,
    candidates: tuple[str, ...],
) -> str:
    """Return the matching column name for one logical ONDE field.

    The ONDE exports are not always stable across providers/conversions:
    some files carry raw names like ``<LbSiteHyd`` while others may include
    closing ``>`` or slight punctuation variants. We therefore resolve columns
    by normalized token, while keeping deterministic priority from *candidates*.
    """
    candidate_map = {_normalize_col_token(col): col for col in available_columns}
    for candidate in candidates:
        key = _normalize_col_token(candidate)
        if key in candidate_map:
            return candidate_map[key]
    raise KeyError(
        f"Intermittency column for '{role}' was not found. "
        f"Tried candidates={candidates}. Available={available_columns}"
    )


def _resolve_onde_columns(available_columns: list[str]) -> dict[str, str]:
    """Resolve the logical ONDE schema to concrete column names."""
    return {
        "station_label": _resolve_required_column(
            available_columns,
            role="station_label",
            candidates=("<LbSiteHyd", "<LbSiteHyd>", "LbSiteHyd", "label_site"),
        ),
        "station_code": _resolve_required_column(
            available_columns,
            role="station_code",
            candidates=("<CdSiteHyd", "<CdSiteHyd>", "CdSiteHyd", "code_site"),
        ),
        "x_coord": _resolve_required_column(
            available_columns,
            role="x_coord",
            candidates=("<CoordXSit", "<CoordXSit>", "CoordXSit", "x"),
        ),
        "y_coord": _resolve_required_column(
            available_columns,
            role="y_coord",
            candidates=("<CoordYSit", "<CoordYSit>", "CoordYSit", "y"),
        ),
        "obs_date": _resolve_required_column(
            available_columns,
            role="obs_date",
            candidates=("<DtRealObs", "<DtRealObs>", "DtRealObs", "date_obs"),
        ),
        "obs_label": _resolve_required_column(
            available_columns,
            role="obs_label",
            candidates=("<LbRsObser", "<LbRsObser>", "LbRsObser", "observation_label"),
        ),
    }


def _vector_dataset_family(path: str) -> tuple[str, ...]:
    """Return the file family used to track one vector dataset freshness."""
    root, ext = os.path.splitext(path)
    if ext.lower() != ".shp":
        return (path,)
    return (
        root + ".shp",
        root + ".shx",
        root + ".dbf",
        root + ".prj",
        root + ".cpg",
        root + ".qmd",
    )


def _latest_existing_mtime(path: str) -> float:
    """Return newest mtime among existing files from one vector dataset family."""
    candidates = [item for item in _vector_dataset_family(path) if os.path.exists(item)]
    if not candidates:
        raise FileNotFoundError(path)
    return max(os.path.getmtime(item) for item in candidates)


def _clip_cache_is_valid(*, source_path: str, mask_path: str, output_path: str) -> bool:
    """Check whether clipped output is present and newer than source/mask inputs."""
    output_root, _ = os.path.splitext(output_path)
    required_output = (
        output_root + ".shp",
        output_root + ".shx",
        output_root + ".dbf",
    )
    if not all(os.path.exists(item) for item in required_output):
        return False

    try:
        output_mtime = _latest_existing_mtime(output_path)
        source_mtime = _latest_existing_mtime(source_path)
        mask_mtime = _latest_existing_mtime(mask_path)
    except FileNotFoundError:
        return False

    return output_mtime >= max(source_mtime, mask_mtime)


class Intermittency:
    """Extract, structure, and visualize stream intermittency observations.

    Parameters
    ----------
    out_path : str
        HydroModPy output root (watershed output directory).
    intermittency_path : str
        Directory containing the source intermittency shapefile.
    file_name : str
        Source shapefile name (typically a national ONDE dataset).
    geographic : object
        Watershed geographic object, expected to expose `watershed_shp`.

    Notes
    -----
    Key attributes populated by the workflow:
    - `onde_clip`: clipped shapefile path,
    - `flowing`: per-station code table indexed by datetime,
    - `code_onde`, `label`, `x_coord`, `y_coord`, `date_first`, `date_last`.
    """

    def __init__(
        self,
        out_path: str,
        intermittency_path: str,
        file_name: str,
        geographic: object,
    ):
        logger.info("Extracting stream intermittency data from %s", intermittency_path)

        data_folder = os.path.join(out_path, "results_stable", "intermittency")
        os.makedirs(data_folder, exist_ok=True)
        self.fig_intermit = os.path.join(out_path, "results_stable", "_figures", "intermittency")
        os.makedirs(self.fig_intermit, exist_ok=True)

        # Station-level metadata extracted from the clipped ONDE dataset.
        self.code_onde: list[str | None] = []
        self.label: list[str | None] = []
        self.x_coord: list[float | None] = []
        self.y_coord: list[float | None] = []
        self.date_first: list[pd.Timestamp | None] = []
        self.date_last: list[pd.Timestamp | None] = []
        self.flowing: pd.DataFrame = pd.DataFrame()

        try:
            self.extract_intermittency_from_watershed(
                data_folder=data_folder,
                intermittency_path=intermittency_path,
                file_name=file_name,
                geographic=geographic,
            )
            self.load_intermittency_data(data_folder)
        except Exception as exc:
            logger.warning("Intermittency loading failed: %s", exc, exc_info=True)

    def extract_intermittency_from_watershed(
        self,
        data_folder: str,
        intermittency_path: str,
        file_name: str,
        geographic: object,
    ) -> None:
        """Clip national intermittency observations to the watershed.

        Side effects
        ------------
        - writes `self.onde_clip` shapefile in `data_folder`,
        - fills station metadata lists (`code_onde`, `label`, coordinates, dates).
        """

        onde_data = os.path.join(intermittency_path, file_name)
        self.onde_clip = os.path.join(data_folder, file_name)
        if _clip_cache_is_valid(
            source_path=onde_data,
            mask_path=geographic.watershed_shp,
            output_path=self.onde_clip,
        ):
            logger.info("Intermittency clip cache hit, reusing %s", self.onde_clip)
        else:
            logger.info("Intermittency clip cache miss, running Whitebox clip")
            WBT.clip(onde_data, geographic.watershed_shp, self.onde_clip)

        if not os.path.exists(self.onde_clip):
            raise FileNotFoundError(f"Intermittency clip output was not created: {self.onde_clip}")

        intermit_bv = gpd.read_file(self.onde_clip)
        cols = _resolve_onde_columns(list(intermit_bv.columns))
        stations = intermit_bv[cols["station_label"]].dropna().unique()

        for station_label in stations:
            station_rows = intermit_bv[intermit_bv[cols["station_label"]] == station_label]
            if station_rows.empty:
                continue

            first_row = station_rows.iloc[0]
            last_row = station_rows.iloc[-1]

            station_code_col = cols["station_code"]
            station_label_col = cols["station_label"]
            x_coord_col = cols["x_coord"]
            y_coord_col = cols["y_coord"]
            obs_date_col = cols["obs_date"]

            code_value = first_row[station_code_col] if pd.notnull(first_row[station_code_col]) else None
            self.code_onde.append(code_value)
            self.label.append(
                first_row[station_label_col] if pd.notnull(first_row[station_label_col]) else None
            )
            self.x_coord.append(first_row[x_coord_col] if pd.notnull(first_row[x_coord_col]) else None)
            self.y_coord.append(first_row[y_coord_col] if pd.notnull(first_row[y_coord_col]) else None)
            self.date_first.append(pd.to_datetime(first_row[obs_date_col], errors="coerce"))
            self.date_last.append(pd.to_datetime(last_row[obs_date_col], errors="coerce"))

    def load_intermittency_data(self, data_folder: str) -> None:
        """Load clipped observations, build code table, and export station plots.

        Parameters
        ----------
        data_folder : str
            Kept for API compatibility with legacy call sites. The method
            currently reads from `self.onde_clip`.
        """

        # Convert ONDE labels to a compact ordinal code (dry -> visible flow).
        label_to_code = {
            "Assec": 1,
            "Ecoulement non visible": 2,
            "Ecoulement visible faible": 3,
            "Ecoulement visible acceptable": 4,
            "Ecoulement visible": 5,
        }

        shp = gpd.read_file(self.onde_clip)
        cols = _resolve_onde_columns(list(shp.columns))
        shp["date"] = pd.to_datetime(shp[cols["obs_date"]], format="%Y-%m-%d", errors="coerce")
        shp["code_flow"] = shp[cols["obs_label"]].map(label_to_code)
        self.flowing = pd.DataFrame()

        unknown_labels = sorted(
            {
                str(value)
                for value in shp[cols["obs_label"]].dropna().unique()
                if value not in label_to_code
            }
        )
        if unknown_labels:
            logger.warning(
                "Unknown intermittency observation labels encountered: %s",
                ", ".join(unknown_labels),
            )

        for code in self.code_onde:
            if code is None:
                continue
            station_rows = shp[shp[cols["station_code"]] == code]
            if station_rows.empty:
                continue

            station_series = station_rows[["date", "code_flow"]].copy()
            station_series = station_series.dropna(subset=["date"]).set_index("date")
            station_series.columns = [code]
            self.flowing = pd.concat([self.flowing, station_series], axis=1).sort_index()

            # Station diagnostic plot: one point per observation date.
            fig, ax = plt.subplots(1, 1, figsize=(5, 2))
            ax.scatter(
                station_series.index,
                station_series[code],
                c=station_series[code],
                cmap="jet_r",
                vmin=1,
                vmax=5,
                marker="|",
                s=50,
                lw=1.5,
            )
            station_label = str(station_rows.iloc[0][cols["station_label"]])
            ax.set_title(f"{code} - {station_label}")
            ax.set_yticks(list(label_to_code.values()))
            ax.set_yticklabels(["Dry", "Invisible", "Low", "Acceptable", "Visible"])
            ax.set_ylim(0.5, 5.5)
            ax.set_xlim([pd.to_datetime("2012"), pd.to_datetime("2022")])

            ax.xaxis.set_major_locator(mdates.YearLocator(2))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
            ax.xaxis.set_minor_locator(mdates.YearLocator(1))
            ax.grid(True, axis="x", which="major")

            plt.tight_layout()
            figure_name = f"{code}_{station_label}.png"
            fig.savefig(
                os.path.join(self.fig_intermit, figure_name),
                dpi=300,
                bbox_inches="tight",
                transparent=False,
            )
            plt.close(fig)
            logger.debug("Intermittency station processed: %s", code)


__all__ = ["Intermittency"]
