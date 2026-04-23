"""Sync repeated mesh-gallery cases from existing ``mesh_catchment_runs`` outputs."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .import_mesh_bundle import import_mesh_bundle_case
from .mesh_case_registry import MESH_GALLERY_VARIANT_SPECS, REPO_ROOT, mesh_gallery_root

DEFAULT_RESULTS_ROOT = Path("C:/results/Hydromodpy/mesh_catchment_runs")


@dataclass(frozen=True, slots=True)
class ManagedMeshFamilySpec:
    """Describe one repeated mesh-gallery family sourced from batch results."""

    key: str
    label: str
    scale: str
    variant: str
    launcher_config_path: str
    results_subdir: str
    featured_outlet_ids: tuple[int, ...]
    deck: str
    summary: str
    what_it_shows: tuple[str, ...]


FAMILY_SPECS: tuple[ManagedMeshFamilySpec, ...] = (
    ManagedMeshFamilySpec(
        key="s3_10km2",
        label="10 km2, Strahler 3",
        scale="10km2",
        variant="geology_rivers_buffer30",
        launcher_config_path="old/launchers/mesh_catchment/scenarios/config_s3_10km2.toml",
        results_subdir="s3_10km2",
        featured_outlet_ids=(1,),
        deck=(
            "10 km2 Strahler-3 catchment mesh with rivers, geology interfaces, watershed "
            "boundary, and outside coarsening kept active on a 30% buffered support."
        ),
        summary=(
            "This family captures repeated conformal meshing runs on the 10 km2 Strahler-3 "
            "selection, keeping geology and rivers active while comparing multiple outlets "
            "under one stable gallery layout."
        ),
        what_it_shows=(
            "How several 10 km2 Strahler-3 outlets compare under the same conformal meshing policy.",
            "How geology interfaces and river traces stay coupled across repeated small-catchment runs.",
            "How the documentation can be refreshed directly from committed batch outputs.",
        ),
    ),
    ManagedMeshFamilySpec(
        key="headwater_100km2",
        label="100 km2, headwater",
        scale="100km2",
        variant="geology_rivers_buffer30",
        launcher_config_path="old/launchers/mesh_catchment/scenarios/config_headwater_100km2.toml",
        results_subdir="headwater_100km2",
        featured_outlet_ids=(27,),
        deck=(
            "100 km2 headwater catchment mesh with rivers, geology interfaces, watershed "
            "boundary, and outside coarsening kept active on a 30% buffered support."
        ),
        summary=(
            "This family captures repeated conformal meshing runs on the 100 km2 headwater "
            "selection so the gallery can compare several outlets under one stable geology-plus-rivers setup."
        ),
        what_it_shows=(
            "How several headwater outlets around 100 km2 compare under the same meshing policy.",
            "How the same gallery case can be repeated across multiple outlets without changing the documentation structure.",
            "How geology and river constraints scale from one headwater support to the next.",
        ),
    ),
    ManagedMeshFamilySpec(
        key="s3_100km2",
        label="100 km2, Strahler 3",
        scale="100km2",
        variant="geology_rivers_buffer30",
        launcher_config_path="old/launchers/mesh_catchment/scenarios/config_s3_100km2.toml",
        results_subdir="s3_100km2",
        featured_outlet_ids=(2,),
        deck=(
            "100 km2 Strahler-3 catchment mesh with rivers, geology interfaces, watershed "
            "boundary, and outside coarsening kept active on a 30% buffered support."
        ),
        summary=(
            "This family captures repeated conformal meshing runs on the 100 km2 Strahler-3 "
            "selection so the gallery can compare several outlets under one stable geology-plus-rivers setup."
        ),
        what_it_shows=(
            "How several Strahler-3 outlets around 100 km2 compare under the same meshing policy.",
            "How one filtered 100 km2 selection differs from the headwater-oriented 100 km2 family.",
            "How repeated imports from batch outputs can stay deterministic across documentation refreshes.",
        ),
    ),
    ManagedMeshFamilySpec(
        key="1000km2",
        label="1000 km2",
        scale="1000km2",
        variant="geology_rivers_buffer30",
        launcher_config_path="old/launchers/mesh_catchment/scenarios/config_1000km2.toml",
        results_subdir="1000km2",
        featured_outlet_ids=(2,),
        deck=(
            "1000 km2 catchment mesh with rivers, geology interfaces, watershed boundary, "
            "and outside coarsening kept active on a 30% buffered support."
        ),
        summary=(
            "This family captures repeated conformal meshing runs on the 1000 km2 selection "
            "so the gallery can compare several larger outlets under one stable geology-plus-rivers setup."
        ),
        what_it_shows=(
            "How several 1000 km2 outlets compare under the same conformal meshing policy.",
            "How larger supports change the visual balance between basin focus and outside coarsening.",
            "How the gallery can keep a stable repeated-sites layout even for larger domains.",
        ),
    ),
)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for repeated mesh-gallery sync."""

    parser = argparse.ArgumentParser(
        description=(
            "Import repeated mesh-gallery cases from existing mesh_catchment_runs "
            "results and optionally refresh the generated documentation pages."
        )
    )
    parser.add_argument(
        "--results-root",
        default=str(DEFAULT_RESULTS_ROOT),
        help="Root directory containing the batch run outputs under mesh_catchment_runs/.",
    )
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Repository root containing examples/projects/07_mesh_gallery/.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=5,
        help="Number of outlet repetitions to import per family.",
    )
    parser.add_argument(
        "--families",
        nargs="*",
        choices=tuple(spec.key for spec in FAMILY_SPECS),
        default=None,
        help="Optional subset of family keys to import. Defaults to all managed families.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite destination case directories when they already exist.",
    )
    parser.add_argument(
        "--no-clean-destination",
        dest="clean_destination",
        action="store_false",
        help="Do not clear existing imported case directories under examples/projects/07_mesh_gallery/ before syncing.",
    )
    parser.add_argument(
        "--update-gallery",
        action="store_true",
        help="Run `python -m tools.doc_gallery` after importing the repeated cases.",
    )
    parser.set_defaults(clean_destination=True)
    return parser


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _family_spec_by_key(key: str) -> ManagedMeshFamilySpec:
    for spec in FAMILY_SPECS:
        if spec.key == key:
            return spec
    raise KeyError(f"Unknown family key: {key}")


