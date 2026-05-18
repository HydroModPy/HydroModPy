"""Build compact network synthesis pages for the natural site-candidate testbed."""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import os
import shutil
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[5]))

from hydromodpy.analysis.comparison.web.compact_network_synthesis import (
    CompactNetworkSynthesisConfig,
    GroupSection,
    InfoCard,
    SimulationMeta,
    build_compact_network_synthesis,
    resolve_recorded_path,
)

HERE = Path(__file__).resolve().parent
OUTPUT_ROOT = (
    HERE
    / "../../outputs/boussinesq_natural_network_site_candidates_testbed"
).resolve()
MANIFEST_PATH = OUTPUT_ROOT / "testbed_manifest.json"
WEB_ROOT = OUTPUT_ROOT / "web_synthesis" / "network_candidates"
BASE_SIMULATION_CONFIG = HERE / "base_site_01_mf6_bouss_transient.toml"
SITE_CATALOG_PATH = HERE / "natural_network_site_candidates_sites.csv"
CONTEXT_WATERSHED_SNAP_DISTANCES_M = (1000, 4000, 8000, 10000)

SIMULATIONS: tuple[SimulationMeta, ...] = (
    SimulationMeta(
        "mf6_unstructured_reference",
        "MF6 maillage triangulaire contraint",
        "solveur_meme_maillage",
        mesh_summary="Maillage triangulaire contraint par le reseau observe",
        short_label="MF6 triangulaire",
    ),
    SimulationMeta(
        "bouss_unstructured_same_mesh",
        "Boussinesq meme maillage triangulaire",
        "solveur_meme_maillage",
        mesh_summary="Meme maillage triangulaire contraint par le reseau observe",
        short_label="Boussinesq triangulaire",
    ),
    SimulationMeta(
        "mf6_regular_120",
        "MF6 grille reguliere 120 x 120",
        "sensibilite_maillage_mf6",
        mesh_summary="Grille reguliere 120 x 120",
        short_label="MF6 regulier 120",
    ),
    SimulationMeta(
        "mf6_regular_180",
        "MF6 grille reguliere 180 x 180",
        "sensibilite_maillage_mf6",
        mesh_summary="Grille reguliere 180 x 180",
        short_label="MF6 regulier 180",
    ),
    SimulationMeta(
        "mf6_unstructured_350m",
        "MF6 maillage triangulaire 350 m",
        "sensibilite_maillage_mf6",
        mesh_summary="Maillage triangulaire genere, taille cible 350 m",
        short_label="MF6 triangulaire 350 m",
    ),
)

LARGE_SITE_SIMULATIONS: tuple[SimulationMeta, ...] = (
    SimulationMeta(
        "mf6_unstructured_reference",
        "MF6 maillage triangulaire preconstruit",
        "sensibilite_maillage_mf6",
        mesh_summary="Maillage triangulaire preconstruit contraint par le reseau",
        short_label="MF6 triangulaire",
    ),
    SimulationMeta(
        "mf6_regular_120",
        "MF6 grille reguliere 120 x 120",
        "sensibilite_maillage_mf6",
        mesh_summary="Grille reguliere 120 x 120",
        short_label="MF6 regulier 120",
    ),
    SimulationMeta(
        "mf6_regular_180",
        "MF6 grille reguliere 180 x 180",
        "sensibilite_maillage_mf6",
        mesh_summary="Grille reguliere 180 x 180",
        short_label="MF6 regulier 180",
    ),
)

GROUP_SECTIONS: tuple[GroupSection, ...] = (
    GroupSection(
        "solveur_meme_maillage",
        "Comparaison solveur sur le meme maillage",
        (
            "Ici le support geometrique est identique. Les differences restantes "
            "viennent principalement du solveur et du traitement de la sortie de nappe."
        ),
    ),
    GroupSection(
        "sensibilite_maillage_mf6",
        "Sensibilite au maillage avec MF6",
        (
            "Ici le solveur et la physique MF6 sont fixes. Les differences restantes "
            "doivent venir principalement du support numerique et du routage sur ce support."
        ),
    ),
)

