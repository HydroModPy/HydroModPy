"""Publish generated simulation-comparison artifacts as gallery inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from shutil import copy2
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLISHED_ROOT = (
    REPO_ROOT / "examples" / "projects" / "09_capability_gallery" / "simulation_comparison"
)
REQUIRED_ARTIFACTS = (
    "comparison_manifest.json",
    "comparison_metrics.json",
    "observables.csv",
)
OPTIONAL_ARTIFACTS = (
    "comparison_audit.json",
    "comparison_report.md",
    "execution_times.csv",
    "source_manifest.json",
    "comparison.toml",
    "hydrographic_network_metrics.csv",
    "hydrographic_network_metrics_skipped.json",
    "release_flux_network_distance_metrics.csv",
    "release_flux_network_distance_metrics_skipped.json",
    "release_flux_network_overlap_metrics.csv",
    "release_flux_network_overlap_metrics_skipped.json",
    "simulated_active_network_distance_metrics.csv",
    "simulated_active_network_distance_metrics_skipped.json",
    "simulated_active_network_figures_skipped.json",
    "simulated_active_network_metrics.csv",
    "simulated_active_network_metrics_skipped.json",
    "simulated_active_network_overlap_metrics.csv",
    "simulated_active_network_overlap_metrics_skipped.json",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Copy a reviewed simulation-comparison output bundle into the versioned "
            "capability-gallery input tree."
        )
    )
    parser.add_argument(
        "comparison_roots",
        nargs="*",
        type=Path,
        help="Generated comparison output directories containing comparison_manifest.json.",
    )
    parser.add_argument(
        "--testbed-output-root",
        action="append",
        type=Path,
        default=[],
        help=(
            "Discover comparison bundles under one testbed/benchmark output root. "
            "Supports either <root>/comparisons/* or <root>/comparison."
        ),
    )
    parser.add_argument(
        "--slug",
        help="Gallery slug. Defaults to the comparison_id from comparison_manifest.json.",
    )
    parser.add_argument("--title", help="Gallery case title.")
    parser.add_argument(
        "--study-area",
        default="Testbed comparison",
        help="Study-area label stored in case.json.",
    )
    parser.add_argument(
        "--focus-simulation-id",
        default=None,
        help="Simulation shown as the candidate/focus in the generated gallery figure.",
    )
    parser.add_argument(
        "--case-order",
        type=int,
        default=10,
        help="Ordering inside the Boussinesq/MF6 testbed comparison family.",
    )
    parser.add_argument(
        "--family-key",
        default="boussinesq_mf6_testbed",
        help="Gallery comparison-family key.",
    )
    parser.add_argument(
        "--family-label",
        default="Boussinesq / MODFLOW 6 Testbed",
        help="Gallery comparison-family label.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing published bundle for the same slug.",
    )
    return parser


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _title_from_slug(slug: str) -> str:
    return slug.replace("_", " ").replace("-", " ").title()


def _infer_focus_simulation_id(manifest: dict[str, Any]) -> str:
    reference = str(manifest.get("reference_simulation", "")).strip()
    for row in manifest.get("simulations", []):
        if not isinstance(row, dict):
            continue
        simulation_id = str(row.get("id", "")).strip()
        if simulation_id and simulation_id != reference:
            return simulation_id
    return "bouss_candidate"


def _case_payload(
    *,
    slug: str,
    title: str,
    study_area: str,
    focus_simulation_id: str,
    case_order: int,
    family_key: str,
    family_label: str,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    comparison_id = str(manifest.get("comparison_id", slug))
    reference = str(manifest.get("reference_simulation", "mf6_ref"))
    return {
        "slug": slug,
        "title": title,
        "deck": (
            "Published MODFLOW 6 and Boussinesq comparison artifacts, reused by "
            "the documentation without rerunning the solvers."
        ),
        "summary": (
            f"This page republishes reviewed artifacts from `{comparison_id}`. "
            "The gallery generation reads committed comparison outputs only; "
            "heavy solver runs are refreshed separately before publication."
        ),
        "study_area": study_area,
        "focus_simulation_id": focus_simulation_id,
        "comparison_family_key": family_key,
        "comparison_family_label": family_label,
        "comparison_family_deck": (
            "These pages publish reviewed Boussinesq/MODFLOW 6 comparison outputs "
            "from the testbed workflow without running the solvers during doc generation."
        ),
        "comparison_family_order": 40,
        "comparison_case_order": case_order,
        "publish_full_artifacts": False,
        "what_it_shows": [
            f"How `{focus_simulation_id}` compares against the `{reference}` reference.",
            "How map metrics and runtime diagnostics can be published from stable artifacts.",
            "How documentation pages can be regenerated without rerunning heavy simulations.",
        ],
        "case_setup": [
            f"Reference simulation: `{reference}`.",
            f"Focus simulation: `{focus_simulation_id}`.",
            "Input artifacts are copied from a reviewed comparison output directory.",
        ],
        "key_parameters": [
            "The published comparison root provides `comparison_manifest.json`, "
            "`comparison_metrics.json`, and `observables.csv`.",
            "Execution-time diagnostics should use solver flow time, not whole workflow wall time.",
        ],
        "how_to_read": [
            "Read the metrics as a reviewed solver-to-solver comparison, not as a validation benchmark.",
            "Use the source pointers and optional source manifest to decide when the bundle needs refresh.",
        ],
    }


def publish_comparison(
    comparison_root: Path,
    *,
    slug: str | None = None,
    title: str | None = None,
    study_area: str = "Testbed comparison",
    focus_simulation_id: str | None = None,
    case_order: int = 10,
    family_key: str = "boussinesq_mf6_testbed",
    family_label: str = "Boussinesq / MODFLOW 6 Testbed",
    force: bool = False,
) -> Path:
    source_root = comparison_root.resolve()
    missing = [name for name in REQUIRED_ARTIFACTS if not (source_root / name).exists()]
    if missing:
        raise FileNotFoundError(
            f"Comparison root is missing required artifact(s): {', '.join(missing)}"
        )

    manifest = _read_json(source_root / "comparison_manifest.json")
    resolved_slug = str(slug or manifest.get("comparison_id", "")).strip()
    if not resolved_slug:
        raise ValueError("A slug is required when comparison_manifest.json has no comparison_id.")

    destination = PUBLISHED_ROOT / resolved_slug
    if destination.exists() and not force:
        raise FileExistsError(
            f"Published bundle already exists: {destination}. Re-run with --force to refresh it."
        )
    destination.mkdir(parents=True, exist_ok=True)
    if force:
        for name in (*REQUIRED_ARTIFACTS, *OPTIONAL_ARTIFACTS, "case.json"):
            (destination / name).unlink(missing_ok=True)

    for name in (*REQUIRED_ARTIFACTS, *OPTIONAL_ARTIFACTS):
        source = source_root / name
        if source.exists():
            copy2(source, destination / name)

    resolved_title = str(title or _title_from_slug(resolved_slug))
    resolved_focus_simulation_id = str(
        focus_simulation_id or _infer_focus_simulation_id(manifest)
    )
    case_payload = _case_payload(
        slug=resolved_slug,
        title=resolved_title,
        study_area=study_area,
        focus_simulation_id=resolved_focus_simulation_id,
        case_order=case_order,
        family_key=family_key,
        family_label=family_label,
        manifest=manifest,
    )
    (destination / "case.json").write_text(
        json.dumps(case_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def discover_comparison_roots(
    *,
    comparison_roots: list[Path],
    testbed_output_roots: list[Path],
) -> list[Path]:
    """Return comparison roots from explicit paths and testbed output directories."""

    discovered: list[Path] = []
    for root in comparison_roots:
        discovered.append(root)

    for raw_root in testbed_output_roots:
        root = raw_root.expanduser().resolve()
        if (root / "comparison_manifest.json").is_file():
            discovered.append(root)
            continue
        single_comparison = root / "comparison"
        if (single_comparison / "comparison_manifest.json").is_file():
            discovered.append(single_comparison)
        comparisons_dir = root / "comparisons"
        if comparisons_dir.is_dir():
            discovered.extend(
                path
                for path in sorted(comparisons_dir.iterdir())
                if (path / "comparison_manifest.json").is_file()
            )

    unique: list[Path] = []
    seen: set[Path] = set()
    for root in discovered:
        resolved = root.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    comparison_roots = discover_comparison_roots(
        comparison_roots=list(args.comparison_roots),
        testbed_output_roots=list(args.testbed_output_root),
    )
    if not comparison_roots:
        raise SystemExit("No comparison roots supplied or discovered.")
    if len(comparison_roots) > 1 and (args.slug or args.title):
        raise SystemExit("--slug and --title are only valid when publishing one comparison root.")

    destinations: list[Path] = []
    for index, comparison_root in enumerate(comparison_roots):
        destinations.append(
            publish_comparison(
                comparison_root,
                slug=args.slug,
                title=args.title,
                study_area=args.study_area,
                focus_simulation_id=args.focus_simulation_id,
                case_order=args.case_order + index * 10,
                family_key=args.family_key,
                family_label=args.family_label,
                force=args.force,
            )
        )

    print(f"Published {len(destinations)} simulation-comparison gallery bundle(s):")
    for destination in destinations:
        print(f"- {destination}")
    slugs = ",".join(destination.name for destination in destinations)
    print(f"Regenerate the page(s) with: python -m tools.doc_gallery --only {slugs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
