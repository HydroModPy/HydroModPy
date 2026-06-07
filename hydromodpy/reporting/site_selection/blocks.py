"""Reusable report blocks for site-selection HTML reports."""

from __future__ import annotations

import csv
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from hydromodpy.display.report_blocks import (
    DetailLevel,
    ReportBlock,
    ReportFigure,
    ReportLink,
    ReportMetric,
    ReportTable,
    key_value_table,
)

DETAIL_LEVELS: tuple[DetailLevel, ...] = ("compact", "standard", "audit")
DETAIL_LEVEL_RANK = {level: index for index, level in enumerate(DETAIL_LEVELS)}


def build_site_selection_plan_blocks(
    plan: Mapping[str, Any],
    *,
    manifest_path: Path,
    output_root: Path,
) -> list[ReportBlock]:
    """Build blocks for a plan-only site-selection report."""

    selection_id = str(plan.get("selection_id") or "site_selection_plan")
    strategy = _mapping(plan.get("strategy"))
    territory = _mapping(plan.get("territory"))
    dem = _mapping(plan.get("dem"))
    input_cfg = _mapping(plan.get("input"))
    hydrology = _mapping(plan.get("hydrology"))
    criteria = _mapping(plan.get("criteria"))
    map_context = _mapping(plan.get("map_context"))
    context_layers = _sequence(map_context.get("layers"))
    planned_outputs = _sequence(plan.get("planned_outputs"))

    return [
        ReportBlock(
            block_id="selection_identity",
            title="Identite de la selection",
            level="compact",
            lead="Synthese du plan avant execution spatiale.",
            metrics=(
                ReportMetric("Selection", selection_id),
                ReportMetric("Mode", input_cfg.get("mode") or "plan_only"),
                ReportMetric("Sorties prevues", len(planned_outputs)),
                ReportMetric("Racine de sortie", output_root),
            ),
            warnings=(
                "Aucun site n'est retenu ou rejete dans ce rapport: il decrit le plan avant execution.",
            ),
        ),
        ReportBlock(
            block_id="selection_strategy",
            title="Strategie",
            level="standard",
            tables=(
                key_value_table(
                    "selection_strategy_table",
                    "Parametres de strategie",
                    (
                        ("Principe", strategy.get("principle")),
                        ("Profil", strategy.get("effective_profile") or strategy.get("profile")),
                        ("Mode candidats", strategy.get("candidate_mode")),
                        ("Observation principale", strategy.get("primary_observation_type")),
                        ("Axes principaux", _format_value(strategy.get("primary_axes"))),
                    ),
                ),
            ),
        ),
        ReportBlock(
            block_id="territory_context",
            title="Territoire et contexte",
            level="standard",
            tables=(
                key_value_table(
                    "territory_context_table",
                    "Perimetre spatial",
                    (
                        ("Territoire", _territory_label(territory)),
                        ("Couches contexte", _context_layer_summary(context_layers)),
                    ),
                ),
            ),
        ),
        ReportBlock(
            block_id="dem_and_hydrology",
            title="Donnees et calculs prevus",
            level="standard",
            tables=(
                key_value_table(
                    "dem_and_hydrology_table",
                    "DEM et hydrologie",
                    (
                        ("Source DEM", dem.get("source")),
                        ("Chemin DEM", dem.get("path")),
                        ("Resolution DEM", _unit_value(dem.get("resolution_m"), "m")),
                        ("Politique cache", dem.get("cache_policy")),
                        ("Methode hydrologique", hydrology.get("method")),
                        ("Algorithme d'ecoulement", hydrology.get("flow_algorithm")),
                        ("Conditionnement DEM", hydrology.get("dem_correction_type")),
                    ),
                ),
            ),
        ),
        ReportBlock(
            block_id="selection_criteria",
            title="Criteres",
            level="standard",
            tables=(
                key_value_table(
                    "selection_criteria_table",
                    "Configuration des criteres",
                    _criteria_items(criteria),
                ),
            ),
        ),
        ReportBlock(
            block_id="planned_outputs",
            title="Sorties prevues",
            level="audit",
            tables=(
                ReportTable(
                    "planned_outputs_table",
                    "Sorties",
                    columns=(("output", "Sortie"),),
                    rows=tuple({"output": item} for item in planned_outputs),
                    empty_message="Aucune sortie prevue.",
                ),
            ),
        ),
        ReportBlock(
            block_id="artifact_links",
            title="Artefacts disponibles",
            level="audit",
            links=(ReportLink(manifest_path.name, manifest_path, "manifest"),),
        ),
    ]


