"""Build a compact HTML synthesis for the Nancon network benchmark."""

from __future__ import annotations

import csv
import html
import json
import os
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCHMARK_ROOT = HERE / "outputs" / "nancon_network_physical_benchmark"
COMPARISON_ROOT = BENCHMARK_ROOT / "comparison"
PAGE_PATH = BENCHMARK_ROOT / "web_synthesis" / "index.html"
FIGURE_ROOT = BENCHMARK_ROOT / "web_synthesis" / "field_figures"
RECHARGE_FIGURE_PATH = BENCHMARK_ROOT / "web_synthesis" / "recharge_forcing.png"
METRIC_SYNTHESIS_FIGURE_PATH = BENCHMARK_ROOT / "web_synthesis" / "distance_ratio_synthesis.png"
BASE_CONFIG = HERE / "base_nancon_physics.toml"


@dataclass(frozen=True)
class SimulationMeta:
    simulation_id: str
    label: str
    group: str
    purpose: str


@dataclass
class SimulationRecord:
    meta: SimulationMeta
    simulation_label: str = ""
    solver: str = ""
    mesh_mode: str = ""
    mesh_label: str = ""
    closure: dict[str, str] = field(default_factory=dict)
    release_distance: dict[str, str] | None = None
    accumulation_distance: dict[str, str] | None = None
    release_accumulation_distance: dict[str, str] | None = None
    vector_network: dict[str, str] | None = None


SIMULATIONS: tuple[SimulationMeta, ...] = (
    SimulationMeta(
        "mf6_disv_drain_high",
        "MF6 triangulaire contraint par le reseau",
        "solveur_meme_maillage",
        "MODFLOW 6 sur le maillage triangulaire contraint par le reseau.",
    ),
    SimulationMeta(
        "bouss_same_mesh_no_drain",
        "Boussinesq triangulaire contraint par le reseau",
        "solveur_meme_maillage",
        "Boussinesq sur le meme maillage triangulaire.",
    ),
    SimulationMeta(
        "mf6_regular_120_drain_high",
        "MF6 grille reguliere 120 x 120",
        "sensibilite_maillage_mf6",
        "Grille reguliere grossiere, physique MF6 identique.",
    ),
    SimulationMeta(
        "mf6_regular_180_drain_high",
        "MF6 grille reguliere 180 x 180",
        "sensibilite_maillage_mf6",
        "Grille reguliere plus dense, physique MF6 identique.",
    ),
    SimulationMeta(
        "mf6_irregular_350_drain_high",
        "MF6 maillage triangulaire 350 m",
        "sensibilite_maillage_mf6",
        "Maillage irregularise genere, taille globale 350 m.",
    ),
)

META_BY_ID = {item.simulation_id: item for item in SIMULATIONS}


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    return data if isinstance(data, dict) else {}


