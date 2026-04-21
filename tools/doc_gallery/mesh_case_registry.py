"""Shared conventions for versioned mesh-gallery cases."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
MESH_GALLERY_CASE_SCHEMA_VERSION = "mesh_gallery_case_v1"
MESH_GALLERY_REQUIRED_BUNDLE_FILES = (
    "mesh_2d.msh",
    "nodes.csv",
    "cells.csv",
    "edges.csv",
    "cell_geology_fractions.csv",
    "metadata.json",
    "mesh_summary.json",
)

MESH_GALLERY_SCALE_SPECS: dict[str, dict[str, str]] = {
    "10km2": {
        "label": "10 km2",
        "default_launcher_config": "launchers/mesh_catchment/scenarios/config_s3_10km2.toml",
    },
    "100km2": {
        "label": "100 km2",
        "default_launcher_config": "launchers/mesh_catchment/scenarios/config_headwater_100km2.toml",
    },
    "1000km2": {
        "label": "1000 km2",
        "default_launcher_config": "launchers/mesh_catchment/scenarios/config_1000km2.toml",
    },
}
MESH_GALLERY_SCALE_ORDER = tuple(MESH_GALLERY_SCALE_SPECS)

MESH_GALLERY_VARIANT_SPECS: dict[str, dict[str, Any]] = {
    "geology_rivers_buffer30": {
        "label": "Geology + rivers, 30% buffer",
        "expected_constraints_mode": "geology_rivers",
        "color_field": "geology_key",
        "deck_template": (
            "{scale_label} catchment mesh with rivers, geology interfaces, watershed boundary, "
            "and outside coarsening kept active on a 30% buffered support."
        ),
        "summary_template": (
            "This case is reserved for a conformal catchment mesh where HydroModPy keeps both "
            "river traces and geology interfaces as active constraints while preserving the current "
            "watershed-boundary handling and de-refinement outside the basin."
        ),
        "what_it_shows": (
            "How river traces, geology interfaces, and the watershed boundary interact on one buffered support domain.",
            "How outside coarsening keeps the basin readable without over-resolving the external envelope.",
            "What changes visually when geology remains fully coupled to the conformal mesh.",
        ),
    },
    "rivers_only_buffer30": {
        "label": "Rivers only, 30% buffer",
        "expected_constraints_mode": "rivers_only",
        "color_field": "area_m2",
        "deck_template": (
            "{scale_label} catchment mesh where only rivers constrain the internal mesh, while the "
            "watershed boundary and outside coarsening remain active on a 30% buffered support."
        ),
        "summary_template": (
            "This case is reserved for a catchment mesh where geology is removed from the internal "
            "constraint set, but the watershed boundary, support extent, and outside de-refinement "
            "stay aligned with the standard gallery workflow."
        ),
        "what_it_shows": (
            "How the river network alone structures the internal conformal mesh when geology is not enforced.",
            "How the same buffered watershed support can be compared fairly against the geology-plus-rivers variant.",
            "How outside coarsening still protects the basin focus while simplifying the external region.",
        ),
    },
}


@dataclass(frozen=True, slots=True)
class ImportedMeshCasePaths:
    """Filesystem layout produced for one imported mesh-gallery case."""

    case_dir: Path
    bundle_dir: Path
    figures_dir: Path
    case_json_path: Path
    viewer_config_path: Path
    readme_path: Path


def mesh_gallery_root(*, repo_root: Path = REPO_ROOT) -> Path:
    """Return the canonical root directory for versioned mesh-gallery cases."""

    return repo_root / "examples" / "07_mesh_gallery"


def _validate_scale(scale: str) -> str:
    token = str(scale).strip()
    if token not in MESH_GALLERY_SCALE_SPECS:
        allowed = ", ".join(MESH_GALLERY_SCALE_SPECS)
        raise ValueError(f"scale must be one of: {allowed}.")
    return token


def _validate_variant(variant: str) -> str:
    token = str(variant).strip()
    if token not in MESH_GALLERY_VARIANT_SPECS:
        allowed = ", ".join(MESH_GALLERY_VARIANT_SPECS)
        raise ValueError(f"variant must be one of: {allowed}.")
    return token


def scale_label(scale: str) -> str:
    """Return the human-readable scale label used in gallery copy."""

    return str(MESH_GALLERY_SCALE_SPECS[_validate_scale(scale)]["label"])


def default_launcher_config_for_scale(scale: str) -> str:
    """Return the default launcher config associated with one gallery scale."""

    return str(MESH_GALLERY_SCALE_SPECS[_validate_scale(scale)]["default_launcher_config"])


def default_case_slug(*, scale: str, outlet_id: str, variant: str) -> str:
    """Build the canonical slug used when importing one mesh-gallery case."""

    return f"mesh_{_validate_scale(scale)}_outlet_{str(outlet_id).strip()}_{_validate_variant(variant)}"


def canonical_case_dir(*, scale: str, slug: str, repo_root: Path = REPO_ROOT) -> Path:
    """Return the canonical case directory for one imported mesh-gallery case."""

    token = str(slug).strip()
    if token == "":
        raise ValueError("slug cannot be empty.")
    return mesh_gallery_root(repo_root=repo_root) / _validate_scale(scale) / token


def case_paths(*, scale: str, slug: str, repo_root: Path = REPO_ROOT) -> ImportedMeshCasePaths:
    """Return the standard file layout for one canonical mesh-gallery case."""

    case_dir = canonical_case_dir(scale=scale, slug=slug, repo_root=repo_root)
    return ImportedMeshCasePaths(
        case_dir=case_dir,
        bundle_dir=case_dir / "bundle",
        figures_dir=case_dir / "figures",
        case_json_path=case_dir / "case.json",
        viewer_config_path=case_dir / "viewer_config.toml",
        readme_path=case_dir / "README.md",
    )


def repo_relative(path: Path, *, repo_root: Path = REPO_ROOT) -> str:
    """Return one stable repo-relative POSIX path."""

    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def validate_bundle_dir(bundle_dir: Path) -> None:
    """Ensure the imported bundle looks like one standard mesh bundle."""

    missing = [
        filename for filename in MESH_GALLERY_REQUIRED_BUNDLE_FILES if not (bundle_dir / filename).exists()
    ]
    if missing:
        raise FileNotFoundError(
            f"Bundle directory {bundle_dir} is missing required files: {', '.join(missing)}"
        )


def load_bundle_summary(bundle_dir: Path) -> dict[str, Any]:
    """Load the canonical ``mesh_summary.json`` sidecar from one bundle."""

    validate_bundle_dir(bundle_dir)
    summary_path = bundle_dir / "mesh_summary.json"
    return json.loads(summary_path.read_text(encoding="utf-8"))


def iter_mesh_case_json_paths(*, repo_root: Path = REPO_ROOT) -> tuple[Path, ...]:
    """Return all discovered canonical mesh-gallery case metadata files."""

    root = mesh_gallery_root(repo_root=repo_root)
    if not root.exists():
        return ()
    discovered: list[Path] = []
    for scale in MESH_GALLERY_SCALE_ORDER:
        scale_root = root / scale
        if not scale_root.exists():
            continue
        discovered.extend(sorted(scale_root.rglob("case.json")))
    return tuple(discovered)


def build_default_case_metadata(
    *,
    scale: str,
    variant: str,
    outlet_id: str,
    slug: str,
    case_rel_dir: str,
    launcher_config_path: str,
    source_bundle_summary: dict[str, Any],
    title: str | None = None,
    deck: str | None = None,
    summary: str | None = None,
    what_it_shows: tuple[str, ...] | None = None,
    reproduction_command: str | None = None,
    preferred_doc_figure_path: str | None = None,
    preferred_doc_regional_figure_path: str | None = None,
) -> dict[str, Any]:
    """Build the canonical ``case.json`` payload for one mesh-gallery case."""

    scale_token = _validate_scale(scale)
    variant_token = _validate_variant(variant)
    scale_title = scale_label(scale_token)
    variant_spec = MESH_GALLERY_VARIANT_SPECS[variant_token]
    outlet_label = str(outlet_id).strip()
    constraints_mode = source_bundle_summary.get("constraints_mode")

    title_value = (
        str(title).strip()
        if title is not None and str(title).strip()
        else f"{scale_title} Mesh, Outlet {outlet_label}, {variant_spec['label']}"
    )
    deck_value = (
        str(deck).strip()
        if deck is not None and str(deck).strip()
        else str(variant_spec["deck_template"]).format(scale_label=scale_title)
    )
    summary_value = (
        str(summary).strip()
        if summary is not None and str(summary).strip()
        else str(variant_spec["summary_template"])
    )
    what_it_shows_value = tuple(what_it_shows or tuple(variant_spec["what_it_shows"]))
    if not what_it_shows_value:
        raise ValueError("what_it_shows cannot be empty.")

    reproduction_value = (
        str(reproduction_command).strip()
        if reproduction_command is not None and str(reproduction_command).strip()
        else f"python -m launchers mesh-catchment run {launcher_config_path}"
    )

    case_setup = [
        f"Scale target: {scale_title}.",
        f"Outlet identifier: {outlet_label}.",
        f"Gallery variant: {variant_spec['label']}.",
    ]
    if constraints_mode:
        case_setup.append(f"Bundle-reported constraints mode: {constraints_mode}.")

    rel_prefix = f"{case_rel_dir}/bundle"
    source_paths = [
        launcher_config_path,
        f"{case_rel_dir}/case.json",
        f"{case_rel_dir}/viewer_config.toml",
        f"{case_rel_dir}/README.md",
        f"{rel_prefix}/mesh_2d.msh",
        f"{rel_prefix}/nodes.csv",
        f"{rel_prefix}/cells.csv",
        f"{rel_prefix}/edges.csv",
        f"{rel_prefix}/cell_geology_fractions.csv",
        f"{rel_prefix}/metadata.json",
        f"{rel_prefix}/mesh_summary.json",
    ]
    if source_bundle_summary.get("bundle_readme_present", True):
        source_paths.append(f"{rel_prefix}/README.md")
    if preferred_doc_figure_path:
        source_paths.append(preferred_doc_figure_path)
    if preferred_doc_regional_figure_path:
        source_paths.append(preferred_doc_regional_figure_path)

    image_caption = (
        "Original mesh figure copied from the imported meshing run and reused directly in the documentation."
        if preferred_doc_figure_path
        else f"Mesh overview rendered from the versioned bundle stored under `{case_rel_dir}/bundle`."
    )

    payload: dict[str, Any] = {
        "case_schema_version": MESH_GALLERY_CASE_SCHEMA_VERSION,
        "slug": slug,
        "title": title_value,
        "deck": deck_value,
        "summary": summary_value,
        "what_it_shows": list(what_it_shows_value),
        "case_setup": case_setup,
        "scale": scale_token,
        "scale_label": scale_title,
        "variant": variant_token,
        "variant_label": str(variant_spec["label"]),
        "outlet_id": outlet_label,
        "constraints_mode": constraints_mode,
        "reproduction_command": reproduction_value,
        "config_path": f"{case_rel_dir}/viewer_config.toml",
        "image_caption": image_caption,
        "image_alt_text": f"{title_value} overview",
        "source_paths": source_paths,
    }
    if preferred_doc_figure_path:
        payload["preferred_doc_figure_path"] = preferred_doc_figure_path
    if preferred_doc_regional_figure_path:
        payload["preferred_doc_regional_figure_path"] = preferred_doc_regional_figure_path
        payload["regional_image_caption"] = (
            "Regional framing figure copied from the imported meshing run."
        )
        payload["regional_image_alt_text"] = f"{title_value} regional context"
    return payload


def load_mesh_case_metadata(case_json_path: Path) -> dict[str, Any]:
    """Load and lightly validate one canonical mesh-gallery ``case.json`` file."""

    payload = json.loads(case_json_path.read_text(encoding="utf-8"))
    required_keys = (
        "case_schema_version",
        "slug",
        "title",
        "deck",
        "summary",
        "what_it_shows",
        "scale",
        "variant",
        "outlet_id",
        "reproduction_command",
        "config_path",
        "source_paths",
    )
    missing = [key for key in required_keys if key not in payload]
    if missing:
        raise ValueError(f"{case_json_path} is missing required keys: {', '.join(missing)}")
    if payload["case_schema_version"] != MESH_GALLERY_CASE_SCHEMA_VERSION:
        raise ValueError(
            f"{case_json_path} declares unsupported schema version {payload['case_schema_version']!r}."
        )
    _validate_scale(str(payload["scale"]))
    _validate_variant(str(payload["variant"]))
    if not list(payload["what_it_shows"]):
        raise ValueError(f"{case_json_path} must define at least one what_it_shows bullet.")
    if not list(payload["source_paths"]):
        raise ValueError(f"{case_json_path} must define at least one source path.")
    return payload


def build_viewer_config_text(*, title: str, color_field: str) -> str:
    """Return one stable TOML config for the standalone mesh viewer."""

    return "\n".join(
        [
            "[mesh_distribution]",
            'bundle_dir = "./bundle"',
            "show_window = false",
            "",
            "[mesh_distribution.plot]",
            f'color_field = "{color_field}"',
            'color_map = "tab20"',
            "figure_size = [16.0, 8.0]",
            "dpi = 170",
            f'title = "{title}"',
            "show_topography_panel = true",
            'topography_field = "z_top_mean"',
            'topography_cmap = "terrain"',
            'topography_title = "Topographic overview"',
            "show_mesh_edges = true",
            'mesh_edge_color = "0.30"',
            "mesh_edge_linewidth = 0.65",
            "show_boundaries = true",
            "show_geology_interfaces = true",
            "show_river_edges = true",
            "annotate_cell_ids = false",
            "",
        ]
    )


def build_case_readme_text(metadata: dict[str, Any]) -> str:
    """Return one human-readable README for one imported mesh-gallery case."""

    lines = [
        f"# {metadata['title']}",
        "",
        metadata["summary"],
        "",
        "## Gallery Metadata",
        "",
        f"- Scale: `{metadata['scale_label']}`",
        f"- Outlet: `{metadata['outlet_id']}`",
        f"- Variant: `{metadata['variant_label']}`",
    ]
    if metadata.get("constraints_mode"):
        lines.append(f"- Bundle constraints mode: `{metadata['constraints_mode']}`")
    lines.extend(
        [
            "",
            "## Files",
            "",
            "- `case.json`: gallery metadata consumed by `tools.doc_gallery`",
            "- `viewer_config.toml`: standalone mesh-viewer config kept as fallback and used for bundle metrics",
            "- `bundle/`: versioned mesh bundle imported from one local meshing run",
        ]
    )
    if metadata.get("preferred_doc_figure_path"):
        lines.extend(
            [
                "- `figures/mesh_overview.png`: copied original figure reused on the documentation page",
            ]
        )
        if metadata.get("preferred_doc_regional_figure_path"):
            lines.append("- `figures/mesh_regional.png`: copied regional context figure")
    lines.extend(
        [
            "",
            "## Reproduction",
            "",
            "```bash",
            metadata["reproduction_command"],
            "```",
            "",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "ImportedMeshCasePaths",
    "MESH_GALLERY_CASE_SCHEMA_VERSION",
    "MESH_GALLERY_REQUIRED_BUNDLE_FILES",
    "MESH_GALLERY_SCALE_ORDER",
    "MESH_GALLERY_SCALE_SPECS",
    "MESH_GALLERY_VARIANT_SPECS",
    "REPO_ROOT",
    "build_case_readme_text",
    "build_default_case_metadata",
    "build_viewer_config_text",
    "canonical_case_dir",
    "case_paths",
    "default_case_slug",
    "default_launcher_config_for_scale",
    "iter_mesh_case_json_paths",
    "load_bundle_summary",
    "load_mesh_case_metadata",
    "mesh_gallery_root",
    "repo_relative",
    "scale_label",
    "validate_bundle_dir",
]
