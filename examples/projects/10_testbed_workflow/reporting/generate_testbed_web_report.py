"""Generate reusable static HTML reports for testbed and regional-lab outputs.

The script is intentionally a post-processing layer: it does not build meshes,
does not run simulations, and does not require any extra output contract from
the numerical workflow. It reads the standard JSON/CSV/TOML artifacts already
written by ``hydromodpy.analysis.testbed``.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import os
import re
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback.
    tomllib = None  # type: ignore[assignment]

try:
    from hydromodpy.core.toml_io.loader import load_toml_with_base_config
except Exception:  # pragma: no cover - standalone fallback when HydroModPy is unavailable.
    load_toml_with_base_config = None  # type: ignore[assignment]


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".svg", ".webp"}
CLOSURE_STATUS_ORDER = {"OK": 0, "WARN": 1, "UNKNOWN": 2, "CHECK": 3}


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    output_root = args.output_root.resolve()
    web_root = _resolve_web_root(output_root, args.web_dir)
    site_catalog_rows = _read_csv(args.site_catalog) if args.site_catalog else []
    context = {
        "title": args.title,
        "site_catalog_path": args.site_catalog,
        "site_generation_config": args.site_generation_config,
        "site_generation_summary": args.site_generation_summary,
        "comparison_roots": args.comparison_root or [],
        "comparison_index_only": bool(args.comparison_index_only),
        "site_catalog_rows": site_catalog_rows,
        "site_generation_config_details": _summarize_site_generation_config(
            args.site_generation_config
        ),
        "site_generation_summary_details": _summarize_site_generation_summary(
            args.site_generation_summary
        ),
    }

    if (output_root / "testbed_manifest.json").is_file():
        written = render_testbed_report(output_root=output_root, web_root=web_root, context=context)
    elif (output_root / "regional_lab_report.json").is_file():
        written = render_regional_lab_report(
            output_root=output_root, web_root=web_root, context=context
        )
    else:
        raise SystemExit(
            "No supported report contract found. Expected testbed_manifest.json "
            "or regional_lab_report.json under the output root."
        )

    print(f"Wrote {len(written)} HTML files under {web_root}")
    print(f"Open {web_root / 'index.html'}")
    return 0


def render_testbed_report(
    *,
    output_root: Path,
    web_root: Path,
    context: Mapping[str, Any],
) -> list[Path]:
    manifest_path = output_root / "testbed_manifest.json"
    manifest = _read_json(manifest_path)
    cases_path = output_root / "testbed_cases.csv"
    metrics_path = output_root / "testbed_metrics.csv"
    report_md_path = output_root / "testbed_report.md"
    plan_path = output_root / "testbed_plan.json"
    cases = _read_csv(cases_path)
    if not cases:
        raw_cases = manifest.get("cases", [])
        cases = [dict(item) for item in raw_cases if isinstance(item, Mapping)]
    metrics = _read_csv(metrics_path)
    plan = _read_json(plan_path) if plan_path.is_file() else {}
    context = dict(context)
    site_catalog_path = _path_or_none(
        context.get("site_catalog_path") or manifest.get("site_catalog_path")
    )
    site_catalog_rows = list(context.get("site_catalog_rows") or [])
    if not site_catalog_rows and site_catalog_path is not None and site_catalog_path.is_file():
        site_catalog_rows = _read_csv(site_catalog_path)
    context["site_catalog_path"] = site_catalog_path
    context["site_catalog_rows"] = site_catalog_rows
    site_index = _index_site_catalog(site_catalog_rows)
    comparisons = _load_comparison_summaries(
        output_root=output_root,
        extra_roots=context.get("comparison_roots") or [],
    )

    enriched_cases = [
        _enrich_testbed_case(
            case,
            output_root=output_root,
            site_index=site_index,
            comparisons=comparisons,
        )
        for case in cases
    ]

    web_root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    if bool(context.get("comparison_index_only")):
        _remove_generated_case_pages(web_root)
    else:
        case_dir = web_root / "cases"
        case_dir.mkdir(parents=True, exist_ok=True)
        for case in enriched_cases:
            case_html = _render_testbed_case_page(
                case=case,
                output_root=output_root,
                web_root=web_root,
                page_dir=case_dir,
                context=context,
            )
            path = case_dir / f"{case['page_id']}.html"
            _write_text(path, case_html)
            written.append(path)

    index_html = _render_testbed_index(
        output_root=output_root,
        web_root=web_root,
        manifest=manifest,
        plan=plan,
        cases=enriched_cases,
        metrics=metrics,
        context=context,
        comparisons=comparisons,
        artifacts=[
            manifest_path,
            plan_path,
            cases_path,
            metrics_path,
            report_md_path,
            output_root / "_generated_configs",
        ],
    )
    index_path = web_root / "index.html"
    _write_text(index_path, index_html)
    written.insert(0, index_path)
    return written


def render_regional_lab_report(
    *,
    output_root: Path,
    web_root: Path,
    context: Mapping[str, Any],
) -> list[Path]:
    report_path = output_root / "regional_lab_report.json"
    report = _read_json(report_path)
    inventory_path = output_root / "regional_lab_site_inventory.csv"
    case_matrix_path = output_root / "regional_lab_case_matrix.csv"
    metrics_path = output_root / "regional_lab_execution_metrics.csv"
    summary_md_path = output_root / "regional_lab_summary.md"
    inventory = _read_csv(inventory_path)
    case_matrix = _read_csv(case_matrix_path)
    metrics = _read_csv(metrics_path)
    comparisons = _load_comparison_summaries(
        output_root=output_root,
        extra_roots=context.get("comparison_roots") or [],
    )

    if not inventory:
        selected = report.get("selected_sites", [])
        inventory = [dict(item) for item in selected if isinstance(item, Mapping)]
    if not case_matrix:
        raw_cases = report.get("cases", [])
        case_matrix = [dict(item) for item in raw_cases if isinstance(item, Mapping)]

    cases_by_site: dict[str, list[dict[str, str]]] = defaultdict(list)
    for case in case_matrix:
        site_id = _normalize_key(case.get("site_id")) or "unassigned"
        cases_by_site[site_id].append(case)

    web_root.mkdir(parents=True, exist_ok=True)
    site_dir = web_root / "sites"
    site_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for site in inventory:
        raw_site_id = _display_value(site.get("site_id") or site.get("id") or "site")
        page_id = _safe_page_id(raw_site_id)
        site_cases = cases_by_site.get(_normalize_key(raw_site_id) or "", [])
        html_text = _render_regional_lab_site_page(
            site=site,
            cases=site_cases,
            comparisons=_match_comparisons(
                case={
                    "variant_id": raw_site_id,
                    "variant_label": site.get("site_label"),
                    "page_id": page_id,
                    "site": site,
                },
                comparisons=comparisons,
            ),
            output_root=output_root,
            web_root=web_root,
            page_dir=site_dir,
            context=context,
        )
        path = site_dir / f"{page_id}.html"
        _write_text(path, html_text)
        written.append(path)

    index_html = _render_regional_lab_index(
        output_root=output_root,
        web_root=web_root,
        report=report,
        inventory=inventory,
        case_matrix=case_matrix,
        metrics=metrics,
        context=context,
        comparisons=comparisons,
        artifacts=[
            report_path,
            inventory_path,
            case_matrix_path,
            metrics_path,
            summary_md_path,
            output_root / "regional_lab_plan.json",
        ],
    )
    index_path = web_root / "index.html"
    _write_text(index_path, index_html)
    written.insert(0, index_path)
    return written


def _render_testbed_index(
    *,
    output_root: Path,
    web_root: Path,
    manifest: Mapping[str, Any],
    plan: Mapping[str, Any],
    cases: Sequence[Mapping[str, Any]],
    metrics: Sequence[Mapping[str, str]],
    context: Mapping[str, Any],
    comparisons: Sequence[Mapping[str, Any]],
    artifacts: Sequence[Path],
) -> str:
    title = str(context.get("title") or f"Testbed report - {manifest.get('testbed_id', output_root.name)}")
    status_counts = Counter(str(case.get("status") or "unknown") for case in cases)
    summary_cards = [
        ("Cas", manifest.get("variant_count") or len(cases)),
        ("OK", manifest.get("successful_count")),
        ("Echecs", manifest.get("failed_count")),
        ("Comparaisons", len(comparisons)),
    ]
    comparison_index_only = bool(context.get("comparison_index_only"))
    run_definition = _summarize_testbed_run_definition(cases)
    case_rows = []
    if not comparison_index_only:
        for case in cases:
            case_path = web_root / "cases" / f"{case['page_id']}.html"
            label = _display_value(case.get("variant_label") or case.get("variant_id"))
            status = _display_value(case.get("status"))
            site = case.get("site") or {}
            site_text = _display_value(site.get("site_id") or site.get("outlet_id") or "")
            case_rows.append(
                [
                    _link(case_path, "Ouvrir", web_root),
                    _case_comparison_links(case.get("comparisons") or [], from_dir=web_root),
                    _simulation_html_links(case.get("simulation_html_pages") or [], from_dir=web_root),
                    label,
                    _display_value(case.get("variant_id")),
                    site_text,
                    _status_badge(status),
                    _display_value(case.get("axis")),
                    _format_float(case.get("duration_seconds")),
                    _display_value(case.get("runner")),
                ]
            )

    artifacts_html = _render_artifact_links(artifacts, from_dir=web_root)
    sections = [
        _hero(title, subtitle=_path_text(output_root)),
        _cards(summary_cards),
    ]
    if comparison_index_only:
        sections.extend(
            [
                _section(
                    "Comparaisons",
                    _render_testbed_comparison_overview_table(cases, web_root=web_root),
                ),
                _section(
                    "Precision de resolution",
                    _render_comparison_closure_overview(comparisons, from_dir=web_root),
                ),
                _section("Artefacts", artifacts_html),
            ]
        )
    else:
        provenance = _render_provenance_section(
            output_root=output_root,
            web_root=web_root,
            context=context,
            manifest=manifest,
            plan=plan,
            contract_label="testbed",
        )
        sections.extend(
            [
                _section("Liens directs", _render_testbed_direct_links(cases, web_root=web_root)),
                _render_catalog_testbed_guidance(
                    manifest=manifest,
                    plan=plan,
                    context=context,
                    web_root=web_root,
                ),
                _section(
                    "Statut",
                    "<p>"
                    + html.escape(", ".join(f"{key}: {value}" for key, value in sorted(status_counts.items())))
                    + "</p>",
                ),
                _section(
                    "Comparaisons disponibles",
                    _render_comparison_summary_table(comparisons, from_dir=web_root),
                ),
                _section(
                    "Precision de resolution",
                    _render_comparison_closure_overview(comparisons, from_dir=web_root),
                ),
                _section(
                    "Cas",
                    _table_from_rows(
                        [
                            "Page cas",
                            "Comparaison HTML",
                            "Simulation HTML",
                            "Cas",
                            "Variant id",
                            "Site",
                            "Status",
                            "Axis",
                            "Duration (s)",
                            "Runner",
                        ],
                        case_rows,
                    ),
                ),
                _section("Contexte d'execution", _definition_list(run_definition)),
                _section("Metriques", _render_metrics_summary(metrics, metrics_path=output_root / "testbed_metrics.csv", from_dir=web_root)),
                provenance,
                _section("Artefacts", artifacts_html),
                _section(
                    "Contrat du rapport",
                    "<p>This page is generated after the simulations. It reads the standard "
                    "testbed artifacts and the generated child TOML files; it does not create "
                    "meshes, run solvers, or add a second execution path.</p>",
                ),
            ]
        )
    body = "\n".join(sections)
    return _page(title, body)


def _render_catalog_testbed_guidance(
    *,
    manifest: Mapping[str, Any],
    plan: Mapping[str, Any],
    context: Mapping[str, Any],
    web_root: Path,
) -> str:
    catalog = manifest.get("catalog") if isinstance(manifest.get("catalog"), Mapping) else None
    if catalog is None and isinstance(plan.get("catalog"), Mapping):
        catalog = plan.get("catalog")
    rules = manifest.get("variant_from_catalog")
    if not isinstance(rules, list) and isinstance(plan.get("variant_from_catalog"), list):
        rules = plan.get("variant_from_catalog")
    if catalog is None and not rules:
        return ""

    catalog_path = _path_or_none(context.get("site_catalog_path") or (catalog or {}).get("path"))
    selected_rows = len(context.get("site_catalog_rows") or [])
    runner = _display_value(manifest.get("runner"))
    base_config = _path_or_none(manifest.get("base_config"))
    generated_dir = _path_or_none(_get_nested(manifest, ["paths", "generated_configs_dir"]))
    comparison_note = ""
    if runner == "comparison":
        comparison_note = (
            "<p>Dans ce mode, chaque ligne retenue du catalogue produit un TOML "
            "<code>workflow = &quot;comparison&quot;</code>. Les valeurs physiques du site "
            "sont injectees dans <code>comparison.base_simulation_overlay</code>, puis le "
            "workflow de comparaison genere et lance les simulations enfants declarees "
            "dans le TOML de base. Les pages HTML de comparaison sont les sorties "
            "principales a consulter.</p>"
        )

    fields = [
        (
            "Catalogue",
            _link(catalog_path, _path_text(catalog_path), web_root) if catalog_path else "",
        ),
        ("Lignes lues", selected_rows if selected_rows else ""),
        ("Runner testbed", runner),
        ("Base config", _link(base_config, _path_text(base_config), web_root) if base_config else ""),
        (
            "Configs generees",
            _link(generated_dir, _path_text(generated_dir), web_root) if generated_dir else "",
        ),
        (
            "Regles catalogue",
            len(rules) if isinstance(rules, list) else "",
        ),
    ]
    steps = [
        "Le testbed charge le catalogue CSV/JSONL declare dans <code>[testbed.catalog]</code>.",
        "Les filtres du catalogue et de <code>[[testbed.variant_from_catalog]]</code> retiennent les lignes utiles.",
        "Pour chaque ligne, les champs <code>{...}</code> des templates sont remplaces par les valeurs du catalogue.",
        "Le TOML enfant est ecrit dans <code>_generated_configs</code>; il ne contient plus de section <code>[testbed]</code>.",
        "L'execution delegue ensuite ce TOML au runner choisi, sans script de commodite supplementaire.",
    ]
    body = (
        "<p>Cette section documente le mode catalogue du testbed. Il permet de "
        "declarer une liste de sites une seule fois, puis d'appliquer la meme "
        "configuration de comparaison, de simulation ou de maillage a chaque site.</p>"
        + comparison_note
        + _definition_list(fields)
        + "<ol>"
        + "".join(f"<li>{item}</li>" for item in steps)
        + "</ol>"
    )
    return _section("Mode catalogue pas a pas", body)


def _render_testbed_case_page(
    *,
    case: Mapping[str, Any],
    output_root: Path,
    web_root: Path,
    page_dir: Path,
    context: Mapping[str, Any],
) -> str:
    label = _display_value(case.get("variant_label") or case.get("variant_id"))
    config = case.get("config") if isinstance(case.get("config"), Mapping) else {}
    site = case.get("site") if isinstance(case.get("site"), Mapping) else {}
    figures = list(case.get("figures") or [])
    config_path = _path_or_none(case.get("config_path"))
    facts = [
        ("Variant id", case.get("variant_id")),
        ("Status", _status_badge(_display_value(case.get("status")))),
        ("Axis", case.get("axis")),
        ("Runner", case.get("runner")),
        ("Duration (s)", _format_float(case.get("duration_seconds"))),
        ("Simulation name", _get_nested(config, ["simulation", "name"])),
        ("Simulation run id", _get_nested(config, ["simulation", "run_id"])),
        ("Config", _link(config_path, _path_text(config_path), page_dir) if config_path else ""),
    ]
    site_facts = _case_site_facts(site=site, config=config)
    generation_facts = _case_generation_facts(config=config)
    recharge_facts = _case_recharge_facts(config=config)
    time_facts = _case_time_facts(config=config)
    flow_facts = _case_flow_facts(config=config)
    artifacts = [
        config_path,
        _path_or_none(_get_nested(config, ["workspace", "project_root"])),
        _path_or_none(_get_nested(config, ["display", "output_dir"])),
    ]
    comparisons = [
        item for item in case.get("comparisons", []) if isinstance(item, Mapping)
    ]
    simulation_html_pages = [
        path for path in case.get("simulation_html_pages", []) if isinstance(path, Path)
    ]
    body = "\n".join(
        [
            _hero(label, subtitle=f"{_display_value(case.get('variant_id'))} - {_path_text(output_root)}"),
            '<p><a href="../index.html">Back to synthesis</a></p>',
            _section(
                "Liens",
                _definition_list(
                    [
                        (
                            "Comparaison HTML",
                            _case_comparison_links(comparisons, from_dir=page_dir),
                        ),
                        (
                            "Simulation HTML",
                            _render_artifact_links(simulation_html_pages, from_dir=page_dir),
                        ),
                        (
                            "Config",
                            _link(config_path, _path_text(config_path), page_dir)
                            if config_path
                            else "",
                        ),
                    ]
                ),
            ),
            _section("Identification", _definition_list(facts + site_facts)),
            _section("Comparaisons de methodes", _render_case_comparisons(comparisons, from_dir=page_dir)),
            _section("Maillage et contexte geographique", _definition_list(generation_facts)),
            _section("Recharge", _definition_list(recharge_facts)),
            _section("Temps et condition initiale", _definition_list(time_facts)),
            _section("Processus et parametres", _definition_list(flow_facts) + _render_parameter_table(config)),
            _section("Figures de simulation", _render_figure_grid(figures, from_dir=page_dir)),
            _section("Artefacts", _render_artifact_links(artifacts, from_dir=page_dir)),
            _section(
                "Provenance note",
                _render_case_provenance_note(context=context, from_dir=page_dir),
            ),
        ]
    )
    return _page(label, body)


def _render_regional_lab_index(
    *,
    output_root: Path,
    web_root: Path,
    report: Mapping[str, Any],
    inventory: Sequence[Mapping[str, str]],
    case_matrix: Sequence[Mapping[str, str]],
    metrics: Sequence[Mapping[str, str]],
    context: Mapping[str, Any],
    comparisons: Sequence[Mapping[str, Any]],
    artifacts: Sequence[Path],
) -> str:
    title = str(context.get("title") or f"Regional lab report - {report.get('lab_id', output_root.name)}")
    summary_cards = [
        ("Sites", report.get("selected_site_count") or len(inventory)),
        ("Cas prevus", report.get("planned_case_count") or len(case_matrix)),
        ("OK", report.get("successful_case_count")),
        ("Comparaisons", len(comparisons)),
    ]
    provenance = _render_provenance_section(
        output_root=output_root,
        web_root=web_root,
        context=context,
        manifest=report,
        plan={},
        contract_label="regional_lab",
    )
    site_rows = []
    for site in inventory:
        site_id = _display_value(site.get("site_id") or site.get("id") or "site")
        page_path = web_root / "sites" / f"{_safe_page_id(site_id)}.html"
        site_comparisons = _match_comparisons(
            case={
                "variant_id": site_id,
                "variant_label": site.get("site_label"),
                "page_id": _safe_page_id(site_id),
                "site": site,
            },
            comparisons=comparisons,
        )
        site_rows.append(
            [
                _link(page_path, site_id, web_root),
                _case_comparison_links(site_comparisons, from_dir=web_root),
                _display_value(site.get("site_label")),
                _display_value(site.get("region_id")),
                _display_value(site.get("cluster_id")),
                _display_value(site.get("cluster_family")),
                _display_value(site.get("cluster_scale")),
                _display_value(site.get("area_km2")),
                _display_value(site.get("site_status")),
            ]
        )
    body = "\n".join(
        [
            _hero(title, subtitle=_path_text(output_root)),
            _cards(summary_cards),
            _section(
                "Liens directs",
                _table_from_rows(
                    [
                        "Site",
                        "Comparaison HTML",
                        "Label",
                        "Region",
                        "Cluster",
                        "Family",
                        "Scale",
                        "Area km2",
                        "Status",
                    ],
                    site_rows,
                ),
            ),
            _section(
                "Comparaisons disponibles",
                _render_comparison_summary_table(comparisons, from_dir=web_root),
            ),
            _section(
                "Apercu des cas",
                _render_table(
                    _preview_rows(case_matrix, max_rows=20),
                    caption="Case matrix",
                    empty_message="No case matrix rows were produced.",
                    from_dir=web_root,
                ),
            ),
            _section(
                "Apercu des metriques",
                _render_table(
                    _preview_rows(metrics, max_rows=20),
                    caption="Execution metrics",
                    empty_message="No execution metric rows were produced.",
                    from_dir=web_root,
                ),
            ),
            provenance,
            _section("Artefacts", _render_artifact_links(artifacts, from_dir=web_root)),
            _section(
                "Contrat du rapport",
                "<p>This page is generated after the regional lab run. It reads the "
                "standard regional_lab artifacts and can be reused for other process "
                "families as long as they keep the same report contract.</p>",
            ),
        ]
    )
    return _page(title, body)


def _render_regional_lab_site_page(
    *,
    site: Mapping[str, str],
    cases: Sequence[Mapping[str, str]],
    comparisons: Sequence[Mapping[str, Any]],
    output_root: Path,
    web_root: Path,
    page_dir: Path,
    context: Mapping[str, Any],
) -> str:
    site_id = _display_value(site.get("site_id") or site.get("id") or "site")
    title = _display_value(site.get("site_label") or site_id)
    body = "\n".join(
        [
            _hero(title, subtitle=f"{site_id} - {_path_text(output_root)}"),
            '<p><a href="../index.html">Back to synthesis</a></p>',
            _section(
                "Liens",
                _definition_list(
                    [
                        (
                            "Comparaison HTML",
                            _case_comparison_links(comparisons, from_dir=page_dir),
                        )
                    ]
                ),
            ),
            _section("Site", _definition_list(sorted(site.items()))),
            _section("Comparaisons de methodes", _render_case_comparisons(comparisons, from_dir=page_dir)),
            _section(
                "Cas",
                _render_table(
                    cases,
                    caption="Cases attached to this site",
                    empty_message="No cases were attached to this site.",
                    from_dir=page_dir,
                ),
            ),
            _section(
                "Provenance note",
                _render_case_provenance_note(context=context, from_dir=page_dir),
            ),
        ]
    )
    return _page(title, body)


def _enrich_testbed_case(
    case: Mapping[str, Any],
    *,
    output_root: Path,
    site_index: Mapping[str, Mapping[str, str]],
    comparisons: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    enriched = dict(case)
    variant_id = _display_value(case.get("variant_id") or case.get("id") or "case")
    enriched["page_id"] = _safe_page_id(variant_id)
    config_path = _path_or_none(case.get("config_path"))
    config = _read_toml(config_path) if config_path and config_path.is_file() else {}
    enriched["config"] = config
    site = _match_site_row(case, config=config, site_index=site_index)
    enriched["site"] = site
    enriched["figures"] = _find_case_figures(config=config, output_root=output_root)
    enriched["simulation_html_pages"] = _find_case_html_pages(
        case=enriched,
        config=config,
        site=site,
        output_root=output_root,
    )
    enriched["comparisons"] = _match_comparisons(
        case=enriched,
        comparisons=comparisons,
    )
    return enriched


def _match_site_row(
    case: Mapping[str, Any],
    *,
    config: Mapping[str, Any],
    site_index: Mapping[str, Mapping[str, str]],
) -> Mapping[str, str]:
    candidates = [
        case.get("variant_id"),
        case.get("variant_label"),
        _get_nested(config, ["simulation", "name"]),
        _get_nested(config, ["simulation", "run_id"]),
    ]
    for candidate in candidates:
        for key in _site_lookup_keys(_display_value(candidate)):
            if key in site_index:
                return site_index[key]
    return {}


def _index_site_catalog(rows: Sequence[Mapping[str, str]]) -> dict[str, Mapping[str, str]]:
    index: dict[str, Mapping[str, str]] = {}
    for row in rows:
        keys: list[str] = []
        for field in (
            "variant_id",
            "case_id",
            "site_id",
            "outlet_id",
            "id",
            "source_selection_id",
            "site_label",
        ):
            value = _display_value(row.get(field))
            keys.extend(_site_lookup_keys(value))
        for key in keys:
            index.setdefault(key, row)
    return index


def _site_lookup_keys(value: str) -> list[str]:
    value = value.strip()
    if not value:
        return []
    lower = _normalize_key(value)
    keys = [lower] if lower else []
    site_match = re.fullmatch(r"site[_ -]?(\d+)", lower or "")
    if site_match:
        num = site_match.group(1).lstrip("0") or "0"
        keys.extend([num, num.zfill(2), f"site_{num.zfill(2)}"])
    if re.fullmatch(r"\d+", lower or ""):
        num = (lower or "").lstrip("0") or "0"
        keys.extend([num, num.zfill(2), f"site_{num.zfill(2)}"])
    return list(dict.fromkeys(key for key in keys if key))


def _summarize_testbed_run_definition(cases: Sequence[Mapping[str, Any]]) -> list[tuple[str, Any]]:
    configs = [case.get("config") for case in cases if isinstance(case.get("config"), Mapping)]
    recharge_fingerprints = Counter(_recharge_fingerprint(config) for config in configs)
    time_fingerprints = Counter(_time_fingerprint(config) for config in configs)
    ic_fingerprints = Counter(_initial_condition_fingerprint(config) for config in configs)
    geographic_sources = Counter(
        _display_value(_get_nested(config, ["geographic", "source_mode"]) or "unknown")
        for config in configs
    )
    flow_regimes = Counter(
        _display_value(_get_nested(config, ["flow", "flow_regime"]) or "unknown")
        for config in configs
    )
    return [
        ("Generated child configs", len(configs)),
        ("Geographic source modes", _counter_text(geographic_sources)),
        ("Flow regimes", _counter_text(flow_regimes)),
        ("Recharge definitions", _counter_text(recharge_fingerprints)),
        ("Time windows", _counter_text(time_fingerprints)),
        ("Initial conditions", _counter_text(ic_fingerprints)),
    ]


def _recharge_fingerprint(config: Mapping[str, Any]) -> str:
    recharge = _get_nested(config, ["data", "recharge"])
    if not isinstance(recharge, Mapping):
        return "not declared"
    sources = recharge.get("sources")
    source_bits = []
    if isinstance(sources, list):
        for source in sources:
            if not isinstance(source, Mapping):
                continue
            values = source.get("values")
            count = len(values) if isinstance(values, list) else 0
            source_bits.append(
                "source={source}, freq={freq}, start={start}, periods={periods}, values={count}".format(
                    source=_display_value(source.get("source") or "?"),
                    freq=_display_value(source.get("freq") or "?"),
                    start=_display_value(source.get("start_date") or "?"),
                    periods=_display_value(source.get("periods") or "?"),
                    count=count,
                )
            )
    if not source_bits:
        source_bits.append("sources=none")
    return (
        f"{_display_value(recharge.get('date_start'))} to "
        f"{_display_value(recharge.get('date_end'))}; "
        + "; ".join(source_bits)
    )


def _time_fingerprint(config: Mapping[str, Any]) -> str:
    time_cfg = _get_nested(config, ["simulation", "time"])
    if not isinstance(time_cfg, Mapping):
        return "not declared"
    return (
        f"{_display_value(time_cfg.get('start_datetime'))} to "
        f"{_display_value(time_cfg.get('end_datetime'))}; "
        f"step={_display_value(time_cfg.get('step_value'))}; "
        f"coverage={_display_value(time_cfg.get('coverage_policy'))}"
    )


def _initial_condition_fingerprint(config: Mapping[str, Any]) -> str:
    flow_ic = _get_nested(config, ["flow", "ic"])
    if not isinstance(flow_ic, Mapping):
        return "not declared"
    return ", ".join(f"{key}={_display_value(value)}" for key, value in sorted(flow_ic.items()))


def _case_site_facts(
    *,
    site: Mapping[str, Any],
    config: Mapping[str, Any],
) -> list[tuple[str, Any]]:
    facts = [
        ("Site id", site.get("site_id")),
        ("Outlet id", site.get("outlet_id")),
        ("Label", site.get("site_label")),
        ("Region", site.get("region_id")),
        ("Cluster", site.get("cluster_id")),
        ("Family", site.get("cluster_family")),
        ("Scale", site.get("cluster_scale")),
        ("Area km2", site.get("area_km2")),
        ("Tags", site.get("tags")),
        ("X outlet", site.get("x_outlet") or _get_nested(config, ["geographic", "x_outlet"])),
        ("Y outlet", site.get("y_outlet") or _get_nested(config, ["geographic", "y_outlet"])),
    ]
    if not site:
        facts.append(("Catalog match", "No matching site row supplied or detected."))
    return facts


def _case_generation_facts(config: Mapping[str, Any]) -> list[tuple[str, Any]]:
    geographic = _get_nested(config, ["geographic"])
    if not isinstance(geographic, Mapping):
        geographic = {}
    river = geographic.get("river_network")
    if not isinstance(river, Mapping):
        river = {}
    workspace = _get_nested(config, ["workspace"])
    if not isinstance(workspace, Mapping):
        workspace = {}
    return [
        ("Workspace", workspace.get("project_root")),
        ("Source mode", geographic.get("source_mode")),
        ("Catchment definition", geographic.get("catch_def")),
        ("DEM", geographic.get("dem_init_path")),
        ("Project CRS", geographic.get("crs_project")),
        ("Snap distance", geographic.get("snap_dist")),
        ("Buffer area", geographic.get("buff_area")),
        ("DEM correction", geographic.get("dem_correc_type")),
        ("Reuse existing geographic outputs", geographic.get("reuse_existing_outputs")),
        ("River network enabled", river.get("enabled")),
        ("River threshold mode", river.get("threshold_mode")),
        ("River threshold area km2", river.get("threshold_area_km2")),
    ]


def _case_recharge_facts(config: Mapping[str, Any]) -> list[tuple[str, Any]]:
    recharge = _get_nested(config, ["data", "recharge"])
    if not isinstance(recharge, Mapping):
        return [("Recharge", "not declared")]
    facts: list[tuple[str, Any]] = [
        ("Date start", recharge.get("date_start")),
        ("Date end", recharge.get("date_end")),
    ]
    sources = recharge.get("sources")
    if isinstance(sources, list):
        for idx, source in enumerate(sources, start=1):
            if not isinstance(source, Mapping):
                continue
            values = source.get("values")
            stats = _numeric_stats(values) if isinstance(values, list) else ""
            facts.extend(
                [
                    (f"Source {idx}", source.get("source")),
                    (f"Source {idx} frequency", source.get("freq")),
                    (f"Source {idx} start", source.get("start_date")),
                    (f"Source {idx} periods", source.get("periods")),
                    (f"Source {idx} runoff ratio", source.get("runoff_ratio")),
                    (f"Source {idx} values", stats),
                ]
            )
            for key, value in sorted(source.items()):
                if key in {"source", "freq", "start_date", "periods", "runoff_ratio", "values"}:
                    continue
                facts.append((f"Source {idx} {key}", value))
    return facts


def _case_time_facts(config: Mapping[str, Any]) -> list[tuple[str, Any]]:
    time_cfg = _get_nested(config, ["simulation", "time"])
    flow_ic = _get_nested(config, ["flow", "ic"])
    facts: list[tuple[str, Any]] = []
    if isinstance(time_cfg, Mapping):
        facts.extend(
            [
                ("Start datetime", time_cfg.get("start_datetime")),
                ("End datetime", time_cfg.get("end_datetime")),
                ("Step", time_cfg.get("step_value")),
                ("Coverage policy", time_cfg.get("coverage_policy")),
            ]
        )
    else:
        facts.append(("Simulation time", "not declared"))
    if isinstance(flow_ic, Mapping):
        facts.extend((f"Initial condition {key}", value) for key, value in sorted(flow_ic.items()))
    else:
        facts.append(("Initial condition", "not declared"))
    return facts


def _case_flow_facts(config: Mapping[str, Any]) -> list[tuple[str, Any]]:
    flow = _get_nested(config, ["flow"])
    simulation = _get_nested(config, ["simulation"])
    if not isinstance(flow, Mapping):
        flow = {}
    if not isinstance(simulation, Mapping):
        simulation = {}
    process_rows = simulation.get("process")
    processes = []
    if isinstance(process_rows, list):
        for item in process_rows:
            if isinstance(item, Mapping):
                processes.append(
                    "{id} ({type}) solvers={solvers}".format(
                        id=_display_value(item.get("id")),
                        type=_display_value(item.get("type")),
                        solvers=_display_value(item.get("solvers")),
                    )
                )
    return [
        ("Flow regime", flow.get("flow_regime")),
        ("Active sinks/sources", flow.get("active_sinks_sources")),
        ("Active boundary conditions", flow.get("active_bc")),
        ("Parameter list", flow.get("param_list")),
        ("Processes", "; ".join(processes)),
    ]


def _render_parameter_table(config: Mapping[str, Any]) -> str:
    params = _get_nested(config, ["flow", "param"])
    if not isinstance(params, Mapping) or not params:
        return '<p class="muted">No hydraulic parameters declared.</p>'
    rows = []
    for name, spec in sorted(params.items()):
        if not isinstance(spec, Mapping):
            rows.append([_display_value(name), "", "", _display_value(spec), ""])
            continue
        field = spec.get("field") if isinstance(spec.get("field"), Mapping) else {}
        kind = _display_value(field.get("kind") if isinstance(field, Mapping) else "")
        unit = _display_value(field.get("unit") if isinstance(field, Mapping) else "")
        value = ""
        details = []
        if kind:
            kind_block = spec.get(f"field_{kind}")
            if isinstance(kind_block, Mapping):
                value = _display_value(kind_block.get("value") or kind_block.get("path"))
                details = [f"{key}={_display_value(val)}" for key, val in sorted(kind_block.items())]
        if not value:
            for key, val in sorted(spec.items()):
                if isinstance(val, Mapping) and key != "field":
                    value = _display_value(val.get("value") or val.get("path") or "")
                    if value:
                        details = [f"{sub_key}={_display_value(sub_val)}" for sub_key, sub_val in sorted(val.items())]
                        break
        rows.append([_display_value(name), kind, unit, value, "; ".join(details)])
    return _table_from_rows(["Parameter", "Kind", "Unit", "Value/path", "Details"], rows)


def _find_case_figures(
    *,
    config: Mapping[str, Any],
    output_root: Path,
) -> list[Path]:
    candidates: list[Path] = []
    display_dir = _path_or_none(_get_nested(config, ["display", "output_dir"]))
    if display_dir:
        candidates.append(display_dir)
    workspace = _path_or_none(_get_nested(config, ["workspace", "project_root"]))
    if workspace:
        candidates.append(workspace / "figures")
    seen: set[Path] = set()
    figures: list[Path] = []
    for candidate in candidates:
        if not candidate.is_absolute():
            candidate = (output_root / candidate).resolve()
        if not candidate.exists():
            continue
        for path in sorted(candidate.rglob("*")):
            if path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            figures.append(resolved)
    return figures


def _find_case_html_pages(
    *,
    case: Mapping[str, Any],
    config: Mapping[str, Any],
    site: Mapping[str, Any],
    output_root: Path,
) -> list[Path]:
    names: list[str] = []
    for value in (
        case.get("variant_id"),
        case.get("page_id"),
        case.get("variant_label"),
        site.get("site_id") if isinstance(site, Mapping) else None,
        site.get("outlet_id") if isinstance(site, Mapping) else None,
    ):
        names.extend(_html_name_candidates(_display_value(value)))

    candidates: list[Path] = []
    for name in dict.fromkeys(names):
        candidates.append(output_root / "web" / f"{name}.html")

    workspace = _path_or_none(_get_nested(config, ["workspace", "project_root"]))
    if workspace:
        if not workspace.is_absolute():
            workspace = (output_root / workspace).resolve()
        if workspace.is_dir():
            candidates.extend(sorted(workspace.rglob("*.html")))

    seen: set[Path] = set()
    pages: list[Path] = []
    for candidate in candidates:
        if not candidate.is_file():
            continue
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        if "web_synthesis" in resolved.parts:
            continue
        seen.add(resolved)
        pages.append(resolved)
    return pages


def _html_name_candidates(value: str) -> list[str]:
    keys = _site_lookup_keys(value)
    names: list[str] = []
    for key in keys:
        names.append(key)
        if re.fullmatch(r"\d+", key):
            names.append(f"site_{key.zfill(2)}")
    return [name for name in dict.fromkeys(names) if name]


def _load_comparison_summaries(
    *,
    output_root: Path,
    extra_roots: Sequence[Path | str],
) -> list[dict[str, Any]]:
    roots: list[Path] = []
    auto_root = output_root / "comparisons"
    if auto_root.is_dir():
        roots.extend(path for path in sorted(auto_root.iterdir()) if path.is_dir())
    roots.extend(Path(root) for root in extra_roots)

    summaries: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for root in roots:
        root = root.expanduser().resolve()
        if root in seen:
            continue
        seen.add(root)
        if not root.is_dir():
            continue
        manifest_path = root / "comparison_manifest.json"
        manifest = _read_json(manifest_path)
        web_index = _comparison_web_index(root=root, manifest=manifest)
        figures = _comparison_figure_items(root=root, manifest=manifest)
        default_metrics_path = root / "comparison_metrics.csv"
        metrics_path = _path_or_none(manifest.get("comparison_metrics_csv"))
        if metrics_path is None:
            metrics_path = default_metrics_path
        elif _looks_like_wsl_mount_path(metrics_path) and default_metrics_path.is_file():
            metrics_path = default_metrics_path
        elif not metrics_path.is_absolute():
            metrics_path = (root / metrics_path).resolve()
        elif not metrics_path.exists() and default_metrics_path.is_file():
            metrics_path = default_metrics_path
        differences_path = _comparison_artifact_path(
            root=root,
            manifest_value=manifest.get("comparison_differences_csv"),
            default_name="comparison_differences.csv",
        )
        budget_wide_path = _comparison_artifact_path(
            root=root,
            manifest_value=None,
            default_name="budget_timeseries_wide.csv",
        )
        numerical_closure_path = _comparison_artifact_path(
            root=root,
            manifest_value=None,
            default_name="numerical_closure_summary.csv",
        )
        simulations = _comparison_simulations(manifest)
        numerical_closure_rows = _comparison_numerical_closure_rows(
            path=numerical_closure_path,
            manifest=manifest,
        )
        closure_summary = _summarize_numerical_closure(numerical_closure_rows)
        summary = {
            "comparison_id": _display_value(manifest.get("comparison_id") or root.name),
            "root": root,
            "manifest_path": manifest_path,
            "manifest": manifest,
            "web_index": web_index,
            "metrics_path": metrics_path,
            "metrics_rows": _read_csv(metrics_path),
            "differences_path": differences_path,
            "budget_wide_path": budget_wide_path,
            "numerical_closure_path": numerical_closure_path,
            "numerical_closure_rows": numerical_closure_rows,
            "figures": figures,
            "key_figures": _select_comparison_key_figures(figures),
            "simulations": simulations,
            "reference_simulation": manifest.get("reference_simulation"),
            "audit_status": manifest.get("audit_status"),
            "n_metric_rows": manifest.get("n_metric_rows"),
            "n_difference_rows": manifest.get("n_difference_rows"),
            "wall_time_seconds": manifest.get("wall_time_seconds"),
            "head_mean_abs_relative_error_percent": _head_mean_abs_relative_error_percent(
                differences_path
            ),
            "global_outflow_mean_abs_relative_error_percent": (
                _global_outflow_mean_abs_relative_error_percent(
                    budget_wide_path=budget_wide_path,
                    reference_simulation=manifest.get("reference_simulation"),
                    simulations=simulations,
                )
            ),
        }
        summary.update(closure_summary)
        summaries.append(summary)
    return summaries


def _comparison_artifact_path(
    *,
    root: Path,
    manifest_value: Any,
    default_name: str,
) -> Path:
    default_path = root / default_name
    path = _path_or_none(manifest_value)
    if path is None:
        return default_path
    if _looks_like_wsl_mount_path(path) and default_path.is_file():
        return default_path
    if not path.is_absolute():
        return (root / path).resolve()
    if not path.exists() and default_path.is_file():
        return default_path
    return path


def _comparison_numerical_closure_rows(
    *,
    path: Path,
    manifest: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [dict(row) for row in _read_csv(path)]
    if rows:
        return rows
    payload = manifest.get("numerical_closure")
    if not isinstance(payload, Mapping):
        return []
    raw_rows = payload.get("rows")
    if not isinstance(raw_rows, list):
        return []
    return [dict(row) for row in raw_rows if isinstance(row, Mapping)]


def _summarize_numerical_closure(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    return {
        "closure_status": _worst_closure_status(rows),
        "closure_max_abs_m3_s": _max_numeric_field(rows, "max_abs_closure_m3_s"),
        "closure_max_abs_mm_d": _max_numeric_field(rows, "max_abs_closure_mm_d"),
        "closure_relative_error_p95": _max_numeric_field(
            rows,
            "relative_closure_error_p95",
        ),
    }


def _max_numeric_field(rows: Sequence[Mapping[str, Any]], field: str) -> float | None:
    values = []
    for row in rows:
        value = _float_or_none(row.get(field))
        if value is not None:
            values.append(value)
    return max(values) if values else None


def _worst_closure_status(rows: Sequence[Mapping[str, Any]]) -> str:
    worst = ""
    for row in rows:
        status = _display_value(row.get("diagnostic")).strip().upper()
        if CLOSURE_STATUS_ORDER.get(status, -1) > CLOSURE_STATUS_ORDER.get(worst, -1):
            worst = status
    return worst or "UNKNOWN"


def _float_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _head_mean_abs_relative_error_percent(differences_path: Path) -> float | None:
    rows = _read_csv(differences_path)
    numerator = 0.0
    denominator = 0.0
    for row in rows:
        observable = _display_value(row.get("observable")).lower()
        if not observable.startswith("head"):
            continue
        if _display_value(row.get("unit")).strip() not in {"m", "meter", "meters"}:
            continue
        try:
            error = abs(float(row.get("absolute_error", "")))
            reference = abs(float(row.get("reference_value", "")))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(error) or not math.isfinite(reference) or reference <= 0.0:
            continue
        numerator += error
        denominator += reference
    if denominator <= 0.0:
        return None
    return 100.0 * numerator / denominator


def _global_outflow_mean_abs_relative_error_percent(
    *,
    budget_wide_path: Path,
    reference_simulation: Any,
    simulations: Sequence[Mapping[str, Any]],
) -> float | None:
    rows = _read_csv(budget_wide_path)
    if not rows:
        return None
    reference_id = _display_value(reference_simulation).strip()
    candidate_id = _first_candidate_simulation_id(
        simulations=simulations,
        reference_simulation=reference_id,
    )
    if not reference_id or not candidate_id:
        return None
    reference_column = f"value__{reference_id}"
    candidate_column = f"value__{candidate_id}"
    for component in (
        "comparable_outflow_total_m3_s",
        "balance_implied_outflow_total_m3_s",
    ):
        numerator = 0.0
        denominator = 0.0
        for row in rows:
            if _display_value(row.get("component")) != component:
                continue
            try:
                candidate = float(row.get(candidate_column, ""))
                reference = float(row.get(reference_column, ""))
            except (TypeError, ValueError):
                continue
            if not math.isfinite(candidate) or not math.isfinite(reference):
                continue
            numerator += abs(candidate - reference)
            denominator += abs(reference)
        if denominator > 0.0:
            return 100.0 * numerator / denominator
    return None


def _first_candidate_simulation_id(
    *,
    simulations: Sequence[Mapping[str, Any]],
    reference_simulation: str,
) -> str | None:
    for simulation in simulations:
        simulation_id = _display_value(simulation.get("id")).strip()
        if simulation_id and simulation_id != reference_simulation:
            return simulation_id
    return None


def _comparison_web_index(*, root: Path, manifest: Mapping[str, Any]) -> Path | None:
    data_artifacts = manifest.get("comparison_data_artifacts")
    if isinstance(data_artifacts, list):
        for item in data_artifacts:
            if not isinstance(item, Mapping):
                continue
            if item.get("kind") != "comparison_web_report_html":
                continue
            path = _path_or_none(item.get("path"))
            if path is not None and not path.is_absolute():
                path = root / path
            if path and path.is_file():
                return path.resolve()
    path = root / "web" / "index.html"
    return path.resolve() if path.is_file() else None


def _comparison_simulations(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    simulations = manifest.get("simulations", [])
    if not isinstance(simulations, list):
        return []
    return [dict(item) for item in simulations if isinstance(item, Mapping)]


def _comparison_figure_items(
    *,
    root: Path,
    manifest: Mapping[str, Any],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    raw_items = manifest.get("comparison_figures", [])
    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, Mapping):
                continue
            path = _path_or_none(item.get("path"))
            if path is None:
                continue
            if not path.is_absolute():
                path = root / path
            if path.suffix.lower() not in IMAGE_SUFFIXES or not path.is_file():
                continue
            payload = dict(item)
            payload["path"] = path.resolve()
            if _include_comparison_figure(payload):
                items.append(payload)
    known = {Path(str(item["path"])).resolve() for item in items if item.get("path")}
    figure_root = root / "comparison_figures"
    if figure_root.is_dir():
        for path in sorted(figure_root.glob("*")):
            if path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            resolved = path.resolve()
            if resolved in known:
                continue
            payload = {"kind": "figure", "observable": path.stem, "path": resolved}
            if _include_comparison_figure(payload):
                items.append(payload)
    return items


def _include_comparison_figure(item: Mapping[str, Any]) -> bool:
    name = Path(str(item.get("path", ""))).name.lower()
    kind = _display_value(item.get("kind")).lower()
    observable = _display_value(item.get("observable")).lower()
    text = " ".join((name, kind, observable))
    if "case_configuration" in text:
        return True
    if (
        kind == "fine_raster_map_comparison" and observable == "head_map_wet_year1"
    ) or ("head_map_wet_year1" in text and "fine_raster_map_comparison" in text):
        return True
    if (kind == "timeseries" and observable.startswith("head_") and observable.endswith("_series")) or (
        name.startswith("head_") and name.endswith("__timeseries.png")
    ):
        return True
    if kind in {"storage_comparison_dashboard", "total_inputs_outputs_dashboard"}:
        return True
    if any(
        token in text
        for token in (
            "storage_comparison_dashboard",
            "total_inputs_outputs_dashboard",
        )
    ):
        return True
    return False


def _select_comparison_key_figures(figures: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    priority = {
        "case_configuration": 0,
        "fine_raster_map_comparison": 1,
        "timeseries": 2,
        "storage_comparison_dashboard": 3,
        "total_inputs_outputs_dashboard": 4,
        "figure": 7,
    }

    def score(item: Mapping[str, Any]) -> tuple[int, str, str]:
        kind = _display_value(item.get("kind"))
        observable = _display_value(item.get("observable"))
        name = Path(str(item.get("path", ""))).name
        return (priority.get(kind, 99), observable, name)

    selected = []
    for item in sorted(figures, key=score):
        if len(selected) >= 9:
            break
        selected.append(dict(item))
    return selected


def _match_comparisons(
    *,
    case: Mapping[str, Any],
    comparisons: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    candidates: set[str] = set()
    for value in (
        case.get("variant_id"),
        case.get("variant_label"),
        case.get("page_id"),
    ):
        candidates.update(_site_lookup_keys(_display_value(value)))
    site = case.get("site")
    if isinstance(site, Mapping):
        for field in ("site_id", "outlet_id", "source_selection_id", "site_label"):
            candidates.update(_site_lookup_keys(_display_value(site.get(field))))
    if not candidates:
        return []
    matches = []
    for comparison in comparisons:
        haystack = _comparison_match_text(comparison)
        if any(_comparison_candidate_matches(candidate, haystack) for candidate in candidates):
            matches.append(comparison)
    return matches


def _comparison_candidate_matches(candidate: str, haystack: str) -> bool:
    if not candidate or not haystack:
        return False
    if candidate.isdigit():
        numeric = candidate.lstrip("0") or "0"
        padded = numeric.zfill(2)
        return f"site_{numeric}" in haystack or f"site_{padded}" in haystack
    return candidate in haystack


def _comparison_match_text(comparison: Mapping[str, Any]) -> str:
    values = [
        comparison.get("comparison_id"),
        comparison.get("root"),
        comparison.get("web_index"),
    ]
    manifest = comparison.get("manifest")
    if isinstance(manifest, Mapping):
        for key in (
            "comparison_id",
            "case_id",
            "site_id",
            "variant_id",
            "source_selection_id",
            "config_path",
            "base_simulation_config",
            "comparison_root",
            "tags",
        ):
            values.append(manifest.get(key))
    simulations = comparison.get("simulations")
    if isinstance(simulations, list):
        for simulation in simulations:
            if isinstance(simulation, Mapping):
                values.extend(
                    [
                        simulation.get("id"),
                        simulation.get("label"),
                        simulation.get("run_name"),
                        simulation.get("config_path"),
                    ]
                )
    text = " ".join(_display_value(value) for value in values if value is not None)
    return _normalize_key(text) or ""


def _render_provenance_section(
    *,
    output_root: Path,
    web_root: Path,
    context: Mapping[str, Any],
    manifest: Mapping[str, Any],
    plan: Mapping[str, Any],
    contract_label: str,
) -> str:
    site_catalog_path = _path_or_none(context.get("site_catalog_path") or manifest.get("site_catalog_path"))
    generation_config = _path_or_none(context.get("site_generation_config"))
    generation_summary = _path_or_none(context.get("site_generation_summary"))
    rows = [
        ("Output root", _path_text(output_root)),
        ("Report contract", contract_label),
        ("Config path", manifest.get("config_path") or plan.get("config_path")),
        ("Base config", manifest.get("base_config") or plan.get("base_config")),
        (
            "Site catalog",
            _link(site_catalog_path, _path_text(site_catalog_path), web_root) if site_catalog_path else "",
        ),
        (
            "Site generation config",
            _link(generation_config, _path_text(generation_config), web_root)
            if generation_config
            else "",
        ),
        (
            "Site generation summary",
            _link(generation_summary, _path_text(generation_summary), web_root)
            if generation_summary
            else "",
        ),
    ]
    site_catalog_rows = context.get("site_catalog_rows") or []
    if site_catalog_rows:
        rows.append(("Site catalog rows", len(site_catalog_rows)))
    for key, value in context.get("site_generation_config_details") or []:
        rows.append((f"Site generation config - {key}", value))
    for key, value in context.get("site_generation_summary_details") or []:
        rows.append((f"Site generation summary - {key}", value))
    body = _definition_list(rows)
    if not site_catalog_path:
        body += (
            '<p class="muted">No external site catalog was supplied to the HTML generator. '
            "The report still shows the sites available in the run artifacts.</p>"
        )
    return _section("Input provenance", body)


def _render_case_provenance_note(context: Mapping[str, Any], *, from_dir: Path) -> str:
    site_catalog_path = _path_or_none(context.get("site_catalog_path"))
    generation_config = _path_or_none(context.get("site_generation_config"))
    generation_summary = _path_or_none(context.get("site_generation_summary"))
    parts = [
        "This page is produced from existing run artifacts and generated child configs.",
    ]
    if site_catalog_path:
        parts.append(
            "Site metadata comes from "
            + _link(site_catalog_path, _path_text(site_catalog_path), from_dir)
            + "."
        )
    if generation_config:
        parts.append(
            "The site-selection configuration is "
            + _link(generation_config, _path_text(generation_config), from_dir)
            + "."
        )
    if generation_summary:
        parts.append(
            "The site-selection summary is "
            + _link(generation_summary, _path_text(generation_summary), from_dir)
            + "."
        )
    return "<p>" + " ".join(parts) + "</p>"


def _summarize_site_generation_config(path: Path | None) -> list[tuple[str, Any]]:
    if path is None or not path.is_file():
        return []
    payload = _read_toml(path)
    if not payload:
        return []
    section = payload.get("catchment_identification_scan")
    if not isinstance(section, Mapping):
        section = payload
    keys = [
        "dem_path",
        "region_polygon_path",
        "output_dir",
        "accumulation_area_km2",
        "outlet_selection_mode",
        "scan_tile_size_km",
        "scan_max_outlets_per_tile",
        "scan_min_outlet_spacing_km",
        "scan_max_total_outlets",
        "basin_selection_mode",
        "headwater_max_strahler_order",
        "headwater_min_target_ratio",
        "target_basin_area_km2",
        "target_area_tolerance_ratio",
        "max_basin_overlap_ratio",
        "dem_correction",
        "snap_dist",
        "gpkg_name",
        "basins_layer",
        "outlets_layer",
        "outlets_csv_name",
    ]
    rows = []
    for key in keys:
        value = section.get(key)
        if value is None or value == "":
            continue
        rows.append((key, value))
    return rows


def _summarize_site_generation_summary(path: Path | None) -> list[tuple[str, Any]]:
    if path is None or not path.is_file():
        return []
    suffix = path.suffix.lower()
    if suffix == ".json":
        payload = _read_json(path)
        return _summarize_json_payload(payload)
    if suffix == ".csv":
        rows = _read_csv(path)
        columns = _collect_columns(rows)
        return [("rows", len(rows)), ("columns", ", ".join(columns))]
    return [("path", str(path))]


def _summarize_json_payload(payload: Mapping[str, Any]) -> list[tuple[str, Any]]:
    rows: list[tuple[str, Any]] = []
    preferred_keys = [
        "candidate_outlet_count",
        "retained_outlet_count",
        "retained_basin_count",
        "selected_site_count",
        "candidate_count",
        "selected_count",
        "output_dir",
        "outlets_csv_path",
        "gpkg_path",
        "basins_path",
        "figures_dir",
    ]
    for key in preferred_keys:
        if key in payload:
            rows.append((key, payload.get(key)))
    for key, value in payload.items():
        if key in preferred_keys:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            rows.append((key, value))
        elif isinstance(value, list):
            rows.append((f"{key} count", len(value)))
        elif isinstance(value, Mapping):
            rows.append((f"{key} keys", ", ".join(str(item) for item in value.keys())))
        if len(rows) >= 24:
            break
    return rows


def _render_artifact_links(paths: Iterable[Path | None], *, from_dir: Path) -> str:
    items = []
    for path in paths:
        if path is None:
            continue
        if not isinstance(path, Path):
            path = Path(path)
        label = _path_text(path)
        exists = path.exists()
        css = "" if exists else ' class="missing"'
        text = _link(path, label, from_dir) if exists else html.escape(label)
        suffix = "" if exists else " (missing)"
        items.append(f"<li{css}>{text}{html.escape(suffix)}</li>")
    if not items:
        return '<p class="muted">No artifacts listed.</p>'
    return "<ul>" + "\n".join(items) + "</ul>"


def _render_figure_grid(figures: Sequence[Path], *, from_dir: Path) -> str:
    if not figures:
        return '<p class="muted">No figures were found for this case.</p>'
    cards = []
    for path in figures:
        href = _relative_url(path, from_dir)
        label = html.escape(path.stem.replace("_", " "))
        cards.append(
            '<figure class="figure-card">'
            f'<a href="{href}"><img src="{href}" alt="{label}"></a>'
            f"<figcaption>{label}</figcaption>"
            "</figure>"
        )
    return '<div class="figure-grid">' + "\n".join(cards) + "</div>"


def _render_comparison_summary_table(
    comparisons: Sequence[Mapping[str, Any]],
    *,
    from_dir: Path,
) -> str:
    if not comparisons:
        return (
            '<p class="muted">No comparison report was found. Expected folders are '
            '<code>comparisons/&lt;comparison_id&gt;/comparison_manifest.json</code> '
            "with an optional <code>web/index.html</code>.</p>"
        )
    rows = []
    for comparison in comparisons:
        web_index = comparison.get("web_index")
        metrics_path = comparison.get("metrics_path")
        rows.append(
            [
                _comparison_link(comparison, from_dir=from_dir),
                _display_value(comparison.get("reference_simulation")),
                _simulation_list_text(comparison.get("simulations")),
                _display_value(comparison.get("audit_status")),
                _display_value(comparison.get("n_metric_rows") or len(comparison.get("metrics_rows") or [])),
                _display_value(comparison.get("n_difference_rows")),
                _display_value(len(comparison.get("figures") or [])),
                _display_value(comparison.get("closure_status")),
                _link(metrics_path, "CSV", from_dir) if isinstance(metrics_path, Path) else "",
                _link(web_index, "HTML", from_dir) if isinstance(web_index, Path) else "",
            ]
        )
    return _table_from_rows(
        [
            "Comparison",
            "Reference",
            "Methods",
            "Audit",
            "Metrics",
            "Differences",
            "Figures",
            "Precision",
            "Metrics CSV",
            "Report HTML",
        ],
        rows,
    )


def _render_comparison_closure_overview(
    comparisons: Sequence[Mapping[str, Any]],
    *,
    from_dir: Path,
) -> str:
    comparisons_with_closure = [
        comparison
        for comparison in comparisons
        if comparison.get("numerical_closure_rows")
    ]
    if not comparisons_with_closure:
        return (
            '<p class="muted">Aucune metrique de fermeture de bilan numerique '
            "n'a ete trouvee pour les comparaisons disponibles.</p>"
        )
    rows = []
    for comparison in comparisons_with_closure:
        path = comparison.get("numerical_closure_path")
        rows.append(
            [
                _comparison_link(comparison, from_dir=from_dir),
                _format_float(_closure_solver_metric(comparison, ("modflow", "mf6", "nwt"))),
                _format_float(_closure_solver_metric(comparison, ("bouss",))),
                _format_float(comparison.get("closure_relative_error_p95")),
                _display_value(comparison.get("closure_status")),
                _link(path, "CSV", from_dir) if isinstance(path, Path) and path.is_file() else "",
            ]
        )
    note = (
        '<p class="muted">Diagnostic calcule apres coup sur les budgets normalises: '
        "entrees moins sorties moins variation de stockage. Les valeurs en mm/j "
        "expriment le maximum de residu de fermeture equivalent sur chaque simulation.</p>"
    )
    return _table_from_rows(
        [
            "Comparaison",
            "MODFLOW max mm/j",
            "Boussinesq max mm/j",
            "Erreur rel. p95 max",
            "Avis",
            "Detail",
        ],
        rows,
    ) + note


def _render_testbed_comparison_overview_table(
    cases: Sequence[Mapping[str, Any]],
    *,
    web_root: Path,
) -> str:
    rows = []
    for case in cases:
        comparisons = [
            comparison
            for comparison in case.get("comparisons", [])
            if isinstance(comparison, Mapping)
        ]
        comparison = comparisons[0] if comparisons else {}
        status = _display_value(case.get("status"))
        label = _display_value(case.get("variant_label") or case.get("variant_id"))
        web_index = comparison.get("web_index") if comparison else None
        rows.append(
            [
                _link(web_index, label, web_root)
                if isinstance(web_index, Path)
                else html.escape(label),
                _display_value(case.get("axis")),
                _status_badge(status),
                _format_float(_comparison_solver_wall_time(comparison, "modflow6")),
                _format_float(_comparison_solver_wall_time(comparison, "boussinesq")),
                _format_percent(comparison.get("head_mean_abs_relative_error_percent")),
                _format_percent(comparison.get("global_outflow_mean_abs_relative_error_percent")),
                _format_float(_closure_solver_metric(comparison, ("modflow", "mf6", "nwt"))),
                _format_float(_closure_solver_metric(comparison, ("bouss",))),
                _display_value(comparison.get("closure_status")),
            ]
        )
    table = _table_from_rows(
        [
            "Cas",
            "Axe",
            "Statut",
            "MODFLOW 6 (s)",
            "Boussinesq (s)",
            "Ecart moyen charge (%)",
            "Ecart moyen sorties globales (%)",
            "Fermeture MODFLOW mm/j",
            "Fermeture Bouss. mm/j",
            "Avis precision",
        ],
        rows,
    )
    note = (
        '<p class="muted">Les pourcentages sont des NMAE globales: '
        "somme des ecarts absolus divisee par la somme des valeurs de reference. "
        "Pour les charges, toutes les observables de charge disponibles sont "
        "agregees; pour les sorties globales, le composant "
        "<code>comparable_outflow_total_m3_s</code> est utilise quand il existe.</p>"
    )
    return table + note


def _comparison_solver_wall_time(comparison: Mapping[str, Any], solver: str) -> Any:
    simulations = comparison.get("simulations")
    if not isinstance(simulations, list):
        return None
    solver_key = solver.strip().lower()
    for simulation in simulations:
        if not isinstance(simulation, Mapping):
            continue
        if _display_value(simulation.get("solver")).strip().lower() == solver_key:
            return simulation.get("wall_time_seconds")
    return None


def _closure_solver_metric(
    comparison: Mapping[str, Any],
    solver_tokens: Sequence[str],
    *,
    field: str = "max_abs_closure_mm_d",
) -> float | None:
    rows = comparison.get("numerical_closure_rows")
    if not isinstance(rows, list):
        return None
    values: list[float] = []
    normalized_tokens = tuple(token.lower() for token in solver_tokens)
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        solver = _display_value(row.get("solver")).strip().lower()
        simulation_id = _display_value(row.get("simulation_id")).strip().lower()
        haystack = f"{solver} {simulation_id}"
        if not any(token in haystack for token in normalized_tokens):
            continue
        value = _float_or_none(row.get(field))
        if value is not None:
            values.append(abs(value))
    return max(values) if values else None


def _render_convergence_analysis_section(manifest: Mapping[str, Any]) -> str:
    analysis = manifest.get("convergence_analysis")
    if isinstance(analysis, list):
        items = [
            f"<li>{html.escape(_display_value(item))}</li>"
            for item in analysis
            if _display_value(item).strip()
        ]
        if items:
            return _section("Contraintes de convergence", "<ul>" + "".join(items) + "</ul>")
    if isinstance(analysis, str) and analysis.strip():
        paragraphs = [
            f"<p>{html.escape(part.strip())}</p>"
            for part in analysis.split("\n\n")
            if part.strip()
        ]
        if paragraphs:
            return _section("Contraintes de convergence", "".join(paragraphs))
    return ""


def _render_testbed_direct_links(
    cases: Sequence[Mapping[str, Any]],
    *,
    web_root: Path,
) -> str:
    rows = []
    for case in cases:
        case_path = web_root / "cases" / f"{case['page_id']}.html"
        rows.append(
            [
                _display_value(case.get("variant_label") or case.get("variant_id")),
                _link(case_path, "Page cas", web_root),
                _case_comparison_links(case.get("comparisons") or [], from_dir=web_root),
                _simulation_html_links(case.get("simulation_html_pages") or [], from_dir=web_root),
                _status_badge(_display_value(case.get("status"))),
            ]
        )
    return _table_from_rows(
        ["Cas", "Page", "Comparaison", "Simulation", "Statut"],
        rows,
    )


def _render_case_comparisons(
    comparisons: Sequence[Mapping[str, Any]],
    *,
    from_dir: Path,
) -> str:
    if not comparisons:
        return (
            '<p class="muted">No method comparison was associated with this case yet. '
            "When a comparison run is available, store it under "
            '<code>comparisons/&lt;site_or_case_id&gt;_...</code> or pass it with '
            "<code>--comparison-root</code>.</p>"
        )
    blocks = []
    for comparison in comparisons:
        facts = [
            ("Comparison", _comparison_link(comparison, from_dir=from_dir)),
            ("Report HTML", _comparison_report_link(comparison, from_dir=from_dir)),
            ("Reference", comparison.get("reference_simulation")),
            ("Methods", _simulation_list_text(comparison.get("simulations"))),
            ("Audit", comparison.get("audit_status")),
            ("Metric rows", comparison.get("n_metric_rows") or len(comparison.get("metrics_rows") or [])),
            ("Difference rows", comparison.get("n_difference_rows")),
            ("Figures", len(comparison.get("figures") or [])),
            ("Precision de resolution", comparison.get("closure_status")),
        ]
        blocks.append(
            '<div class="comparison-block">'
            + _definition_list(facts)
            + _render_comparison_closure_table(comparison, from_dir=from_dir)
            + _render_comparison_figure_grid(comparison.get("key_figures") or [], from_dir=from_dir)
            + "</div>"
        )
    return "\n".join(blocks)


def _case_comparison_links(
    comparisons: Sequence[Any],
    *,
    from_dir: Path,
) -> str:
    links = []
    for index, comparison in enumerate(comparisons, start=1):
        if not isinstance(comparison, Mapping):
            continue
        web_index = comparison.get("web_index")
        if not isinstance(web_index, Path):
            continue
        label = "Ouvrir" if len(comparisons) == 1 else f"Ouvrir {index}"
        links.append(_link(web_index, label, from_dir))
    return "<br>".join(links) if links else '<span class="muted">not found</span>'


def _render_comparison_closure_table(
    comparison: Mapping[str, Any],
    *,
    from_dir: Path,
) -> str:
    rows = comparison.get("numerical_closure_rows")
    if not isinstance(rows, list) or not rows:
        return ""
    body_rows = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        body_rows.append(
            [
                _display_value(row.get("simulation_id")),
                _display_value(row.get("solver")),
                _display_value(row.get("n_periods")),
                _format_float(row.get("max_abs_closure_m3_s")),
                _format_float(row.get("max_abs_closure_mm_d")),
                _format_float(row.get("relative_closure_error_p95")),
                _display_value(row.get("diagnostic")),
            ]
        )
    if not body_rows:
        return ""
    path = comparison.get("numerical_closure_path")
    link = (
        "<p>"
        + _link(path, "Ouvrir le detail numerique", from_dir)
        + "</p>"
        if isinstance(path, Path) and path.is_file()
        else ""
    )
    return (
        "<h3>Precision de resolution</h3>"
        + _table_from_rows(
            [
                "Simulation",
                "Solveur",
                "Periodes",
                "Max residu m3/s",
                "Max residu mm/j",
                "Erreur rel. p95",
                "Avis",
            ],
            body_rows,
        )
        + link
    )


def _render_comparison_figure_grid(
    figures: Sequence[Mapping[str, Any]],
    *,
    from_dir: Path,
) -> str:
    if not figures:
        return '<p class="muted">No comparison figures were found.</p>'
    cards = []
    for item in figures:
        path = item.get("path")
        if not isinstance(path, Path) or not path.is_file():
            continue
        href = _relative_url(path, from_dir)
        kind = _display_value(item.get("kind") or "figure")
        observable = _display_value(item.get("observable") or path.stem)
        method_text = _comparison_figure_method_text(item)
        label = " - ".join(part for part in (observable, kind, method_text) if part)
        cards.append(
            '<figure class="figure-card">'
            f'<a href="{href}"><img src="{href}" alt="{html.escape(label)}"></a>'
            f"<figcaption><strong>{html.escape(observable)}</strong>"
            f"<span>{html.escape(kind)}</span>"
            + (f"<span>{html.escape(method_text)}</span>" if method_text else "")
            + "</figcaption></figure>"
        )
    if not cards:
        return '<p class="muted">No displayable comparison figures were found.</p>'
    return '<div class="figure-grid comparison-figures">' + "\n".join(cards) + "</div>"


def _comparison_figure_method_text(item: Mapping[str, Any]) -> str:
    reference = _display_value(item.get("reference_simulation"))
    candidate = _display_value(item.get("candidate_simulation"))
    simulation = _display_value(item.get("simulation_id"))
    if reference and candidate:
        return f"{reference} vs {candidate}"
    return simulation


def _comparison_link(comparison: Mapping[str, Any], *, from_dir: Path) -> str:
    label = _display_value(comparison.get("comparison_id") or "comparison")
    web_index = comparison.get("web_index")
    if isinstance(web_index, Path):
        return _link(web_index, label, from_dir)
    root = comparison.get("root")
    if isinstance(root, Path):
        return _link(root, label, from_dir)
    return html.escape(label)


def _comparison_report_link(comparison: Mapping[str, Any], *, from_dir: Path) -> str:
    web_index = comparison.get("web_index")
    if isinstance(web_index, Path):
        return _link(web_index, _path_text(web_index), from_dir)
    return ""


def _simulation_list_text(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return ""
    labels = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        label = _display_value(item.get("label") or item.get("id"))
        solver = _display_value(item.get("solver"))
        status = _display_value(item.get("status"))
        detail = ", ".join(part for part in (solver, status) if part)
        labels.append(f"{label} ({detail})" if detail else label)
    return "; ".join(labels)


def _render_table(
    rows: Sequence[Mapping[str, Any]],
    *,
    caption: str,
    empty_message: str,
    from_dir: Path,
) -> str:
    del caption, from_dir
    if not rows:
        return f'<p class="muted">{html.escape(empty_message)}</p>'
    columns = _collect_columns(rows)
    body_rows = [[_display_value(row.get(column)) for column in columns] for row in rows]
    return _table_from_rows(columns, body_rows)


def _render_metrics_summary(
    metrics: Sequence[Mapping[str, Any]],
    *,
    metrics_path: Path,
    from_dir: Path,
) -> str:
    if not metrics:
        return (
            '<p class="muted">No metric rows were produced by this run. '
            + _link(metrics_path, "Open testbed_metrics.csv", from_dir)
            + "</p>"
        )
    columns = _collect_columns(metrics)
    identity_columns = {"variant_id", "variant_label", "axis", "status", "duration_s"}
    populated_metric_columns = []
    for column in columns:
        if column in identity_columns:
            continue
        if any(_display_value(row.get(column)).strip() for row in metrics):
            populated_metric_columns.append(column)
    status_counts = Counter(_display_value(row.get("status") or "unknown") for row in metrics)
    rows = [
        ("Metric rows", len(metrics)),
        ("Statuses", _counter_text(status_counts)),
        (
            "Populated scalar metrics",
            ", ".join(populated_metric_columns) if populated_metric_columns else "none populated",
        ),
        ("Full CSV", _link(metrics_path, _path_text(metrics_path), from_dir)),
    ]
    return _definition_list(rows)


def _simulation_html_links(pages: Sequence[Any], *, from_dir: Path) -> str:
    paths = [page for page in pages if isinstance(page, Path)]
    if not paths:
        return '<span class="muted">not found</span>'
    links = []
    for index, path in enumerate(paths, start=1):
        label = "Open" if len(paths) == 1 else f"Open {index}"
        links.append(_link(path, label, from_dir))
    return "<br>".join(links)


def _table_from_rows(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    if not rows:
        return '<p class="muted">No rows.</p>'
    head = "".join(f"<th>{html.escape(str(header))}</th>" for header in headers)
    body = []
    for row in rows:
        cells = []
        for value in row:
            text = str(value)
            if text.startswith("<") and text.endswith(">"):
                cells.append(f"<td>{text}</td>")
            else:
                cells.append(f"<td>{html.escape(text)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (
        '<div class="table-wrap"><table><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "\n".join(body)
        + "</tbody></table></div>"
    )


def _definition_list(items: Iterable[tuple[Any, Any]]) -> str:
    rows = []
    for key, value in items:
        rendered = _render_value(value)
        if rendered == "":
            rendered = '<span class="muted">not declared</span>'
        rows.append(
            "<div>"
            f"<dt>{html.escape(str(key))}</dt>"
            f"<dd>{rendered}</dd>"
            "</div>"
        )
    if not rows:
        return '<p class="muted">No details.</p>'
    return '<dl class="facts">' + "\n".join(rows) + "</dl>"


def _render_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value if value.startswith("<") and value.endswith(">") else html.escape(value)
    if isinstance(value, bool):
        return html.escape(str(value).lower())
    if isinstance(value, (list, tuple, set)):
        return html.escape(", ".join(_display_value(item) for item in value))
    if isinstance(value, Mapping):
        return html.escape("; ".join(f"{key}={_display_value(val)}" for key, val in value.items()))
    return html.escape(_display_value(value))


def _section(title: str, body: str) -> str:
    return f'<section><h2>{html.escape(title)}</h2>{body}</section>'


def _hero(title: str, *, subtitle: str) -> str:
    return (
        '<header class="hero">'
        f"<h1>{html.escape(title)}</h1>"
        f"<p>{html.escape(subtitle)}</p>"
        "</header>"
    )


def _cards(items: Sequence[tuple[str, Any]]) -> str:
    cards = []
    for label, value in items:
        cards.append(
            '<div class="stat">'
            f"<span>{html.escape(label)}</span>"
            f"<strong>{_render_value(value)}</strong>"
            "</div>"
        )
    return '<section class="stats">' + "\n".join(cards) + "</section>"


def _page(title: str, body: str) -> str:
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"  <title>{html.escape(title)}</title>\n"
        "  <style>\n"
        + _css()
        + "  </style>\n"
        "</head>\n"
        "<body>\n"
        '  <main class="page">\n'
        + body
        + "\n  </main>\n"
        "</body>\n"
        "</html>\n"
    )


def _css() -> str:
    return """