def _manifest_path(results_root: Path, family: ManagedMeshFamilySpec) -> Path:
    return (
        results_root
        / family.results_subdir
        / "mesh"
        / "batch"
        / "mesh_catchment_batch_manifest.csv"
    )


def _bundle_dir_from_manifest_row(row: dict[str, str]) -> Path:
    summary_path = Path(str(row["output_summary_json"]).strip()).expanduser().resolve()
    if not summary_path.exists():
        raise FileNotFoundError(f"Missing mesh summary referenced by manifest: {summary_path}")
    if not summary_path.stem.endswith("_summary"):
        raise ValueError(f"Unexpected mesh summary filename: {summary_path.name}")
    bundle_dir = summary_path.parent / f"{summary_path.stem[:-8]}_bundle"
    if not bundle_dir.exists():
        raise FileNotFoundError(f"Missing bundle directory next to summary: {bundle_dir}")
    return bundle_dir


def _load_manifest_rows(manifest_path: Path) -> list[dict[str, str]]:
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing batch manifest: {manifest_path}")
    with manifest_path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = [dict(row) for row in reader]
    filtered_rows = [
        row
        for row in rows
        if str(row.get("status", "")).strip().lower() == "ok"
        and str(row.get("outlet_id", "")).strip() != ""
        and str(row.get("output_summary_json", "")).strip() != ""
    ]
    filtered_rows.sort(key=lambda row: int(str(row["outlet_id"]).strip()))
    return filtered_rows


def _select_rows(
    rows: list[dict[str, str]],
    *,
    featured_outlet_ids: tuple[int, ...],
    count: int,
) -> list[dict[str, str]]:
    rows_by_outlet = {int(str(row["outlet_id"]).strip()): row for row in rows}
    selected_outlet_ids: list[int] = []
    for outlet_id in featured_outlet_ids:
        if outlet_id in rows_by_outlet and outlet_id not in selected_outlet_ids:
            selected_outlet_ids.append(outlet_id)
    for outlet_id in sorted(rows_by_outlet):
        if outlet_id in selected_outlet_ids:
            continue
        selected_outlet_ids.append(outlet_id)
        if len(selected_outlet_ids) >= count:
            break
    if len(selected_outlet_ids) < count:
        raise ValueError(
            f"Requested {count} outlets but only {len(selected_outlet_ids)} valid rows were found."
        )
    return [rows_by_outlet[outlet_id] for outlet_id in selected_outlet_ids[:count]]


