from pathlib import Path

from ..core.managers import HelpManager


def run_help(
    *,
    workdir: Path,
    grid_csv: Path,
    precip_csv: Path,
    airtemp_csv: Path,
    solrad_csv: Path,
    cellnames=None,
    tfsoil_c: float = -1.0,
    sf_edepth: float = 1.0,
    sf_ulai: float = 1.0,
    sf_cn: float = 1.0,
    build_help_input_files: bool = True,
    path_to_hdf5: Path | None = None,
):
    """Run PyHELP process using HelpManager."""
    hm = HelpManager(
        str(workdir),
        path_to_grid=str(grid_csv),
        path_to_precip=str(precip_csv),
        path_to_airtemp=str(airtemp_csv),
        path_to_solrad=str(solrad_csv),
    )
    return hm.calc_help_cells(
        path_to_hdf5=str(path_to_hdf5) if path_to_hdf5 else None,
        cellnames=cellnames,
        tfsoil=tfsoil_c,
        sf_edepth=sf_edepth,
        sf_ulai=sf_ulai,
        sf_cn=sf_cn,
        build_help_input_files=build_help_input_files,
    )
