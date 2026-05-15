"""Build a pre-calibration context package for the gauged Nancon case."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
DATA_ROOT = REPO_ROOT / "examples" / "data"
NANCON_PROJECT = REPO_ROOT / "examples" / "projects" / "02_nancon_watershed"


@dataclass(frozen=True)
class SeriesStats:
    rows: int
    start: str | None
    end: str | None
    mean: float | None
    minimum: float | None
    maximum: float | None

    @classmethod
    def from_frame(cls, frame: pd.DataFrame) -> SeriesStats:
        if frame.empty:
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


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _read_series(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["datetime"] = pd.to_datetime(
        frame["datetime"], errors="coerce", utc=True, format="mixed"
    ).dt.tz_convert(None)
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    return frame.dropna(subset=["datetime", "value"]).sort_values("datetime")


def _load_project_config(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _configured_station_ids(config: dict[str, Any], family: str) -> list[str]:
    data = config.get("data", {})
    section = data.get(family, {})
    sources = section.get("sources", [])
    ids: list[str] = []
    for source in sources:
        ids.extend(str(item) for item in source.get("station_ids", []) or [])
    return ids


def _latest_network_figure_dir(project_dir: Path) -> Path | None:
    figures_root = project_dir / "figures"
    if not figures_root.exists():
        return None
    required = {
        "hydrographic_network_reference.png",
        "hydrographic_network_generated.png",
        "hydrographic_network_comparison.png",
    }
    candidates: list[Path] = []
    for folder in figures_root.glob("run_*"):
        if folder.is_dir() and required.issubset({item.name for item in folder.iterdir()}):
            candidates.append(folder)
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _latest_simulation_parquet_dir(project_dir: Path) -> Path | None:
    simulations = project_dir / "simulations"
    if not simulations.exists():
        return None
    candidates = [
        path
        for path in simulations.glob("*.parquet")
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


def _copy_network_assets(source_dir: Path | None, assets_dir: Path) -> dict[str, str]:
    names = [
        "hydrographic_network_reference.png",
        "hydrographic_network_generated.png",
        "hydrographic_network_comparison.png",
        "hydrographic_network_reference_missing_only.png",
        "hydrographic_network_generated_extra_only.png",
    ]
    copied: dict[str, str] = {}
    if source_dir is None:
        return copied
    for name in names:
        source = source_dir / name
        if not source.exists():
            continue
        target = assets_dir / name
        shutil.copy2(source, target)
        copied[name.removesuffix(".png")] = f"assets/{name}"
    return copied


def _write_timeseries_outputs(
    context_dir: Path,
    observed: pd.DataFrame,
    forcing_frames: dict[str, pd.DataFrame],
    simulated: pd.DataFrame | None,
) -> dict[str, str]:
    observed_out = context_dir / "observed_discharge_daily.csv"
    observed.assign(station_id="NANCON", variable="discharge", unit="m3/s").to_csv(
        observed_out,
        index=False,
    )

    forcing_rows: list[pd.DataFrame] = []
    for label, frame in forcing_frames.items():
        variable, station_id = label.split(":", maxsplit=1)
        forcing_rows.append(
            frame.assign(variable=variable, station_id=station_id, unit="mm/day")[
                ["datetime", "station_id", "variable", "value", "unit"]
            ]
        )
    forcing_out = context_dir / "forcings_monthly.csv"
    pd.concat(forcing_rows, ignore_index=True).sort_values(
        ["variable", "station_id", "datetime"]
    ).to_csv(forcing_out, index=False)

    outputs = {
        "observed_discharge_daily": str(observed_out.relative_to(SCRIPT_DIR)),
        "forcings_monthly": str(forcing_out.relative_to(SCRIPT_DIR)),
    }
    if simulated is not None:
        simulated_out = context_dir / "baseline_simulated_discharge.csv"
        simulated.to_csv(simulated_out, index=False)
        outputs["baseline_simulated_discharge"] = str(simulated_out.relative_to(SCRIPT_DIR))
    return outputs


def _plot_full_observed(observed: pd.DataFrame, output_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(12, 4.2))
    ax.plot(observed["datetime"], observed["value"], color="#2563eb", linewidth=0.8)
    ax.axvspan(
        pd.Timestamp("2000-01-01"),
        pd.Timestamp("2002-12-31"),
        color="#f59e0b",
        alpha=0.16,
        label="Fenetre simulation 2000-2002",
    )
    ax.set_title("Debit observe Nancon, chronique complete")
    ax.set_ylabel("Q (m3/s)")
    ax.grid(True, color="#d1d5db", linewidth=0.6, alpha=0.8)
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)


def _plot_window_forcing(
    observed: pd.DataFrame,
    forcing_frames: dict[str, pd.DataFrame],
    output_path: Path,
) -> None:
    window = observed[
        (observed["datetime"] >= pd.Timestamp("2000-01-01"))
        & (observed["datetime"] <= pd.Timestamp("2002-12-31"))
    ].copy()
    monthly_obs = window.set_index("datetime")["value"].resample("ME").mean().rename("Q observe")
    fig, axes = plt.subplots(2, 1, figsize=(12, 6), sharex=True)
    axes[0].plot(window["datetime"], window["value"], color="#94a3b8", linewidth=0.6, alpha=0.8)
    axes[0].plot(monthly_obs.index, monthly_obs.values, color="#dc2626", linewidth=2.0)
    axes[0].set_ylabel("Q (m3/s)")
    axes[0].set_title("Debit observe sur la fenetre de simulation")
    axes[0].grid(True, color="#d1d5db", linewidth=0.6, alpha=0.8)

    colors = {
        "recharge:EX04": "#2563eb",
        "recharge:NANCON": "#0f766e",
        "runoff:EX04": "#f97316",
        "runoff:NANCON": "#a855f7",
    }
    for label, frame in forcing_frames.items():
        axes[1].plot(
            frame["datetime"],
            frame["value"],
            marker="o",
            linewidth=1.8,
            markersize=3.5,
            color=colors.get(label, "#334155"),
            label=label.replace(":", " "),
        )
    axes[1].set_ylabel("mm/day")
    axes[1].set_title("Recharge et runoff disponibles")
    axes[1].grid(True, color="#d1d5db", linewidth=0.6, alpha=0.8)
    axes[1].legend(ncols=2, loc="upper right")
    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)


def _plot_baseline_comparison(
    observed: pd.DataFrame,
    simulated: pd.DataFrame | None,
    output_path: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(12, 4.4))
    window = observed[
        (observed["datetime"] >= pd.Timestamp("2000-01-01"))
        & (observed["datetime"] <= pd.Timestamp("2003-01-01"))
    ].copy()
    monthly_obs = window.set_index("datetime")["value"].resample("ME").mean()
    ax.plot(
        window["datetime"],
        window["value"],
        color="#cbd5e1",
        linewidth=0.6,
        label="observe journalier",
    )
    ax.plot(
        monthly_obs.index,
        monthly_obs.values,
        color="#111827",
        linewidth=2.0,
        label="observe mensuel",
    )
    if simulated is not None and not simulated.empty:
        ax.plot(
            simulated["datetime"],
            simulated["value"],
            color="#dc2626",
            linewidth=2.2,
            label="simulation de preparation non calibree",
        )
    ax.set_title("Debit observe et debit simule non calibre")
    ax.set_ylabel("Q (m3/s)")
    ax.grid(True, color="#d1d5db", linewidth=0.6, alpha=0.8)
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)


def _html_metric(label: str, value: Any, unit: str = "") -> str:
    if value is None:
        shown = "n/a"
    elif isinstance(value, float):
        shown = f"{value:.4g}"
    else:
        shown = str(value)
    suffix = f" {unit}" if unit else ""
    return f"<div class='metric'><span>{label}</span><strong>{shown}{suffix}</strong></div>"


def _write_html(
    web_dir: Path,
    summary: dict[str, Any],
    assets: dict[str, str],
) -> None:
    stats = summary["stats"]
    config = summary["configuration"]
    network = summary["network"]
    baseline = summary["baseline_run"]
    simulation_window = f"{config['start_datetime']} a {config['end_datetime']}"
    data_note = (
        "La configuration historique utilise EX04 pour recharge/runoff, tandis que "
        "des fichiers NANCON dedies existent aussi. La page affiche les deux pour "
        "decider du choix avant calibration."
    )
    network_cards = []
    for key, title in [
        ("hydrographic_network_comparison", "Reference BD Topage vs reseau derive DEM"),
        ("hydrographic_network_reference", "Reseau hydrographique de reference"),
        ("hydrographic_network_generated", "Reseau derive du DEM"),
        ("hydrographic_network_reference_missing_only", "Reference non retrouvee par le DEM"),
        ("hydrographic_network_generated_extra_only", "Branches DEM hors reference"),
    ]:
        if key not in assets:
            continue
        network_cards.append(
            f"<figure class='panel'><img src='{assets[key]}' alt='{title}'><figcaption>{title}</figcaption></figure>"
        )
    html = f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Nancon jauge - contexte pre-calibration</title>
  <style>
    :root {{
      --ink: #111827;
      --muted: #64748b;
      --line: #d7dee8;
      --band: #f8fafc;
      --accent: #2563eb;
      --red: #dc2626;
    }}
    body {{
      margin: 0;
      font-family: Inter, Segoe UI, Arial, sans-serif;
      color: var(--ink);
      background: white;
      line-height: 1.45;
    }}
    header, section {{
      padding: 28px clamp(18px, 4vw, 56px);
    }}
    header {{
      background: #eef4fb;
      border-bottom: 1px solid var(--line);
    }}
    h1, h2, h3 {{
      margin: 0 0 12px;
      letter-spacing: 0;
    }}
    h1 {{
      font-size: clamp(1.8rem, 3.2vw, 3rem);
    }}
    h2 {{
      font-size: 1.35rem;
      border-bottom: 1px solid var(--line);
      padding-bottom: 8px;
    }}
    p {{
      max-width: 1100px;
      color: #334155;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
      gap: 12px;
      margin-top: 16px;
    }}
    .metric {{
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 12px 14px;
      background: white;
    }}
    .metric span {{
      display: block;
      color: var(--muted);
      font-size: 0.86rem;
    }}
    .metric strong {{
      display: block;
      font-size: 1.15rem;
      margin-top: 4px;
    }}
    .band {{
      background: var(--band);
    }}
    .panel-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
      gap: 16px;
      margin-top: 16px;
    }}
    figure.panel {{
      margin: 0;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: white;
      overflow: hidden;
    }}
    figure.panel img {{
      display: block;
      width: 100%;
      height: auto;
    }}
    figcaption {{
      padding: 9px 12px;
      color: var(--muted);
      font-size: 0.9rem;
      border-top: 1px solid var(--line);
    }}
    table {{
      border-collapse: collapse;
      width: 100%;
      margin-top: 14px;
      font-size: 0.92rem;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 8px 10px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      background: #eef2f7;
    }}
    code {{
      font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
      font-size: 0.9em;
    }}
    .warn {{
      border-left: 4px solid #f59e0b;
      background: #fffbeb;
      padding: 10px 12px;
      color: #78350f;
      max-width: 1100px;
    }}
  </style>
</head>
<body>
  <header>
    <h1>Nancon jauge: contexte avant calibration</h1>
    <p>
      Cette page verifie le support spatial, les donnees de debit observe,
      les forcages recharge/runoff et le reseau hydrographique avant de lancer
      une calibration. Le run utilise ici est un run de preparation non calibre,
      pas un resultat scientifique final.
    </p>
  </header>

  <section>
    <h2>Probleme construit</h2>
    <div class="grid">
      {_html_metric("Exutoire X Lambert-93", config["x_outlet"], "m")}
      {_html_metric("Exutoire Y Lambert-93", config["y_outlet"], "m")}
      {_html_metric("Fenetre simulation", simulation_window)}
      {_html_metric("Pas de temps", config["step_value"])}
      {_html_metric("K initial", config["K"], "m/s")}
      {_html_metric("Sy initial", config["Sy"])}
      {_html_metric("Epaisseur aquifere", config["thickness"], "m")}
      {_html_metric("Drainage Cauchy", config["drainage"], "m2/s")}
    </div>
    <p class="warn">{data_note}</p>
  </section>

  <section class="band">
    <h2>Domaine et reseau hydrographique</h2>
    <div class="grid">
      {_html_metric("Cellules du run de preparation", baseline.get("n_cells"))}
      {_html_metric("Pas calcules", baseline.get("n_timesteps"))}
      {_html_metric("Temps solveur", baseline.get("runtime_seconds"), "s")}
      {_html_metric("Segments BD Topage", network.get("reference_segments"))}
      {_html_metric("Segments reseau DEM", network.get("generated_segments"))}
    </div>
    <div class="panel-grid">
      {"".join(network_cards)}
    </div>
  </section>

  <section>
    <h2>Chroniques observees et forcages</h2>
    <div class="grid">
      {_html_metric("Debit observe: points", stats["observed_discharge"]["rows"])}
      {_html_metric("Debit observe: debut", stats["observed_discharge"]["start"])}
      {_html_metric("Debit observe: fin", stats["observed_discharge"]["end"])}
      {_html_metric("Debit observe moyen", stats["observed_discharge"]["mean"], "m3/s")}
      {_html_metric("Recharge EX04 moyenne", stats["recharge_ex04"]["mean"], "mm/day")}
      {_html_metric("Recharge NANCON moyenne", stats["recharge_nancon"]["mean"], "mm/day")}
      {_html_metric("Runoff EX04 moyen", stats["runoff_ex04"]["mean"], "mm/day")}
      {_html_metric("Runoff NANCON moyen", stats["runoff_nancon"]["mean"], "mm/day")}
    </div>
    <div class="panel-grid">
      <figure class="panel"><img src="assets/observed_discharge_full.png" alt="Debit observe complet"><figcaption>Chronique journaliere observee, avec la fenetre 2000-2002 surlignee.</figcaption></figure>
      <figure class="panel"><img src="assets/forcing_window.png" alt="Forcages recharge runoff"><figcaption>Debit observe dans la fenetre et forcages disponibles EX04/NANCON.</figcaption></figure>
      <figure class="panel"><img src="assets/baseline_discharge_comparison.png" alt="Debit simule baseline"><figcaption>Simulation de preparation non calibree comparee au debit observe.</figcaption></figure>
    </div>
  </section>

  <section class="band">
    <h2>Fichiers produits</h2>
    <table>
      <tr><th>Artefact</th><th>Chemin</th></tr>
      <tr><td>Resume JSON</td><td><code>outputs/context/nancon_gauged_context_summary.json</code></td></tr>
      <tr><td>Debit observe journalier</td><td><code>outputs/context/observed_discharge_daily.csv</code></td></tr>
      <tr><td>Recharge/runoff mensuels</td><td><code>outputs/context/forcings_monthly.csv</code></td></tr>
      <tr><td>Debit simule non calibre</td><td><code>outputs/context/baseline_simulated_discharge.csv</code></td></tr>
    </table>
  </section>
</body>
</html>
"""
    (web_dir / "index.html").write_text(html, encoding="utf-8")


