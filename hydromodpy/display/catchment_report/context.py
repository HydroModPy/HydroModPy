"""Generic context artifact builder for catchment reports."""

from __future__ import annotations

import json
import math
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hydromodpy.core.config_kit.root import RootConfig

import matplotlib.pyplot as plt
import pandas as pd

from hydromodpy.core.logging import get_logger
from hydromodpy.core.toml_io.loader import load_toml_with_base_config
from hydromodpy.display.catchment_report.artifacts import rel
from hydromodpy.display.catchment_report.inputs import CatchmentReportInputs
from hydromodpy.display.catchment_report.simulation_source import (
    open_simulation_run,
    read_simulated_discharge,
    simulation_parquet_dir,
)
from hydromodpy.results.catalog.listing import SEALED_SOLVE_METRIC, solve_seconds

logger = get_logger(__name__)


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


def build_context_from_report_config(config_path: Path, *, root: RootConfig | None) -> Path:
    """Build context JSON, context HTML and assets from a catchment report TOML."""
    inputs = CatchmentReportInputs.from_toml(config_path, root=root)
    return build_context(inputs, root=root)


def build_context(inputs: CatchmentReportInputs, *, root: RootConfig | None) -> Path:
    """Build the context artifacts consumed by ``build_catchment_report``.

    They land under ``report/context/`` of the run the report describes. The
    caller passes the ``RootConfig`` it holds, or ``None`` for a report read
    outside a session, which reads the configuration as it is written.
    """
    context_dir = inputs.context_dir
    assets_dir = inputs.context_assets
    web_dir = assets_dir.parent
    context_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    config = load_toml_with_base_config(inputs.transient_config, root=root)
    with open_simulation_run(inputs) as store:
        simulated = read_simulated_discharge(store, station=inputs.observed_discharge_station_id)
        parquet_dir = simulation_parquet_dir(store)
        n_cells = store.facts.n_cells
    observed = _observed_series(inputs.observed_discharge_path)
    _write_timeseries(context_dir, simulated, observed)
    _plot_single_series(
        observed if observed is not None else simulated,
        assets_dir / "observed_discharge_full.png",
        title=f"{inputs.site_label} - observed discharge series",
    )
    _plot_window_series(
        observed,
        simulated,
        assets_dir / "forcing_window.png",
        title=f"{inputs.site_label} - simulation window",
    )
    _plot_window_series(
        observed,
        simulated,
        assets_dir / "baseline_discharge_comparison.png",
        title=f"{inputs.site_label} - reference simulated discharge",
    )
    network_assets = _copy_network_assets(inputs.simulation_figures, assets_dir)

    baseline = {
        "source_export": _rel(parquet_dir / "timeseries.parquet") if parquet_dir else None,
        "simulation_name": inputs.simulation_name,
        "simulation_parquet": _rel(parquet_dir) if parquet_dir else None,
        "n_cells": n_cells,
        "n_timesteps": int(len(simulated)),
        "runtime_seconds": _read_runtime_seconds(inputs.run_dir, parquet_dir),
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
    return inputs.context_summary


def _observed_series(path: Path | None) -> pd.DataFrame | None:
    """Read the observed discharge, or say why the report goes without it."""
    if path is None:
        return None
    if not path.exists():
        logger.warning(
            "Catchment report: observed discharge file %s not found; "
            "the report shows the simulation alone.",
            path,
        )
        return None
    return _read_series(path)


def _resolve_dem_summary_path(
    config: Mapping[str, Any],
    inputs: CatchmentReportInputs,
) -> str:
    run_dir = inputs.transient_config.parent
    inputs_json = run_dir / "inputs.json"
    if inputs_json.is_file():
        try:
            payload = json.loads(inputs_json.read_text(encoding="utf-8"))
            for entry in payload.get("inputs", ()):
                if entry.get("variable") == "dem" or entry.get("role") == "dem":
                    return str(entry.get("path") or "")
        except Exception:
            pass
    data = _mapping(config.get("data"))
    dem_cfg = _mapping(data.get("dem"))
    sources = dem_cfg.get("sources")
    if isinstance(sources, Sequence) and sources:
        first = _mapping(sources[0])
        return str(first.get("path") or "")
    catchment = _mapping(_mapping(config.get("geographic")).get("catchment"))
    return str(catchment.get("dem_init_path") or "")


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
        "dem": _resolve_dem_summary_path(config, inputs),
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
        "drainage": _nested(flow, ("bc", "drainage", "value")),
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


def _read_series(path: Path) -> pd.DataFrame:
    """Read an observed discharge CSV (``datetime`` / ``value`` columns)."""
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
            label="Observed",
        )
    ax.plot(
        simulated["datetime"],
        simulated["value"],
        color="#2563eb",
        linewidth=1.4,
        label="Simulated",
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


def _parquet_scalar(parquet_dir: Path | None, file_name: str, sql: str) -> Any:
    """Return the first value ``sql`` reads from one Parquet file, or None.

    ``sql`` names the file as its first parameter. A missing file, a file
    DuckDB cannot read or an empty answer all give None: the summary then
    leaves the number out.
    """
    if parquet_dir is None:
        return None
    file_path = parquet_dir / file_name
    if not file_path.exists():
        return None
    import duckdb

    try:
        with duckdb.connect() as con:
            row = con.execute(sql, [file_path.as_posix()]).fetchone()
    except duckdb.Error:
        return None
    return None if row is None else row[0]


def _read_parquet_count(parquet_dir: Path | None, file_name: str) -> int | None:
    count = _parquet_scalar(parquet_dir, file_name, "select count(*) from read_parquet(?)")
    return None if count is None else int(count)


def _read_runtime_seconds(run_dir: Path, parquet_dir: Path | None) -> float | None:
    """Return the wall time of the flow solve, from ``profile.json`` first.

    A run of HydroModPy 2.0 has no profile and holds the time as a row of its
    ``metrics.parquet``, which is the floor of the reading.
    """
    measured = solve_seconds(run_dir)
    if measured is not None:
        return measured
    return _finite_float(
        _parquet_scalar(
            parquet_dir,
            "metrics.parquet",
            "select value from read_parquet(?) "
            f"where metric_name = '{SEALED_SOLVE_METRIC}' limit 1",
        )
    )


def _write_context_html(
    web_dir: Path,
    inputs: CatchmentReportInputs,
    summary: Mapping[str, Any],
) -> None:
    web_dir.mkdir(parents=True, exist_ok=True)
    baseline = _mapping(summary.get("baseline_run"))
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{inputs.site_label} - context</title>
</head>
<body>
  <h1>{inputs.site_label} - context</h1>
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
    return None if path is None else rel(path)