def build_site_selection_plan_block_variants(
    plan: Mapping[str, Any],
    *,
    manifest_path: Path,
    output_root: Path,
) -> tuple[tuple[str, dict[str, ReportBlock]], ...]:
    """Build per-block level variants for a plan-only report."""

    return build_block_variants(
        build_site_selection_plan_blocks(
            plan,
            manifest_path=manifest_path,
            output_root=output_root,
        )
    )


def build_site_selection_result_blocks(
    manifest: Mapping[str, Any],
    *,
    manifest_path: Path,
    output_root: Path,
    map_path: Path,
    selected: list[dict[str, str]],
    rejected: list[dict[str, str]],
    decisions: list[dict[str, Any]],
    components: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    candidate_generation: list[dict[str, Any]] | None = None,
) -> list[ReportBlock]:
    """Build blocks for an executed site-selection report."""

    selection_id = str(manifest.get("selection_id") or "site_selection")
    counts = _mapping(manifest.get("counts"))
    strategy = _mapping(manifest.get("strategy"))
    territory = _mapping(manifest.get("territory"))
    criteria = _mapping(manifest.get("criteria"))
    dem = _mapping(manifest.get("dem"))
    flow_products = _mapping(manifest.get("flow_products"))
    outputs = _mapping(manifest.get("outputs"))
    map_context = _mapping(manifest.get("map_context"))
    context_layers = _sequence(map_context.get("layers"))
    provenance_warnings = _provenance_warnings(
        manifest,
        output_root=output_root,
        outputs=outputs,
    )

    decision_by_site = _final_decision_by_site(decisions)
    component_counts, family_counts = _component_counts(components)
    candidate_generation_rows = candidate_generation or []

    return [
        ReportBlock(
            block_id="selection_identity",
            title="Identite de la selection",
            level="compact",
            lead="Synthese de la selection executee.",
            metrics=(
                ReportMetric("Selection", selection_id),
                ReportMetric("Sites retenus", counts.get("selected", len(selected))),
                ReportMetric("Sites rejetes", counts.get("rejected", len(rejected))),
                ReportMetric("Decisions", counts.get("decisions", len(decisions))),
                ReportMetric("Criteres traces", counts.get("criteria_components", len(components))),
            ),
            warnings=provenance_warnings,
        ),
        ReportBlock(
            block_id="selection_strategy",
            title="Strategie",
            level="standard",
            lead="Regles de selection et contexte de calcul declares dans le manifeste.",
            tables=(
                key_value_table(
                    "selection_strategy_table",
                    "Parametres de strategie",
                    (
                        ("Principe", strategy.get("principle")),
                        ("Profil", strategy.get("effective_profile") or strategy.get("profile")),
                        ("Mode candidats", strategy.get("candidate_mode")),
                        ("Observation principale", strategy.get("primary_observation_type")),
                        ("Territoire", _territory_label(territory)),
                        ("Ruleset", criteria.get("ruleset")),
                        ("Contexte cartographique", _context_layer_summary(context_layers)),
                    ),
                ),
            ),
            warnings=tuple(
                item
                for item in (
                    _principle_explanation(strategy, criteria),
                    _dem_explanation(dem, flow_products),
                )
                if item
            ),
        ),
        ReportBlock(
            block_id="selection_map",
            title="Carte de controle",
            level="compact",
            figures=(
                ReportFigure(
                    "site_selection_map",
                    "Carte de controle",
                    map_path,
                    (
                        "Fond DEM regional, contours des bassins, exutoires retenus/rejetes "
                        "et stations d'observation associees."
                    ),
                    embed=True,
                ),
            ),
        ),
        _candidate_generation_block(candidate_generation_rows),
        ReportBlock(
            block_id="selected_sites",
            title="Sites retenus",
            level="standard",
            tables=(
                ReportTable(
                    "selected_sites_table",
                    "Sites retenus",
                    columns=(
                        ("site_id", "Site"),
                        ("region_id", "Region"),
                        ("area_km2", "Surface km2"),
                        ("rank_score", "Score"),
                        ("decision_reason", "Decision"),
                        ("warning_flags", "Avertissements"),
                    ),
                    rows=tuple(
                        _selected_row(row, decision_by_site.get(row.get("site_id", "")))
                        for row in selected
                    ),
                    empty_message="Aucun site retenu.",
                ),
            ),
        ),
        ReportBlock(
            block_id="rejected_sites",
            title="Sites rejetes",
            level="standard",
            tables=(
                ReportTable(
                    "rejected_sites_table",
                    "Sites rejetes",
                    columns=(
                        ("site_id", "Site"),
                        ("area_km2", "Surface km2"),
                        ("status", "Statut"),
                        ("decision_stage", "Etape"),
                        ("decision_reason", "Raison"),
                        ("blocking_flags", "Flags bloquants"),
                    ),
                    rows=tuple(
                        _rejected_row(row, decision_by_site.get(row.get("site_id", "")))
                        for row in rejected
                    ),
                    empty_message="Aucun site rejete.",
                ),
            ),
        ),
        _station_influence_block(components),
        ReportBlock(
            block_id="criteria_components",
            title="Criteres et evidences",
            level="audit",
            metrics=(
                ReportMetric("Observations tracees", len(evidence)),
                ReportMetric("Rejets bloquants", counts.get("blocking_rejections", 0)),
                ReportMetric("Avertissements", counts.get("warnings", 0)),
            ),
            tables=(
                key_value_table(
                    "criteria_component_summary",
                    "Synthese des criteres",
                    (
                        ("Criteres", _component_summary(component_counts)),
                        ("Familles auditees", _component_summary(family_counts)),
                    ),
                ),
            ),
        ),
        ReportBlock(
            block_id="artifact_links",
            title="Artefacts",
            level="audit",
            links=_artifact_links(
                manifest_path=manifest_path, output_root=output_root, outputs=outputs
            ),
        ),
    ]


