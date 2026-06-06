"""Generic context artifact builder for catchment reports."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd

from hydromodpy.display.catchment_report.inputs import CatchmentReportInputs
from hydromodpy.display.catchment_report.resources import REPO_ROOT
from hydromodpy.display.catchment_report.semantic_artifacts import semantic_artifact_id
from hydromodpy.display.report_artifacts import (
    ReportArtifact,
    ReportArtifactManifest,
    ReportArtifactRequirement,
)

REPORT_ARTIFACT_MANIFEST_NAME = "report_artifact_manifest.json"


@dataclass(frozen=True)
class SeriesStats:
    rows: int
    start: str | None
    end: str | None
    mean: float | None
    minimum: float | None
    maximum: float | None

    @classmethod
    def from_frame(cls, frame: pd.DataFrame | None) -> SeriesStats:
        if frame is None or frame.empty:
            return cls(0, None, None, None, None, None)
        values = pd.to_numeric(frame["value"], errors="coerce")
        return cls(
            rows=int(len(frame)),
            start=str(frame["datetime"].min()),
            end=str(frame["datetime"].max()),
            mean=_finite_float(values.mean()),
            minimum=_finite_float(values.min()),
            maximum=_finite_float(values.max()),
        )


def build_context_from_report_config(config_path: Path) -> Path:
    """Build context JSON, context HTML and assets from a catchment report TOML."""
    inputs = CatchmentReportInputs.from_toml(config_path)
    return build_context(inputs)


def build_context(inputs: CatchmentReportInputs) -> Path:
    """Build the context artifacts consumed by ``build_catchment_report``."""
    context_dir = inputs.context_summary.parent
    assets_dir = inputs.context_assets
    web_dir = assets_dir.parent
    context_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    config = _load_resolved_toml(inputs.transient_config)
    simulated = _read_series(inputs.simulation_export)
    observed = (
        _read_series(inputs.observed_discharge_path)
        if inputs.observed_discharge_path is not None and inputs.observed_discharge_path.exists()
        else None
    )
    _write_timeseries(context_dir, simulated, observed)
    _plot_single_series(
        observed if observed is not None else simulated,
        assets_dir / "observed_discharge_full.png",
        title=f"{inputs.site_label} - chronique de debit observe",
    )
    _plot_window_series(
        observed,
        simulated,
        assets_dir / "forcing_window.png",
        title=f"{inputs.site_label} - fenetre de simulation",
    )
    _plot_window_series(
        observed,
        simulated,
        assets_dir / "baseline_discharge_comparison.png",
        title=f"{inputs.site_label} - debit simule de reference",
    )
    network_assets = _copy_network_assets(inputs.simulation_figures, assets_dir)
    parquet_dir = _simulation_parquet_dir(inputs)

    baseline = {
        "source_export": _rel(inputs.simulation_export),
        "simulation_name": inputs.simulation_name,
        "simulation_parquet": _rel(parquet_dir) if parquet_dir else None,
        "n_cells": _grid_cell_count(config),
        "n_timesteps": int(len(simulated)),
        "runtime_seconds": _read_runtime_seconds(parquet_dir),
        "figure_dir": _rel(inputs.simulation_figures),
        "reference_segments": _read_parquet_count(
            parquet_dir,
            "geographic_hydrographic_network_reference.parquet",
        ),
        "generated_segments": _read_parquet_count(
            parquet_dir,
            "geographic_hydrographic_network_generated.parquet",
        ),
    }
    summary = {
        "title": f"{inputs.site_label} catchment context",
        "configuration": _configuration_summary(config, inputs),
        "stats": {
            "observed_discharge": SeriesStats.from_frame(observed).__dict__,
            "baseline_simulated_discharge": SeriesStats.from_frame(simulated).__dict__,
        },
        "baseline_run": baseline,
        "network": baseline,
        "outputs": {
            "observed_discharge": _rel(context_dir / "observed_discharge.csv")
            if observed is not None
            else None,
            "baseline_simulated_discharge": _rel(context_dir / "baseline_simulated_discharge.csv"),
        },
        "network_assets": network_assets,
    }
    inputs.context_summary.write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_context_html(web_dir, inputs, summary)
    _write_context_artifact_manifest(
        inputs,
        context_summary=inputs.context_summary,
        context_html=web_dir / "index.html",
        network_assets=network_assets,
    )
    return inputs.context_summary


def context_artifact_manifest_path(inputs: CatchmentReportInputs) -> Path:
    return inputs.context_outputs_dir / REPORT_ARTIFACT_MANIFEST_NAME


def _write_context_artifact_manifest(
    inputs: CatchmentReportInputs,
    *,
    context_summary: Path,
    context_html: Path,
    network_assets: Mapping[str, str],
) -> Path:
    assets_dir = inputs.context_assets
    figure_paths: dict[str, Path | None] = {
        "observed_discharge_full": assets_dir / "observed_discharge_full.png",
        "forcing_window": assets_dir / "forcing_window.png",
        "baseline_discharge_comparison": assets_dir / "baseline_discharge_comparison.png",
        "network_reference": _network_asset_path(
            assets_dir,
            network_assets,
            "hydrographic_network_reference",
        ),
        "network_generated": _network_asset_path(
            assets_dir,
            network_assets,
            "hydrographic_network_generated",
        ),
        "network_comparison": _network_asset_path(
            assets_dir,
            network_assets,
            "hydrographic_network_comparison",
        ),
        "network_missing": _network_asset_path(
            assets_dir,
            network_assets,
            "hydrographic_network_reference_missing_only",
        ),
        "network_extra": _network_asset_path(
            assets_dir,
            network_assets,
            "hydrographic_network_generated_extra_only",
        ),
    }
    requirements = (
        ReportArtifactRequirement(
            "context.summary",
            kind="json",
            required=True,
            title="Resume contexte bassin",
            producer="catchment.context",
        ),
        ReportArtifactRequirement(
            "context.html",
            kind="html",
            required=False,
            title="Page HTML contexte",
            producer="catchment.context",
        ),
        *(
            ReportArtifactRequirement(
                semantic_artifact_id(figure_id),
                kind="figure",
                required=_context_figure_is_required(figure_id),
                title=figure_id,
                producer="catchment.context",
                metadata={"display_figure": figure_id},
            )
            for figure_id in figure_paths
        ),
    )
    paths_by_id = {
        "context.summary": context_summary,
        "context.html": context_html,
        **{
            semantic_artifact_id(figure_id): path
            for figure_id, path in figure_paths.items()
        },
    }
    manifest = ReportArtifactManifest(
        profile="catchment_gauged",
        requirements=requirements,
        artifacts=tuple(
            ReportArtifact.from_requirement(
                requirement,
                path=paths_by_id.get(requirement.artifact_id),
            )
            for requirement in requirements
        ),
        metadata={
            "artifact_scope": "catchment.context",
            "site_label": inputs.site_label,
            "context_outputs_dir": _rel(inputs.context_outputs_dir),
        },
    )
    return manifest.write_json(
        context_artifact_manifest_path(inputs),
        base_dir=REPO_ROOT,
    )


def _context_figure_is_required(figure_id: str) -> bool:
    return figure_id in {
        "observed_discharge_full",
        "forcing_window",
        "baseline_discharge_comparison",
    }


def _network_asset_path(
    assets_dir: Path,
    network_assets: Mapping[str, str],
    asset_key: str,
) -> Path | None:
    value = network_assets.get(asset_key)
    if not value:
        return None
    return assets_dir / Path(value).name


def _load_resolved_toml(path: Path) -> dict[str, Any]:
    path = Path(path).resolve()
    payload = _load_toml(path)
    base_name = payload.get("base_config")
    if not base_name:
        return payload
    base_path = Path(str(base_name))
    if not base_path.is_absolute():
        base_path = path.parent / base_path
    base_payload = _load_resolved_toml(base_path)
    return _deep_merge(base_payload, payload)


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _deep_merge(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _configuration_summary(
    config: Mapping[str, Any],
    inputs: CatchmentReportInputs,
) -> dict[str, Any]:
    geographic = _mapping(config.get("geographic"))
    catchment = _mapping(geographic.get("catchment"))
    simulation = _mapping(config.get("simulation"))
    time = _mapping(simulation.get("time"))
    flow = _mapping(config.get("flow"))
    domain = _mapping(config.get("domain"))
    depth = _mapping(domain.get("depth_model"))
    data = _mapping(config.get("data"))
    return {
        "base_config": _rel(inputs.transient_config),
        "dem": str(catchment.get("dem_init_path") or ""),
        "x_outlet": catchment.get("x_outlet"),
        "y_outlet": catchment.get("y_outlet"),
        "crs": geographic.get("crs_project"),
        "start_datetime": time.get("start_datetime"),
        "end_datetime": time.get("end_datetime"),
        "step_value": time.get("step_value"),
        "K": _nested(flow, ("param", "K", "field", "value")),
        "Sy": _nested(flow, ("param", "Sy", "field", "value")),
        "Ss": _nested(flow, ("param", "Ss", "field", "value")),
        "thickness": depth.get("thickness"),
        "drainage": _nested(flow, ("bc", "cauchy", "drainage", "value")),
        "configured_recharge_station_ids": _configured_station_ids(data, "recharge"),
        "configured_runoff_station_ids": _configured_station_ids(data, "runoff"),
        "configured_hydrometry_station_ids": _configured_station_ids(data, "hydrometry"),
        "observed_discharge_station_id": inputs.observed_discharge_station_id,
        "network_threshold_area_km2": _nested(
            geographic,
            ("river_network", "threshold_area_km2"),
        ),
    }


def _configured_station_ids(data: Mapping[str, Any], family: str) -> list[str]:
    section = _mapping(data.get(family))
    ids: list[str] = []
    for source in section.get("sources", []) or []:
        if isinstance(source, Mapping):
            ids.extend(str(item) for item in source.get("station_ids", []) or [])
    return ids


def _grid_cell_count(config: Mapping[str, Any]) -> int | None:
    nx = _nested(config, ("modflownwt", "sgrid", "planar", "nx"))
    ny = _nested(config, ("modflownwt", "sgrid", "planar", "ny"))
    try:
        return int(nx) * int(ny)
    except (TypeError, ValueError):
        return None


def _read_series(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["datetime"] = pd.to_datetime(
        frame["datetime"],
        errors="coerce",
        utc=True,
        format="mixed",
    ).dt.tz_convert(None)
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    return frame.dropna(subset=["datetime", "value"]).sort_values("datetime")


def _write_timeseries(
    context_dir: Path,
    simulated: pd.DataFrame,
    observed: pd.DataFrame | None,
) -> None:
    if observed is not None:
        observed.to_csv(context_dir / "observed_discharge.csv", index=False)
    simulated.to_csv(context_dir / "baseline_simulated_discharge.csv", index=False)


def _plot_single_series(frame: pd.DataFrame, output_path: Path, *, title: str) -> None:
    fig, ax = plt.subplots(figsize=(12, 4.2))
    ax.plot(frame["datetime"], frame["value"], color="#2563eb", linewidth=1.4)
    ax.set_title(title)
    ax.set_ylabel("Q (m3/s)")
    ax.grid(True, color="#d1d5db", linewidth=0.6, alpha=0.8)
    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)


def _plot_window_series(
    observed: pd.DataFrame | None,
    simulated: pd.DataFrame,
    output_path: Path,
    *,
    title: str,
) -> None:
    fig, ax = plt.subplots(figsize=(12, 4.2))
    if observed is not None and not observed.empty:
        ax.plot(
            observed["datetime"],
            observed["value"],
            color="#0f766e",
            linewidth=1.0,
            label="Observe",
        )
    ax.plot(
        simulated["datetime"],
        simulated["value"],
        color="#2563eb",
        linewidth=1.4,
        label="Simule",
    )
    ax.set_title(title)
    ax.set_ylabel("Q (m3/s)")
    ax.grid(True, color="#d1d5db", linewidth=0.6, alpha=0.8)
    ax.legend(loc="upper right", fontsize=11, framealpha=0.92)
    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)


def _copy_network_assets(source_dir: Path, assets_dir: Path) -> dict[str, str]:
    names = [
        "hydrographic_network_reference.png",
        "hydrographic_network_generated.png",
        "hydrographic_network_comparison.png",
        "hydrographic_network_reference_missing_only.png",
        "hydrographic_network_generated_extra_only.png",
    ]
    copied: dict[str, str] = {}
    for name in names:
        source = source_dir / name
        if not source.exists():
            continue
        target = assets_dir / name
        shutil.copy2(source, target)
        copied[name.removesuffix(".png")] = f"assets/{name}"
    return copied


def _simulation_parquet_dir(inputs: CatchmentReportInputs) -> Path | None:
    candidates = [
        path
        for path in inputs.dem_network_root.glob(f"*__{inputs.simulation_name}__*.parquet")
        if path.is_dir() and (path / "timeseries.parquet").exists()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _read_parquet_count(parquet_dir: Path | None, file_name: str) -> int | None:
    if parquet_dir is None:
        return None
    file_path = parquet_dir / file_name
    if not file_path.exists():
        return None
    try:
        import duckdb
    except ImportError:
        return None
    query_path = file_path.as_posix().replace("'", "''")
    try:
        with duckdb.connect() as con:
            return int(
                con.execute(f"select count(*) from read_parquet('{query_path}')").fetchone()[0]
            )
    except Exception:
        return None


def _read_runtime_seconds(parquet_dir: Path | None) -> float | None:
    if parquet_dir is None:
        return None
    file_path = parquet_dir / "metrics.parquet"
    if not file_path.exists():
        return None
    try:
        import duckdb
    except ImportError:
        return None
    query_path = file_path.as_posix().replace("'", "''")
    try:
        with duckdb.connect() as con:
            result = con.execute(
                "select value from read_parquet(?) "
                "where metric_name = 'flow_solve_time_seconds' limit 1",
                [query_path],
            ).fetchone()
    except Exception:
        return None
    if result is None:
        return None
    return _finite_float(result[0])


def _read_provenance_n_records(parquet_dir: Path | None, variable: str) -> int | None:
    if parquet_dir is None:
        return None
    file_path = parquet_dir / "provenance.parquet"
    if not file_path.exists():
        return None
    try:
        import duckdb
    except ImportError:
        return None
    query_path = file_path.as_posix().replace("'", "''")
    try:
        with duckdb.connect() as con:
            result = con.execute(
                f"select n_records from read_parquet('{query_path}') where variable = ? limit 1",
                [variable],
            ).fetchone()
    except Exception:
        return None
    if result is None:
        return None
    return int(result[0])


def _write_context_html(
    web_dir: Path,
    inputs: CatchmentReportInputs,
    summary: Mapping[str, Any],
) -> None:
    web_dir.mkdir(parents=True, exist_ok=True)
    baseline = _mapping(summary.get("baseline_run"))
    html = f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <title>{inputs.site_label} - contexte</title>
</head>
<body>
  <h1>{inputs.site_label} - contexte</h1>
  <p>Simulation: <code>{baseline.get("simulation_name", "")}</code></p>
  <p>Export: <code>{baseline.get("source_export", "")}</code></p>
  <p>Figures: <code>{baseline.get("figure_dir", "")}</code></p>
</body>
</html>
"""
    (web_dir / "index.html").write_text(html, encoding="utf-8")


def _nested(mapping: Mapping[str, Any], keys: tuple[str, ...]) -> Any:
    value: Any = mapping
    for key in keys:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _rel(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-config", type=Path, required=True)
    args = parser.parse_args(argv)
    summary_path = build_context_from_report_config(args.report_config)
    print(summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