LARGE_SITE_GROUP_SECTIONS: tuple[GroupSection, ...] = (
    GroupSection(
        "sensibilite_maillage_mf6",
        "Sensibilite au maillage avec MF6",
        (
            "Sur les grands bassins, cette page se limite aux configurations MF6 "
            "stables: maillage triangulaire preconstruit et grilles regulieres. "
            "La physique reste commune; la difference principale est le support numerique."
        ),
    ),
)

INTERPRETATION_CARDS: tuple[InfoCard, ...] = (
    InfoCard(
        "Grilles regulieres",
        (
            "Les cellules carrees echantillonnent mal les lignes fines de vallee. "
            "Les centres de cellules actifs peuvent etre loin du reseau observe, "
            "ce qui augmente surtout calc &rarr; obs."
        ),
    ),
    InfoCard(
        "Maillages triangulaires",
        (
            "Le maillage contraint par le reseau et le maillage triangulaire genere "
            "suivent mieux la geometrie du bassin. Les mailles actives restent plus "
            "proches des lignes observees."
        ),
    ),
    InfoCard(
        "Signal dans le ratio",
        (
            "Un ratio proche de 1 indique une erreur assez symetrique. Un ratio eleve "
            "indique que le calcule est plus disperse que l'observe."
        ),
    ),
)


def _contract_cards_for_case(case: dict[str, object]) -> tuple[InfoCard, ...]:
    variant_id = str(case.get("variant_id") or "")
    size_label = _case_size_label(case)
    k_html = (
        "1 &times; 10<sup>-5</sup> m s<sup>-1</sup>"
        if variant_id.endswith("_low_k")
        else "5 &times; 10<sup>-5</sup> m s<sup>-1</sup>"
    )
    return (
        InfoCard(
            "Taille du bassin",
            f"Bassin cible: {html.escape(size_label)}.",
        ),
        InfoCard(
            "Temps et recharge",
            "Transitoire mensuel avec la meme chronique synthetique pour toutes les configurations.",
        ),
        InfoCard(
            "Hydraulique",
            f"<i>K</i> = {k_html}; <i>S<sub>y</sub></i> = 0.05; epaisseur aquifere = 30 m.",
        ),
        InfoCard(
            "Condition initiale",
            "Etat permanent sous recharge moyenne, avec la meme regle pour chaque simulation.",
        ),
        InfoCard(
            "Distances",
            (
                "Distances continues: calcule vers observe, observe vers calcule, "
                "puis moyenne symetrique."
            ),
        ),
    )


def _is_large_case(case: dict[str, object]) -> bool:
    variant_id = str(case.get("variant_id") or "")
    axis = str(case.get("axis") or "")
    return "100km2" in variant_id or "100km2" in axis


def _site_catalog_rows() -> dict[str, dict[str, str]]:
    if not SITE_CATALOG_PATH.exists():
        return {}
    with SITE_CATALOG_PATH.open("r", encoding="utf-8", newline="") as stream:
        return {
            str(row.get("site_id") or ""): row
            for row in csv.DictReader(stream)
            if row.get("site_id")
        }


def _base_site_id(variant_id: str) -> str:
    if variant_id.endswith("_low_k"):
        return variant_id.removesuffix("_low_k")
    return variant_id


def _site_row_for_variant(variant_id: str) -> dict[str, str]:
    rows = _site_catalog_rows()
    return rows.get(variant_id) or rows.get(_base_site_id(variant_id)) or {}


def _site_row_for_case(case: dict[str, object]) -> dict[str, str]:
    variant_id = str(case.get("variant_id") or case.get("comparison_id") or "")
    return _site_row_for_variant(variant_id)


def _case_size_label(case: dict[str, object]) -> str:
    row = _site_row_for_case(case)
    raw_area = row.get("target_area_km2", "")
    try:
        area = float(raw_area)
    except (TypeError, ValueError):
        area = None
    if area is not None and area > 0.0:
        return f"{area:g} km2"
    cluster = row.get("cluster_scale", "")
    return cluster or str(case.get("axis") or "")


