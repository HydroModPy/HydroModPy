"""Build site inventories for strict stationary Boussinesq stress campaigns.

The inventories are dry-run artifacts only: they do not generate comparison
configs and do not launch MF6 or Boussinesq.  They reuse the regional-lab site
catalog and the mesh-bundle preflight helper so the next Picard/VI campaigns can
be selected from auditable rows instead of hard-coded case lists.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import tomllib
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.analysis.testbed.regional_lab_bootstrap import (  # noqa: E402
    inspect_mesh_bundle_boussinesq_readiness,
)
from hydromodpy.analysis.testbed.regional_lab_catalog import load_site_catalog  # noqa: E402
from hydromodpy.analysis.testbed.regional_lab_config import RegionalLabConfig  # noqa: E402
from hydromodpy.analysis.testbed.regional_lab_site_selection import filter_sites  # noqa: E402

DEFAULT_REGIONAL_LAB_CONFIG = HERE / "natural_regional_lab.toml"
DEFAULT_MESH_GALLERY_ROOT = REPO_ROOT / "examples/projects/07_mesh_gallery"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "docs/_dev_notes/diagnostics/boussinesq_stationary_site_inventory"

SITE_INVENTORY_CSV = "bouss_stationary_site_inventory.csv"
MESH_INVENTORY_CSV = "bouss_stationary_mesh_inventory.csv"
SUMMARY_JSON = "bouss_stationary_site_inventory_summary.json"
SUMMARY_MD = "bouss_stationary_site_inventory_summary.md"

SCALE_TARGET_COUNTS = {
    "10km2": 10,
    "100km2": 10,
    "1000km2": 10,
}

MESH_DIR_RE = re.compile(
    r"^mesh_(?:(?P<family>headwater|s3)_)?(?P<scale>\d+km2)_outlet_"
    r"(?P<outlet_id>\d+)_(?P<constraints>.+?)_buffer(?P<buffer_m>\d+)"
    r"(?P<variant_suffix>.*)$"
)


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)
    regional_lab_config = _resolve_path(args.regional_lab_config)
    mesh_gallery_root = _resolve_path(args.mesh_gallery_root)
    output_dir = _resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    site_rows = _regional_lab_site_rows(regional_lab_config)
    mesh_rows = _regional_lab_existing_child_mesh_rows(site_rows) + _mesh_gallery_rows(
        mesh_gallery_root
    )
    site_rows = _merge_mesh_gallery_counts(site_rows, mesh_rows)
    summary = _build_summary(
        regional_lab_config=regional_lab_config,
        mesh_gallery_root=mesh_gallery_root,
        output_dir=output_dir,
        site_rows=site_rows,
        mesh_rows=mesh_rows,
    )

    _write_csv(output_dir / SITE_INVENTORY_CSV, site_rows)
    _write_csv(output_dir / MESH_INVENTORY_CSV, mesh_rows)
    _write_json(output_dir / SUMMARY_JSON, summary)
    _write_markdown(output_dir / SUMMARY_MD, summary, site_rows, mesh_rows)

    print(f"[written] {output_dir / SITE_INVENTORY_CSV}")
    print(f"[written] {output_dir / MESH_INVENTORY_CSV}")
    print(f"[written] {output_dir / SUMMARY_JSON}")
    print(f"[written] {output_dir / SUMMARY_MD}")
    return 0


def _regional_lab_site_rows(config_path: Path) -> list[dict[str, Any]]:
    cfg = RegionalLabConfig.from_file(config_path)
    selected_sites = filter_sites(load_site_catalog(cfg.catalog), selection=cfg.selection)
    rows: list[dict[str, Any]] = []
    for site in selected_sites:
        raw = site.raw
        rows.append(
            {
                "inventory_source": "regional_lab_catalog",
                "site_id": site.site_id,
                "site_label": site.site_label or "",
                "region_id": site.region_id or "",
                "cluster_id": site.cluster_id or "",
                "cluster_family": site.cluster_family or "",
                "cluster_scale": site.cluster_scale or "",
                "site_group": raw.get("site_group", ""),
                "source_selection_id": site.source_selection_id or "",
                "site_status": site.site_status or "",
                "maturity": site.maturity or "",
                "x": "" if site.x is None else site.x,
                "y": "" if site.y is None else site.y,
                "target_area_km2": "" if site.area_km2 is None else site.area_km2,
                "geology_strategy": raw.get("geology_strategy", ""),
                "k_table_id": raw.get("k_table_id", ""),
                "tags": ";".join(site.tags),
                "enabled": bool(site.enabled),
                "n1_compare_config": str(site.resolved_paths.get("n1_compare_config", "")),
                "n1_compare_config_exists": _path_exists(
                    site.resolved_paths.get("n1_compare_config")
                ),
                "n2_compare_config": str(site.resolved_paths.get("n2_compare_config", "")),
                "n2_compare_config_exists": _path_exists(
                    site.resolved_paths.get("n2_compare_config")
                ),
                "n3_compare_config_prefix": str(
                    site.resolved_paths.get("n3_compare_config_prefix", "")
                ),
                "n3_compare_config_count": _n3_config_count(
                    site.resolved_paths.get("n3_compare_config_prefix")
                ),
                "recommended_stationary_campaign": _recommended_campaign(site.cluster_scale),
                "stationary_target_drainage": "0.0 m2/s",
                "stationary_target_k_mode": "heterogeneous_bundle_k",
                "preflight_mesh_variant_count": 0,
                "preflight_ready_variant_count": 0,
                "preflight_heterogeneous_ready_variant_count": 0,
                "mesh_gallery_variant_count": 0,
                "mesh_gallery_ready_variant_count": 0,
                "inventory_note": "",
            }
        )
    rows.sort(key=lambda row: (str(row["cluster_scale"]), str(row["site_id"])))
    return rows


def _mesh_gallery_rows(mesh_gallery_root: Path) -> list[dict[str, Any]]:
    if not mesh_gallery_root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for bundle_dir in sorted(mesh_gallery_root.glob("*km2/*/bundle")):
        mesh_dir = bundle_dir.parent
        parsed = _parse_mesh_dir(mesh_dir.name)
        if parsed is None:
            continue
        readiness = inspect_mesh_bundle_boussinesq_readiness(bundle_dir)
        k_stats = _bundle_k_stats(bundle_dir)
        area_stats = _bundle_area_stats(bundle_dir)
        site_id = _gallery_site_id(parsed)
        rows.append(
            {
                "inventory_source": "mesh_gallery",
                "site_id": site_id,
                "mesh_variant_id": mesh_dir.name,
                "cluster_scale": parsed["scale"],
                "cluster_family": parsed["family"],
                "outlet_id": parsed["outlet_id"],
                "constraints": parsed["constraints"],
                "buffer_m": parsed["buffer_m"],
                "mesh_variant_suffix": parsed["variant_suffix"],
                "bundle_dir": str(bundle_dir.resolve()),
                "stationary_target_drainage": "0.0 m2/s",
                "stationary_target_k_mode": "heterogeneous_bundle_k",
                **readiness,
                **k_stats,
                **area_stats,
                "recommended_stationary_campaign": _recommended_campaign(parsed["scale"]),
                "inventory_note": _mesh_inventory_note(readiness, k_stats),
            }
        )
    rows.sort(
        key=lambda row: (
            str(row["cluster_scale"]),
            str(row["cluster_family"]),
            int(row["outlet_id"]),
            str(row["mesh_variant_id"]),
        )
    )
    return rows


def _regional_lab_existing_child_mesh_rows(
    site_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for site in site_rows:
        for recipe_id, config_path in _existing_bouss_candidate_configs(site):
            bundle_dir = _bouss_child_bundle_dir(config_path)
            readiness = inspect_mesh_bundle_boussinesq_readiness(bundle_dir)
            k_stats = _bundle_k_stats(bundle_dir) if bundle_dir is not None else _empty_k_stats()
            area_stats = (
                _bundle_area_stats(bundle_dir) if bundle_dir is not None else _empty_area_stats()
            )
            rows.append(
                {
                    "inventory_source": "regional_lab_existing_child",
                    "site_id": site["site_id"],
                    "mesh_variant_id": recipe_id,
                    "cluster_scale": site["cluster_scale"],
                    "cluster_family": site["cluster_family"],
                    "outlet_id": _outlet_id_from_site_id(str(site["site_id"])),
                    "constraints": "generated_comparison_child",
                    "buffer_m": "",
                    "mesh_variant_suffix": recipe_id,
                    "bundle_dir": "" if bundle_dir is None else str(bundle_dir.resolve()),
                    "bouss_candidate_config": str(config_path.resolve()),
                    "stationary_target_drainage": "0.0 m2/s",
                    "stationary_target_k_mode": "heterogeneous_bundle_k",
                    **readiness,
                    **k_stats,
                    **area_stats,
                    "recommended_stationary_campaign": site["recommended_stationary_campaign"],
                    "inventory_note": _mesh_inventory_note(readiness, k_stats),
                }
            )
    return rows


def _existing_bouss_candidate_configs(site: Mapping[str, Any]) -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    n1_config = _existing_child_config_from_parent(site.get("n1_compare_config"))
    if n1_config is not None:
        out.append(("n1_10km2_compare_existing_child", n1_config))
    n2_config = _existing_child_config_from_parent(site.get("n2_compare_config"))
    if n2_config is not None:
        out.append(("n2_100km2_compare_existing_child", n2_config))
    prefix = str(site.get("n3_compare_config_prefix", "")).strip()
    if prefix:
        for suffix in ("coarse", "reference", "refined"):
            config = _existing_child_config_from_parent(f"{prefix}_mesh_{suffix}.toml")
            if config is not None:
                out.append((f"n3_mesh_{suffix}_existing_child", config))
    return out


def _existing_child_config_from_parent(raw_parent_config: object) -> Path | None:
    text = str(raw_parent_config or "").strip()
    if not text:
        return None
    parent_config = _resolve_path(text)
    if not parent_config.is_file():
        return None
    with parent_config.open("rb") as stream:
        payload = tomllib.load(stream)
    comparison = payload.get("comparison")
    output_root_text = comparison.get("output_root") if isinstance(comparison, dict) else None
    if not output_root_text:
        return None
    child_config = _resolve_path(output_root_text) / "_generated_configs" / "bouss_candidate.toml"
    return child_config if child_config.is_file() else None


def _bouss_child_bundle_dir(config_path: Path) -> Path | None:
    with config_path.open("rb") as stream:
        payload = tomllib.load(stream)
    workspace_root_text = payload.get("workspace", {}).get("project_root")
    if workspace_root_text:
        workspace_bundle = _resolve_path(workspace_root_text) / "mesh" / "mesh_catchment_bundle"
        if workspace_bundle.is_dir():
            return workspace_bundle
    mesh_input_bundle = payload.get("mesh_input", {}).get("bundle_dir")
    if mesh_input_bundle:
        bundle_path = _resolve_path(mesh_input_bundle)
        if bundle_path.is_dir():
            return bundle_path
    return None


def _merge_mesh_gallery_counts(
    site_rows: list[dict[str, Any]],
    mesh_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    ready_counts: Counter[str] = Counter()
    hetero_ready_counts: Counter[str] = Counter()
    gallery_counts: Counter[str] = Counter()
    gallery_ready_counts: Counter[str] = Counter()
    for row in mesh_rows:
        site_id = str(row["site_id"])
        is_ready = str(row.get("bundle_boussinesq_steady_ready", "")).lower() == "true"
        is_hetero = row.get("k_is_heterogeneous") is True
        counts[site_id] += 1
        if is_ready:
            ready_counts[site_id] += 1
        if is_ready and is_hetero:
            hetero_ready_counts[site_id] += 1
        if row.get("inventory_source") == "mesh_gallery":
            gallery_counts[site_id] += 1
            if is_ready:
                gallery_ready_counts[site_id] += 1
    merged: list[dict[str, Any]] = []
    seen_ids = {str(row["site_id"]) for row in site_rows}
    for row in site_rows:
        updated = dict(row)
        site_id = str(updated["site_id"])
        updated["preflight_mesh_variant_count"] = int(counts.get(site_id, 0))
        updated["preflight_ready_variant_count"] = int(ready_counts.get(site_id, 0))
        updated["preflight_heterogeneous_ready_variant_count"] = int(
            hetero_ready_counts.get(site_id, 0)
        )
        updated["mesh_gallery_variant_count"] = int(gallery_counts.get(site_id, 0))
        updated["mesh_gallery_ready_variant_count"] = int(gallery_ready_counts.get(site_id, 0))
        if counts.get(site_id, 0) <= 0:
            updated["inventory_note"] = "regional_lab site; no preflight bundle found"
        merged.append(updated)

    for site_id in sorted(set(counts) - seen_ids):
        matching = [row for row in mesh_rows if row["site_id"] == site_id]
        first = matching[0]
        merged.append(
            {
                "inventory_source": "mesh_gallery_only",
                "site_id": site_id,
                "site_label": site_id.replace("_", " "),
                "region_id": "armorican_massif",
                "cluster_id": f"gallery_{first['cluster_scale']}_{first['cluster_family']}",
                "cluster_family": first["cluster_family"],
                "cluster_scale": first["cluster_scale"],
                "site_group": "mesh_gallery",
                "source_selection_id": "mesh_gallery",
                "site_status": "inventory",
                "maturity": "screening",
                "x": "",
                "y": "",
                "target_area_km2": first["cluster_scale"].replace("km2", ""),
                "geology_strategy": "geology_rivers_k",
                "k_table_id": "bundle_hydraulic_conductivity_m_s",
                "tags": "natural;regional_lab_candidate;boussinesq;geology_heterogeneous;mesh_gallery",
                "enabled": True,
                "n1_compare_config": "",
                "n1_compare_config_exists": False,
                "n2_compare_config": "",
                "n2_compare_config_exists": False,
                "n3_compare_config_prefix": "",
                "n3_compare_config_count": 0,
                "recommended_stationary_campaign": first["recommended_stationary_campaign"],
                "stationary_target_drainage": "0.0 m2/s",
                "stationary_target_k_mode": "heterogeneous_bundle_k",
                "preflight_mesh_variant_count": int(counts[site_id]),
                "preflight_ready_variant_count": int(ready_counts[site_id]),
                "preflight_heterogeneous_ready_variant_count": int(hetero_ready_counts[site_id]),
                "mesh_gallery_variant_count": int(counts[site_id]),
                "mesh_gallery_ready_variant_count": int(ready_counts[site_id]),
                "inventory_note": "mesh-gallery bundle exists but regional_lab row is missing",
            }
        )
    merged.sort(key=lambda row: (str(row["cluster_scale"]), str(row["site_id"])))
    return merged


def _build_summary(
    *,
    regional_lab_config: Path,
    mesh_gallery_root: Path,
    output_dir: Path,
    site_rows: list[dict[str, Any]],
    mesh_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    site_counts_by_scale = Counter(str(row["cluster_scale"]) for row in site_rows)
    regional_lab_site_counts_by_scale = Counter(
        str(row["cluster_scale"])
        for row in site_rows
        if row["inventory_source"] == "regional_lab_catalog"
    )
    ready_mesh_sites_by_scale: dict[str, set[str]] = defaultdict(set)
    ready_mesh_variants_by_scale: Counter[str] = Counter()
    hetero_ready_mesh_sites_by_scale: dict[str, set[str]] = defaultdict(set)
    hetero_ready_mesh_variants_by_scale: Counter[str] = Counter()
    preflight_mesh_sites_by_scale: dict[str, set[str]] = defaultdict(set)
    gallery_mesh_sites_by_scale: dict[str, set[str]] = defaultdict(set)
    existing_child_sites_by_scale: dict[str, set[str]] = defaultdict(set)
    for row in mesh_rows:
        scale = str(row["cluster_scale"])
        source = str(row.get("inventory_source", ""))
        preflight_mesh_sites_by_scale[scale].add(str(row["site_id"]))
        if source == "mesh_gallery":
            gallery_mesh_sites_by_scale[scale].add(str(row["site_id"]))
        if source == "regional_lab_existing_child":
            existing_child_sites_by_scale[scale].add(str(row["site_id"]))
        is_ready = str(row.get("bundle_boussinesq_steady_ready", "")).lower() == "true"
        is_hetero = row.get("k_is_heterogeneous") is True
        if is_ready:
            ready_mesh_sites_by_scale[scale].add(str(row["site_id"]))
            ready_mesh_variants_by_scale[scale] += 1
        if is_ready and is_hetero:
            hetero_ready_mesh_sites_by_scale[scale].add(str(row["site_id"]))
            hetero_ready_mesh_variants_by_scale[scale] += 1

    scale_rows: list[dict[str, Any]] = []
    for scale in sorted(set(site_counts_by_scale) | set(SCALE_TARGET_COUNTS)):
        target = SCALE_TARGET_COUNTS.get(scale, 10)
        catalog_count = int(site_counts_by_scale.get(scale, 0))
        ready_mesh_site_count = len(ready_mesh_sites_by_scale.get(scale, set()))
        hetero_ready_mesh_site_count = len(hetero_ready_mesh_sites_by_scale.get(scale, set()))
        scale_rows.append(
            {
                "scale": scale,
                "target_site_count": target,
                "inventory_site_count": catalog_count,
                "regional_lab_site_count": int(regional_lab_site_counts_by_scale.get(scale, 0)),
                "preflight_mesh_site_count": len(preflight_mesh_sites_by_scale.get(scale, set())),
                "mesh_gallery_site_count": len(gallery_mesh_sites_by_scale.get(scale, set())),
                "existing_child_site_count": len(existing_child_sites_by_scale.get(scale, set())),
                "ready_mesh_site_count": ready_mesh_site_count,
                "ready_mesh_variant_count": int(ready_mesh_variants_by_scale.get(scale, 0)),
                "heterogeneous_ready_mesh_site_count": hetero_ready_mesh_site_count,
                "heterogeneous_ready_mesh_variant_count": int(
                    hetero_ready_mesh_variants_by_scale.get(scale, 0)
                ),
                "site_gap_to_target": max(0, target - catalog_count),
                "ready_mesh_gap_to_target": max(0, target - ready_mesh_site_count),
                "heterogeneous_ready_mesh_gap_to_target": max(
                    0, target - hetero_ready_mesh_site_count
                ),
            }
        )

    missing_regional_lab_rows = [
        row["site_id"] for row in site_rows if row["inventory_source"] == "mesh_gallery_only"
    ]
    return {
        "schema_version": "bouss_stationary_site_inventory_v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "regional_lab_config": str(regional_lab_config.resolve()),
        "mesh_gallery_root": str(mesh_gallery_root.resolve()),
        "output_dir": str(output_dir.resolve()),
        "site_inventory_csv": str((output_dir / SITE_INVENTORY_CSV).resolve()),
        "mesh_inventory_csv": str((output_dir / MESH_INVENTORY_CSV).resolve()),
        "site_count": len(site_rows),
        "mesh_variant_count": len(mesh_rows),
        "scale_summary": scale_rows,
        "missing_regional_lab_rows_for_gallery_sites": missing_regional_lab_rows,
        "recommended_next_step": (
            "Promote selected mesh_gallery_only rows into the regional_lab catalog "
            "or regenerate regional_lab_sites.csv from an upstream site-selection table "
            "before launching the wider strict drain_00 campaign."
        ),
    }


def _parse_mesh_dir(name: str) -> dict[str, str] | None:
    match = MESH_DIR_RE.match(name)
    if match is None:
        return None
    family = match.group("family") or "headwater"
    constraints = match.group("constraints")
    variant_suffix = match.group("variant_suffix").lstrip("_")
    return {
        "family": "strahler3" if family == "s3" else family,
        "scale": match.group("scale"),
        "outlet_id": match.group("outlet_id"),
        "constraints": constraints,
        "buffer_m": match.group("buffer_m"),
        "variant_suffix": variant_suffix,
    }


def _gallery_site_id(parsed: Mapping[str, str]) -> str:
    scale = parsed["scale"]
    outlet_id = parsed["outlet_id"]
    family = parsed["family"]
    if scale == "10km2":
        return f"s3_10km2_outlet_{outlet_id}" if family == "strahler3" else f"site_{outlet_id}"
    if scale == "100km2":
        return (
            f"s3_100km2_outlet_{outlet_id}"
            if family == "strahler3"
            else f"headwater_100km2_outlet_{outlet_id}"
        )
    return f"{scale}_outlet_{outlet_id}"


def _bundle_k_stats(bundle_dir: Path) -> dict[str, Any]:
    values = _float_column(bundle_dir / "cells.csv", "hydraulic_conductivity_m_s")
    if not values:
        return _empty_k_stats()
    unique_values = sorted(set(values))
    return {
        "k_min_m_s": min(values),
        "k_median_m_s": _median(values),
        "k_max_m_s": max(values),
        "k_unique_count": len(unique_values),
        "k_is_heterogeneous": len(unique_values) > 1,
    }


def _empty_k_stats() -> dict[str, Any]:
    return {
        "k_min_m_s": "",
        "k_median_m_s": "",
        "k_max_m_s": "",
        "k_unique_count": "",
        "k_is_heterogeneous": "",
    }


def _bundle_area_stats(bundle_dir: Path) -> dict[str, Any]:
    values = _float_column(bundle_dir / "cells.csv", "area_m2")
    if not values:
        return _empty_area_stats()
    area_min = min(values)
    return {
        "cell_area_min_m2": area_min,
        "cell_area_median_m2": _median(values),
        "cell_area_max_m2": max(values),
        "cell_area_ratio_max_min": "" if area_min <= 0.0 else max(values) / area_min,
    }


def _empty_area_stats() -> dict[str, Any]:
    return {
        "cell_area_min_m2": "",
        "cell_area_median_m2": "",
        "cell_area_max_m2": "",
        "cell_area_ratio_max_min": "",
    }


def _outlet_id_from_site_id(site_id: str) -> str:
    match = re.search(r"outlet_(\d+)$", site_id)
    if match is not None:
        return match.group(1)
    match = re.search(r"site_(\d+)$", site_id)
    return "" if match is None else match.group(1)


def _float_column(path: Path, column: str) -> list[float]:
    if not path.is_file():
        return []
    values: list[float] = []
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            raw = row.get(column)
            if raw is None or str(raw).strip() == "":
                continue
            try:
                value = float(raw)
            except ValueError:
                continue
            if value == value:
                values.append(value)
    return values


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])


def _mesh_inventory_note(readiness: Mapping[str, Any], k_stats: Mapping[str, Any]) -> str:
    if str(readiness.get("bundle_boussinesq_steady_ready", "")).lower() != "true":
        return "bundle not steady-ready for Boussinesq"
    if k_stats.get("k_is_heterogeneous") is not True:
        return "steady-ready but K is not heterogeneous"
    return "steady-ready heterogeneous-K bundle"


def _recommended_campaign(scale: object) -> str:
    text = str(scale or "").strip()
    if text == "10km2":
        return "stationary_picard_n1_10km2_hetero_drain00"
    if text == "100km2":
        return "stationary_picard_n2_100km2_hetero_drain00"
    if text == "1000km2":
        return "stationary_picard_n4_1000km2_hetero_drain00"
    return "stationary_picard_unclassified_hetero_drain00"


def _path_exists(raw_path: str | Path | None) -> bool:
    if raw_path is None or str(raw_path).strip() == "":
        return False
    return _resolve_path(raw_path).is_file()


def _n3_config_count(raw_prefix: str | Path | None) -> int:
    if raw_prefix is None or str(raw_prefix).strip() == "":
        return 0
    prefix = str(_resolve_path(raw_prefix))
    return sum(
        1
        for suffix in ("coarse", "reference", "refined")
        if Path(f"{prefix}_mesh_{suffix}.toml").is_file()
    )


def _resolve_path(path: str | Path) -> Path:
    text = str(path)
    match = re.match(r"^/mnt/([a-zA-Z])/(.*)$", text)
    if match is not None:
        return Path(f"{match.group(1).upper()}:/{match.group(2)}").resolve()
    candidate = Path(text)
    if candidate.is_absolute():
        return candidate.resolve()
    return (REPO_ROOT / candidate).resolve()


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: _csv_cell(row.get(name, "")) for name in fieldnames})


def _csv_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _write_markdown(
    path: Path,
    summary: Mapping[str, Any],
    site_rows: list[dict[str, Any]],
    mesh_rows: list[dict[str, Any]],
) -> None:
    lines = [
        "# Boussinesq stationary site inventory",
        "",
        "Dry inventory for strict stationary Boussinesq Picard/VI campaigns.",
        "",
        "Problem definition: heterogeneous bundle K, drainage `0.0 m2/s`, no "
        "`b_min`, no added surface conductance.",
        "",
        "## Scale coverage",
        "",
        "| scale | inventory sites | regional-lab sites | preflight mesh sites | existing child sites | mesh-gallery sites | ready mesh sites | hetero-ready sites | hetero-ready variants | gap to 10 hetero-ready sites |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary["scale_summary"]:
        lines.append(
            "| {scale} | {inventory_site_count} | {regional_lab_site_count} | "
            "{preflight_mesh_site_count} | {existing_child_site_count} | "
            "{mesh_gallery_site_count} | {ready_mesh_site_count} | "
            "{heterogeneous_ready_mesh_site_count} | "
            "{heterogeneous_ready_mesh_variant_count} | "
            "{heterogeneous_ready_mesh_gap_to_target} |".format(**row)
        )

    lines.extend(
        [
            "",
            "## Regional-lab site counts",
            "",
            "| scale | family | count |",
            "|---|---|---:|",
        ]
    )
    grouped = Counter(
        (str(row["cluster_scale"]), str(row["cluster_family"]))
        for row in site_rows
        if row["inventory_source"] == "regional_lab_catalog"
    )
    for (scale, family), count in sorted(grouped.items()):
        lines.append(f"| {scale} | {family} | {count} |")

    lines.extend(
        [
            "",
            "## Preflight hetero-ready variants",
            "",
            "| scale | family | source | hetero-ready variants |",
            "|---|---|---|---:|",
        ]
    )
    ready_grouped = Counter(
        (
            str(row["cluster_scale"]),
            str(row["cluster_family"]),
            str(row["inventory_source"]),
        )
        for row in mesh_rows
        if str(row.get("bundle_boussinesq_steady_ready", "")).lower() == "true"
        and row.get("k_is_heterogeneous") is True
    )
    for (scale, family, source), count in sorted(ready_grouped.items()):
        lines.append(f"| {scale} | {family} | {source} | {count} |")

    missing = summary["missing_regional_lab_rows_for_gallery_sites"]
    lines.extend(
        [
            "",
            "## Gaps",
            "",
            "- The current regional-lab catalog has 8 N1 10 km2 sites, 9 N2 100 km2 sites, "
            "and no 1000 km2 regional-lab rows.",
            "- The mesh gallery adds candidate bundles not yet promoted into "
            "`natural_regional_lab_sites.csv`.",
            "- Mesh-gallery-only site ids: " + (", ".join(missing) if missing else "none"),
            "",
            "## Artifacts",
            "",
            f"- Site inventory CSV: `{summary['site_inventory_csv']}`",
            f"- Mesh inventory CSV: `{summary['mesh_inventory_csv']}`",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _parse_args(argv: Iterable[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--regional-lab-config",
        default=str(DEFAULT_REGIONAL_LAB_CONFIG),
        help="Regional-lab TOML to use as the current site catalog contract.",
    )
    parser.add_argument(
        "--mesh-gallery-root",
        default=str(DEFAULT_MESH_GALLERY_ROOT),
        help="Mesh gallery root used to find additional scale/site bundles.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory where CSV/JSON/Markdown inventories are written.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


if __name__ == "__main__":
    raise SystemExit(main())
