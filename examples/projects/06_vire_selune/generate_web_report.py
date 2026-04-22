from __future__ import annotations

import csv
import json
import math
import shutil
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from matplotlib.collections import LineCollection, PolyCollection
from rasterio.plot import show as rio_show

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.solver.utils.mesh.gmsh_grid.catchment_mesh_bundle_reader import (  # noqa: E402
    load_catchment_mesh_bundle,
)

WEB_DIR = ROOT / "web"
ASSETS_DIR = WEB_DIR / "assets"


@dataclass(frozen=True)
class CatchmentCase:
    slug: str
    label: str
    outlet_x: float
    outlet_y: float
    area_km2: float
    nwt_run_dir: Path
    irregular_root: Path
    nwt_run_toml: Path
    irregular_toml: Path


CASES = (
    CatchmentCase(
        slug="vire",
        label="Vire",
        outlet_x=400866.1983,
        outlet_y=6923974.693,
        area_km2=1258.2,
        nwt_run_dir=ROOT
        / "outputs"
        / "vire_nwt_steady"
        / "results_simulations"
        / "vire_nwt_steady",
        irregular_root=ROOT / "outputs" / "vire_mf6_irregular_steady",
        nwt_run_toml=ROOT / "run_vire_nwt_steady.toml",
        irregular_toml=ROOT / "run_vire_mf6_irregular_steady.toml",
    ),
    CatchmentCase(
        slug="selune",
        label="Selune",
        outlet_x=379541.3716,
        outlet_y=6845659.878,
        area_km2=366.9,
        nwt_run_dir=ROOT
        / "outputs"
        / "selune_nwt_steady"
        / "results_simulations"
        / "selune_nwt_steady",
        irregular_root=ROOT / "outputs" / "selune_mf6_irregular_steady",
        nwt_run_toml=ROOT / "run_selune_nwt_steady.toml",
        irregular_toml=ROOT / "run_selune_mf6_irregular_steady.toml",
    ),
)


def _load_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _ensure_dirs() -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)


def _copy_result_figures(case: CatchmentCase) -> dict[str, str]:
    figures_dir = case.nwt_run_dir / "_postprocess" / "_figures"
    wanted = {
        "dem_overview": figures_dir / "dem_overview.png",
        "hydrography": figures_dir / "hydrography.png",
        "recharge_discharge_cumulative": figures_dir / "recharge_discharge_cumulative.png",
        "seepage_areas": figures_dir / "seepage_areas.png",
        "watertable_depth": figures_dir / "watertable_depth.png",
        "watertable_elevation": figures_dir / "watertable_elevation.png",
    }
    copied: dict[str, str] = {}
    for key, source in wanted.items():
        target = ASSETS_DIR / f"{case.slug}_{key}.png"
        shutil.copy2(source, target)
        copied[key] = f"assets/{target.name}"
    return copied


def _mesh_context(case: CatchmentCase) -> dict[str, Path]:
    root = case.irregular_root / "results_stable"
    return {
        "bundle_dir": root / "mesh" / "mesh_catchment_bundle",
        "mesh_summary": root / "mesh" / "mesh_catchment_summary.json",
        "watershed_shp": root / "geographic" / "watershed.shp",
        "watershed_box_buff_dem": root / "geographic" / "watershed_box_buff_dem.tif",
        "river_network_shp": root / "geographic" / "river_network.shp",
        "outlet_shp": root / "geographic" / "outlet.shp",
    }


def _poly_and_line_data(bundle_dir: Path):
    bundle = load_catchment_mesh_bundle(bundle_dir)
    vertices = np.asarray(bundle.node_coordinates(), dtype=float)
    polygons = [vertices[list(nodes)] for nodes in bundle.cell_connectivity()]
    geology_keys = [cell.geology_key or "NA" for cell in bundle.cells]
    geology_order = sorted(set(geology_keys))
    geology_index = {key: idx for idx, key in enumerate(geology_order)}
    geology_values = np.asarray([geology_index[key] for key in geology_keys], dtype=float)

    river_lines: list[np.ndarray] = []
    interface_lines: list[np.ndarray] = []
    for edge in bundle.edges:
        seg = vertices[[edge.node_a, edge.node_b], :]
        if edge.is_river:
            river_lines.append(seg)
        if (edge.geology_a_key or "") != (edge.geology_b_key or ""):
            interface_lines.append(seg)
    return vertices, polygons, geology_order, geology_values, river_lines, interface_lines