def _case_k_label(case: dict[str, object]) -> str:
    variant_id = str(case.get("variant_id") or case.get("comparison_id") or "")
    return "K faible" if variant_id.endswith("_low_k") else "K nominal"


def _resolve_catalog_path(raw_path: str) -> Path | None:
    text = str(raw_path or "").strip()
    if not text:
        return None
    path = Path(text)
    if not path.is_absolute():
        path = (SITE_CATALOG_PATH.parent / path).resolve()
    return path


def _watershed_area_km2(path: Path) -> float | None:
    if not path.exists():
        return None
    try:
        import geopandas as gpd

        gdf = gpd.read_file(path)
        if gdf.empty:
            return None
        if gdf.crs is not None and gdf.crs.is_geographic:
            gdf = gdf.to_crs("EPSG:2154")
        return float(gdf.geometry.area.sum()) / 1_000_000.0
    except Exception:
        return None


def _validated_context_watershed(
    path: Path,
    *,
    variant_id: str,
    target_area_km2: float | None,
) -> Path | None:
    if not path.exists():
        return None
    area_km2 = _watershed_area_km2(path)
    if area_km2 is None:
        print(f"[WARN] Could not validate context watershed for {variant_id}: {path}")
        return None

    if target_area_km2 and target_area_km2 > 0.0:
        min_area = 0.25 * target_area_km2
        max_area = 5.0 * target_area_km2
        if not min_area <= area_km2 <= max_area:
            print(
                "[WARN] Ignoring context watershed for "
                f"{variant_id}: area {area_km2:.2f} km2 is inconsistent "
                f"with target {target_area_km2:.2f} km2."
            )
            return None

    return path


def _expected_context_area_km2(row: dict[str, str]) -> float | None:
    bundle_dir = _resolve_catalog_path(row.get("mesh_bundle_dir", ""))
    if bundle_dir is not None:
        summary_path = bundle_dir / "mesh_summary.json"
        if summary_path.exists():
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                area_m2 = (
                    summary.get("watershed_boundary", {})
                    .get("boundary_area_source")
                )
                if area_m2:
                    return float(area_m2) / 1_000_000.0
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                pass
    try:
        return float(row.get("target_area_km2") or 0.0) or None
    except (TypeError, ValueError):
        return None