def build_site_selection_result_block_variants(
    manifest: Mapping[str, Any],
    *,
    manifest_path: Path,
    output_root: Path,
    map_path: Path,
    selected: list[dict[str, str]],
    rejected: list[dict[str, str]],
    decisions: list[dict[str, Any]],
    components: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    candidate_generation: list[dict[str, Any]] | None = None,
) -> tuple[tuple[str, dict[str, ReportBlock]], ...]:
    """Build per-block level variants for an executed selection report."""

    return build_block_variants(
        build_site_selection_result_blocks(
            manifest,
            manifest_path=manifest_path,
            output_root=output_root,
            map_path=map_path,
            selected=selected,
            rejected=rejected,
            decisions=decisions,
            components=components,
            evidence=evidence,
            candidate_generation=candidate_generation,
        )
    )


def blocks_for_detail_level(
    blocks: Sequence[ReportBlock],
    level: DetailLevel,
) -> tuple[ReportBlock, ...]:
    """Return the blocks whose minimum level is visible at ``level``."""

    return tuple(
        replace(block, level=level) for block in blocks if _level_at_least(level, block.level)
    )


def build_block_variants(
    blocks: Sequence[ReportBlock],
) -> tuple[tuple[str, dict[str, ReportBlock]], ...]:
    """Expand minimum-level blocks into compact/standard/audit variants."""

    groups: list[tuple[str, dict[str, ReportBlock]]] = []
    for block in blocks:
        variants: dict[str, ReportBlock] = {}
        for level in DETAIL_LEVELS:
            if _level_at_least(level, block.level):
                variants[level] = replace(block, level=level)
            else:
                variants[level] = ReportBlock(
                    block_id=block.block_id,
                    title=block.title,
                    level=level,
                    status="empty",
                    lead=f"Bloc disponible a partir du niveau {block.level}.",
                )
        groups.append((block.block_id, variants))
    return tuple(groups)