def _render_mesh_overview(case: CatchmentCase) -> str:
    ctx = _mesh_context(case)
    vertices, polygons, geology_order, geology_values, river_lines, interface_lines = (
        _poly_and_line_data(ctx["bundle_dir"])
    )
    watershed = gpd.read_file(ctx["watershed_shp"])

    fig, ax = plt.subplots(figsize=(11.5, 8.5), constrained_layout=True)
    poly = PolyCollection(
        polygons,
        array=geology_values,
        cmap="tab20",
        edgecolors="0.55",
        linewidths=0.18,
        alpha=0.96,
    )
    ax.add_collection(poly)
    if interface_lines:
        ax.add_collection(
            LineCollection(interface_lines, colors="white", linewidths=0.60, alpha=0.95)
        )
    if river_lines:
        ax.add_collection(
            LineCollection(river_lines, colors="#0a5f99", linewidths=0.90, alpha=0.95)
        )
    watershed.boundary.plot(ax=ax, color="black", linewidth=1.0, zorder=5)

    ax.set_title(f"{case.label} - maillage conforme geologie + rivieres", fontsize=14)
    ax.set_aspect("equal")
    ax.set_xlim(float(vertices[:, 0].min()), float(vertices[:, 0].max()))
    ax.set_ylim(float(vertices[:, 1].min()), float(vertices[:, 1].max()))
    ax.set_xticks([])
    ax.set_yticks([])
    cbar = fig.colorbar(poly, ax=ax, shrink=0.82, pad=0.01)
    cbar.set_ticks(np.arange(len(geology_order)) + 0.5)
    cbar.set_ticklabels(geology_order)
    cbar.ax.tick_params(labelsize=7)
    cbar.set_label("Geologie effective par maille", fontsize=9)

    out = ASSETS_DIR / f"{case.slug}_mesh_overview.png"
    fig.savefig(out, dpi=190, bbox_inches="tight")
    plt.close(fig)
    return f"assets/{out.name}"


def _render_mesh_regional(case: CatchmentCase) -> str:
    ctx = _mesh_context(case)
    _, polygons, _, geology_values, river_lines, _ = _poly_and_line_data(ctx["bundle_dir"])
    watershed = gpd.read_file(ctx["watershed_shp"])
    rivers = gpd.read_file(ctx["river_network_shp"])
    outlet = gpd.read_file(ctx["outlet_shp"])

    fig, ax = plt.subplots(figsize=(12.5, 8.5), constrained_layout=True)
    with rasterio.open(ctx["watershed_box_buff_dem"]) as src:
        rio_show(src, ax=ax, cmap="Greys_r")
    poly = PolyCollection(
        polygons,
        array=geology_values,
        cmap="tab20",
        edgecolors="none",
        linewidths=0.0,
        alpha=0.48,
    )
    ax.add_collection(poly)
    if river_lines:
        ax.add_collection(LineCollection(river_lines, colors="#0a5f99", linewidths=0.7, alpha=0.9))
    rivers.plot(ax=ax, color="#1d7fbf", linewidth=0.45, alpha=0.55)
    watershed.boundary.plot(ax=ax, color="black", linewidth=1.2)
    outlet.plot(ax=ax, color="#d94f2b", markersize=30, zorder=6)
    ax.set_title(f"{case.label} - contexte regional et geologie effective", fontsize=14)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])

    out = ASSETS_DIR / f"{case.slug}_mesh_regional.png"
    fig.savefig(out, dpi=190, bbox_inches="tight")
    plt.close(fig)
    return f"assets/{out.name}"