def _river_outlet_candidates_from_bundle(
    bundle_dir: Path,
    *,
    limit: int = 1,
) -> list[dict[str, float]]:
    nodes_path = bundle_dir / "nodes.csv"
    edges_path = bundle_dir / "edges.csv"
    if not nodes_path.exists() or not edges_path.exists():
        return []

    river_degree: dict[int, int] = {}
    with edges_path.open("r", encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            if str(row.get("is_river", "")).strip().lower() != "true":
                continue
            try:
                node_a = int(row["node_a"])
                node_b = int(row["node_b"])
            except (KeyError, TypeError, ValueError):
                continue
            river_degree[node_a] = river_degree.get(node_a, 0) + 1
            river_degree[node_b] = river_degree.get(node_b, 0) + 1

    endpoints = {node_id for node_id, degree in river_degree.items() if degree == 1}
    if not endpoints:
        return []

    candidates: list[dict[str, float]] = []
    with nodes_path.open("r", encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            try:
                node_id = int(row["node_id"])
            except (KeyError, TypeError, ValueError):
                continue
            if node_id not in endpoints:
                continue
            try:
                candidates.append(
                    {
                        "node_id": float(node_id),
                        "x": float(row["x"]),
                        "y": float(row["y"]),
                        "z_top": float(row.get("z_top") or 0.0),
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue

    candidates.sort(key=lambda item: item["z_top"])
    return candidates[:limit]


def _write_context_watershed_geojson(source_path: Path, target_path: Path) -> None:
    import geopandas as gpd

    gdf = gpd.read_file(source_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(target_path, driver="GeoJSON")


def _derive_context_watershed_from_mesh_bundle(
    *,
    row: dict[str, str],
    variant_id: str,
    expected_area_km2: float | None,
) -> Path | None:
    bundle_dir = _resolve_catalog_path(row.get("mesh_bundle_dir", ""))
    if bundle_dir is None or not bundle_dir.exists():
        return None

    context_root = WEB_ROOT / variant_id / "_context_watershed"
    final_path = context_root / "watershed.geojson"
    final_dem_path = context_root / "watershed_box_buff_dem.tif"
    validated = _validated_context_watershed(
        final_path,
        variant_id=variant_id,
        target_area_km2=expected_area_km2,
    )
    if validated is not None and final_dem_path.exists():
        return validated

    candidates = _river_outlet_candidates_from_bundle(bundle_dir)
    if not candidates:
        return None

    try:
        import hydromodpy as hmp
        from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
        from hydromodpy.spatial.geographic.pipeline import build_geographic_runtime_context

        base_cfg = hmp.HydroModPyConfig.from_toml(BASE_SIMULATION_CONFIG)
    except Exception as exc:
        print(f"[WARN] Could not prepare watershed derivation for {variant_id}: {exc}")
        return None

    best_path: Path | None = None
    best_dem_path: Path | None = None
    best_area: float | None = None
    best_score: float | None = None
    candidates_root = context_root / "_candidates"

    for candidate in candidates:
        node_id = int(candidate["node_id"])
        for snap_m in CONTEXT_WATERSHED_SNAP_DISTANCES_M:
            candidate_root = candidates_root / f"node_{node_id}_snap_{snap_m}m"
            try:
                geographic = GeographicConfig.from_outlet(
                    x=float(candidate["x"]),
                    y=float(candidate["y"]),
                    dem=base_cfg.geographic.dem_init_path,
                    snap_dist=f"{snap_m} m",
                    buff_area="1 m",
                    crs_project=base_cfg.geographic.crs_project,
                    dem_correc_type=base_cfg.geographic.dem_correc_type,
                    river_network={"enabled": False},
                    reuse_existing_outputs=True,
                )
                context = build_geographic_runtime_context(
                    config=geographic,
                    out_dir_path=candidate_root,
                )
                path = Path(context.paths.watershed_shp)
                raw_dem_path = getattr(context.paths, "watershed_box_buff_dem", None)
                dem_path = Path(raw_dem_path) if raw_dem_path else None
            except Exception as exc:
                print(
                    "[WARN] Could not derive context watershed candidate for "
                    f"{variant_id} node {node_id} snap {snap_m} m: {exc}"
                )
                continue

            area_km2 = _watershed_area_km2(path)
            if area_km2 is None or area_km2 <= 0.0:
                continue
            if expected_area_km2 and expected_area_km2 > 0.0:
                ratio = area_km2 / expected_area_km2
                if not 0.25 <= ratio <= 5.0:
                    continue
                score = abs(math.log(ratio))
            else:
                score = 0.0
            if best_score is None or score < best_score:
                best_path = path
                best_dem_path = (
                    dem_path
                    if dem_path is not None and dem_path.exists() and dem_path.is_file()
                    else None
                )
                best_area = area_km2
                best_score = score

    if best_path is None:
        return None

    try:
        _write_context_watershed_geojson(best_path, final_path)
        if best_dem_path is not None:
            shutil.copy2(best_dem_path, final_dem_path)
        metadata = {
            "source": "derived_from_mesh_bundle_river_endpoint",
            "mesh_bundle_dir": str(bundle_dir),
            "area_km2": best_area,
            "expected_area_km2": expected_area_km2,
            "topography_raster": str(final_dem_path) if final_dem_path.exists() else None,
        }
        (context_root / "watershed_context.json").write_text(
            json.dumps(metadata, indent=2),
            encoding="utf-8",
        )
        if candidates_root.exists():
            shutil.rmtree(candidates_root, ignore_errors=True)
    except Exception as exc:
        print(f"[WARN] Could not write context watershed for {variant_id}: {exc}")
        return None

    return _validated_context_watershed(
        final_path,
        variant_id=variant_id,
        target_area_km2=expected_area_km2,
    )


def _ensure_context_watershed(case: dict[str, object]) -> Path | None:
    if not _is_large_case(case):
        return None

    variant_id = str(case.get("variant_id") or "")
    row = _site_catalog_rows().get(variant_id)
    if not row:
        return None
    expected_area_km2 = _expected_context_area_km2(row)

    for key in ("context_watershed_path", "watershed_polygon_path", "watershed_path"):
        path = _resolve_catalog_path(row.get(key, ""))
        if path is None:
            continue
        return _validated_context_watershed(
            path,
            variant_id=variant_id,
            target_area_km2=expected_area_km2,
        )

    existing_paths = ()
    legacy_context_root = WEB_ROOT / variant_id / "_context_geographic"
    existing_paths += (
        legacy_context_root / ".solver_scratch" / "_preprocessing" / "geographic" / "watershed.shp",
        legacy_context_root / "geographic" / "watershed.shp",
    )
    for existing in existing_paths:
        if existing.exists():
            return _validated_context_watershed(
                existing,
                variant_id=variant_id,
                target_area_km2=expected_area_km2,
            )

    return _derive_context_watershed_from_mesh_bundle(
        row=row,
        variant_id=variant_id,
        expected_area_km2=expected_area_km2,
    )


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    return data if isinstance(data, dict) else {}


def _relative(path: Path, base: Path) -> str:
    return os.path.relpath(path, base).replace(os.sep, "/")


def _case_page_path(case: dict[str, object]) -> Path:
    variant_id = str(case.get("variant_id") or case.get("comparison_id") or "site")
    return WEB_ROOT / variant_id / "index.html"


def _label_from_variant_id(variant_id: str) -> str:
    row = _site_row_for_variant(variant_id)
    label = row.get("site_label", "")
    if label:
        return f"{label} / K faible" if variant_id.endswith("_low_k") else label
    return variant_id.replace("_natural_network_site_candidates", "").replace("_", " ")


def _axis_from_variant_id(variant_id: str) -> str:
    if variant_id.endswith("_low_k"):
        return "10km2_low_k"
    if "100km2" in variant_id:
        if variant_id.startswith("s3_"):
            return "s3_100km2"
        return "headwater_100km2"
    return ""


def _case_from_comparison_manifest(path: Path) -> dict[str, object]:
    manifest = _read_json(path)
    comparison_id = str(manifest.get("comparison_id") or path.parent.name)
    suffix = "_natural_network_site_candidates"
    variant_id = comparison_id[: -len(suffix)] if comparison_id.endswith(suffix) else comparison_id
    return {
        "variant_id": variant_id,
        "variant_label": _label_from_variant_id(variant_id),
        "axis": _axis_from_variant_id(variant_id),
        "status": "ok",
        "audit_status": str(manifest.get("audit_status") or ""),
        "comparison_id": comparison_id,
        "comparison_root": str(path.parent),
    }


def _build_case(case: dict[str, object]) -> Path | None:
    comparison_root_raw = str(case.get("comparison_root") or "")
    if not comparison_root_raw:
        return None
    comparison_root = resolve_recorded_path(comparison_root_raw)
    if not comparison_root.exists():
        return None
    variant_id = str(case.get("variant_id") or comparison_root.name)
    label = str(case.get("variant_label") or variant_id)
    size_label = _case_size_label(case)
    k_label = _case_k_label(case)
    page_path = _case_page_path(case)
    return build_compact_network_synthesis(
        CompactNetworkSynthesisConfig(
            comparison_root=comparison_root,
            page_path=page_path,
            title=f"{label} - {size_label} - benchmark reseau naturel",
            intro=(
                f"Page compacte pour comparer les diagnostics de sorties de nappe "
                f"au reseau observe sur {label}. Taille du bassin: "
                f"{size_label}; scenario hydraulique: {k_label}."
            ),
            simulations=LARGE_SITE_SIMULATIONS if _is_large_case(case) else SIMULATIONS,
            group_sections=LARGE_SITE_GROUP_SECTIONS if _is_large_case(case) else GROUP_SECTIONS,
            contract_cards=_contract_cards_for_case(case),
            interpretation_cards=INTERPRETATION_CARDS,
            base_config=BASE_SIMULATION_CONFIG,
            comparison_id=str(case.get("comparison_id") or comparison_root.name),
            context_watershed_path=_ensure_context_watershed(case),
        )
    )


def _write_index(pages: list[tuple[dict[str, object], Path]]) -> Path:
    WEB_ROOT.mkdir(parents=True, exist_ok=True)
    rows = []
    for case, page in sorted(pages, key=_case_sort_key):
        label = str(case.get("variant_label") or case.get("variant_id") or page.parent.name)
        size = _case_size_label(case)
        k_label = _case_k_label(case)
        status = str(case.get("status") or "")
        audit = str(case.get("audit_status") or "")
        rel = _relative(page, WEB_ROOT)
        rows.append(
            "<tr>"
            f"<td><a href=\"{html.escape(rel)}\">{html.escape(label)}</a></td>"
            f"<td>{html.escape(size)}</td>"
            f"<td>{html.escape(k_label)}</td>"
            f"<td>{html.escape(status)}</td>"
            f"<td>{html.escape(audit)}</td>"
            "</tr>"
        )
    index = WEB_ROOT / "index.html"
    index.write_text(
        f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Benchmark reseaux naturels - pages compactes</title>
  <style>
    body {{ margin: 0; font-family: Arial, Helvetica, sans-serif; color: #1f2933; background: #eef2f5; }}
    main {{ max-width: 900px; margin: 0 auto; padding: 28px; }}
    section {{ background: #fff; border: 1px solid #d8dee6; border-radius: 8px; padding: 18px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid #d8dee6; padding: 10px; text-align: left; }}
    th {{ background: #f5f7fa; }}
    a {{ color: #0f5f6f; }}
    p {{ color: #627080; }}
  </style>
</head>
<body>
<main>
  <h1>Benchmark reseaux naturels - pages compactes</h1>
  <p>Ces pages reprennent la disposition compacte du benchmark Nancon: reseaux observes/calcules, metriques de distance et synthese finale.</p>
  <section>
    <table>
      <thead><tr><th>site</th><th>taille</th><th>scenario</th><th>execution</th><th>audit</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </section>
</main>
</body>
</html>
""",
        encoding="utf-8",
    )
    return index


def _case_sort_key(item: tuple[dict[str, object], Path]) -> tuple[float, int, int, str]:
    case, page = item
    row = _site_row_for_case(case)
    try:
        area = float(row.get("target_area_km2") or 0.0)
    except (TypeError, ValueError):
        area = 0.0
    site_order = {
        site_id: index
        for index, site_id in enumerate(_site_catalog_rows().keys())
    }
    variant_id = str(case.get("variant_id") or page.parent.name)
    base_site_id = _base_site_id(variant_id)
    k_order = 1 if variant_id.endswith("_low_k") else 0
    return (area or 1.0e12, site_order.get(base_site_id, 1_000_000), k_order, variant_id)


def build_pages(manifest_path: Path = MANIFEST_PATH) -> list[Path]:
    manifest = _read_json(manifest_path)
    cases_by_id: dict[str, dict[str, object]] = {}
    pages: list[tuple[dict[str, object], Path]] = []
    for case in manifest.get("cases", []):
        if not isinstance(case, dict) or case.get("status") != "ok":
            continue
        cases_by_id[str(case.get("variant_id") or case.get("comparison_id"))] = case

    if not cases_by_id:
        comparisons_root = manifest_path.parent / "comparisons"
        for comparison_manifest in sorted(comparisons_root.glob("*/comparison_manifest.json")):
            case = _case_from_comparison_manifest(comparison_manifest)
            cases_by_id.setdefault(str(case["variant_id"]), case)

    for case in cases_by_id.values():
        page = _build_case(case)
        if page is not None:
            pages.append((case, page))
    index = _write_index(pages)
    return [index, *(page for _, page in pages)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=MANIFEST_PATH,
        help="Path to the testbed manifest. Defaults to the natural network candidate output.",
    )
    args = parser.parse_args(argv)
    pages = build_pages(args.manifest)
    for page in pages:
        print(page)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
