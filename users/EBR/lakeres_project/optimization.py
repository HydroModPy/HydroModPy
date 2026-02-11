from __future__ import annotations

import datetime
import logging
import os
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from .config import ProjectConfig

PENALTY_VALUE = 1e6


@dataclass
class SimplexResult:
    best_hk_m_day: float
    best_hk_m_s: float
    best_log_hk: float
    best_sy: float
    best_thick: float
    best_nse: float | None
    best_r_squared: float | None
    best_rmse: float | None
    iterations: int
    duration_seconds: float
    best_model_name: str
    results_file: str
    all_simulations_file: str


class SimplexOptimizer:
    def __init__(self, BV, dam_df: pd.DataFrame, config: ProjectConfig):
        self.BV = BV
        self.dam_df = dam_df
        self.config = config
        self.optim = config.optimization
        self.counter = 0

        self.optim_folder = os.path.join(BV.simulations_folder, "optimization_results")
        os.makedirs(self.optim_folder, exist_ok=True)

        self.all_simulations_results: list[dict] = []
        self.best_record: dict | None = None

    @staticmethod
    def _normalize(value: float, vmin: float, vmax: float) -> float:
        return (value - vmin) / (vmax - vmin)

    @staticmethod
    def _denormalize(value_norm: float, vmin: float, vmax: float) -> float:
        return value_norm * (vmax - vmin) + vmin

    def _filter_dates(self, dates: pd.DatetimeIndex) -> pd.Series:
        if not isinstance(dates, pd.DatetimeIndex):
            dates = pd.DatetimeIndex(dates)

        mask = pd.Series(True, index=dates)

        if self.optim.use_time_filter:
            mask = mask & (dates >= self.optim.calib_start_date) & (dates <= self.optim.calib_end_date)

            if self.optim.use_seasonal_filter:

                def is_in_season(date: pd.Timestamp) -> bool:
                    start = pd.Timestamp(date.year, self.optim.season_start_month, self.optim.season_start_day)
                    if self.optim.season_end_month < self.optim.season_start_month:
                        end = pd.Timestamp(date.year + 1, self.optim.season_end_month, self.optim.season_end_day)
                    else:
                        end = pd.Timestamp(date.year, self.optim.season_end_month, self.optim.season_end_day)
                    return (date >= start) and (date <= end)

                seasonal_mask = dates.map(is_in_season)
                mask = mask & seasonal_mask

        return mask

    def _save_iteration(self, record: dict) -> None:
        self.all_simulations_results.append(record)
        pd.DataFrame(self.all_simulations_results).to_csv(
            os.path.join(self.optim_folder, "all_simulations_results.csv"),
            index=False,
        )

    def _objective(self, params_norm: np.ndarray) -> float:
        hk_min, hk_max = self.optim.hk_bounds_m_day
        sy_min, sy_max = self.optim.sy_bounds
        thick_min, thick_max = self.optim.thick_bounds

        log_hk_min = np.log10(hk_min)
        log_hk_max = np.log10(hk_max)

        log_hk_value = self._denormalize(params_norm[0], log_hk_min, log_hk_max)
        hk_value = 10**log_hk_value

        sy_value = self._denormalize(params_norm[1], sy_min, sy_max)
        thick_value = self._denormalize(params_norm[2], thick_min, thick_max)

        self.BV.hydraulic.update_hk(hk_value)
        self.BV.hydraulic.update_sy(sy_value)
        self.BV.hydraulic.update_thick(thick_value)

        timestamp = datetime.datetime.now().strftime("%H%M%S")
        model_name = (
            f"optim_{self.counter}_{timestamp}_hk{hk_value/24/3600:.2e}"
            f"_sy{sy_value*100:.2f}%_th{thick_value:.1f}"
        )
        self.BV.settings.update_model_name(model_name)

        logging.info(
            "Simulation %s: hk=%s m/s, sy=%s%%, thick=%sm",
            self.counter,
            f"{hk_value/24/3600:.2e}",
            f"{sy_value*100:.2f}",
            f"{thick_value:.1f}",
        )

        model_modflow = self.BV.preprocessing_modflow()
        success_modflow = self.BV.processing_modflow(model_modflow, write_model=True, run_model=True)

        if not success_modflow:
            logging.error("Échec de la simulation!")
            return PENALTY_VALUE

        self.BV.postprocessing_modflow(
            model_modflow,
            watertable_elevation=True,
            watertable_depth=False,
            seepage_areas=False,
            outflow_drain=False,
            lake_leakage=True,
            accumulation_flux=True,
        )

        self.BV.postprocessing_timeseries(model_modflow, model_modpath=None, datetime_format=True)

        csv_path = os.path.join(
            self.BV.simulations_folder,
            model_name,
            "_postprocess",
            "_timeseries",
            "_simulated_timeseries.csv",
        )
        if not os.path.exists(csv_path):
            logging.error("Fichier de résultats non trouvé: %s", csv_path)
            return PENALTY_VALUE

        sim_df = pd.read_csv(csv_path, sep=";", index_col=0, parse_dates=True)
        target_col = f"{self.config.reservoir.lake_id}_level"
        if target_col not in sim_df.columns:
            logging.error("Colonne %s absente. Colonnes: %s", target_col, sim_df.columns.tolist())
            return PENALTY_VALUE

        sim_series = sim_df[target_col]
        if sim_series.empty:
            logging.error("Série simulée vide.")
            return PENALTY_VALUE

        sim_dates = sim_series.index
        date_mask = self._filter_dates(sim_dates)
        filtered_dates = sim_dates[date_mask]
        simulated_values = sim_series[date_mask].values

        if len(filtered_dates) == 0:
            logging.warning("Aucune date ne correspond aux critères de filtrage.")
            return PENALTY_VALUE

        observed_values = []
        for date in filtered_dates:
            if date in self.dam_df.index:
                observed_values.append(self.dam_df.loc[date, "cheze_lvl"])
            else:
                closest_date = self.dam_df.index[abs(self.dam_df.index - date).argmin()]
                observed_values.append(self.dam_df.loc[closest_date, "cheze_lvl"])

        n = len(simulated_values)
        if n == 0:
            return PENALTY_VALUE

        squared_errors = [(simulated_values[i] - observed_values[i]) ** 2 for i in range(n)]
        rmse = np.sqrt(np.mean(squared_errors))

        mean_observed = np.mean(observed_values)
        numerator = sum(squared_errors)
        denominator = sum((observed_values[i] - mean_observed) ** 2 for i in range(n))
        nse = -np.inf if denominator == 0 else 1 - (numerator / denominator)

        mean_sim = np.mean(simulated_values)
        r_num = sum((observed_values[i] - mean_observed) * (simulated_values[i] - mean_sim) for i in range(n))
        r_den = np.sqrt(
            sum((observed_values[i] - mean_observed) ** 2 for i in range(n))
            * sum((simulated_values[i] - mean_sim) ** 2 for i in range(n))
        )
        r_squared = (r_num / r_den) ** 2 if r_den != 0 else 0.0

        error = 1 - nse

        record = {
            "iteration": self.counter,
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "model_name": model_name,
            "hk": hk_value,
            "hk_ms": hk_value / 24 / 3600,
            "log_hk": log_hk_value,
            "sy": sy_value,
            "thick": thick_value,
            "nse": nse,
            "r_squared": r_squared,
            "rmse": rmse,
            "error": error,
            "filtered_points": len(filtered_dates),
            "total_points": len(sim_dates),
        }

        self._save_iteration(record)

        if self.best_record is None or error < self.best_record["error"]:
            self.best_record = record
            logging.info("► Meilleure simulation jusqu'à présent ◄")

        logging.info("NSE: %.4f, R²: %.4f, RMSE: %.2f", nse, r_squared, rmse)

        self.counter += 1
        return error

    def run(self) -> SimplexResult | None:
        if not self.optim.enabled:
            logging.info("Optimisation désactivée.")
            return None

        logging.info("=== DÉMARRAGE DE L'OPTIMISATION SIMPLEX ===")
        start_time = datetime.datetime.now()

        hk_min, hk_max = self.optim.hk_bounds_m_day
        sy_min, sy_max = self.optim.sy_bounds
        thick_min, thick_max = self.optim.thick_bounds

        log_hk_min = np.log10(hk_min)
        log_hk_max = np.log10(hk_max)

        hk_init = self.config.hydraulic.hk_m_day
        sy_init = self.config.hydraulic.sy
        thick_init = self.config.hydraulic.thick

        log_hk_init = np.log10(hk_init)

        x0_norm = [
            self._normalize(log_hk_init, log_hk_min, log_hk_max),
            self._normalize(sy_init, sy_min, sy_max),
            self._normalize(thick_init, thick_min, thick_max),
        ]

        result = minimize(
            self._objective,
            x0_norm,
            method="Nelder-Mead",
            options={
                "xatol": self.optim.xatol,
                "fatol": self.optim.fatol,
                "maxiter": self.optim.maxiter,
                "disp": True,
            },
        )

        best_log_hk = self._denormalize(result.x[0], log_hk_min, log_hk_max)
        best_hk = 10**best_log_hk
        best_sy = self._denormalize(result.x[1], sy_min, sy_max)
        best_thick = self._denormalize(result.x[2], thick_min, thick_max)

        final_model_name = f"final_optimized_hk{best_hk/24/3600:.2e}_sy{best_sy:.4f}_th{best_thick:.1f}"

        self.BV.hydraulic.update_hk(best_hk)
        self.BV.hydraulic.update_sy(best_sy)
        self.BV.hydraulic.update_thick(best_thick)
        self.BV.settings.update_model_name(final_model_name)

        end_time = datetime.datetime.now()
        duration = end_time - start_time

        optim_results = {
            "best_hk": best_hk,
            "best_hk_ms": best_hk / 24 / 3600,
            "best_log_hk": best_log_hk,
            "best_sy": best_sy,
            "best_thick": best_thick,
            "best_nse": None if self.best_record is None else self.best_record.get("nse"),
            "best_r_squared": None if self.best_record is None else self.best_record.get("r_squared"),
            "best_rmse": None if self.best_record is None else self.best_record.get("rmse"),
            "iterations": self.counter,
            "duration_seconds": duration.total_seconds(),
            "optimization_start": start_time.strftime("%Y-%m-%d %H:%M:%S"),
            "optimization_end": end_time.strftime("%Y-%m-%d %H:%M:%S"),
            "best_model": None if self.best_record is None else self.best_record.get("model_name"),
            "time_filter": {
                "enabled": self.optim.use_time_filter,
                "global_start": self.optim.calib_start_date,
                "global_end": self.optim.calib_end_date,
                "seasonal_filter": self.optim.use_seasonal_filter,
                "season_start": f"{self.optim.season_start_day}/{self.optim.season_start_month}",
                "season_end": f"{self.optim.season_end_day}/{self.optim.season_end_month}",
            },
        }

        results_file = os.path.join(
            self.optim_folder,
            f"optimization_results_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        )
        pd.DataFrame([optim_results]).to_csv(results_file, index=False)

        all_simulations_file = os.path.join(self.optim_folder, "all_simulations_results.csv")

        logging.info("=== RÉSULTATS DE L'OPTIMISATION ===")
        logging.info("Conductivité optimale: %.2e m/s (%.2e m/jour)", best_hk / 24 / 3600, best_hk)
        logging.info("Log(hk) optimal: %.4f", best_log_hk)
        logging.info("Sy optimal: %.4f", best_sy)
        logging.info("Épaisseur optimale: %.2f m", best_thick)

        return SimplexResult(
            best_hk_m_day=best_hk,
            best_hk_m_s=best_hk / 24 / 3600,
            best_log_hk=best_log_hk,
            best_sy=best_sy,
            best_thick=best_thick,
            best_nse=optim_results["best_nse"],
            best_r_squared=optim_results["best_r_squared"],
            best_rmse=optim_results["best_rmse"],
            iterations=self.counter,
            duration_seconds=duration.total_seconds(),
            best_model_name=final_model_name,
            results_file=results_file,
            all_simulations_file=all_simulations_file,
        )


def run_simplex_optimization(BV, dam_df: pd.DataFrame, config: ProjectConfig) -> SimplexResult | None:
    optimizer = SimplexOptimizer(BV, dam_df, config)
    return optimizer.run()