def _render_resurgence(case: CatchmentCase) -> tuple[str, int]:
    ctx = _mesh_context(case)
    vertices, polygons, _, geology_values, river_lines, _ = _poly_and_line_data(ctx["bundle_dir"])
    watershed = gpd.read_file(ctx["watershed_shp"])
    seepage_raster = case.nwt_run_dir / "_postprocess" / "_rasters" / "seepage_areas_t(0).tif"

    fig, ax = plt.subplots(figsize=(11.5, 8.5), constrained_layout=True)
    poly = PolyCollection(
        polygons,
        array=geology_values,
        cmap="tab20",
        edgecolors="0.50",
        linewidths=0.14,
        alpha=0.85,
    )
    ax.add_collection(poly)
    if river_lines:
        ax.add_collection(LineCollection(river_lines, colors="#0a5f99", linewidths=0.75, alpha=0.9))

    positive_cells = 0
    with rasterio.open(seepage_raster) as src:
        data = src.read(1)
        mask = np.isfinite(data) & (data > 0)
        positive_cells = int(mask.sum())
        masked = np.where(mask, data, np.nan)
        ax.imshow(
            masked,
            extent=(src.bounds.left, src.bounds.right, src.bounds.bottom, src.bounds.top),
            origin="upper",
            cmap="autumn_r",
            alpha=0.72,
        )

    watershed.boundary.plot(ax=ax, color="black", linewidth=1.0, zorder=5)
    ax.set_title(f"{case.label} - zones de resurgence simulees", fontsize=14)
    ax.set_aspect("equal")
    ax.set_xlim(float(vertices[:, 0].min()), float(vertices[:, 0].max()))
    ax.set_ylim(float(vertices[:, 1].min()), float(vertices[:, 1].max()))
    ax.set_xticks([])
    ax.set_yticks([])

    out = ASSETS_DIR / f"{case.slug}_resurgence_geology.png"
    fig.savefig(out, dpi=190, bbox_inches="tight")
    plt.close(fig)
    return f"assets/{out.name}", positive_cells


def _read_balance_percent(list_path: Path) -> float | None:
    text = list_path.read_text(encoding="utf-8", errors="ignore")
    marker = "PERCENT DISCREPANCY ="
    for line in text.splitlines():
        if marker in line:
            try:
                return float(line.split(marker, 1)[1].split()[0])
            except Exception:
                return None
    return None


def _read_run_status(list_path: Path) -> dict[str, str | bool]:
    text = list_path.read_text(encoding="utf-8", errors="ignore")
    failed = (
        "FAILURE TO MEET SOLVER CONVERGENCE CRITERIA" in text
        or "FAILED TO MEET SOLVER CONVERGENCE CRITERIA" in text
    )
    status = "exploratoire"
    note = "solution indicative issue du dernier etat ecrit par le solveur"
    if not failed:
        status = "a verifier"
        note = "pas d'echec explicite dans le list file, mais bilan a verifier"
    return {
        "failed": failed,
        "status": status,
        "note": note,
    }


def _load_mesh_metrics(summary_path: Path) -> dict[str, int | str]:
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    return {
        "n_nodes": int(data.get("n_nodes", 0) or 0),
        "n_cells": int(data.get("n_cells", 0) or 0),
        "constraints_mode": str(data.get("constraints_mode", "")),
    }


def _load_k_reference(csv_path: Path) -> dict[str, float | int | str]:
    rows: list[dict[str, str]] = []
    with csv_path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append(row)
    k_values = [float(row["K_value"]) for row in rows if row.get("K_value")]
    return {
        "n_rows": len(rows),
        "k_min": min(k_values) if k_values else math.nan,
        "k_max": max(k_values) if k_values else math.nan,
        "dataset_note": rows[0].get("dataset_note", "") if rows else "",
        "source_doc": rows[0].get("source_doc", "") if rows else "",
    }


