"""Build a compact HTML synthesis for the Nancon network benchmark."""

from __future__ import annotations

import csv
import html
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

HERE = Path(__file__).resolve().parent
BENCHMARK_ROOT = HERE / "outputs" / "nancon_network_physical_benchmark"
COMPARISON_ROOT = BENCHMARK_ROOT / "comparison"
PAGE_PATH = BENCHMARK_ROOT / "web_synthesis" / "index.html"
FIGURE_ROOT = BENCHMARK_ROOT / "web_synthesis" / "field_figures"


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
    vector_network: dict[str, str] | None = None


SIMULATIONS: tuple[SimulationMeta, ...] = (
    SimulationMeta(
        "mf6_disv_drain_high",
        "MF6 DISV, drain fort",
        "solveur_meme_maillage",
        "Reference MF6 sur le maillage triangulaire Nancon.",
    ),
    SimulationMeta(
        "bouss_same_mesh_no_drain",
        "Boussinesq, meme maillage, drain nul",
        "solveur_meme_maillage",
        "Comparaison solveur sur le meme support, avec drainance Boussinesq nulle.",
    ),
    SimulationMeta(
        "mf6_regular_120_drain_high",
        "MF6 regulier 120, drain fort",
        "sensibilite_maillage_mf6",
        "Grille reguliere grossiere, physique MF6 identique.",
    ),
    SimulationMeta(
        "mf6_regular_180_drain_high",
        "MF6 regulier 180, drain fort",
        "sensibilite_maillage_mf6",
        "Grille reguliere plus dense, physique MF6 identique.",
    ),
    SimulationMeta(
        "mf6_irregular_250_drain_high",
        "MF6 irregulier 250 m, drain fort",
        "sensibilite_maillage_mf6",
        "Maillage irregularise genere, taille globale 250 m.",
    ),
    SimulationMeta(
        "mf6_irregular_350_drain_high",
        "MF6 irregulier 350 m, drain fort",
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
        for row in (record.release_distance, record.accumulation_distance):
            if not row:
                continue
            try:
                values.append(float(row["bidirectional_distance_mean_m"]))
            except (KeyError, TypeError, ValueError):
                pass
    return values


def distance_cell(row: dict[str, str] | None, max_distance: float) -> str:
    if row is None:
        return '<td class="missing">non disponible</td>'
    value = row.get("bidirectional_distance_mean_m", "")
    try:
        width = max(4.0, min(100.0, 100.0 * float(value) / max_distance))
    except (TypeError, ValueError, ZeroDivisionError):
        width = 0.0
    active = row.get("active_cell_count", "")
    precision = f'<span class="sub">cellules actives: {safe(active)}</span>' if active else ""
    return (
        "<td>"
        f'<div class="bar" style="width:{width:.1f}%"></div>'
        f'<strong>{safe(fmt_m(value))} m</strong>'
        f"{precision}"
        "</td>"
    )


def method_rows(records: list[SimulationRecord], *, group: str) -> str:
    rows = []
    for record in records:
        if record.meta.group != group:
            continue
        for method_key, method_label, row in (
            ("release", "sorties directes", record.release_distance),
            ("accumulation", "apres accumulation drain", record.accumulation_distance),
        ):
            if row is None:
                continue
            rows.append(
                "<tr>"
                f"<td>{safe(record.meta.label)}</td>"
                f'<td><span class="method {method_key}">{safe(method_label)}</span></td>'
                f"<td><strong>{safe(fmt_m(row.get('sim_to_network_distance_mean_m', '')))} m</strong></td>"
                f"<td><strong>{safe(fmt_m(row.get('network_to_sim_distance_mean_m', '')))} m</strong></td>"
                f"<td>{safe(fmt_number(row.get('planar_distance_ratio', ''), 3))}</td>"
                f"<td><strong>{safe(fmt_m(row.get('bidirectional_distance_mean_m', '')))} m</strong></td>"
                "</tr>"
            )
    if not rows:
        return '<tr><td colspan="6" class="missing">Aucune metrique disponible pour le moment.</td></tr>'
    return "".join(rows)


def main_table(records: list[SimulationRecord], *, group: str) -> str:
    max_distance = max(all_bidirectional_distances(records) or [1.0])
    rows = []
    for record in records:
        if record.meta.group != group:
            continue
        closure = record.closure.get("diagnostic", "")
        rows.append(
            "<tr>"
            f"<td><strong>{safe(record.meta.label)}</strong><span class=\"sub\">{safe(record.meta.purpose)}</span></td>"
            f"<td>{safe(record.solver or 'n/a')}<span class=\"sub\">{safe(record.mesh_mode or record.mesh_label)}</span></td>"
            f"<td>{safe(closure or 'n/a')}</td>"
            f"{distance_cell(record.release_distance, max_distance)}"
            f"{distance_cell(record.accumulation_distance, max_distance)}"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="5" class="missing">Aucune simulation dans ce groupe.</td></tr>')
    return f"""
<table>
  <thead>
    <tr>
      <th>configuration calculee</th>
      <th>support</th>
      <th>bilan</th>
      <th>sorties directes<br><span>release_flux, moyenne sym.</span></th>
      <th>apres accumulation<br><span>accumulation_flux, moyenne sym.</span></th>
    </tr>
  </thead>
  <tbody>{''.join(rows)}</tbody>
</table>
"""


def detailed_table(records: list[SimulationRecord], *, group: str) -> str:
    return f"""
<table class="dense">
  <thead>
    <tr>
      <th>configuration calculee</th>
      <th>methode</th>
      <th>calc &rarr; obs moy.</th>
      <th>obs &rarr; calc moy.</th>
      <th>ratio<br><span>calc &rarr; obs / obs &rarr; calc</span></th>
      <th>moyenne sym.</th>
    </tr>
  </thead>
  <tbody>{method_rows(records, group=group)}</tbody>
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
    from hydromodpy.display._map_axes import overlay_watershed_contour
    from hydromodpy.display.figures.hydrographic_network import _project_gdf_for_metric_operations

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
    overlay_watershed_contour(ax, run, color="#404040", linewidth=0.9, alpha=0.65)


def _render_log_flux_figure(run, *, variable: str, title: str, save_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    import numpy as np

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
    render_face_field(
        ax,
        run,
        values,
        cmap="viridis",
        vmin=vmin,
        vmax=vmax,
        cbar_label="log10 flux moyen positif",
    )
    _overlay_reference(ax, run)
    style_map_axes(ax)
    ax.set_title(title)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def figure_path(record: SimulationRecord, variable: str) -> Path:
    return FIGURE_ROOT / record.meta.simulation_id / f"{variable}_log_intensity.png"


def generate_field_figures(records: list[SimulationRecord]) -> int:
    try:
        from hydromodpy.results.catalog import SimulationCatalog
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
            catalog = SimulationCatalog(resolve_recorded_path(run_folder))
            run = catalog[str(sim_id)]
            for variable, title in (
                ("release_flux", "release_flux - intensite moyenne positive"),
                ("accumulation_flux", "accumulation_flux - intensite moyenne positive"),
                (
                    "release_accumulation_flux",
                    "release_accumulation_flux - intensite moyenne positive",
                ),
            ):
                if not run.has_field(variable) or not run.has_hydrographic_network("reference"):
                    continue
                out = figure_path(record, variable)
                if not out.exists():
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


def figure_cell(record: SimulationRecord, variable: str, label: str) -> str:
    path = figure_path(record, variable)
    if not path.exists():
        return '<td class="figure-missing">non disponible</td>'
    return (
        "<td>"
        '<figure class="table-figure">'
        f'<img src="{safe(relative_path(path))}" alt="{safe(record.meta.label)} {safe(label)}">'
        f"<figcaption>{safe(label)}</figcaption>"
        "</figure>"
        "</td>"
    )


def figures_section(records: list[SimulationRecord], *, group: str) -> str:
    rows = []
    for record in records:
        if record.meta.group != group:
            continue
        rows.append(
            "<tr>"
            f"<td><strong>{safe(record.meta.label)}</strong></td>"
            + figure_cell(record, "release_flux", "sorties directes")
            + figure_cell(record, "accumulation_flux", "accumulation drain")
            + figure_cell(record, "release_accumulation_flux", "routage release")
            + "</tr>"
        )
    if not rows:
        return ""
    return f"""
<table class="figure-table">
  <thead>
    <tr>
      <th>configuration calculee</th>
      <th>release_flux</th>
      <th>accumulation_flux</th>
      <th>release_accumulation_flux</th>
    </tr>
  </thead>
  <tbody>{''.join(rows)}</tbody>
</table>
"""


def contract_section() -> str:
    return """
<section>
  <h2>Contrat physique commun</h2>
  <div class="cards">
    <article><h3>Temps et recharge</h3><p>Transitoire mensuel du 2020-10-01 au 2021-09-30, meme chronique synthetique mensuelle.</p></article>
    <article><h3>Hydraulique</h3><p>K = 5e-5 m/s, Ss = 1e-5 m-1, Sy = 0.05, epaisseur = 30 m.</p></article>
    <article><h3>Condition initiale</h3><p>Etat permanent sous recharge moyenne, avec la meme regle pour chaque simulation.</p></article>
    <article><h3>Drainage MF6</h3><p>Conductance top elevee: 1.0e-3 m2/s.</p></article>
    <article><h3>Drainage Boussinesq</h3><p>Conductance nulle: 0.0 m2/s. La sortie calculee vient donc du surface excess.</p></article>
    <article><h3>Distances</h3><p>Distances continues, sans categorisation: calcule vers observe, observe vers calcule, puis moyenne symetrique.</p></article>
  </div>
</section>
"""


def group_section(records: list[SimulationRecord], *, group: str, title: str, intro: str) -> str:
    return f"""
<section>
  <h2>{safe(title)}</h2>
  <p>{safe(intro)}</p>
  {main_table(records, group=group)}
  <h3>Distances detaillees</h3>
  {detailed_table(records, group=group)}
  <h3>Cartes de flux</h3>
  {figures_section(records, group=group)}
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
    <li>statut audit: <strong>{safe(manifest.get('audit_status', 'non lance'))}</strong></li>
  </ul>
</section>
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
.dense { font-size: 13px; }
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
.method {
  display: inline-block;
  border-radius: 999px;
  padding: 3px 8px;
  background: var(--soft);
  border: 1px solid var(--line);
}
.method.release { background: #e6f4ea; border-color: #b7dfc4; }
.method.accumulation { background: #e8eefb; border-color: #c9d7f2; }
figure {
  margin: 0;
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
}
img { display: block; width: 100%; height: auto; }
figcaption {
  padding: 9px 11px;
  color: var(--muted);
  font-size: 13px;
}
.figure-table { table-layout: fixed; }
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
}
@media (max-width: 900px) {
  main { padding: 14px; }
  .cards { grid-template-columns: 1fr; }
  table { display: block; overflow-x: auto; white-space: nowrap; }
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
  {not_run}
  {group_section(records, group="solveur_meme_maillage", title="Comparaison solveur sur le meme maillage", intro="Ici le support geometrique est identique. La difference volontaire restante est le traitement de la sortie de surface: drain fort dans MF6, drain nul dans Boussinesq.")}
  {group_section(records, group="sensibilite_maillage_mf6", title="Sensibilite au maillage avec MF6", intro="Ici le solveur et la physique MF6 sont fixes. Les differences restantes doivent venir principalement du support numerique et du routage sur ce support.")}
  {links_section()}
</main>
</body>
</html>
"""


def build_page() -> Path:
    records = records_by_simulation()
    generated = generate_field_figures(records)
    PAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PAGE_PATH.write_text(render_page(records), encoding="utf-8")
    print(f"Wrote {PAGE_PATH}")
    print(f"Rows: {len(records)}")
    print(f"Field figures generated: {generated}")
    return PAGE_PATH


def main() -> None:
    build_page()


if __name__ == "__main__":
    main()