def _level_at_least(level: DetailLevel, minimum: DetailLevel) -> bool:
    return DETAIL_LEVEL_RANK[level] >= DETAIL_LEVEL_RANK[minimum]


def _selected_row(row: Mapping[str, str], decision: Mapping[str, Any] | None) -> dict[str, Any]:
    decision = decision or {}
    return {
        "site_id": row.get("site_id"),
        "region_id": row.get("region_id"),
        "area_km2": row.get("area_km2"),
        "rank_score": _format_score(_decision_value(decision, "rank_score")),
        "decision_reason": _decision_message(decision) or "selected",
        "warning_flags": _join_flags(_decision_value(decision, "warning_flags")),
    }


def _rejected_row(row: Mapping[str, str], decision: Mapping[str, Any] | None) -> dict[str, Any]:
    decision = decision or {}
    return {
        "site_id": row.get("site_id"),
        "area_km2": row.get("area_km2"),
        "status": row.get("status"),
        "decision_stage": _decision_value(decision, "decision_stage"),
        "decision_reason": _decision_message(decision) or row.get("failure_reason"),
        "blocking_flags": _join_flags(_decision_value(decision, "blocking_flags")),
    }


def _final_decision_by_site(decisions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for decision in decisions:
        if str(decision.get("criterion_id") or "") != "final_selection":
            continue
        catchment_id = str(decision.get("catchment_id") or "").strip()
        if catchment_id:
            records[catchment_id] = decision
    return records


def _decision_value(decision: Mapping[str, Any], key: str) -> Any:
    if key in decision:
        return decision.get(key)
    properties = decision.get("properties")
    if isinstance(properties, Mapping):
        return properties.get(key)
    return None


def _decision_message(decision: Mapping[str, Any]) -> Any:
    return _decision_value(decision, "decision_reason") or decision.get("message")


def _candidate_generation_block(rows: list[dict[str, Any]]) -> ReportBlock:
    if not rows:
        return ReportBlock(
            block_id="candidate_generation",
            title="Generation de candidats",
            level="audit",
            status="not_applicable",
        )
    statuses = Counter(str(row.get("status") or "unknown") for row in rows)
    reasons = Counter(
        str(row.get("rejection_reason") or "accepted")
        for row in rows
        if str(row.get("status") or "") == "rejected"
    )
    scored_distances = [
        float(row["reference_network_distance_m"])
        for row in rows
        if row.get("reference_network_distance_m") not in (None, "")
    ]
    metrics = [
        ReportMetric("Candidats acceptes", statuses.get("accepted", 0)),
        ReportMetric("Candidats rejetes audites", statuses.get("rejected", 0)),
        ReportMetric("Raisons de rejet", _component_summary(reasons)),
    ]
    if scored_distances:
        metrics.append(
            ReportMetric(
                "Distance mediane au reseau de reference",
                f"{_median(scored_distances):.1f}",
                "m",
            )
        )
    return ReportBlock(
        block_id="candidate_generation",
        title="Generation de candidats",
        level="audit",
        lead=(
            "Audit des cellules du reseau DEM transformees en exutoires candidats. "
            "Les lignes rejetees expliquent pourquoi une cellule n'a pas ete delimitee."
        ),
        metrics=tuple(metrics),
        tables=(
            ReportTable(
                "candidate_generation_table",
                "Candidats generes et rejets audites",
                columns=(
                    ("candidate_id", "Candidat"),
                    ("status", "Statut"),
                    ("rejection_reason", "Rejet"),
                    ("accumulation_value", "Accumulation"),
                    ("nearest_selected_distance_m", "Distance selection m"),
                    ("reference_network_distance_m", "Distance ref m"),
                    ("reference_network_status", "Statut ref"),
                ),
                rows=tuple(_candidate_generation_row(row) for row in rows[:80]),
                empty_message="Aucun candidat genere.",
            ),
        ),
    )


def _candidate_generation_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": row.get("candidate_id"),
        "status": row.get("status"),
        "rejection_reason": row.get("rejection_reason"),
        "accumulation_value": _format_score(row.get("accumulation_value")),
        "nearest_selected_distance_m": _format_score(row.get("nearest_selected_distance_m")),
        "reference_network_distance_m": _format_score(row.get("reference_network_distance_m")),
        "reference_network_status": row.get("reference_network_status"),
    }


