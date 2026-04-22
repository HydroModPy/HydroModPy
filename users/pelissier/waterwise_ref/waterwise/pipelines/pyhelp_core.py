from __future__ import annotations

import argparse
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

EXTERNAL_DIR = Path(r"C:\Users\Pelissierm\Hydromodpy")
sys.path.insert(0, str(EXTERNAL_DIR))

from hydromodpy.pyhelp import bilan as HelpBilan
from hydromodpy.pyhelp.daily_output import calc_area_daily_avg
from hydromodpy.pyhelp.managers import HelpManager
from hydromodpy.tools import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ClimateInputs:
    precip: Path
    airtemp: Path
    solrad: Path


@dataclass(frozen=True)
class WorkflowFiles:
    workdir: Path
    grid: Path
    climate_input: ClimateInputs
    climate_backup: ClimateInputs | None = None

    @classmethod
    def from_workdir(
        cls,
        workdir: str | Path,
        climate_map: Mapping[str, str | Path] | None = None,
    ) -> "WorkflowFiles":
        wd = Path(workdir)
        if not wd.exists():
            raise FileNotFoundError(f"workdir not found: {wd}")

        grid = wd / "input_grid.csv"
        if not grid.exists():
            raise FileNotFoundError(f"Missing grid file: {grid}")

        climate = _resolve_primary_climate_inputs(wd, climate_map)
        _assert_climate_inputs_exist(climate)
        backup = _resolve_backup_climate_inputs(wd)
        return cls(workdir=wd, grid=grid, climate_input=climate, climate_backup=backup)


@dataclass(frozen=True)
class PyhelpExecution:
    helpm: HelpManager
    cellnames: object
    output_help: object
    used_backup: int


@dataclass(frozen=True)
class PyhelpOutputs:
    yearly_csv: Path
    daily_csv: Path | None
    surface_out: Path
    plots_dir: Path | None


@dataclass(frozen=True)
class PyhelpRunResult:
    files: WorkflowFiles
    execution: PyhelpExecution
    outputs: PyhelpOutputs


def _resolve_primary_climate_inputs(
    workdir: Path,
    climate_map: Mapping[str, str | Path] | None,
) -> ClimateInputs:
    if climate_map:
        return ClimateInputs(
            precip=Path(climate_map["precip_input"]),
            airtemp=Path(climate_map["airtemp_input"]),
            solrad=Path(climate_map["solrad_input"]),
        )
    return ClimateInputs(
        precip=workdir / "precip_input_data.csv",
        airtemp=workdir / "airtemp_input_data.csv",
        solrad=workdir / "solrad_input_data.csv",
    )


def _resolve_backup_climate_inputs(workdir: Path) -> ClimateInputs | None:
    backup = ClimateInputs(
        precip=workdir / "precip_input_data_backup.csv",
        airtemp=workdir / "airtemp_input_data_backup.csv",
        solrad=workdir / "solrad_input_data_backup.csv",
    )
    if all(path.exists() for path in (backup.precip, backup.airtemp, backup.solrad)):
        return backup
    return None


def _assert_climate_inputs_exist(climate: ClimateInputs) -> None:
    for path in (climate.precip, climate.airtemp, climate.solrad):
        if not path.exists():
            raise FileNotFoundError(f"Missing climate input: {path}")


def ensure_plots_dir(workdir: Path) -> Path:
    plot_dir = workdir / "plots_pyhelp"
    plot_dir.mkdir(parents=True, exist_ok=True)
    return plot_dir


def _temp_out_dir(workdir: Path) -> Path:
    return workdir / "help_input_files"


def _run_help_once(workdir: Path, grid: Path, climate: ClimateInputs) -> tuple[HelpManager, object, object]:
    helpm = HelpManager(
        str(workdir),
        path_to_grid=str(grid),
        path_to_precip=str(climate.precip),
        path_to_airtemp=str(climate.airtemp),
        path_to_solrad=str(climate.solrad),
    )
    cellnames = helpm.grid.index[helpm.grid["Bassin"] == 1]
    output_help = helpm.calc_help_cells(
        path_to_hdf5=str(workdir / "help_example.out"),
        cellnames=cellnames,
        tfsoil=-1,
        sf_edepth=1,
        sf_ulai=1,
        sf_cn=1,
    )
    return helpm, cellnames, output_help


def run_help_model(files: WorkflowFiles) -> PyhelpExecution:
    logger.info("Running PyHELP in workdir: %s", files.workdir)
    logger.info("pyhelp.bilan module resolved at %s", getattr(HelpBilan, "__file__", "unknown"))

    try:
        helpm, cellnames, output_help = _run_help_once(files.workdir, files.grid, files.climate_input)
        return PyhelpExecution(helpm=helpm, cellnames=cellnames, output_help=output_help, used_backup=0)
    except ValueError as exc:
        if files.climate_backup is None:
            raise
        logger.warning("Primary climate inputs failed (%s). Falling back to backup climate inputs.", exc)
        helpm, cellnames, output_help = _run_help_once(files.workdir, files.grid, files.climate_backup)
        return PyhelpExecution(helpm=helpm, cellnames=cellnames, output_help=output_help, used_backup=1)