def _case_payload(case: CatchmentCase) -> dict:
    base_cfg = _load_toml(ROOT / "project_simulation_steady.toml")
    nwt_cfg = _load_toml(case.nwt_run_toml)
    irr_cfg = _load_toml(case.irregular_toml)
    mesh_ctx = _mesh_context(case)

    figures = _copy_result_figures(case)
    figures["mesh_overview"] = _render_mesh_overview(case)
    figures["mesh_regional"] = _render_mesh_regional(case)
    figures["resurgence_geology"], resurgence_cells = _render_resurgence(case)

    mesh_metrics = _load_mesh_metrics(mesh_ctx["mesh_summary"])
    recharge_source = base_cfg["data"]["recharge"]["sources"][0]
    recharge_mm_day = float(recharge_source["values"][0])
    recharge_mm_year = recharge_mm_day * 365.25

    k_cfg = base_cfg["flow"]["param"]["K"]
    k_csv_rel = Path(k_cfg["field_heterogeneous"]["values_csv_file"])
    k_reference = _load_k_reference((ROOT / k_csv_rel).resolve())

    run_id = nwt_cfg["simulation"]["run_id"]
    list_path = case.nwt_run_dir / f"{run_id}.list"
    run_status = _read_run_status(list_path)

    return {
        "slug": case.slug,
        "label": case.label,
        "area_km2": case.area_km2,
        "outlet_x": case.outlet_x,
        "outlet_y": case.outlet_y,
        "figures": figures,
        "mesh_nodes": mesh_metrics["n_nodes"],
        "mesh_cells": mesh_metrics["n_cells"],
        "constraints_mode": mesh_metrics["constraints_mode"],
        "resurgence_cells": resurgence_cells,
        "balance_percent": _read_balance_percent(list_path),
        "run_status": run_status["status"],
        "run_status_note": run_status["note"],
        "run_failed": run_status["failed"],
        "recharge_mm_day": recharge_mm_day,
        "recharge_mm_year": recharge_mm_year,
        "runoff_ratio": recharge_source["runoff_ratio"],
        "k_kind": k_cfg["field"]["kind"],
        "k_csv_rel": k_csv_rel.as_posix(),
        "k_table_rows": k_reference["n_rows"],
        "k_table_min": k_reference["k_min"],
        "k_table_max": k_reference["k_max"],
        "k_dataset_note": k_reference["dataset_note"],
        "k_source_doc": k_reference["source_doc"],
        "ss_value": base_cfg["flow"]["param"]["Ss"]["field_homogeneous"]["value"],
        "sy_value": base_cfg["flow"]["param"]["Sy"]["field_homogeneous"]["value"],
        "thickness": base_cfg["domain"]["depth_model"]["thickness"],
        "nlay_nwt": nwt_cfg["modflownwt"]["sgrid"]["vertical"]["nlay"],
        "nlay_irregular": irr_cfg["modflow6"]["sgrid"]["vertical"]["nlay"],
        "nwt_planar_mode": nwt_cfg.get("modflownwt", {})
        .get("sgrid", {})
        .get("planar", {})
        .get("mode", "keep_native"),
        "nwt_nx": nwt_cfg.get("modflownwt", {}).get("sgrid", {}).get("planar", {}).get("nx"),
        "nwt_ny": nwt_cfg.get("modflownwt", {}).get("sgrid", {}).get("planar", {}).get("ny"),
        "sim_dir_rel": case.nwt_run_dir.relative_to(ROOT).as_posix(),
        "mesh_dir_rel": (case.irregular_root / "results_stable" / "mesh")
        .relative_to(ROOT)
        .as_posix(),
    }