def _managed_case_slug(family: ManagedMeshFamilySpec, outlet_id: str) -> str:
    return f"mesh_{family.key}_outlet_{str(outlet_id).strip()}_{family.variant}"


def _clean_destination_roots(
    *, repo_root: Path, selected_families: tuple[ManagedMeshFamilySpec, ...]
) -> None:
    gallery_root = mesh_gallery_root(repo_root=repo_root)
    managed_case_dirs: set[Path] = set()
    for family in selected_families:
        scale_dir = gallery_root / family.scale
        if not scale_dir.exists():
            continue
        prefix = f"mesh_{family.key}_outlet_"
        suffix = f"_{family.variant}"
        for child in sorted(scale_dir.iterdir()):
            if not child.is_dir():
                continue
            name = child.name
            if name.startswith(prefix) and name.endswith(suffix):
                managed_case_dirs.add(child)

    for case_dir in sorted(managed_case_dirs):
        shutil.rmtree(case_dir)


def sync_mesh_catchment_runs(
    *,
    results_root: Path,
    repo_root: Path,
    family_keys: tuple[str, ...] | None = None,
    count: int = 5,
    clean_destination: bool = True,
    force: bool = False,
    update_gallery: bool = False,
) -> list[Path]:
    """Import repeated mesh-gallery cases from existing batch outputs."""

    if count <= 0:
        raise ValueError("count must be strictly positive.")

    results_root = results_root.expanduser().resolve()
    repo_root = repo_root.expanduser().resolve()
    selected_families = (
        tuple(_family_spec_by_key(key) for key in family_keys) if family_keys else FAMILY_SPECS
    )

    if clean_destination:
        _clean_destination_roots(repo_root=repo_root, selected_families=selected_families)

    imported_case_dirs: list[Path] = []
    for family_order, family in enumerate(selected_families, start=1):
        manifest_path = _manifest_path(results_root, family)
        selected_rows = _select_rows(
            _load_manifest_rows(manifest_path),
            featured_outlet_ids=family.featured_outlet_ids,
            count=count,
        )
        variant_label = str(MESH_GALLERY_VARIANT_SPECS[family.variant]["label"])

        for tab_order, row in enumerate(selected_rows, start=1):
            outlet_id = str(row["outlet_id"]).strip()
            case_dir = import_mesh_bundle_case(
                source_bundle=_bundle_dir_from_manifest_row(row),
                scale=family.scale,
                variant=family.variant,
                outlet_id=outlet_id,
                repo_root=repo_root,
                case_slug=_managed_case_slug(family, outlet_id),
                title=f"{family.label} Mesh, Outlet {outlet_id}, {variant_label}",
                deck=family.deck,
                summary=family.summary,
                what_it_shows=family.what_it_shows,
                launcher_config_path=family.launcher_config_path,
                force=force or clean_destination,
            )

            case_json_path = case_dir / "case.json"
            payload = json.loads(case_json_path.read_text(encoding="utf-8"))
            payload["case_setup"] = [
                f"Case family: {family.label}.",
                f"Gallery repetition: {tab_order}/{count}.",
                *list(payload.get("case_setup", ())),
            ]
            payload["case_family_key"] = family.key
            payload["case_family_label"] = family.label
            payload["case_family_order"] = family_order
            payload["site_tabs_group_key"] = f"family::{family.key}"
            payload["site_tabs_group_title"] = family.label
            payload["site_tabs_label"] = f"Outlet {outlet_id}"
            payload["site_tabs_order"] = tab_order
            payload["source_results_family_dir"] = str(
                (results_root / family.results_subdir).resolve()
            )
            payload["source_results_manifest_path"] = str(manifest_path)
            _write_json(case_json_path, payload)
            imported_case_dirs.append(case_dir)

    if update_gallery:
        subprocess.run(
            [sys.executable, "-m", "tools.doc_gallery"],
            cwd=repo_root,
            check=True,
        )

    return imported_case_dirs


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""

    args = build_parser().parse_args(argv)
    imported_case_dirs = sync_mesh_catchment_runs(
        results_root=Path(args.results_root),
        repo_root=Path(args.repo_root),
        family_keys=None if args.families is None else tuple(args.families),
        count=int(args.count),
        clean_destination=bool(args.clean_destination),
        force=bool(args.force),
        update_gallery=bool(args.update_gallery),
    )
    print("Imported repeated mesh-gallery cases:")
    for case_dir in imported_case_dirs:
        print(f"  - {case_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