def _station_influence_block(components: list[dict[str, Any]]) -> ReportBlock:
    rows = [
        _station_influence_row(component)
        for component in components
        if str(component.get("criterion_id") or "") == "station_influence"
    ]
    if not rows:
        return ReportBlock(
            block_id="station_influence",
            title="Influence hydrometrique des stations",
            level="standard",
            status="not_applicable",
        )
    status_counts = Counter(str(row.get("decision") or "unknown") for row in rows)
    return ReportBlock(
        block_id="station_influence",
        title="Influence hydrometrique des stations",
        level="standard",
        lead=(
            "Controle des metadonnees d'influence associees aux stations de debit. "
            "Ce filtre signale une station ou un site hydrometrique declare influence; "
            "il ne prouve pas l'absence de barrage en amont du bassin."
        ),
        metrics=(
            ReportMetric("Sans influence connue", status_counts.get("no_known_influence", 0)),
            ReportMetric("Influence locale", status_counts.get("local_influence", 0)),
            ReportMetric("Influence generale", status_counts.get("general_influence", 0)),
            ReportMetric("Inconnu", status_counts.get("unknown", 0)),
        ),
        tables=(
            ReportTable(
                "station_influence_table",
                "Influence station",
                columns=(
                    ("site_id", "Site"),
                    ("station_id", "Station"),
                    ("decision", "Influence"),
                    ("criterion_status", "Decision critere"),
                    ("flags", "Flags"),
                    ("keywords", "Mots-cles"),
                    ("reason", "Raison"),
                ),
                rows=tuple(rows),
                empty_message="Aucun critere station_influence trace.",
            ),
        ),
        warnings=(
            "Le controle station_influence utilise les metadonnees hydrometriques "
            "disponibles. Pour prouver spatialement l'absence d'obstacle amont, il "
            "faudra une couche dediee type ROE.",
        ),
    )


def _station_influence_row(component: Mapping[str, Any]) -> dict[str, Any]:
    evidence = _mapping(component.get("evidence_json"))
    return {
        "site_id": component.get("site_id"),
        "station_id": evidence.get("source_feature_id"),
        "decision": evidence.get("station_influence_status") or component.get("raw_value"),
        "criterion_status": component.get("criterion_status"),
        "flags": _join_flags(evidence.get("station_influence_flags")),
        "keywords": _join_flags(evidence.get("matched_keywords")),
        "reason": component.get("reason"),
    }


def _artifact_links(
    *,
    manifest_path: Path,
    output_root: Path,
    outputs: Mapping[str, Any],
) -> tuple[ReportLink, ...]:
    links = [ReportLink(manifest_path.name, manifest_path, "manifest")]
    for label, raw_path in sorted(outputs.items()):
        if not raw_path:
            continue
        path = Path(str(raw_path))
        if not path.is_absolute():
            path = output_root / path
        links.append(ReportLink(str(label), path, "output"))
    return tuple(links)


def _provenance_warnings(
    manifest: Mapping[str, Any],
    *,
    output_root: Path,
    outputs: Mapping[str, Any],
) -> tuple[str, ...]:
    provenance = _synthetic_provenance_labels(manifest, output_root=output_root, outputs=outputs)
    if not provenance:
        return ()
    labels = ", ".join(sorted(provenance))
    return (
        "Cette selection utilise des entrees de fixture ou synthetiques "
        f"({labels}). Les positions et bassins servent au controle du workflow "
        "et du rendu; ils ne doivent pas etre interpretes comme des sites reels.",
    )