def _html_for_case(case: dict) -> str:
    balance = "n/a" if case["balance_percent"] is None else f"{case['balance_percent']:.4f} %"
    nwt_planar = case["nwt_planar_mode"]
    if case["nwt_nx"] and case["nwt_ny"]:
        nwt_planar = f"{nwt_planar} ({case['nwt_nx']} x {case['nwt_ny']})"
    return f"""
    <section class="case-block" id="{case["slug"]}">
      <div class="case-header">
        <div>
          <h2>{case["label"]}</h2>
          <p class="deck">Simulation permanente de premier test: maillage conforme geology+rivers pour la lecture geometrique, et resultat NWT structure au statut <code>{case["run_status"]}</code>.</p>
        </div>
        <div class="meta">
          <span>{case["area_km2"]:.1f} km2</span>
          <span>Outlet ({case["outlet_x"]:.1f}, {case["outlet_y"]:.1f})</span>
        </div>
      </div>

      <div class="grid two">
        <article class="card">
          <h3>Parametres</h3>
          <table class="kv">
            <tr><th>Regime</th><td>permanent</td></tr>
            <tr><th>Recharge affichee</th><td>{case["recharge_mm_year"]:.0f} mm/an</td></tr>
            <tr><th>Recharge interne</th><td>{case["recharge_mm_day"]:.4f} mm/j</td></tr>
            <tr><th>Runoff ratio</th><td>{case["runoff_ratio"]}</td></tr>
            <tr><th>K</th><td>{case["k_kind"]} par geologie</td></tr>
            <tr><th>Table K</th><td><code>{case["k_csv_rel"]}</code></td></tr>
            <tr><th>Plage K table</th><td>{case["k_table_min"]:.1e} a {case["k_table_max"]:.1e} m/s</td></tr>
            <tr><th>Ss homogene</th><td>{case["ss_value"]}</td></tr>
            <tr><th>Sy homogene</th><td>{case["sy_value"]}</td></tr>
            <tr><th>Epaisseur aquifere</th><td>{case["thickness"]}</td></tr>
            <tr><th>Grille NWT</th><td>{nwt_planar}</td></tr>
            <tr><th>Couches NWT</th><td>{case["nlay_nwt"]}</td></tr>
            <tr><th>Couches MF6 irregular</th><td>{case["nlay_irregular"]}</td></tr>
            <tr><th>BC active</th><td>drainage top</td></tr>
            <tr><th>Statut run</th><td>{case["run_status"]}</td></tr>
            <tr><th>Discrepance bilan</th><td>{balance}</td></tr>
          </table>
        </article>

        <article class="card">
          <h3>Contexte</h3>
          <ul class="flat">
            <li>DEM regional: <code>examples/data/dem/DEM_armorican_massif.tif</code></li>
            <li>Geologie: BRGM 1M, zonation effective projetee sur le maillage</li>
            <li>Conductivite heterogene: une valeur K par zone geologique via <code>{case["k_csv_rel"]}</code></li>
            <li>Document associe: <code>examples/data/geology/{case["k_source_doc"]}</code></li>
            <li>Statut du tableau K: <code>{case["k_dataset_note"]}</code></li>
            <li>Couverture de la table K: {case["k_table_rows"]} entrees</li>
            <li>Reseau hydrographique: derive du pretraitement geographic local</li>
            <li>Maillage conforme: <code>{case["constraints_mode"]}</code></li>
            <li>Maillage exporte: {case["mesh_nodes"]} noeuds, {case["mesh_cells"]} cellules</li>
            <li>Note solveur: {case["run_status_note"]}</li>
            <li>Run resultats: <code>{case["sim_dir_rel"]}</code></li>
            <li>Run maillage: <code>{case["mesh_dir_rel"]}</code></li>
          </ul>
        </article>
      </div>

      <div class="grid two figures">
        <figure class="card">
          <img src="{case["figures"]["mesh_overview"]}" alt="{case["label"]} mesh overview">
          <figcaption>Maillage conforme geology+rivers sur geologie effective, au format galerie d'exemple.</figcaption>
        </figure>
        <figure class="card">
          <img src="{case["figures"]["mesh_regional"]}" alt="{case["label"]} mesh regional">
          <figcaption>Contexte regional avec superposition du maillage et de la geologie effective.</figcaption>
        </figure>
        <figure class="card">
          <img src="{case["figures"]["resurgence_geology"]}" alt="{case["label"]} resurgence">
          <figcaption>Zones de resurgence superposees a la geologie effective. Lecture indicative sous les parametres courants. Pixels positifs: {case["resurgence_cells"]}.</figcaption>
        </figure>
        <figure class="card">
          <img src="{case["figures"]["dem_overview"]}" alt="{case["label"]} dem overview">
          <figcaption>Vue du bassin et de son support topographique dans le contexte regional.</figcaption>
        </figure>
        <figure class="card">
          <img src="{case["figures"]["hydrography"]}" alt="{case["label"]} hydrography">
          <figcaption>Hydrographie extraite sur le bassin et support de simulation.</figcaption>
        </figure>
        <figure class="card">
          <img src="{case["figures"]["seepage_areas"]}" alt="{case["label"]} seepage">
          <figcaption>Carte de seepage/resurgence issue du post-traitement du run NWT steady.</figcaption>
        </figure>
        <figure class="card">
          <img src="{case["figures"]["watertable_depth"]}" alt="{case["label"]} watertable depth">
          <figcaption>Profondeur de nappe calculee sur le run permanent en l'etat.</figcaption>
        </figure>
      </div>
    </section>
    """


