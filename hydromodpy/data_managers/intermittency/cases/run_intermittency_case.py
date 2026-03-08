"""Run a deterministic intermittency-only case from TOML configuration."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
import sys
import tomllib
from typing import Any

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
from shapely.geometry import box

# Support direct execution from file path and ensure local package precedence.
repo_root = Path(__file__).resolve().parents[4]
if (repo_root / "hydromodpy").exists() and str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from hydromodpy.data_managers.intermittency import Intermittency


@dataclass(slots=True)
class _GeographicStub:
    """Minimal geographic payload required by the Intermittency manager."""

    watershed_shp: str


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=True)
        stream.write("\n")


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        token = value.strip().lower()
        if token in {"1", "true", "yes", "on"}:
            return True
        if token in {"0", "false", "no", "off"}:
            return False
    return bool(default)


def _resolve_optional_path(config_toml: Path, value: Any) -> Path | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return (config_toml.parent / text).resolve()


def _remove_shapefile_family(path: Path) -> None:
    for suffix in (".shp", ".shx", ".dbf", ".prj", ".cpg", ".qmd"):
        candidate = path.with_suffix(suffix)
        if candidate.exists():
            candidate.unlink()


def _build_square_mask(
    *,
    out_path: Path,
    center_x: float,
    center_y: float,
    window_km: float,
    mask_crs: str,
) -> Path:
    support_dir = out_path / "results_stable" / "intermittency" / "_case_support"
    support_dir.mkdir(parents=True, exist_ok=True)
    mask_path = support_dir / "case_watershed_mask.shp"
    _remove_shapefile_family(mask_path)

    half_window_m = 1000.0 * float(window_km) / 2.0
    polygon = box(
        float(center_x) - half_window_m,
        float(center_y) - half_window_m,
        float(center_x) + half_window_m,
        float(center_y) + half_window_m,
    )
    gdf = gpd.GeoDataFrame({"case_id": [1]}, geometry=[polygon], crs=str(mask_crs))
    gdf.to_file(mask_path)
    return mask_path


def _load_case_config(config_toml: Path) -> dict[str, Any]:
    with config_toml.open("rb") as stream:
        raw = tomllib.load(stream)

    case_raw = dict(raw.get("intermittency_case", {}))

    intermittency_path = _resolve_optional_path(
        config_toml,
        case_raw.get("intermittency_path", "../../../../examples/launcher_data_overtiew/data"),
    )
    if intermittency_path is None:
        raise ValueError("intermittency_case.intermittency_path cannot be empty")

    out_path = _resolve_optional_path(config_toml, case_raw.get("out_path", "outputs"))
    if out_path is None:
        raise ValueError("intermittency_case.out_path cannot be empty")

    watershed_mode = str(case_raw.get("watershed_mode", "square_mask")).strip().lower()
    if watershed_mode not in {"square_mask", "existing_shp"}:
        raise ValueError(
            "intermittency_case.watershed_mode must be one of: square_mask, existing_shp"
        )

    return {
        "intermittency_path": intermittency_path,
        "file_name": str(case_raw.get("file_name", "regional onde stations.shp")),
        "out_path": out_path,
        "watershed_mode": watershed_mode,
        "watershed_shp": _resolve_optional_path(config_toml, case_raw.get("watershed_shp")),
        "center_x": float(case_raw.get("center_x", 265611.933)),
        "center_y": float(case_raw.get("center_y", 6784182.776)),
        "window_km": float(case_raw.get("window_km", 20.0)),
        "mask_crs": str(case_raw.get("mask_crs", "EPSG:2154")),
        "save_overview": _as_bool(case_raw.get("save_overview"), default=True),
        "show_plot": _as_bool(case_raw.get("show_plot"), default=False),
        "overview_max_stations": max(1, int(case_raw.get("overview_max_stations", 8))),
    }


def _create_overview_figure(
    flowing: pd.DataFrame,
    *,
    figure_path: Path,
    max_stations: int,
    show_plot: bool,
) -> bool:
    if flowing.empty:
        return False

    selected_codes = []
    for code in flowing.columns:
        if len(selected_codes) >= int(max_stations):
            break
        series = pd.to_numeric(flowing[code], errors="coerce")
        if series.notna().any():
            selected_codes.append(code)

    if not selected_codes:
        return False

    fig, ax = plt.subplots(1, 1, figsize=(10.0, 3.6), dpi=140)
    for code in selected_codes:
        series = pd.to_numeric(flowing[code], errors="coerce").dropna()
        if series.empty:
            continue
        ax.scatter(
            series.index,
            series.values,
            marker="|",
            s=55,
            linewidths=1.3,
            alpha=0.8,
            label=str(code),
        )

    ax.set_title("Intermittency observations (preview)")
    ax.set_yticks([1, 2, 3, 4, 5])
    ax.set_yticklabels(["Dry", "Invisible", "Low", "Acceptable", "Visible"])
    ax.set_ylim(0.5, 5.5)
    ax.grid(True, axis="x", alpha=0.25)
    if len(selected_codes) <= 12:
        ax.legend(loc="upper left", ncol=2, fontsize=7)
    fig.tight_layout()

    figure_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(figure_path, dpi=300, bbox_inches="tight", transparent=False)
    if show_plot:
        plt.show()
    plt.close(fig)
    return True


def run_intermittency_case_from_toml(
    config_toml: str | Path,
    *,
    output_json: str | Path | None = None,
) -> dict[str, Any]:
    """Run one intermittency case and return a compact deterministic summary."""
    config_path = Path(config_toml).expanduser().resolve()
    cfg = _load_case_config(config_path)

    if cfg["watershed_mode"] == "existing_shp":
        watershed_shp = cfg["watershed_shp"]
        if watershed_shp is None:
            raise ValueError(
                "intermittency_case.watershed_mode='existing_shp' requires intermittency_case.watershed_shp"
            )
    else:
        watershed_shp = _build_square_mask(
            out_path=cfg["out_path"],
            center_x=cfg["center_x"],
            center_y=cfg["center_y"],
            window_km=cfg["window_km"],
            mask_crs=cfg["mask_crs"],
        )

    if not watershed_shp.exists():
        raise FileNotFoundError(f"Watershed mask was not found: {watershed_shp}")

    geographic = _GeographicStub(watershed_shp=str(watershed_shp))
    intermittency = Intermittency(
        out_path=str(cfg["out_path"]),
        intermittency_path=str(cfg["intermittency_path"]),
        file_name=str(cfg["file_name"]),
        geographic=geographic,
    )

    onde_clip_raw = getattr(intermittency, "onde_clip", None)
    if onde_clip_raw is None:
        raise ValueError("Intermittency case failed before clipped ONDE output creation")

    onde_clip_path = Path(str(onde_clip_raw))
    if not onde_clip_path.exists():
        raise ValueError(f"Clipped ONDE shapefile was not created: {onde_clip_path}")

    figures_dir = Path(str(intermittency.fig_intermit))
    figures_dir.mkdir(parents=True, exist_ok=True)

    flowing = intermittency.flowing.copy()
    if not flowing.empty:
        flowing = flowing.sort_index()

    overview_path = figures_dir / "intermittency_case_overview.png"
    overview_saved = False
    if cfg["save_overview"]:
        overview_saved = _create_overview_figure(
            flowing,
            figure_path=overview_path,
            max_stations=cfg["overview_max_stations"],
            show_plot=cfg["show_plot"],
        )

    figure_names = sorted(path.name for path in figures_dir.glob("*.png"))

    station_codes = []
    for code in getattr(intermittency, "code_onde", []):
        if code is None:
            continue
        token = str(code).strip()
        if token and token not in station_codes:
            station_codes.append(token)

    flow_start = None
    flow_end = None
    flow_min = None
    flow_max = None
    if not flowing.empty:
        date_index = pd.to_datetime(flowing.index, errors="coerce")
        date_index = date_index[~date_index.isna()]
        if len(date_index) > 0:
            flow_start = date_index.min().strftime("%Y-%m-%d")
            flow_end = date_index.max().strftime("%Y-%m-%d")

        flat_values = pd.to_numeric(pd.Series(flowing.to_numpy().ravel()), errors="coerce").dropna()
        if not flat_values.empty:
            flow_min = int(flat_values.min())
            flow_max = int(flat_values.max())

    summary = {
        "intermittency_path_name": str(cfg["intermittency_path"].name),
        "source_file_name": str(cfg["file_name"]),
        "watershed_mode": str(cfg["watershed_mode"]),
        "watershed_shp_name": str(watershed_shp.name),
        "watershed_shp_path": str(watershed_shp),
        "onde_clip_name": str(onde_clip_path.name),
        "onde_clip_path": str(onde_clip_path),
        "station_count": int(len(station_codes)),
        "station_codes_preview": station_codes[:10],
        "flowing_rows": int(flowing.shape[0]),
        "flowing_cols": int(flowing.shape[1]),
        "flowing_date_start": flow_start,
        "flowing_date_end": flow_end,
        "flow_code_min": flow_min,
        "flow_code_max": flow_max,
        "figures_dir": str(figures_dir),
        "figure_count": int(len(figure_names)),
        "figure_preview": figure_names[:10],
        "overview_figure_name": str(overview_path.name if overview_saved else ""),
        "overview_figure_saved": bool(overview_saved),
    }

    if output_json is not None:
        _write_json(Path(output_json).expanduser().resolve(), summary)

    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a deterministic intermittency case from TOML and print a summary."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name("run_intermittency_config.toml"),
        help="Path to intermittency case TOML configuration.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Optional path to persist the summary JSON payload.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    summary = run_intermittency_case_from_toml(args.config, output_json=args.output_json)
    print(json.dumps(summary, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

