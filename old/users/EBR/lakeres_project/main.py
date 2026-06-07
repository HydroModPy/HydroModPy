from __future__ import annotations

import argparse
import datetime
import logging
from dataclasses import dataclass

from .builders import (
    DamInputs,
    ModelOutputs,
    configure_model_settings,
    configure_reservoir,
    configure_streamflow,
    initialize_watershed,
    load_climate_to_watershed,
    load_dam_inputs,
    run_modflow_and_postprocess,
)
from .config import ProjectConfig, profile_common, profile_simplex
from .optimization import SimplexResult, run_simplex_optimization
from .plotting import plot_volume_comparison
from .runtime import RuntimeContext, configure_runtime


@dataclass
class ProjectResult:
    config: ProjectConfig
    runtime: RuntimeContext
    watershed: object
    climate_dataframe: object
    dam_inputs: DamInputs
    optimization: SimplexResult | None
    outputs: ModelOutputs


def run_project(config: ProjectConfig) -> ProjectResult:
    runtime = configure_runtime(config)

    BV = initialize_watershed(config, runtime.data_path, runtime.out_path)
    climate_df = load_climate_to_watershed(BV, config, runtime.data_path)
    dam_inputs = load_dam_inputs(BV, config, runtime.data_path, climate_df.index)

    configure_reservoir(BV, config, runtime.data_path, climate_df, dam_inputs)
    configure_streamflow(BV, config)
    configure_model_settings(BV, config)

    optimization_result = None
    if config.optimization.enabled:
        optimization_result = run_simplex_optimization(BV, dam_inputs.dataframe, config)

    start_time = datetime.datetime.now()
    logging.info("Début exécution Modflow: %s", start_time.strftime("%Y-%m-%d %H:%M"))

    outputs = run_modflow_and_postprocess(BV, config)

    end_time = datetime.datetime.now()
    logging.info("Fin exécution Modflow: %s", end_time.strftime("%Y-%m-%d %H:%M"))
    logging.info("Durée totale: %s", end_time - start_time)

    if config.runtime.make_volume_plot:
        plot_volume_comparison(
            dam_df=dam_inputs.dataframe,
            timeseries_df=outputs.timeseries_dataframe,
            simulations_folder=BV.simulations_folder,
            model_name=outputs.model_name,
            freq_input=config.general.freq_input,
            lake_id=config.reservoir.lake_id,
        )

    return ProjectResult(
        config=config,
        runtime=runtime,
        watershed=BV,
        climate_dataframe=climate_df,
        dam_inputs=dam_inputs,
        optimization=optimization_result,
        outputs=outputs,
    )


def run_common() -> ProjectResult:
    return run_project(profile_common())


def run_simplex() -> ProjectResult:
    return run_project(profile_simplex())


def _configure_basic_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lanceur LakeRes EBR")
    parser.add_argument(
        "--profile",
        choices=["common", "simplex"],
        default="common",
        help="Profil d'exécution",
    )
    return parser.parse_args()


def _main() -> None:
    _configure_basic_logging()
    args = _parse_args()

    if args.profile == "simplex":
        run_simplex()
    else:
        run_common()


if __name__ == "__main__":
    _main()
