"""PyHELP preprocessing functions:

1) build climate CSVs (or use ready ones)
    --> To be done : build from NetCDF files in DATA
        Right now, only ready ones are used
2) build/update grid CSV
3) run PyHELP
4) export rasterized NetCDF
"""

from pathlib import Path

from .config import PyhelpGridParams, PyhelpPreprocessingConfig
from .io import export_daily_outputs_to_netcdf, make_pyhelp_inputs
from .runner import run_help


def prepare_inputs(cfg):

    grid_csv = make_pyhelp_inputs(
        cfg.grid_ready if cfg.grid_ready is not None else cfg.grid_base,
        cfg.dem,
        cfg.shapefile,
        Path(cfg.workdir),
        nc_folder=cfg.nc_folder,
        ready_csvs=cfg.ready_csvs,
        grid_params=cfg.grid_params,
    )

    # Climatic inputs (attendus dans workdir)
    precip_csv = Path(cfg.workdir) / "pyhelp_precip_input_data.csv"
    airtemp_csv = Path(cfg.workdir) / "pyhelp_airtemp_input_data.csv"
    solrad_csv = Path(cfg.workdir) / "pyhelp_solrad_input_data.csv"

    return grid_csv, (precip_csv, airtemp_csv, solrad_csv)


def run_pyhelp(cfg, grid_csv, climate_csvs):
    precip_csv, airtemp_csv, solrad_csv = climate_csvs

    run_help(
        workdir=Path(cfg.workdir),
        grid_csv=Path(grid_csv),
        precip_csv=Path(precip_csv),
        airtemp_csv=Path(airtemp_csv),
        solrad_csv=Path(solrad_csv),
    )

    return Path(cfg.workdir)


def export_netcdf(cfg, grid_csv):
    return export_daily_outputs_to_netcdf(
        workdir=Path(cfg.workdir),
        outpath=Path(cfg.pyhelp_out_nc),
        grid_csv=Path(grid_csv),
        dem=Path(cfg.dem),
        compress_level=int(cfg.compress_level),
        clean_temp=True,
    )


def preprocess(cfg):
    grid_csv, climate_csvs = prepare_inputs(cfg)
    run_pyhelp(cfg, grid_csv, climate_csvs)
    return export_netcdf(cfg, grid_csv)


def preprocessing_pyhelp(
    *,
    workdir: str,
    pyhelp_out_nc: str,
    grid_ready: Path | None = None,
    grid_base: Path | None = None,
    dem: str | None = None,
    ready_climatic_csvs: list[str] | None = None,
    nc_folder: str | None = None,
    shapefile: str | None = None,
    grid_params=None,
    growth_start: int = 140,
    growth_end: int = 280,
    wind: float = 2.5,
    hum1: float = 60,
    hum2: float = 65,
    hum3: float = 70,
    hum4: float = 70,
    LAI: float = 2.4,
    EZD: float = 44.5,
    CN: float = 55,
    nlayer: int = 1,
    lay_type1: int = 1,
    thick1: float = 100,
    poro1: float = 0.45,
    fc1: float = 0.23,
    wp1: float = 0.116,
    ksat1: float = 0.0,
    dist_dr1: float = 50,
    slope1: float = 35,
    # test pour compatibilité
    main_py: str | None = None,
    help_cli: str | None = None,
    compress_level: int = 4,
):

    if grid_params is None:
        grid_params = PyhelpGridParams(
            growth_start=growth_start,
            growth_end=growth_end,
            wind=wind,
            hum1=hum1,
            hum2=hum2,
            hum3=hum3,
            hum4=hum4,
            LAI=LAI,
            EZD=EZD,
            CN=CN,
            nlayer=nlayer,
            lay_type1=lay_type1,
            thick1=thick1,
            poro1=poro1,
            fc1=fc1,
            wp1=wp1,
            ksat1=ksat1,
            dist_dr1=dist_dr1,
            slope1=slope1,
        )

    cfg = PyhelpPreprocessingConfig(
        workdir=workdir,
        pyhelp_out_nc=pyhelp_out_nc,
        grid_ready=grid_ready,
        grid_base=grid_base,
        dem=dem,
        shapefile=shapefile,
        ready_climatic_csvs=ready_climatic_csvs,
        nc_folder=nc_folder,
        grid_params=grid_params,
        compress_level=compress_level,
    )
    return preprocess(cfg)


preprocessing_pyhelp_netcdf = preprocessing_pyhelp