def read_toml(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    with path.open("rb") as stream:
        data = tomllib.load(stream)
    return data if isinstance(data, dict) else {}


def safe(value: object) -> str:
    return html.escape(str(value if value is not None else ""))


def relative_path(path: Path) -> str:
    return os.path.relpath(path, PAGE_PATH.parent).replace(os.sep, "/")


def resolve_recorded_path(raw_path: str) -> Path:
    text = str(raw_path or "").strip()
    if os.name == "nt" and text.startswith("/mnt/") and len(text) > 7 and text[5].isalpha():
        return Path(f"{text[5].upper()}:/{text[7:]}").resolve()
    if os.name != "nt" and len(text) > 2 and text[1] == ":" and text[0].isalpha():
        drive = text[0].lower()
        tail = text[2:].replace("\\", "/").lstrip("/")
        return Path(f"/mnt/{drive}/{tail}").resolve()
    return Path(text).expanduser().resolve()


def first(row: dict[str, str], *names: str) -> str:
    for name in names:
        value = row.get(name, "")
        if value:
            return value
    return ""


def fmt_number(value: str, digits: int = 2) -> str:
    if value in ("", None):
        return ""
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def fmt_m(value: str) -> str:
    if value in ("", None):
        return ""
    try:
        return f"{float(value):,.0f}".replace(",", " ")
    except (TypeError, ValueError):
        return str(value)


def fmt_ratio(value: str) -> str:
    if value in ("", None):
        return ""
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def parse_float(value: object) -> float | None:
    if value in ("", None):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def row_value(row: dict[str, str] | None, name: str) -> str:
    if row is None:
        return ""
    return row.get(name, "")


def _record_for(records: dict[str, SimulationRecord], simulation_id: str) -> SimulationRecord:
    meta = META_BY_ID.get(
        simulation_id,
        SimulationMeta(simulation_id, simulation_id, "autres", ""),
    )
    return records.setdefault(simulation_id, SimulationRecord(meta=meta))


def records_by_simulation() -> list[SimulationRecord]:
    records: dict[str, SimulationRecord] = {}
    for filename, attr in (
        ("release_flux_network_distance_metrics.csv", "release_distance"),
        ("simulated_active_network_distance_metrics.csv", "accumulation_distance"),
        ("release_accumulation_network_distance_metrics.csv", "release_accumulation_distance"),
        ("hydrographic_network_metrics.csv", "vector_network"),
    ):
        for row in read_csv(COMPARISON_ROOT / filename):
            simulation_id = first(row, "simulation_id")
            if not simulation_id:
                continue
            record = _record_for(records, simulation_id)
            record.simulation_label = record.simulation_label or first(row, "simulation_label")
            record.solver = record.solver or first(row, "solver")
            record.mesh_mode = record.mesh_mode or first(row, "mesh_mode")
            record.mesh_label = record.mesh_label or first(row, "mesh_label")
            setattr(record, attr, row)

    for row in read_csv(COMPARISON_ROOT / "numerical_closure_summary.csv"):
        simulation_id = first(row, "simulation_id")
        if not simulation_id:
            continue
        record = _record_for(records, simulation_id)
        record.simulation_label = record.simulation_label or first(row, "simulation_label")
        record.solver = record.solver or first(row, "solver")
        record.closure = row

    ordered = [_record_for(records, meta.simulation_id) for meta in SIMULATIONS]
    seen = {record.meta.simulation_id for record in ordered}
    ordered.extend(record for key, record in sorted(records.items()) if key not in seen)
    return ordered


def all_bidirectional_distances(records: Iterable[SimulationRecord]) -> list[float]:
    values: list[float] = []
    for record in records:
        for row in (
            record.release_distance,
            record.accumulation_distance,
            record.release_accumulation_distance,
        ):
            if not row:
                continue
            try:
                values.append(float(row["bidirectional_distance_mean_m"]))
            except (KeyError, TypeError, ValueError):
                pass
    return values


def routed_distance(record: SimulationRecord) -> dict[str, str] | None:
    return record.release_accumulation_distance or record.accumulation_distance


def solver_summary(record: SimulationRecord) -> str:
    if record.solver == "modflow6":
        return "MODFLOW 6"
    if record.solver == "boussinesq":
        return "Boussinesq"
    return record.solver or "solveur non renseigne"


def mesh_summary(record: SimulationRecord) -> str:
    simulation_id = record.meta.simulation_id
    mesh_label = record.mesh_label or record.mesh_mode or "maillage non renseigne"
    if simulation_id in {"mf6_disv_drain_high", "bouss_same_mesh_no_drain"}:
        title = "Maillage triangulaire contraint par le reseau observe"
    elif simulation_id == "mf6_regular_120_drain_high":
        title = "Grille reguliere 120 x 120"
    elif simulation_id == "mf6_regular_180_drain_high":
        title = "Grille reguliere 180 x 180"
    elif simulation_id == "mf6_irregular_350_drain_high":
        title = "Maillage triangulaire genere, taille cible 350 m"
    else:
        title = mesh_label.replace("_", " ")

    cell_count = (
        row_value(record.release_distance, "catchment_cell_count")
        or row_value(record.release_accumulation_distance, "catchment_cell_count")
        or row_value(record.accumulation_distance, "catchment_cell_count")
    )
    detail = (
        f"{safe(fmt_m(cell_count))} cellules de calcul"
        if cell_count
        else "nombre de cellules non disponible"
    )
    return f"{safe(title)}; {detail}"


def configuration_cell(record: SimulationRecord) -> str:
    return (
        '<td class="config-cell">'
        f"<strong>{safe(record.meta.label)}</strong>"
        f'<span class="sub">{safe(solver_summary(record))}; {mesh_summary(record)}</span>'
        "</td>"
    )


def metric_bar(row: dict[str, str] | None, max_distance: float) -> str:
    if row is None:
        return ""
    value = row.get("bidirectional_distance_mean_m", "")
    try:
        width = max(4.0, min(100.0, 100.0 * float(value) / max_distance))
    except (TypeError, ValueError, ZeroDivisionError):
        width = 0.0
    return f'<div class="bar" style="width:{width:.1f}%"></div>'


def metric_grid(row: dict[str, str], max_distance: float) -> str:
    active = row.get("active_cell_count", "")
    return f"""
<div class="metric-box">
  {metric_bar(row, max_distance)}
  <div class="metric-grid">
    <div><span>calc &rarr; obs moy.</span><strong>{safe(fmt_m(row.get("sim_to_network_distance_mean_m", "")))} m</strong></div>
    <div><span>obs &rarr; calc moy.</span><strong>{safe(fmt_m(row.get("network_to_sim_distance_mean_m", "")))} m</strong></div>
    <div><span>ratio</span><strong>{safe(fmt_ratio(row.get("planar_distance_ratio", "")))}</strong></div>
    <div><span>moyenne sym.</span><strong>{safe(fmt_m(row.get("bidirectional_distance_mean_m", "")))} m</strong></div>
  </div>
  <div class="metric-foot">mailles retenues par le diagnostic: {safe(active or "n/a")}</div>
</div>
"""


def figure_preview(record: SimulationRecord, variable: str, label: str) -> str:
    path = figure_path(record, variable)
    if not path.exists():
        return '<div class="figure-missing">figure non disponible</div>'
    rel = relative_path(path)
    title = f"{record.meta.label} - {label}"
    return f"""
<figure class="method-figure">
  <a href="{safe(rel)}" class="figure-link" data-lightbox-src="{safe(rel)}" data-lightbox-title="{safe(title)}" title="Cliquer pour agrandir">
    <img src="{safe(rel)}" alt="{safe(title)}" loading="lazy">
  </a>
  <figcaption>{safe(label)}</figcaption>
</figure>
"""


def method_cell(
    record: SimulationRecord,
    *,
    row: dict[str, str] | None,
    variable: str,
    label: str,
    description: str,
    missing: str,
    max_distance: float,
) -> str:
    if row is None:
        return f"""
<td class="method-cell">
  <div class="method-title">{safe(label)}</div>
  <p>{safe(description)}</p>
  <div class="figure-missing">{safe(missing)}</div>
</td>
"""
    return f"""
<td class="method-cell">
  <div class="method-title">{safe(label)}</div>
  <p>{safe(description)}</p>
  {figure_preview(record, variable, label)}
  {metric_grid(row, max_distance)}
</td>
"""


def comparison_table(records: list[SimulationRecord], *, group: str) -> str:
    max_distance = max(all_bidirectional_distances(records) or [1.0])
    rows = []
    for record in records:
        if record.meta.group != group:
            continue
        rows.append(
            "<tr>"
            f"{configuration_cell(record)}"
            + method_cell(
                record,
                row=record.release_distance,
                variable="release_flux",
                label="Emergences avant routage",
                description="Mailles ou le modele calcule une sortie d'eau vers la surface: drain + surface excess, sans accumulation aval.",
                missing="metrique non disponible",
                max_distance=max_distance,
            )
            + method_cell(
                record,
                row=routed_distance(record),
                variable="release_accumulation_flux",
                label="Emergences accumulees vers l'aval",
                description="Les emergences sont routees vers l'aval sur le support numerique, puis comparees au reseau observe.",
                missing="non calcule pour cette configuration",
                max_distance=max_distance,
            )
            + "</tr>"
        )
    if not rows:
        rows.append(
            '<tr><td colspan="3" class="missing">Aucune simulation dans ce groupe.</td></tr>'
        )
    return f"""
<table class="comparison-table">
  <thead>
    <tr>
      <th>configuration calculee</th>
      <th>emergences avant routage</th>
      <th>emergences accumulees vers l'aval</th>
    </tr>
  </thead>
  <tbody>{"".join(rows)}</tbody>
</table>
"""


def _field_stack(run, variable: str):
    import numpy as np

    n_timesteps = int(run.n_timesteps or 1)
    return np.stack(
        [
            np.asarray(run.field(variable, timestep=t), dtype="float64").reshape(-1)
            for t in range(n_timesteps)
        ]
    )


def _mean_positive_flux(run, variable: str):
    import numpy as np

    stack = _field_stack(run, variable)
    positive = np.where(np.isfinite(stack) & (stack > 0.0), stack, np.nan)
    with np.errstate(invalid="ignore"):
        return np.nanmean(positive, axis=0)


def _log10_positive(values):
    import numpy as np

    values = np.asarray(values, dtype="float64").reshape(-1)
    out = np.full(values.shape, np.nan, dtype="float64")
    mask = np.isfinite(values) & (values > 0.0)
    out[mask] = np.log10(values[mask])
    return out


def _overlay_reference(ax, run) -> None:
    from matplotlib.lines import Line2D

    from hydromodpy.display._map_axes import overlay_watershed_contour
    from hydromodpy.display.figures.hydrographic_network import _project_gdf_for_metric_operations

    has_reference = False
    try:
        reference = run.hydrographic_network("reference")
    except Exception:
        reference = None
    if reference is not None and not reference.empty:
        try:
            watershed = run.geographic("watershed")
            fallback_crs = None if watershed is None or watershed.empty else watershed.crs
        except Exception:
            fallback_crs = None
        reference = _project_gdf_for_metric_operations(reference, fallback_crs=fallback_crs)
        reference.plot(ax=ax, color="#9b1c1c", linewidth=1.25, alpha=0.98, zorder=6)
        has_reference = True
    overlay_watershed_contour(ax, run, color="#404040", linewidth=0.9, alpha=0.65)
    if has_reference:
        handle = Line2D([0], [0], color="#9b1c1c", lw=1.6, label="reseau observe")
        ax.legend(
            handles=[handle],
            loc="upper right",
            frameon=True,
            framealpha=0.9,
            fontsize=8,
        )


def _render_log_flux_figure(run, *, variable: str, title: str, save_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.ticker import FormatStrFormatter, MaxNLocator

    from hydromodpy.display._map_axes import style_map_axes
    from hydromodpy.display._ugrid import render_face_field

    values = _log10_positive(_mean_positive_flux(run, variable))
    finite = values[np.isfinite(values)]
    if finite.size:
        vmin = float(np.nanpercentile(finite, 5.0))
        vmax = float(np.nanpercentile(finite, 95.0))
        if not np.isfinite(vmin) or not np.isfinite(vmax) or vmin >= vmax:
            vmin = float(np.nanmin(finite))
            vmax = float(np.nanmax(finite))
    else:
        vmin, vmax = -12.0, 0.0

    fig, ax = plt.subplots(figsize=(7.8, 5.8), dpi=180, constrained_layout=True)
    collection = render_face_field(
        ax,
        run,
        values,
        cmap="viridis",
        vmin=vmin,
        vmax=vmax,
        cbar_label="log10(flux moyen positif)",
    )
    ticks = np.linspace(float(vmin), float(vmax), 5)
    tick_labels = [f"{tick:.1f}" for tick in ticks]
    colorbar = getattr(collection, "colorbar", None)
    if colorbar is not None:
        colorbar.set_ticks(ticks)
        colorbar.set_ticklabels(tick_labels)
    elif len(fig.axes) > 1:
        fig.axes[-1].yaxis.set_major_locator(MaxNLocator(nbins=5))
        fig.axes[-1].yaxis.set_major_formatter(FormatStrFormatter("%.1f"))
    _overlay_reference(ax, run)
    style_map_axes(ax)
    ax.set_title(title)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def figure_path(record: SimulationRecord, variable: str) -> Path:
    return FIGURE_ROOT / record.meta.simulation_id / f"{variable}_log_intensity.png"


def _first_recharge_source() -> dict[str, object]:
    config = read_toml(BASE_CONFIG)
    data = config.get("data", {})
    if not isinstance(data, dict):
        return {}
    recharge = data.get("recharge", {})
    if not isinstance(recharge, dict):
        return {}
    sources = recharge.get("sources", [])
    if not isinstance(sources, list) or not sources:
        return {}
    source = sources[0]
    return source if isinstance(source, dict) else {}


def recharge_values_from_config() -> list[float]:
    source = _first_recharge_source()
    values = source.get("values", [])
    if not isinstance(values, list):
        return []
    parsed: list[float] = []
    for value in values:
        try:
            parsed.append(float(value))
        except (TypeError, ValueError):
            continue
    return parsed


def _add_months(start: date, months: int) -> date:
    month_index = start.month - 1 + int(months)
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def recharge_month_labels(n_values: int) -> list[str]:
    source = _first_recharge_source()
    raw_start = source.get("start_date") or "2020-10-01"
    if isinstance(raw_start, date):
        start = raw_start
    else:
        start = date.fromisoformat(str(raw_start)[:10])
    labels = []
    for index in range(n_values):
        item = _add_months(start, index)
        labels.append(f"{item:%b} {item.year}")
    return labels


def recharge_summary_text() -> str:
    values = recharge_values_from_config()
    if not values:
        return "chronique de recharge non trouvee"
    return (
        f"{len(values)} mois; moyenne {sum(values) / len(values):.2f} mm/j; "
        f"min {min(values):.2f}; max {max(values):.2f}"
    )


def generate_recharge_figure() -> bool:
    values = recharge_values_from_config()
    if not values:
        return False

    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    labels = recharge_month_labels(len(values))
    mean_value = sum(values) / len(values)
    fig, ax = plt.subplots(figsize=(6.6, 1.9), dpi=180, constrained_layout=True)
    x_values = list(range(len(values)))
    ax.bar(x_values, values, color="#4c78a8", width=0.72)
    ax.axhline(mean_value, color="#b23a48", linewidth=1.2, linestyle="--", label="moyenne")
    ax.set_title("Recharge mensuelle imposee", fontsize=10)
    ax.set_ylabel("mm/j")
    ax.set_xticks(x_values)
    ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=7)
    ax.grid(axis="y", color="#d8dee6", linewidth=0.7, alpha=0.8)
    ax.legend(loc="upper right", frameon=False, fontsize=8)
    ax.tick_params(axis="y", labelsize=8)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    RECHARGE_FIGURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(RECHARGE_FIGURE_PATH, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return True


def short_configuration_label(record: SimulationRecord) -> str:
    labels = {
        "mf6_disv_drain_high": "MF6 triangulaire contraint",
        "bouss_same_mesh_no_drain": "Boussinesq triangulaire",
        "mf6_regular_120_drain_high": "MF6 regulier 120",
        "mf6_regular_180_drain_high": "MF6 regulier 180",
        "mf6_irregular_350_drain_high": "MF6 triangulaire 350 m",
    }
    return labels.get(record.meta.simulation_id, record.meta.label)


def generate_metric_synthesis_figure(records: list[SimulationRecord]) -> bool:
    items: list[tuple[str, float | None, float | None, float | None, float | None]] = []
    for record in records:
        release = record.release_distance
        routed = routed_distance(record)
        release_distance = parse_float(row_value(release, "bidirectional_distance_mean_m"))
        routed_distance_mean = parse_float(row_value(routed, "bidirectional_distance_mean_m"))
        release_ratio = parse_float(row_value(release, "planar_distance_ratio"))
        routed_ratio = parse_float(row_value(routed, "planar_distance_ratio"))
        if any(
            value is not None
            for value in (release_distance, routed_distance_mean, release_ratio, routed_ratio)
        ):
            items.append(
                (
                    short_configuration_label(record),
                    release_distance,
                    routed_distance_mean,
                    release_ratio,
                    routed_ratio,
                )
            )
    if not items:
        return False

    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    import numpy as np

    labels = [item[0] for item in items]
    y_values = np.arange(len(items), dtype=float)
    release_distances = [item[1] for item in items]
    routed_distances = [item[2] for item in items]
    release_ratios = [item[3] for item in items]
    routed_ratios = [item[4] for item in items]

    fig, axes = plt.subplots(
        1,
        2,
        figsize=(9.4, 3.8),
        dpi=180,
        sharey=True,
        constrained_layout=True,
    )
    styles = (
        ("Emergences avant routage", "#4c78a8", "o"),
        ("Emergences accumulees vers l'aval", "#f58518", "s"),
    )
    for ax, title, xlabel, first, second in (
        (
            axes[0],
            "Distance moyenne symetrique",
            "m",
            release_distances,
            routed_distances,
        ),
        (
            axes[1],
            "Ratio des distances",
            "calc -> obs / obs -> calc",
            release_ratios,
            routed_ratios,
        ),
    ):
        for values, (method_label, color, marker), offset in (
            (first, styles[0], -0.12),
            (second, styles[1], 0.12),
        ):
            xs = [float(value) if value is not None else np.nan for value in values]
            ax.scatter(xs, y_values + offset, label=method_label, color=color, marker=marker, s=34)
            for x_value, y_value in zip(xs, y_values + offset, strict=True):
                if np.isfinite(x_value):
                    ax.text(
                        x_value,
                        y_value,
                        f" {x_value:.0f}" if xlabel == "m" else f" {x_value:.2f}",
                        va="center",
                        fontsize=7,
                    )
        ax.set_title(title, fontsize=10)
        ax.set_xlabel(xlabel)
        ax.grid(axis="x", color="#d8dee6", linewidth=0.7, alpha=0.8)
        ax.tick_params(labelsize=8)
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
    axes[0].set_yticks(y_values)
    axes[0].set_yticklabels(labels, fontsize=8)
    axes[0].invert_yaxis()
    axes[1].axvline(1.0, color="#808b96", linewidth=1.0, linestyle="--")
    axes[0].legend(loc="lower right", frameon=False, fontsize=8)

    METRIC_SYNTHESIS_FIGURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(METRIC_SYNTHESIS_FIGURE_PATH, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return True


def _distance_csv_fieldnames() -> list[str]:
    source = COMPARISON_ROOT / "release_flux_network_distance_metrics.csv"
    if source.exists():
        with source.open("r", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames:
                return list(reader.fieldnames)
    return [
        "comparison_id",
        "simulation_id",
        "simulation_label",
        "solver",
        "mesh_label",
        "mesh_mode",
        "sim_id",
        "run_name",
        "run_folder",
        "network_role",
        "source_variable",
        "threshold",
        "mode",
        "persistence_threshold",
        "timestep",
        "network_buffer_m",
        "distance_method",
        "catchment_cell_count",
        "active_cell_count",
        "network_cell_count",
        "sim_to_network_sample_count",
        "sim_to_network_distance_mean_m",
        "sim_to_network_distance_median_m",
        "sim_to_network_distance_p95_m",
        "sim_to_network_distance_max_m",
        "network_to_sim_sample_count",
        "network_to_sim_distance_mean_m",
        "network_to_sim_distance_median_m",
        "network_to_sim_distance_p95_m",
        "network_to_sim_distance_max_m",
        "bidirectional_distance_mean_m",
        "bidirectional_distance_quadratic_mean_m",
        "bidirectional_distance_absolute_difference_m",
        "planar_distance_ratio",
        "planar_distance_log10_ratio",
    ]


def _write_distance_rows(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        return
    fieldnames = _distance_csv_fieldnames()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def generate_release_accumulation_distance_metrics(records: list[SimulationRecord]) -> int:
    try:
        from hydromodpy.results.catalog import Catalog
    except Exception:
        return 0

    output_path = COMPARISON_ROOT / "release_accumulation_network_distance_metrics.csv"
    rows: list[dict[str, str]] = []
    generated = 0
    for record in records:
        source_row = record.release_distance or record.accumulation_distance or {}
        run_folder = source_row.get("run_folder", "")
        sim_id = source_row.get("sim_id", "")
        if not run_folder or not sim_id:
            continue
        catalog = None
        try:
            catalog = Catalog(resolve_recorded_path(run_folder))
            run = catalog[str(sim_id)]
            if not run.has_field("release_accumulation_flux") or not run.has_hydrographic_network(
                "reference"
            ):
                continue
            metrics = run.cell_field_network_distance_metrics(
                network_role="reference",
                variable="release_accumulation_flux",
                threshold=0.0,
                mode=None,
                persistence_threshold=0.5,
                timestep=None,
                network_buffer_m=0.0,
            )
            row = {
                "comparison_id": "nancon_network_physical_benchmark",
                "simulation_id": record.meta.simulation_id,
                "simulation_label": record.simulation_label or record.meta.label,
                "solver": record.solver,
                "mesh_label": record.mesh_label,
                "mesh_mode": record.mesh_mode,
                "sim_id": str(sim_id),
                "run_name": source_row.get("run_name", ""),
                "run_folder": run_folder,
            }
            row.update(
                {key: str(value if value is not None else "") for key, value in metrics.items()}
            )
            record.release_accumulation_distance = row
            rows.append(row)
            generated += 1
        except Exception:
            continue
        finally:
            if catalog is not None:
                try:
                    catalog.close()
                except Exception:
                    pass

    _write_distance_rows(output_path, rows)
    return generated


def generate_field_figures(records: list[SimulationRecord]) -> int:
    try:
        from hydromodpy.results.catalog import Catalog
    except Exception:
        return 0

    generated = 0
    for record in records:
        source_row = record.release_distance or record.accumulation_distance or {}
        run_folder = source_row.get("run_folder", "")
        sim_id = source_row.get("sim_id", "")
        if not run_folder or not sim_id:
            continue
        catalog = None
        try:
            catalog = Catalog(resolve_recorded_path(run_folder))
            run = catalog[str(sim_id)]
            for variable, title in (
                ("release_flux", "Emergences avant routage - intensite moyenne positive"),
                (
                    "release_accumulation_flux",
                    "Emergences accumulees vers l'aval - intensite moyenne positive",
                ),
            ):
                if not run.has_field(variable) or not run.has_hydrographic_network("reference"):
                    continue
                out = figure_path(record, variable)
                _render_log_flux_figure(run, variable=variable, title=title, save_path=out)
                generated += 1
        except Exception:
            continue
        finally:
            if catalog is not None:
                try:
                    catalog.close()
                except Exception:
                    pass
    return generated


def contract_section() -> str:
    return """
<section>
  <h2>Contrat physique commun</h2>
  <div class="cards">
    <article><h3>Temps et recharge</h3><p>Transitoire mensuel du 2020-10-01 au 2021-09-30, meme chronique synthetique mensuelle.</p></article>
    <article><h3>Hydraulique</h3><p><i>K</i> = 5 &times; 10<sup>-5</sup> m s<sup>-1</sup>; <i>S<sub>y</sub></i> = 0.05; epaisseur aquifere = 30 m.</p></article>
    <article><h3>Condition initiale</h3><p>Etat permanent sous recharge moyenne, avec la meme regle pour chaque simulation.</p></article>
    <article><h3>Distances</h3><p>Distances continues, sans categorisation: calcule vers observe, observe vers calcule, puis moyenne symetrique.</p></article>
  </div>
</section>
"""


def recharge_section() -> str:
    if not RECHARGE_FIGURE_PATH.exists():
        return ""
    rel = relative_path(RECHARGE_FIGURE_PATH)
    title = "Recharge mensuelle imposee"
    return f"""
<section>
  <h2>Recharge imposee</h2>
  <p>{safe(recharge_summary_text())}. Cette chronique est commune aux configurations de ce benchmark.</p>
  <figure class="wide-figure">
    <a href="{safe(rel)}" class="figure-link" data-lightbox-src="{safe(rel)}" data-lightbox-title="{safe(title)}" title="Cliquer pour agrandir">
      <img src="{safe(rel)}" alt="{safe(title)}" loading="lazy">
    </a>
    <figcaption>{safe(title)}</figcaption>
  </figure>
</section>
"""


def group_section(records: list[SimulationRecord], *, group: str, title: str, intro: str) -> str:
    return f"""
<section>
  <h2>{safe(title)}</h2>
  <p>{safe(intro)}</p>
  {comparison_table(records, group=group)}
</section>
"""


def interpretation_section() -> str:
    return """
<section>
  <h2>Lecture des ecarts regulier / irregulier</h2>
  <p>Les fortes differences viennent surtout du support geometrique utilise pour porter les sorties de nappe et pour mesurer les distances.</p>
  <div class="cards">
    <article><h3>Grilles regulieres</h3><p>Les cellules carrees echantillonnent mal les lignes fines de vallee. Les centres de cellules actifs peuvent etre loin du reseau observe, ce qui augmente surtout calc &rarr; obs.</p></article>
    <article><h3>Maillages triangulaires</h3><p>Le maillage contraint par le reseau et le maillage irregulier suivent mieux la geometrie du bassin. Les mailles actives restent plus proches des lignes observees.</p></article>
    <article><h3>Signal dans le ratio</h3><p>Un ratio proche de 1 indique une erreur assez symetrique. Un ratio proche de 3 indique que le calcule est beaucoup plus disperse que l'observe.</p></article>
  </div>
</section>
"""


def metric_synthesis_section() -> str:
    if not METRIC_SYNTHESIS_FIGURE_PATH.exists():
        return ""
    rel = relative_path(METRIC_SYNTHESIS_FIGURE_PATH)
    title = "Synthese des distances au reseau observe"
    return f"""
<section>
  <h2>Synthese des metriques</h2>
  <p>La figure compare, pour chaque configuration, les deux diagnostics de reseau avec la distance moyenne symetrique et le ratio directionnel.</p>
  <figure class="wide-figure synthesis-figure">
    <a href="{safe(rel)}" class="figure-link" data-lightbox-src="{safe(rel)}" data-lightbox-title="{safe(title)}" title="Cliquer pour agrandir">
      <img src="{safe(rel)}" alt="{safe(title)}" loading="lazy">
    </a>
    <figcaption>{safe(title)}</figcaption>
  </figure>
</section>
"""


def links_section() -> str:
    manifest = read_json(COMPARISON_ROOT / "comparison_manifest.json")
    report = COMPARISON_ROOT / "web" / "index.html"
    audit = COMPARISON_ROOT / "comparison_audit.md"
    report_item = (
        f'<a href="{safe(relative_path(report))}">Rapport HTML complet</a>'
        if report.exists()
        else "Rapport HTML complet non encore produit"
    )
    audit_item = (
        f'<a href="{safe(relative_path(audit))}">Audit de comparaison</a>'
        if audit.exists()
        else "Audit de comparaison non encore produit"
    )
    return f"""
<section>
  <h2>Sorties completes</h2>
  <p>Cette page est volontairement compacte. Les artefacts complets restent disponibles dans le dossier de comparaison.</p>
  <ul>
    <li>{report_item}</li>
    <li>{audit_item}</li>
    <li><code>{safe(str(COMPARISON_ROOT))}</code></li>
    <li>statut audit: <strong>{safe(manifest.get("audit_status", "non lance"))}</strong></li>
  </ul>
</section>
"""


def lightbox_markup() -> str:
    return """
<div class="lightbox" id="figure-lightbox" hidden>
  <button type="button" class="lightbox-close">Fermer</button>
  <img alt="">
  <p></p>
</div>
"""


def lightbox_script() -> str:
    return """
<script>
(() => {
  const lightbox = document.getElementById("figure-lightbox");
  if (!lightbox) return;
  const image = lightbox.querySelector("img");
  const caption = lightbox.querySelector("p");
  const closeButton = lightbox.querySelector("button");
  const close = () => {
    lightbox.hidden = true;
    image.removeAttribute("src");
    caption.textContent = "";
  };
  document.querySelectorAll("[data-lightbox-src]").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      image.src = link.dataset.lightboxSrc;
      image.alt = link.dataset.lightboxTitle || "";
      caption.textContent = link.dataset.lightboxTitle || "";
      lightbox.hidden = false;
    });
  });
  closeButton.addEventListener("click", close);
  lightbox.addEventListener("click", (event) => {
    if (event.target === lightbox) close();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !lightbox.hidden) close();
  });
})();
</script>
"""


def css() -> str:
    return """
:root {
  color-scheme: light;
  --text: #1f2933;
  --muted: #627080;
  --line: #d8dee6;
  --soft: #f5f7fa;
  --panel: #ffffff;
  --accent-soft: #d7edf1;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: Arial, Helvetica, sans-serif;
  color: var(--text);
  background: #eef2f5;
}
main {
  max-width: 1320px;
  margin: 0 auto;
  padding: 28px;
}
h1 { margin: 0 0 8px; font-size: 30px; }
h2 { margin: 30px 0 10px; font-size: 21px; }
h3 { margin: 20px 0 8px; font-size: 15px; }
p { max-width: 980px; line-height: 1.45; color: var(--muted); }
a { color: #0f5f6f; }
section {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 18px;
  margin: 16px 0;
}
.cards {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}
article {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 14px;
  background: var(--soft);
}
article h3 { margin-top: 0; }
table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
  font-size: 14px;
}
.comparison-table th:nth-child(1) { width: 24%; }
.comparison-table th:nth-child(2),
.comparison-table th:nth-child(3) { width: 38%; }
th, td {
  border-bottom: 1px solid var(--line);
  padding: 10px 9px;
  text-align: left;
  vertical-align: top;
}
th {
  color: #33404d;
  background: var(--soft);
  font-weight: 700;
}
th span, .sub {
  display: block;
  color: var(--muted);
  font-size: 12px;
  font-weight: 400;
  margin-top: 3px;
}
.missing { color: var(--muted); background: #fafafa; }
.bar {
  height: 6px;
  border-radius: 999px;
  background: var(--accent-soft);
  margin: 0 0 6px;
}
.method-cell p {
  margin: 4px 0 9px;
  font-size: 12px;
  line-height: 1.35;
}
.method-title {
  font-weight: 700;
  color: #26313c;
}
figure {
  margin: 0;
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
}
img { display: block; width: 100%; height: auto; }
.figure-link {
  display: block;
  cursor: zoom-in;
}
figcaption {
  padding: 9px 11px;
  color: var(--muted);
  font-size: 13px;
}
.wide-figure {
  max-width: 720px;
}
.figure-missing {
  color: var(--muted);
  background: repeating-linear-gradient(
    -45deg,
    #fafafa,
    #fafafa 8px,
    #f1f3f5 8px,
    #f1f3f5 16px
  );
  font-style: italic;
  text-align: center;
  vertical-align: middle;
  min-height: 140px;
  display: grid;
  place-items: center;
  border: 1px solid var(--line);
  border-radius: 8px;
}
.metric-box {
  margin-top: 9px;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 10px;
  background: #fbfcfd;
}
.metric-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}
.metric-grid span {
  display: block;
  color: var(--muted);
  font-size: 11px;
}
.metric-grid strong {
  font-size: 16px;
}
.metric-foot {
  margin-top: 7px;
  color: var(--muted);
  font-size: 12px;
}
.lightbox {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  gap: 10px;
  padding: 18px;
  background: rgba(15, 23, 32, 0.82);
}
.lightbox[hidden] { display: none; }
.lightbox img {
  max-width: min(1400px, 96vw);
  max-height: 84vh;
  width: auto;
  height: auto;
  align-self: center;
  justify-self: center;
  border-radius: 8px;
  background: #fff;
}
.lightbox p {
  justify-self: center;
  margin: 0;
  color: #fff;
}
.lightbox-close {
  justify-self: end;
  border: 1px solid rgba(255, 255, 255, 0.5);
  border-radius: 6px;
  padding: 7px 10px;
  color: #fff;
  background: rgba(255, 255, 255, 0.12);
  cursor: pointer;
}
@media (max-width: 900px) {
  main { padding: 14px; }
  .cards { grid-template-columns: 1fr; }
  table { display: block; overflow-x: auto; }
}
"""


def render_page(records: list[SimulationRecord]) -> str:
    if not any(record.release_distance or record.accumulation_distance for record in records):
        not_run = """
<section>
  <h2>Pas encore de sorties</h2>
  <p>Le benchmark n'a pas encore ete execute, ou les CSV de comparaison ne sont pas presents. Lancez le script principal pour produire les simulations et cette page.</p>
</section>
"""
    else:
        not_run = ""
    return f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Nancon - benchmark physique reseau</title>
  <style>{css()}</style>
</head>
<body>
<main>
  <h1>Nancon - benchmark physique reseau</h1>
  <p>Page compacte pour comparer les diagnostics de sorties de nappe au reseau observe, en separant l'effet solveur et l'effet maillage.</p>
  {contract_section()}
  {recharge_section()}
  {not_run}
  {group_section(records, group="solveur_meme_maillage", title="Comparaison solveur sur le meme maillage", intro="Ici le support geometrique est identique. La colonne de droite route les emergences calculees vers l'aval avant comparaison au reseau observe.")}
  {group_section(records, group="sensibilite_maillage_mf6", title="Sensibilite au maillage avec MF6", intro="Ici le solveur et la physique MF6 sont fixes. Les differences restantes doivent venir principalement du support numerique et du routage sur ce support.")}
  {interpretation_section()}
  {metric_synthesis_section()}
  {links_section()}
</main>
{lightbox_markup()}
{lightbox_script()}
</body>
</html>
"""


def build_page() -> Path:
    records = records_by_simulation()
    generated_metrics = generate_release_accumulation_distance_metrics(records)
    generated_recharge = generate_recharge_figure()
    generated_synthesis = generate_metric_synthesis_figure(records)
    generated = generate_field_figures(records)
    PAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PAGE_PATH.write_text(render_page(records), encoding="utf-8")
    print(f"Wrote {PAGE_PATH}")
    print(f"Rows: {len(records)}")
    print(f"Release-accumulation metric rows generated: {generated_metrics}")
    print(f"Recharge figure generated: {generated_recharge}")
    print(f"Metric synthesis figure generated: {generated_synthesis}")
    print(f"Field figures generated: {generated}")
    return PAGE_PATH


def main() -> None:
    build_page()


if __name__ == "__main__":
    main()