:root {
  color-scheme: light;
  --bg: #f7f8fa;
  --panel: #ffffff;
  --ink: #1e252b;
  --muted: #66717c;
  --line: #d7dde4;
  --accent: #0b6b75;
  --ok: #1f7a4d;
  --fail: #b42318;
  --warn: #915930;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font: 18px/1.6 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.page {
  width: min(1760px, calc(100vw - 28px));
  margin: 0 auto;
  padding: 32px 0 56px;
}
.hero {
  margin-bottom: 18px;
  border-bottom: 1px solid var(--line);
  padding-bottom: 18px;
}
.hero h1 {
  margin: 0;
  font-size: clamp(38px, 4vw, 64px);
  line-height: 1.08;
  letter-spacing: 0;
}
.hero p {
  margin: 10px 0 0;
  color: var(--muted);
  word-break: break-word;
}
section {
  margin: 20px 0;
  padding: 26px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
}
h2 {
  margin: 0 0 16px;
  font-size: 28px;
  letter-spacing: 0;
}
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px;
  padding: 0;
  background: transparent;
  border: 0;
}
.stat {
  min-height: 76px;
  padding: 14px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
}
.stat span {
  display: block;
  color: var(--muted);
  font-size: 15px;
  text-transform: uppercase;
}
.stat strong {
  display: block;
  margin-top: 8px;
  font-size: 28px;
  overflow-wrap: anywhere;
}
.facts {
  display: grid;
  grid-template-columns: minmax(180px, 260px) 1fr;
  gap: 1px;
  margin: 0;
  border: 1px solid var(--line);
  background: var(--line);
}
.facts div {
  display: contents;
}
.facts dt,
.facts dd {
  margin: 0;
  padding: 13px 14px;
  background: var(--panel);
  min-width: 0;
}
.facts dt {
  color: var(--muted);
  font-weight: 650;
}
.facts dd {
  overflow-wrap: anywhere;
}
.table-wrap {
  overflow-x: auto;
  border: 1px solid var(--line);
  border-radius: 8px;
}
table {
  width: 100%;
  min-width: 900px;
  border-collapse: collapse;
  background: var(--panel);
}
th, td {
  padding: 14px 15px;
  border-bottom: 1px solid var(--line);
  text-align: left;
  vertical-align: top;
  overflow-wrap: anywhere;
}
th {
  color: var(--muted);
  font-size: 15px;
  text-transform: uppercase;
  background: #f0f3f6;
}
tr:last-child td { border-bottom: 0; }
.badge {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid var(--line);
  font-weight: 650;
  font-size: 16px;
  white-space: nowrap;
}
.badge.ok { color: var(--ok); border-color: color-mix(in srgb, var(--ok), white 70%); }
.badge.failed { color: var(--fail); border-color: color-mix(in srgb, var(--fail), white 70%); }
.badge.planned,
.badge.pending { color: var(--warn); border-color: color-mix(in srgb, var(--warn), white 70%); }
.figure-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
  gap: 16px;
}
.figure-card {
  margin: 0;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  overflow: hidden;
}
.figure-card img {
  display: block;
  width: 100%;
  aspect-ratio: 4 / 3;
  object-fit: contain;
  background: #f1f4f7;
}
.figure-card figcaption {
  padding: 11px 13px;
  color: var(--muted);
  font-size: 18px;
}
.figure-card figcaption strong,
.figure-card figcaption span {
  display: block;
}
.figure-card figcaption strong {
  color: var(--ink);
}
.comparison-block + .comparison-block {
  margin-top: 18px;
  padding-top: 18px;
  border-top: 1px solid var(--line);
}
.muted,
.missing {
  color: var(--muted);
}
ul {
  margin: 0;
  padding-left: 18px;
}
@media (max-width: 720px) {
  .page {
    width: min(100vw - 20px, 100%);
    padding-top: 18px;
  }
  section {
    padding: 14px;
  }
  .facts {
    grid-template-columns: 1fr;
  }
}
"""


def _status_badge(status: str) -> str:
    css = "ok" if status in {"ok", "skipped_existing_ok"} else status.lower().replace(" ", "_")
    css = re.sub(r"[^a-z0-9_-]+", "", css)
    return f'<span class="badge {html.escape(css)}">{html.escape(status or "unknown")}</span>'


def _numeric_stats(values: Sequence[Any]) -> str:
    numeric = []
    for value in values:
        try:
            numeric.append(float(value))
        except (TypeError, ValueError):
            continue
    if not numeric:
        return f"{len(values)} values"
    mean = statistics.fmean(numeric)
    return (
        f"{len(numeric)} values; min={_format_float(min(numeric))}; "
        f"max={_format_float(max(numeric))}; mean={_format_float(mean)}"
    )


def _counter_text(counter: Counter[str]) -> str:
    if not counter:
        return "not declared"
    return "; ".join(f"{key} ({value})" for key, value in counter.most_common())


def _collect_columns(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    columns: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in columns:
                columns.append(str(key))
    return columns


def _preview_rows(rows: Sequence[Mapping[str, Any]], *, max_rows: int) -> list[Mapping[str, Any]]:
    return list(rows[:max_rows])


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def _read_csv(path: Path | str | None) -> list[dict[str, str]]:
    if path is None:
        return []
    path = Path(path)
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _read_toml(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    if load_toml_with_base_config is not None:
        return load_toml_with_base_config(path)
    if tomllib is None:
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _remove_generated_case_pages(web_root: Path) -> None:
    cases_dir = web_root / "cases"
    if not cases_dir.is_dir():
        return
    for path in cases_dir.glob("*.html"):
        path.unlink()
    try:
        cases_dir.rmdir()
    except OSError:
        pass


def _get_nested(mapping: Mapping[str, Any], keys: Sequence[str]) -> Any:
    value: Any = mapping
    for key in keys:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _path_or_none(value: Any) -> Path | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if os.name == "nt":
        match = re.match(r"^/mnt/([A-Za-z])(?:/(.*))?$", text)
        if match:
            drive = match.group(1).upper()
            tail = (match.group(2) or "").replace("/", "\\")
            return Path(f"{drive}:\\{tail}")
    return Path(text)


def _path_text(path: Path | None) -> str:
    if path is None:
        return ""
    return str(path)


def _looks_like_wsl_mount_path(path: Path) -> bool:
    return path.as_posix().startswith("/mnt/")


def _display_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return _format_float(value)
    if isinstance(value, (list, tuple, set)):
        return ", ".join(_display_value(item) for item in value)
    if isinstance(value, Mapping):
        return "; ".join(f"{key}={_display_value(val)}" for key, val in value.items())
    return str(value)


def _format_float(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _display_value(value)
    if not math.isfinite(number):
        return str(number)
    if abs(number) >= 1000 or (0 < abs(number) < 0.001):
        return f"{number:.4g}"
    return f"{number:.4f}".rstrip("0").rstrip(".")


def _format_percent(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(number):
        return ""
    if abs(number) >= 100.0:
        return f"{number:.1f}"
    if abs(number) >= 10.0:
        return f"{number:.2f}"
    return f"{number:.3f}".rstrip("0").rstrip(".")


def _normalize_key(value: Any) -> str | None:
    text = _display_value(value).strip().lower()
    if not text:
        return None
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_") or None


def _safe_page_id(value: str) -> str:
    key = _normalize_key(value)
    return key or "item"


def _resolve_web_root(output_root: Path, web_dir: str) -> Path:
    web_path = Path(web_dir)
    if web_path.is_absolute():
        return web_path.resolve()
    return (output_root / web_path).resolve()


def _relative_url(target: Path, from_dir: Path) -> str:
    try:
        rel = os.path.relpath(str(target.resolve()), str(from_dir.resolve()))
    except ValueError:
        rel = str(target.resolve())
    rel = rel.replace("\\", "/")
    return quote(rel, safe="/._:-")


def _link(path: Path | None, label: str, from_dir: Path) -> str:
    if path is None:
        return html.escape(label)
    href = _relative_url(path, from_dir)
    return f'<a href="{href}">{html.escape(label or _path_text(path))}</a>'


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a reusable static HTML report from testbed or regional-lab outputs."
    )
    parser.add_argument(
        "output_root",
        type=Path,
        help="Directory containing testbed_manifest.json or regional_lab_report.json.",
    )
    parser.add_argument(
        "--web-dir",
        default="web_synthesis",
        help=(
            "HTML output directory, relative to output_root unless absolute. "
            "Default: web_synthesis."
        ),
    )
    parser.add_argument(
        "--title",
        default=None,
        help="Optional title for the generated synthesis page.",
    )
    parser.add_argument(
        "--site-catalog",
        type=Path,
        default=None,
        help="Optional CSV catalog used to enrich site-level pages.",
    )
    parser.add_argument(
        "--site-generation-config",
        type=Path,
        default=None,
        help="Optional TOML config used by the upstream site-generation workflow.",
    )
    parser.add_argument(
        "--site-generation-summary",
        type=Path,
        default=None,
        help="Optional JSON/CSV/MD summary written by the upstream site-generation workflow.",
    )
    parser.add_argument(
        "--comparison-root",
        type=Path,
        action="append",
        default=None,
        help=(
            "Optional comparison output root to include. Can be repeated. "
            "By default, comparisons are auto-discovered under output_root/comparisons/."
        ),
    )
    parser.add_argument(
        "--comparison-index-only",
        action="store_true",
        help=(
            "For testbed reports, generate only one comparison-oriented index "
            "and skip per-case HTML pages."
        ),
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