def build_report() -> Path:
    _ensure_dirs()
    cases = [_case_payload(case) for case in CASES]
    body = "\n".join(_html_for_case(case) for case in cases)
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Vire / Selune - Simulations permanentes</title>
  <style>
    :root {{
      --bg: #f3efe6;
      --panel: #fffdf8;
      --ink: #1f2a2c;
      --muted: #5e6b6d;
      --line: #d8d1c3;
      --accent: #0a5f99;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      background:
        radial-gradient(circle at top left, rgba(10,95,153,0.12), transparent 28%),
        radial-gradient(circle at top right, rgba(198,95,45,0.12), transparent 30%),
        var(--bg);
      color: var(--ink);
    }}
    .page {{
      max-width: 1360px;
      margin: 0 auto;
      padding: 32px 24px 80px;
    }}
    h1, h2, h3 {{
      margin: 0 0 12px;
      font-weight: 600;
      line-height: 1.05;
    }}
    h1 {{ font-size: 2.5rem; letter-spacing: -0.03em; }}
    h2 {{ font-size: 1.8rem; }}
    h3 {{ font-size: 1.05rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--accent); }}
    p {{ margin: 0 0 12px; color: var(--muted); }}
    .lead {{
      max-width: 940px;
      font-size: 1.04rem;
      line-height: 1.55;
      margin-bottom: 28px;
    }}
    .hero, .card {{
      background: rgba(255,253,248,0.92);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: 0 10px 24px rgba(31,42,44,0.07);
    }}
    .hero {{ padding: 28px; margin-bottom: 28px; }}
    .grid {{
      display: grid;
      gap: 18px;
    }}
    .grid.two {{
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }}
    .card {{
      padding: 18px;
      overflow: hidden;
    }}
    .case-block {{
      margin-top: 34px;
    }}
    .case-header {{
      display: flex;
      justify-content: space-between;
      gap: 18px;
      align-items: flex-start;
      margin-bottom: 16px;
    }}
    .meta {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}
    .meta span {{
      border: 1px solid var(--line);
      background: #f8f4eb;
      border-radius: 999px;
      padding: 7px 12px;
      color: var(--ink);
      font-size: 0.92rem;
    }}
    .kv {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.95rem;
    }}
    .kv th, .kv td {{
      text-align: left;
      padding: 8px 0;
      border-bottom: 1px solid #ece5d8;
      vertical-align: top;
    }}
    .kv th {{
      width: 48%;
      color: var(--muted);
      font-weight: 500;
    }}
    .flat {{
      margin: 0;
      padding-left: 18px;
      color: var(--muted);
      line-height: 1.5;
    }}
    figure {{ margin: 0; }}
    figure img {{
      display: block;
      width: 100%;
      height: auto;
      border-radius: 10px;
      border: 1px solid #e6dfd2;
      background: white;
    }}
    figcaption {{
      margin-top: 10px;
      font-size: 0.92rem;
      color: var(--muted);
      line-height: 1.45;
    }}
    code {{
      font-family: Consolas, "Courier New", monospace;
      font-size: 0.9em;
      color: var(--accent);
    }}
    .note {{
      margin-top: 12px;
      font-size: 0.92rem;
      color: var(--muted);
    }}
    @media (max-width: 980px) {{
      .grid.two {{
        grid-template-columns: 1fr;
      }}
      .case-header {{
        flex-direction: column;
      }}
      .meta {{
        justify-content: flex-start;
      }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <h1>Vire / Selune</h1>
      <p class="lead">
        Cette page assemble le contexte des simulations permanentes de premier test, les parametres retenus,
        les figures de resultats sur MODFLOW-NWT, et les figures de maillage conforme
        <code>geology_rivers</code> construites pour les deux bassins. La recharge est affichee en
        <code>mm/an</code> pour la lecture hydrologique, meme si l'entree interne reste un equivalent
        annuel moyen en <code>mm/j</code>. La conductivite hydraulique est heterogene, avec une valeur
        par geologie lue dans le tableau local du repo associe a la geologie BRGM.
      </p>
      <p class="note">
        Etat au 15 avril 2026: les runs <code>NWT steady</code> avec <code>K</code> heterogene par geologie ne sont pas encore
        numeriquement stabilises sur ces grands bassins. Les cartes de resultats affichees ici doivent donc etre lues
        comme des sorties exploratoires de premier test, tandis que les maillages conformes <code>MF6 irregular steady</code>
        restent le support geometrique de reference.
      </p>
      <p class="note">
        Note de reference K: le tableau <code>examples/data/geology/geology_K_dummy_demo.csv</code> est le fichier local
        de correspondance par geologie disponible dans ce repo. Il est explicitement marque
        <code>dummy_demo_not_for_scientific_use</code> dans sa documentation source.
      </p>
    </section>
    {body}
  </main>
</body>
</html>
"""
    out = WEB_DIR / "index.html"
    out.write_text(html, encoding="utf-8")
    return out


if __name__ == "__main__":
    path = build_report()
    print(path.resolve())