def build_context(output_root: Path) -> None:
    context_dir = output_root / "context"
    web_dir = output_root / "web"
    assets_dir = web_dir / "assets"
    context_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    project_config_path = NANCON_PROJECT / "project.toml"
    project_config = _load_project_config(project_config_path)

    observed_path = DATA_ROOT / "hydrometry" / "hydrometry_custom_NANCON_19820201_20220125_D.csv"
    observed = _read_series(observed_path)

    forcing_frames = {
        "recharge:EX04": _read_series(
            DATA_ROOT / "recharge" / "recharge_custom_EX04_20000101_20021231_M.csv"
        ),
        "recharge:NANCON": _read_series(
            DATA_ROOT / "recharge" / "recharge_custom_NANCON_20000101_20021231_M.csv"
        ),
        "runoff:EX04": _read_series(
            DATA_ROOT / "runoff" / "runoff_custom_EX04_20000101_20021231_M.csv"
        ),
        "runoff:NANCON": _read_series(
            DATA_ROOT / "runoff" / "runoff_custom_NANCON_20000101_20021231_M.csv"
        ),
    }

    simulated_path = NANCON_PROJECT / "exports" / "run_0001" / "timeseries.csv"
    simulated = _read_series(simulated_path) if simulated_path.exists() else None

    csv_outputs = _write_timeseries_outputs(context_dir, observed, forcing_frames, simulated)

    _plot_full_observed(observed, assets_dir / "observed_discharge_full.png")
    _plot_window_forcing(observed, forcing_frames, assets_dir / "forcing_window.png")
    _plot_baseline_comparison(observed, simulated, assets_dir / "baseline_discharge_comparison.png")

    figure_dir = _latest_network_figure_dir(NANCON_PROJECT)
    network_assets = _copy_network_assets(figure_dir, assets_dir)

    parquet_dir = _latest_simulation_parquet_dir(NANCON_PROJECT)
    n_timesteps = len(simulated) if simulated is not None else None
    baseline = {
        "source_export": str(simulated_path.relative_to(REPO_ROOT))
        if simulated_path.exists()
        else None,
        "simulation_parquet": str(parquet_dir.relative_to(REPO_ROOT)) if parquet_dir else None,
        "n_cells": _read_provenance_n_records(parquet_dir, "hydrography:hydrography_streams"),
        "n_timesteps": int(n_timesteps) if n_timesteps is not None else None,
        "runtime_seconds": _read_runtime_seconds(parquet_dir),
        "simulated_discharge_mean_m3_s": (
            _finite_float(simulated["value"].mean()) if simulated is not None else None
        ),
    }
    network = {
        "figure_dir": str(figure_dir.relative_to(REPO_ROOT)) if figure_dir else None,
        "reference_segments": _read_parquet_count(
            parquet_dir,
            "geographic_hydrographic_network_reference.parquet",
        ),
        "generated_segments": _read_parquet_count(
            parquet_dir,
            "geographic_hydrographic_network_generated.parquet",
        ),
    }
    geographic = project_config["geographic"]
    flow = project_config["flow"]
    simulation_time = project_config["simulation"]["time"]
    summary = {
        "title": "Nancon gauged pre-calibration context",
        "configuration": {
            "base_config": str(project_config_path.relative_to(REPO_ROOT)),
            "dem": str((DATA_ROOT / "dem" / "DEM_armorican_massif.tif").relative_to(REPO_ROOT)),
            "x_outlet": geographic["x_outlet"],
            "y_outlet": geographic["y_outlet"],
            "crs": geographic["crs_project"],
            "start_datetime": simulation_time["start_datetime"],
            "end_datetime": simulation_time["end_datetime"],
            "step_value": simulation_time["step_value"],
            "K": flow["param"]["K"]["field"]["value"],
            "Sy": flow["param"]["Sy"]["field"]["value"],
            "Ss": flow["param"]["Ss"]["field"]["value"],
            "thickness": project_config["domain"]["depth_model"]["thickness"],
            "drainage": flow["bc"]["cauchy"]["drainage"]["value"],
            "configured_recharge_station_ids": _configured_station_ids(project_config, "recharge"),
            "configured_runoff_station_ids": _configured_station_ids(project_config, "runoff"),
            "configured_hydrometry_station_ids": _configured_station_ids(
                project_config, "hydrometry"
            ),
        },
        "stats": {
            "observed_discharge": SeriesStats.from_frame(observed).__dict__,
            "recharge_ex04": SeriesStats.from_frame(forcing_frames["recharge:EX04"]).__dict__,
            "recharge_nancon": SeriesStats.from_frame(forcing_frames["recharge:NANCON"]).__dict__,
            "runoff_ex04": SeriesStats.from_frame(forcing_frames["runoff:EX04"]).__dict__,
            "runoff_nancon": SeriesStats.from_frame(forcing_frames["runoff:NANCON"]).__dict__,
            "baseline_simulated_discharge": (
                SeriesStats.from_frame(simulated).__dict__ if simulated is not None else None
            ),
        },
        "baseline_run": baseline,
        "network": network,
        "outputs": csv_outputs,
    }

    summary_path = context_dir / "nancon_gauged_context_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    _write_html(web_dir, summary, network_assets)
    print(f"Wrote {summary_path}")
    print(f"Wrote {web_dir / 'index.html'}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=SCRIPT_DIR / "outputs",
        help="Output directory for context CSV/JSON and web report.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_context(args.output_root)


if __name__ == "__main__":
    main()
