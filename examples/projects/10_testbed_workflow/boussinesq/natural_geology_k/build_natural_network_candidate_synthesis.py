"""Build compact network synthesis pages for the natural site-candidate testbed."""

from __future__ import annotations

import argparse
import html
import json
import os
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
    k_html = (
        "1 &times; 10<sup>-5</sup> m s<sup>-1</sup>"
        if variant_id.endswith("_low_k")
        else "5 &times; 10<sup>-5</sup> m s<sup>-1</sup>"
    )


def _is_large_case(case: dict[str, object]) -> bool:
    variant_id = str(case.get("variant_id") or "")
    axis = str(case.get("axis") or "")
    return "100km2" in variant_id or "100km2" in axis
    return (
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
    labels = {
        "site_01": "Site 01",
        "site_05": "Site 05",
        "site_02_low_k": "Site 02 / K faible",
        "site_03_low_k": "Site 03 / K faible",
        "headwater_100km2_outlet_2": "Headwater 100 km2 outlet 2",
        "s3_100km2_outlet_25": "Strahler 3 100 km2 outlet 25",
    }
    if variant_id in labels:
        return labels[variant_id]
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
    axis = str(case.get("axis") or "")
    axis_suffix = f" ({axis})" if axis else ""
    page_path = _case_page_path(case)
    return build_compact_network_synthesis(
        CompactNetworkSynthesisConfig(
            comparison_root=comparison_root,
            page_path=page_path,
            title=f"{label} - benchmark reseau naturel",
            intro=(
                f"Page compacte pour comparer les diagnostics de sorties de nappe "
                f"au reseau observe sur {label}{axis_suffix}."
            ),
            simulations=LARGE_SITE_SIMULATIONS if _is_large_case(case) else SIMULATIONS,
            group_sections=LARGE_SITE_GROUP_SECTIONS if _is_large_case(case) else GROUP_SECTIONS,
            contract_cards=_contract_cards_for_case(case),
            interpretation_cards=INTERPRETATION_CARDS,
            base_config=BASE_SIMULATION_CONFIG,
            comparison_id=str(case.get("comparison_id") or comparison_root.name),
        )
    )


def _write_index(pages: list[tuple[dict[str, object], Path]]) -> Path:
    WEB_ROOT.mkdir(parents=True, exist_ok=True)
    rows = []
    for case, page in pages:
        label = str(case.get("variant_label") or case.get("variant_id") or page.parent.name)
        status = str(case.get("status") or "")
        audit = str(case.get("audit_status") or "")
        rel = _relative(page, WEB_ROOT)
        rows.append(
            "<tr>"
            f"<td><a href=\"{html.escape(rel)}\">{html.escape(label)}</a></td>"
            f"<td>{html.escape(str(case.get('axis') or ''))}</td>"
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
      <thead><tr><th>site</th><th>taille</th><th>execution</th><th>audit</th></tr></thead>
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


def build_pages(manifest_path: Path = MANIFEST_PATH) -> list[Path]:
    manifest = _read_json(manifest_path)
    cases_by_id: dict[str, dict[str, object]] = {}
    pages: list[tuple[dict[str, object], Path]] = []
    for case in manifest.get("cases", []):
        if not isinstance(case, dict) or case.get("status") != "ok":
            continue
        cases_by_id[str(case.get("variant_id") or case.get("comparison_id"))] = case

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