def export_yearly_outputs(files: WorkflowFiles, execution: PyhelpExecution) -> Path:
    yearly_csv = files.workdir / "help_example_yearly.csv"
    execution.output_help.save_to_csv(str(yearly_csv))
    logger.info("Saved yearly outputs: %s", yearly_csv)
    return yearly_csv


def export_daily_outputs(files: WorkflowFiles, execution: PyhelpExecution) -> Path:
    logger.info("Calculating daily components (area mean)")
    df_daily_mean = calc_area_daily_avg(execution.cellnames, execution.helpm.workdir)
    out_daily = files.workdir / "help_example_daily_mean.csv"
    df_daily_mean.to_csv(out_daily, encoding="utf-8")
    logger.info("Saved daily mean: %s", out_daily)
    return out_daily


def export_surface_outputs(files: WorkflowFiles, execution: PyhelpExecution) -> Path:
    surface_out = files.workdir / "surf_example.out"
    execution.helpm.calc_surf_water_cells(
        cellnames=execution.cellnames,
        evp_surf=650,
        path_outfile=str(surface_out),
    )
    logger.info("Saved surface outputs: %s", surface_out)
    return surface_out


def export_builtin_plots(output_help, out_dir: Path, *, fig_title: str = "PyHELP results", ymax=None) -> None:
    try:
        output_help.plot_area_monthly_avg(fig_title=fig_title, figname=str(out_dir / "area_monthly_avg.png"))
        output_help.plot_area_yearly_avg(
            fig_title=fig_title,
            figname=str(out_dir / "area_yearly_avg.png"),
            ymax=ymax,
        )
        output_help.plot_area_yearly_series(
            fig_title=fig_title,
            figname=str(out_dir / "area_yearly_series.png"),
            ymax=ymax,
        )
    except AttributeError as exc:
        logger.warning("PyHELP built-in plots failed (Matplotlib/API change): %s", exc)
    except Exception:
        logger.exception("PyHELP built-in plots failed unexpectedly")


def cleanup_temporary_outputs(files: WorkflowFiles) -> None:
    shutil.rmtree(_temp_out_dir(files.workdir), ignore_errors=True)


def run_pyhelp_workflow(
    workdir: str | Path,
    climate_map: Mapping[str, str | Path] | None = None,
    *,
    fig_title: str = "PyHELP results",
    ymax=None,
    export_daily: bool = True,
    make_builtin_plots: bool = True,
) -> PyhelpRunResult:
    files = WorkflowFiles.from_workdir(workdir, climate_map=climate_map)
    execution = run_help_model(files)

    yearly_csv = export_yearly_outputs(files, execution)
    daily_csv = export_daily_outputs(files, execution) if export_daily else None
    plots_dir = None
    if make_builtin_plots:
        plots_dir = ensure_plots_dir(files.workdir)
        #export_builtin_plots(execution.output_help, plots_dir, fig_title=fig_title, ymax=ymax)
        logger.info("Saved built-in plots: %s", plots_dir)
    surface_out = export_surface_outputs(files, execution)
    cleanup_temporary_outputs(files)

    return PyhelpRunResult(
        files=files,
        execution=execution,
        outputs=PyhelpOutputs(
            yearly_csv=yearly_csv,
            daily_csv=daily_csv,
            surface_out=surface_out,
            plots_dir=plots_dir,
        ),
    )


def run_pyhelp(
    workdir: str | Path,
    climate_map: Mapping[str, str | Path] | None = None,
    *,
    fig_title: str = "PyHELP results",
    ymax=None,
    export_daily: bool = True,
):
    result = run_pyhelp_workflow(
        workdir,
        climate_map=climate_map,
        fig_title=fig_title,
        ymax=ymax,
        export_daily=export_daily,
        make_builtin_plots=True,
    )
    return 0, result.execution.used_backup


def _parse_args():
    parser = argparse.ArgumentParser(description="Run PyHELP workflow.")
    parser.add_argument("--workdir", default=None, help="Working directory containing HELP inputs")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    workdir = args.workdir or os.getenv("PYHELP_WORKDIR")
    if not workdir:
        raise RuntimeError("Working directory missing; set PYHELP_WORKDIR or pass --workdir.")
    exit_code, used_backup = run_pyhelp(workdir)
    logger.info("Workflow completed (used_backup_inputs=%s)", used_backup)
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
