"""Golden non-regression test for deterministic intermittency case outputs."""

from __future__ import annotations

import json
from pathlib import Path
import tomllib

import geopandas as gpd
import pandas as pd
import pytest

from hydromodpy.data_managers.intermittency.cases.run_intermittency_case import (
    run_intermittency_case_from_toml,
)


GOLDEN_FILE = (
    Path(__file__).resolve().parent / "golden" / "run_intermittency_case_golden.json"
)


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "hydromodpy").is_dir():
            return parent
    raise RuntimeError("Cannot locate repository root from test path")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=True)
        stream.write("\n")


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _dump_toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, list):
        return "[" + ", ".join(_dump_toml_value(item) for item in value) + "]"
    raise TypeError(f"Unsupported TOML value type: {type(value)}")


def _render_toml(payload: dict) -> str:
    lines = ["[intermittency_case]"]
    for key, value in payload["intermittency_case"].items():
        lines.append(f"{key} = {_dump_toml_value(value)}")
    lines.append("")
    return "\n".join(lines)


def _build_full_case_test_config(base_config_path: Path, tmp_path: Path) -> Path:
    with base_config_path.open("rb") as stream:
        payload = tomllib.load(stream)

    case_cfg = dict(payload.get("intermittency_case", {}))
    config_dir = base_config_path.parent

    intermittency_path = (config_dir / str(case_cfg["intermittency_path"])).resolve()
    out_path = (tmp_path / "outputs").resolve()

    case_cfg["intermittency_path"] = str(intermittency_path)
    case_cfg["out_path"] = str(out_path)
    case_cfg["watershed_mode"] = "square_mask"
    case_cfg["show_plot"] = False
    case_cfg["save_overview"] = True
    case_cfg["window_km"] = 40.0
    case_cfg["overview_max_stations"] = 10

    tmp_config_path = tmp_path / "run_intermittency_config_test.toml"
    tmp_config_path.write_text(
        _render_toml({"intermittency_case": case_cfg}),
        encoding="utf-8",
    )
    return tmp_config_path


def _normalize_col_token(value: object) -> str:
    text = str(value).strip().lower()
    return "".join(ch for ch in text if ch.isalnum())


def _resolve_required_column(
    available_columns: list[str],
    *,
    candidates: tuple[str, ...],
) -> str:
    candidate_map = {_normalize_col_token(col): col for col in available_columns}
    for candidate in candidates:
        key = _normalize_col_token(candidate)
        if key in candidate_map:
            return candidate_map[key]
    raise KeyError(f"Missing expected column in ONDE clip. candidates={candidates}")


def _resolve_onde_columns(available_columns: list[str]) -> dict[str, str]:
    return {
        "station_code": _resolve_required_column(
            available_columns,
            candidates=("<CdSiteHyd", "<CdSiteHyd>", "CdSiteHyd", "code_site"),
        ),
        "obs_date": _resolve_required_column(
            available_columns,
            candidates=("<DtRealObs", "<DtRealObs>", "DtRealObs", "date_obs"),
        ),
        "obs_label": _resolve_required_column(
            available_columns,
            candidates=("<LbRsObser", "<LbRsObser>", "LbRsObser", "observation_label"),
        ),
    }


def _dict_sorted_by_key(raw: dict) -> dict:
    return {str(key): raw[key] for key in sorted(raw, key=lambda item: str(item))}


def _build_sensitive_signature(summary: dict) -> dict:
    clip_path = Path(summary["onde_clip_path"])
    clip = gpd.read_file(clip_path)
    cols = _resolve_onde_columns(list(clip.columns))

    dates = pd.to_datetime(clip[cols["obs_date"]], errors="coerce")
    station_codes = (
        clip[cols["station_code"]]
        .dropna()
        .astype(str)
        .str.strip()
    )
    station_codes = station_codes[station_codes != ""]

    label_counts = (
        clip[cols["obs_label"]]
        .dropna()
        .astype(str)
        .str.strip()
        .value_counts()
        .to_dict()
    )

    label_to_code = {
        "Assec": 1,
        "Ecoulement non visible": 2,
        "Ecoulement visible faible": 3,
        "Ecoulement visible acceptable": 4,
        "Ecoulement visible": 5,
    }
    mapped_codes = clip[cols["obs_label"]].map(label_to_code)
    code_hist_raw = (
        mapped_codes.dropna()
        .astype(int)
        .value_counts()
        .to_dict()
    )

    station_obs_count = station_codes.value_counts().to_dict()

    figure_count = int(summary["figure_count"])
    station_plot_count = figure_count - 1 if bool(summary["overview_figure_saved"]) else figure_count

    return {
        "source_file_name": str(summary["source_file_name"]),
        "watershed_mode": str(summary["watershed_mode"]),
        "station_count": int(summary["station_count"]),
        "flowing_rows": int(summary["flowing_rows"]),
        "flowing_cols": int(summary["flowing_cols"]),
        "flowing_date_start": summary["flowing_date_start"],
        "flowing_date_end": summary["flowing_date_end"],
        "flow_code_min": summary["flow_code_min"],
        "flow_code_max": summary["flow_code_max"],
        "clip_row_count": int(len(clip)),
        "clip_station_unique": int(station_codes.nunique()),
        "clip_date_start": (
            dates.min().strftime("%Y-%m-%d") if dates.notna().any() else None
        ),
        "clip_date_end": (
            dates.max().strftime("%Y-%m-%d") if dates.notna().any() else None
        ),
        "obs_label_hist": _dict_sorted_by_key(label_counts),
        "obs_code_hist": _dict_sorted_by_key(code_hist_raw),
        "station_obs_count": _dict_sorted_by_key(station_obs_count),
        "overview_figure_saved": bool(summary["overview_figure_saved"]),
        "figure_count": figure_count,
        "station_plot_count": int(station_plot_count),
    }


@pytest.mark.slow
def test_run_intermittency_case_golden(update_goldens: bool, tmp_path: Path) -> None:
    """Check intermittency-case outputs stay stable on deterministic local input."""
    base_config_path = (
        _repo_root()
        / "hydromodpy"
        / "data_managers"
        / "intermittency"
        / "cases"
        / "run_intermittency_config.toml"
    )
    config_path = _build_full_case_test_config(base_config_path, tmp_path)

    actual = run_intermittency_case_from_toml(
        config_path,
        output_json=tmp_path / "intermittency_case_summary.json",
    )

    figures_dir = Path(actual["figures_dir"])
    assert figures_dir.exists()
    assert bool(actual["overview_figure_saved"]) is True
    assert (figures_dir / str(actual["overview_figure_name"])).exists()

    signature = _build_sensitive_signature(actual)
    assert int(signature["station_count"]) >= 2
    assert int(signature["clip_row_count"]) > 0
    assert int(signature["station_plot_count"]) == int(signature["station_count"])
    assert int(signature["figure_count"]) == int(signature["station_count"]) + 1

    if update_goldens:
        _write_json(GOLDEN_FILE, signature)
        return

    if not GOLDEN_FILE.exists():
        pytest.fail(
            f"Missing golden reference file: {GOLDEN_FILE}. "
            "Run tests with --update-goldens to generate it."
        )

    expected = _load_json(GOLDEN_FILE)
    assert signature == expected