def _synthetic_provenance_labels(
    manifest: Mapping[str, Any],
    *,
    output_root: Path,
    outputs: Mapping[str, Any],
) -> set[str]:
    labels: set[str] = set()
    input_cfg = _mapping(manifest.get("input"))
    catchments_csv = input_cfg.get("catchments_csv")
    if catchments_csv:
        labels.update(_synthetic_labels_from_csv(Path(str(catchments_csv))))

    for key in (
        "selected_outlets_geojson",
        "rejected_outlets_geojson",
        "selected_basins_geojson",
        "rejected_basins_geojson",
    ):
        path = _resolve_output_path(outputs.get(key), output_root=output_root)
        if path is not None:
            labels.update(_synthetic_labels_from_geojson(path))
    return labels


def _resolve_output_path(value: object, *, output_root: Path) -> Path | None:
    if not value:
        return None
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = output_root / path
    return path


def _synthetic_labels_from_csv(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    labels: set[str] = set()
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                labels.update(_synthetic_labels_from_mapping(row))
    except OSError:
        return set()
    return labels


def _synthetic_labels_from_geojson(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    labels: set[str] = set()
    features = _sequence(payload.get("features")) if isinstance(payload, Mapping) else []
    for feature in features:
        if isinstance(feature, Mapping):
            labels.update(_synthetic_labels_from_mapping(_mapping(feature.get("properties"))))
    return labels


def _synthetic_labels_from_mapping(row: Mapping[str, Any]) -> set[str]:
    labels: set[str] = set()
    for key in (
        "source",
        "source_dataset",
        "provider_source",
        "inventory_source",
        "geometry_source",
        "outlet_geometry_source",
        "tags",
    ):
        value = str(row.get(key) or "").strip()
        if value and _looks_synthetic_label(value):
            labels.add(value)
    return labels


def _looks_synthetic_label(value: str) -> bool:
    normalized = value.lower()
    return any(token in normalized for token in ("fixture", "synthetic", "test_fixture"))


def _criteria_items(criteria: Mapping[str, Any]) -> tuple[tuple[str, Any], ...]:
    return (
        ("Ruleset", criteria.get("ruleset")),
        ("Hard reject", _format_value(criteria.get("hard_reject"))),
        ("Warning", _format_value(criteria.get("warning"))),
        ("Soft score", _format_value(criteria.get("soft_score"))),
        ("Report only", _format_value(criteria.get("report_only"))),
        ("Surface", criteria.get("area_mode")),
        ("Plages surface", _format_value(criteria.get("area_ranges"))),
        ("Hydrometrie", criteria.get("flow_station_mode")),
        ("Piezometrie", criteria.get("piezometer_mode")),
        ("Geologie", criteria.get("geology_mode")),
    )


def _component_counts(
    components: list[dict[str, Any]],
) -> tuple[dict[str, int], dict[str, int]]:
    by_criterion: dict[str, int] = {}
    by_family: dict[str, int] = {}
    for component in components:
        key = str(component.get("criterion_id") or "unknown")
        by_criterion[key] = by_criterion.get(key, 0) + 1
        family = str(component.get("criterion_family") or "unknown")
        by_family[family] = by_family.get(family, 0) + 1
    return by_criterion, by_family


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _sequence(value: object) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return list(value)
    return []


def _territory_label(territory: Mapping[str, Any]) -> str:
    parts = [str(territory.get("mode") or "")]
    if territory.get("regions"):
        parts.append(", ".join(str(item) for item in territory["regions"]))
    if territory.get("departments"):
        parts.append(", ".join(str(item) for item in territory["departments"]))
    if territory.get("bbox"):
        parts.append(str(territory["bbox"]))
    return " - ".join(part for part in parts if part)


def _context_layer_summary(layers: list[Any]) -> str:
    if not layers:
        return "aucune"
    labels = []
    for layer in layers:
        if isinstance(layer, Mapping):
            labels.append(f"{layer.get('name', '')} ({layer.get('role', 'other')})")
        else:
            labels.append(str(layer))
    return ", ".join(label for label in labels if label)


def _component_summary(counts: Mapping[str, int]) -> str:
    if not counts:
        return "aucun critere trace"
    return ", ".join(f"{key}: {value}" for key, value in sorted(counts.items()))


def _median(values: Sequence[float]) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2.0


def _principle_explanation(
    strategy: Mapping[str, Any],
    criteria: Mapping[str, Any],
) -> str:
    principle = str(strategy.get("principle") or "")
    candidate_mode = str(strategy.get("candidate_mode") or "")
    observation_type = str(strategy.get("primary_observation_type") or "")
    area = _mapping(criteria.get("area"))
    area_rule = _area_rule_label(area)
    if principle == "observation_led" or candidate_mode == "station_outlets":
        return (
            "La selection est pilotee par les observations: les stations de jaugeage "
            "fournissent d'abord les exutoires candidats. Les bassins sont ensuite "
            "delimites depuis ces exutoires et filtres par les criteres declares "
            f"(station principale: {observation_type or 'non precisee'}; {area_rule})."
        )
    return (
        "La selection croise directement les criteres spatiaux et physiques declares "
        f"({area_rule})."
    )


def _area_rule_label(area: Mapping[str, Any]) -> str:
    mode = str(area.get("mode") or "report_only")
    mode_label = {
        "hard_reject": "exigee",
        "warning": "controlee en avertissement",
        "score": "scoree",
        "stratify": "utilisee pour stratifier",
        "report_only": "rapportee",
    }.get(mode, mode)
    ranges = _area_ranges_label(area.get("ranges"))
    if ranges:
        return f"surface {mode_label} dans les plages {ranges}"
    minimum = area.get("hard_min_area_km2")
    maximum = area.get("hard_max_area_km2")
    if minimum is not None and maximum is not None:
        return f"surface {mode_label} entre {minimum} et {maximum} km2"
    if minimum is not None:
        return f"surface {mode_label} >= {minimum} km2"
    if maximum is not None:
        return f"surface {mode_label} <= {maximum} km2"
    preferred = area.get("preferred_area_km2")
    if preferred is not None:
        return f"surface {mode_label} autour de {preferred} km2"
    return f"surface {mode_label}"


def _area_ranges_label(value: object) -> str:
    if not isinstance(value, list):
        return ""
    labels: list[str] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        minimum = item.get("min_area_km2")
        maximum = item.get("max_area_km2")
        if minimum is None or maximum is None:
            continue
        label = str(item.get("label") or item.get("range_id") or "").strip()
        bounds = f"{minimum}-{maximum} km2"
        labels.append(f"{label} ({bounds})" if label else bounds)
    return "; ".join(labels)


def _dem_explanation(
    dem: Mapping[str, Any],
    flow_products: Mapping[str, Any],
) -> str:
    request_extent = str(dem.get("request_extent") or "")
    map_extent = str(dem.get("map_background_extent") or "")
    has_map_dem = bool(flow_products.get("map_dem_path"))
    if has_map_dem and request_extent == "outlets" and map_extent == "territory":
        return (
            "Le calcul hydrologique utilise un DEM limite aux exutoires, tandis que "
            "la carte recharge un DEM regional pour le contexte visuel complet."
        )
    if has_map_dem:
        return "La carte utilise un DEM de fond dedie au controle visuel des bassins."
    return "La carte utilise les artefacts spatiaux disponibles dans le manifeste."


def _unit_value(value: object, unit: str) -> str:
    if value in (None, ""):
        return ""
    return f"{value} {unit}"


def _format_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, Mapping):
        return json.dumps(value, ensure_ascii=True, sort_keys=True)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return ", ".join(_format_value(item) for item in value)
    return str(value)


def _format_score(value: object) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return str(value)


def _join_flags(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=True)


__all__ = [
    "build_site_selection_plan_blocks",
    "build_site_selection_result_blocks",
]
