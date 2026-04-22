import shutil
from pathlib import Path

import pandas as pd

from waterwise.pipelines.climate_debias_ import debias_climate


PYHELP_GRID_FILENAME = "input_grid.csv"


def ensure_grid(src_ref_results: Path, dst_workdir: Path) -> Path:
    dst_workdir.mkdir(parents=True, exist_ok=True)
    src_grid = src_ref_results / PYHELP_GRID_FILENAME
    if not src_grid.exists():
        raise FileNotFoundError(f"Missing reference grid: {src_grid}")
    dst_grid = dst_workdir / PYHELP_GRID_FILENAME
    if not dst_grid.exists():
        shutil.copy2(src_grid, dst_grid)
    return dst_grid


def prepare_projection_climate(site_id, hist_dir, proj_clim_dir, out_model, clean_func):
    out_model.mkdir(parents=True, exist_ok=True)
    clean_func(proj_clim_dir / "precip_input_data_prediction.csv", out_model / "precip_input_data.csv")
    clean_func(proj_clim_dir / "airtemp_input_data_prediction.csv", out_model / "airtemp_input_data.csv")
    clean_func(proj_clim_dir / "solrad_input_data_prediction.csv", out_model / "solrad_input_data.csv")
    
    #debias_climate(site_id=site_id, )

def clean_pyhelp_csv(src: Path, dst: Path) -> None:
    lines = src.read_text(encoding="utf-8", errors="ignore").splitlines()
    lines = [ln for ln in lines if ln.strip()]
    if lines and lines[0].startswith(",0,1,2"):
        lines = lines[1:]
    if len(lines) < 2:
        raise ValueError(f"Unexpected CSV content in {src}")

    out_lines = [lines[0], lines[1]]
    for ln in lines[2:]:
        parts = ln.split(",")
        if not parts:
            continue
        date_str = parts[0].strip()
        if not date_str:
            continue
        try:
            dt = pd.to_datetime(date_str, format="mixed", dayfirst=True, errors="raise")
        except TypeError:
            dt = pd.to_datetime(date_str, dayfirst=True, errors="raise")
        parts[0] = dt.strftime("%d/%m/%Y")
        out_lines.append(",".join(parts))

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    


def filter_prediction_climate(climate_file, start_year = 2015, end_year = 2100, output_file = None):
    climate_file = Path(climate_file)
    df = pd.read_csv(climate_file)
    first_col = df.columns[0]

    parsed_dates = pd.to_datetime(df[first_col], dayfirst=True, errors="coerce")

    keep_mask = parsed_dates.isna() | (
        (parsed_dates.dt.year >= start_year) &
        (parsed_dates.dt.year <= end_year)
    )

    df_filtered = df.loc[keep_mask].copy()

    out = Path(output_file) if output_file else climate_file
    df_filtered.to_csv(out, index=False)

    return out