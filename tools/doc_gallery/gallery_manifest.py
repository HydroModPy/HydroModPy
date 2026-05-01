"""Declarative manifest for the illustrated capability gallery."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .gallery_geometry_specs import build_geometry_specs
from .gallery_hydraulic_property_specs import build_hydraulic_property_specs
from .gallery_mesh_specs import MESH_GALLERY_METRIC_SPECS, build_mesh_static_specs
from .gallery_method_comparison_specs import build_method_comparison_specs
from .gallery_regional_lab_specs import build_regional_lab_specs
from .gallery_schema import (
    CATEGORY_SPECS,
    GalleryCaseSpec,
    GalleryCategorySpec,
    GalleryImageAsset,
    GalleryMetricSpec,
)
from .gallery_simulation_specs import build_simulation_specs
from .manifest_loader import (
    load_json_gallery_case_specs as _load_json_gallery_case_specs_from_module,
)
from .manifest_loader import (
    validate_gallery_specs as _validate_gallery_specs_from_module,
)
from .mesh_case_registry import (
    MESH_GALLERY_SCALE_ORDER,
    iter_mesh_case_json_paths,
    load_mesh_case_metadata,
)

_MANIFESTS_DIR = Path(__file__).resolve().parent / "manifests"


def _load_json_gallery_case_specs(manifest_name: str) -> tuple[GalleryCaseSpec, ...]:
    """Load one small declarative gallery inventory from ``tools/doc_gallery/manifests``."""

    return _load_json_gallery_case_specs_from_module(
        manifest_name,
        manifests_dir=_MANIFESTS_DIR,
    )


def _validate_gallery_specs(specs: tuple[GalleryCaseSpec, ...]) -> tuple[GalleryCaseSpec, ...]:
    return _validate_gallery_specs_from_module(specs)


def build_repo_mesh_gallery_case_specs(*, repo_root=None) -> tuple[GalleryCaseSpec, ...]:
    """Discover versioned mesh-gallery cases under ``examples/projects/07_mesh_gallery``."""

    scale_rank = {scale: index for index, scale in enumerate(MESH_GALLERY_SCALE_ORDER)}
    optional_metadata_keys = (
        "case_family_key",
        "case_family_label",
        "case_family_order",
        "comparison_group",
        "comparison_group_title",
        "site_tabs_group_key",
        "site_tabs_group_title",
        "site_tabs_label",
        "site_tabs_order",
        "source_results_family_dir",
        "source_results_manifest_path",
    )
    discovered_specs: list[tuple[tuple[Any, ...], GalleryCaseSpec]] = []
    discovery_kwargs = {} if repo_root is None else {"repo_root": repo_root}
    for case_json_path in iter_mesh_case_json_paths(**discovery_kwargs):
        payload = load_mesh_case_metadata(case_json_path)
        slug = str(payload["slug"])
        title = str(payload["title"])
        scale = str(payload["scale"])
        scale_label = str(payload.get("scale_label", scale))
        outlet_id = str(payload["outlet_id"])
        variant = str(payload["variant"])
        variant_label = str(payload.get("variant_label", variant))
        family_order = int(payload.get("case_family_order", scale_rank.get(scale, 999)))
        site_tabs_order = int(payload.get("site_tabs_order", 999))
        preferred_doc_figure_path = str(payload.get("preferred_doc_figure_path", "")).strip()
        preferred_doc_regional_figure_path = str(
            payload.get("preferred_doc_regional_figure_path", "")
        ).strip()
        image_assets = []
        if preferred_doc_figure_path:
            image_assets.append(
                GalleryImageAsset(
                    filename=f"{slug}_overview.png",
                    caption=str(
                        payload.get(
                            "image_caption",
                            "Original mesh figure copied from the imported meshing run.",
                        )
                    ),
                    alt_text=str(payload.get("image_alt_text", f"{title} overview")),
                    source_path=preferred_doc_figure_path,
                )
            )
            if preferred_doc_regional_figure_path:
                image_assets.append(
                    GalleryImageAsset(
                        filename=f"{slug}_regional.png",
                        caption=str(
                            payload.get(
                                "regional_image_caption",
                                "Regional framing figure copied from the imported meshing run.",
                            )
                        ),
                        alt_text=str(
                            payload.get("regional_image_alt_text", f"{title} regional context")
                        ),
                        source_path=preferred_doc_regional_figure_path,
                    )
                )
        else:
            image_assets.append(
                GalleryImageAsset(
                    filename=f"{slug}_overview.png",
                    caption=str(
                        payload.get(
                            "image_caption",
                            f"Mesh overview rendered from the versioned bundle shipped with `{slug}`.",
                        )
                    ),
                    alt_text=str(payload.get("image_alt_text", f"{title} overview")),
                )
            )
        family_key = str(payload.get("case_family_key", "")).strip()
        family_label = str(payload.get("case_family_label", "")).strip()
        comparison_group = str(payload.get("comparison_group", "")).strip()
        comparison_group_title = str(payload.get("comparison_group_title", "")).strip()
        if comparison_group == "":
            if family_key != "":
                comparison_group = f"{family_key}::outlet::{outlet_id}"
                comparison_group_title = (
                    comparison_group_title or f"{family_label or scale_label}, outlet {outlet_id}"
                )
            else:
                comparison_group = f"{scale}::outlet::{outlet_id}"
                comparison_group_title = (
                    comparison_group_title or f"{scale_label}, outlet {outlet_id}"
                )

        metadata = {
            "scale": scale,
            "scale_label": scale_label,
            "variant": variant,
            "variant_label": variant_label,
            "outlet_id": outlet_id,
            "comparison_group": comparison_group,
            "comparison_group_title": comparison_group_title,
            "config_path": str(payload["config_path"]),
            "constraints_mode": str(payload.get("constraints_mode", "")),
        }
        for key in optional_metadata_keys:
            if key in payload:
                metadata[key] = payload[key]

        discovered_specs.append(
            (
                (
                    family_order,
                    scale_rank.get(scale, 999),
                    site_tabs_order,
                    int(outlet_id) if outlet_id.isdigit() else outlet_id,
                    slug,
                ),
                GalleryCaseSpec(
                    slug=slug,
                    title=title,
                    category="mesh",
                    deck=str(payload["deck"]),
                    summary=str(payload["summary"]),
                    what_it_shows=tuple(str(item) for item in payload["what_it_shows"]),
                    reproduction_command=str(payload["reproduction_command"]),
                    source_paths=tuple(str(item) for item in payload["source_paths"]),
                    generator="mesh_viewer",
                    image_assets=tuple(image_assets),
                    metric_specs=MESH_GALLERY_METRIC_SPECS,
                    case_setup=tuple(str(item) for item in payload.get("case_setup", ())),
                    key_parameters=tuple(str(item) for item in payload.get("key_parameters", ())),
                    how_to_read=tuple(str(item) for item in payload.get("how_to_read", ())),
                    next_steps=tuple(str(item) for item in payload.get("next_steps", ())),
                    reference_highlights=tuple(
                        str(item) for item in payload.get("reference_highlights", ())
                    ),
                    equations_rst=tuple(str(item) for item in payload.get("equations_rst", ())),
                    walkthrough_doc=(
                        str(payload["walkthrough_doc"]) if payload.get("walkthrough_doc") else None
                    ),
                    walkthrough_title=(
                        str(payload["walkthrough_title"])
                        if payload.get("walkthrough_title")
                        else None
                    ),
                    metadata=metadata,
                ),
            )
        )
    return tuple(spec for _, spec in sorted(discovered_specs, key=lambda item: item[0]))


def _build_validation_gallery_specs() -> tuple[GalleryCaseSpec, ...]:
    from .validation_case_registry import build_validation_case_records

    return tuple(
        GalleryCaseSpec(
            slug=record.slug,
            title=record.title,
            category="validation",
            deck=record.deck,
            summary=record.summary,
            what_it_shows=record.what_it_shows,
            reproduction_command=record.reproduction_command,
            source_paths=record.source_paths,
            generator="validation_case",
            image_assets=(),
            case_setup=record.case_setup,
            reference_highlights=record.reference_highlights,
            equations_rst=record.equations_rst,
            metadata=record.metadata,
        )
        for record in build_validation_case_records()
    )


def _build_calibration_gallery_specs() -> tuple[GalleryCaseSpec, ...]:
    from .calibration_case_registry import build_calibration_case_records

    return tuple(
        GalleryCaseSpec(
            slug=record.slug,
            title=record.title,
            category="calibration",
            deck=record.deck,
            summary=record.summary,
            what_it_shows=record.what_it_shows,
            reproduction_command=record.reproduction_command,
            source_paths=record.source_paths,
            generator="calibration_case",
            image_assets=(),
            case_setup=record.case_setup,
            key_parameters=record.key_parameters,
            how_to_read=record.how_to_read,
            next_steps=record.next_steps,
            metadata=record.metadata,
        )
        for record in build_calibration_case_records()
    )


def build_gallery_specs(
    *,
    only_slugs: tuple[str, ...] = (),
    categories: tuple[str, ...] = (),
) -> tuple[GalleryCaseSpec, ...]:
    """Return the v1 illustrated-gallery inventory."""

    static_specs = (
        *build_mesh_static_specs(),
        *_load_json_gallery_case_specs("geographic_cases.json"),
        *build_geometry_specs(),
        *build_simulation_specs(),
        *build_regional_lab_specs(),
        *build_hydraulic_property_specs(),
        *build_method_comparison_specs(),
        *_load_json_gallery_case_specs("code_comparison_cases.json"),
    )
    mesh_specs = build_repo_mesh_gallery_case_specs()

    requested_categories = {value.strip() for value in categories if value.strip()}
    if requested_categories:
        needs_validation = "validation" in requested_categories
        needs_calibration = "calibration" in requested_categories
    elif only_slugs:
        known_slugs = {spec.slug for spec in static_specs + mesh_specs}
        unresolved_slugs = [slug for slug in only_slugs if slug not in known_slugs]
        needs_validation = bool(unresolved_slugs)
        needs_calibration = bool(unresolved_slugs)
    else:
        needs_validation = True
        needs_calibration = True

    validation_specs = _build_validation_gallery_specs() if needs_validation else ()
    calibration_specs = _build_calibration_gallery_specs() if needs_calibration else ()

    return _validate_gallery_specs(static_specs + validation_specs + calibration_specs + mesh_specs)


__all__ = [
    "CATEGORY_SPECS",
    "GalleryCaseSpec",
    "GalleryCategorySpec",
    "GalleryImageAsset",
    "GalleryMetricSpec",
    "build_gallery_specs",
]
