# -*- coding: utf-8 -*-

from dataclasses import dataclass
from pathlib import Path
from typing import Dict
import logging
import sys

import pandas as pd

EXTERNAL_DIR = Path(r"C:\Users\Pelissierm\waterwise_0.1.0")
sys.path.insert(0, str(EXTERNAL_DIR))

from waterwise.config import Paths, ClimateWindow
from waterwise.predictions.prediction_tools import (
    read_csv_prediction,
    spatial_mean,
    seasonal_aggregation,
    window_mean,
    relative_change_percent,
    classification_explore2,
    classification_plot
)


@dataclass(frozen=True)
class ClimateNarrativesConfig:
    reference: ClimateWindow
    horizons: Dict[str, ClimateWindow]
    classification_horizon: str
    model_precip_filename: str = "total_precipitation_pyhelp.csv"
    summer_dry_threshold: float = -20.0   
    winter_wet_threshold: float = 20.0   


def _iter_models(root):
    for p in sorted(root.glob("_*")):
        if p.is_dir():
            yield p


def run_climate_model_families(paths: Paths, cfg: ClimateNarrativesConfig, logger=None) -> pd.DataFrame:
    logger = logger or logging.getLogger(__name__)
    climate_root = Path(paths.climate_root)

    out_dir = Path(paths.out_root) / "climate_narratives"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []

    for model_dir in _iter_models(climate_root):
        
        model = model_dir.name
        
        dataset = model_dir / cfg.model_precip_filename
        
        ref = read_csv_prediction(dataset)
        ref_mean = spatial_mean(ref.values)
        ref_djf = seasonal_aggregation(ref.time, ref_mean, "DJF", "sum")
        ref_jja = seasonal_aggregation(ref.time, ref_mean, "JJA", "sum")
        ref_DJF = window_mean(ref_djf, cfg.reference.start_date, cfg.reference.end_date)
        ref_JJA = window_mean(ref_jja, cfg.reference.start_date, cfg.reference.end_date)
        
        # Projections seasonal processing
        pr = read_csv_prediction(dataset)
        pr_mean = spatial_mean(pr.values)
        pr_djf = seasonal_aggregation(pr.time, pr_mean, "DJF", "sum")
        pr_jja = seasonal_aggregation(pr.time, pr_mean, "JJA", "sum")

        for hz_name, hz in cfg.horizons.items():
            fut_DJF = window_mean(pr_djf, hz.start_date, hz.end_date)
            fut_JJA = window_mean(pr_jja, hz.start_date, hz.end_date)

            rows.append(
                {
                    "model": model,
                    "horizon": hz_name,
                    "P_DJF_ref": ref_DJF,
                    "P_JJA_ref": ref_JJA,
                    "P_DJF_hz": fut_DJF,
                    "P_JJA_hz": fut_JJA,
                    "dP_DJF": relative_change_percent(fut_DJF, ref_DJF),
                    "dP_JJA": relative_change_percent(fut_JJA, ref_JJA),
                }
            )

    metrics_df = (pd.DataFrame(rows).sort_values(["horizon", "model"]).reset_index(drop=True))

    # Families (computed on one horizon)
    class_df = metrics_df[metrics_df["horizon"] == cfg.classification_horizon].copy()
    class_df = class_df.set_index("model")

    fam = classification_explore2(class_df, summer_col="dP_JJA", winter_col="dP_DJF", summer_dry_threshold=cfg.summer_dry_threshold,
        winter_wet_threshold=cfg.winter_wet_threshold,
    )

    metrics_df["family"] = metrics_df["model"].map(fam.to_dict())

    out_path = out_dir / "climate_metrics_with_families.csv"
    metrics_df.to_csv(out_path, index=False)
    logger.info("Wrote %s", out_path)
    
    classification_plot(out_path)



if __name__ == "__main__":
    from waterwise.logging_utils import setup_logger

    paths = Paths(
        data_root=Path("Z:/HDPY_database_forModelling"),
        out_root=Path('Z:/HDPY_database_forModelling/_climate/_projection/_pyHelpInput'),
        climate_root=Path('Z:/HDPY_database_forModelling/_climate/_projection/_pyHelpInput'),
        base_grid_csv=Path("Z:/HDPY_database_forModelling/base_grid.csv")
    )

    logger = setup_logger(name="waterwise",
        log_file=Path(paths.out_root) / "climate_narratives" / "climate_narratives.log")

    cfg = ClimateNarrativesConfig(
        reference=ClimateWindow("1991-01-01", "2020-12-31", "%Y-%m-%d"),
        horizons={"far": ClimateWindow("2075-01-01", "2100-12-31", "%Y-%m-%d")},
        classification_horizon="far",
        model_precip_filename="total_precipitation_pyhelp.csv")

    run_climate_model_families(paths=paths, cfg=cfg, logger=logger)
