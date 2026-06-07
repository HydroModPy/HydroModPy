"""JSON loader and validation helpers for declarative gallery manifests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .gallery_schema import (
    CATEGORY_SPECS,
    GalleryCaseSpec,
    GalleryImageAsset,
    GalleryMetricSpec,
    _format_float,
    _format_int,
    _format_scientific,
)

_DEFAULT_MANIFESTS_DIR = Path(__file__).resolve().parent / "manifests"


def _manifest_error(
    manifest_path: Path,
    message: str,
    *,
    case_slug: str | None = None,
) -> ValueError:
    location = manifest_path.as_posix()
    if case_slug:
        location = f"{location} [{case_slug}]"
    return ValueError(f"{location}: {message}")


def _coerce_str_tuple(value: Any, *, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raise TypeError(f"{field_name} must be a sequence of strings, not one string.")
    return tuple(str(item) for item in value)


def _metric_formatter_from_payload(payload: Any):
    if payload == "int":
        return _format_int
    if not isinstance(payload, dict):
        raise TypeError("metric formatter payload must be 'int' or a mapping.")

    kind = str(payload.get("kind", "")).strip().lower()
    unit = str(payload.get("unit", "")).strip()
    if kind == "float":
        return _format_float(unit, precision=int(payload.get("precision", 4)))
    if kind == "scientific":
        return _format_scientific(unit, precision=int(payload.get("precision", 2)))
    raise ValueError(f"Unsupported metric formatter kind: {kind!r}")


def _contains_results_stable_path(path: str) -> bool:
    normalized = str(path).replace("\\", "/").lower()
    return "results_stable/" in normalized


def _validate_manifest_image_assets(
    manifest_path: Path,
    *,
    case_slug: str,
    image_assets_payload: Any,
    generator: str,
) -> tuple[str, ...]:
    if not isinstance(image_assets_payload, (list, tuple)):
        raise _manifest_error(
            manifest_path,
            "'image_assets' must be a list of mappings.",
            case_slug=case_slug,
        )

    filenames: list[str] = []
    for asset in image_assets_payload:
        if not isinstance(asset, dict):
            raise _manifest_error(
                manifest_path,
                "image assets must be mappings.",
                case_slug=case_slug,
            )
        for key in ("filename", "caption", "alt_text"):
            value = str(asset.get(key, "")).strip()
            if value == "":
                raise _manifest_error(
                    manifest_path,
                    f"image asset field '{key}' is required.",
                    case_slug=case_slug,
                )
        filename = str(asset["filename"]).strip()
        if filename in filenames:
            raise _manifest_error(
                manifest_path,
                f"duplicate image filename '{filename}'.",
                case_slug=case_slug,
            )
        filenames.append(filename)
        source_path = str(asset.get("source_path", "")).strip()
        if generator == "copy_assets" and source_path == "":
            raise _manifest_error(
                manifest_path,
                "copy_assets cases require 'source_path' on every image asset.",
                case_slug=case_slug,
            )
        if source_path and _contains_results_stable_path(source_path):
            raise _manifest_error(
                manifest_path,
                "copy_assets sources must point to committed repository assets, not one local results_stable tree.",
                case_slug=case_slug,
            )
    return tuple(filenames)


def _validate_manifest_metadata_references(
    manifest_path: Path,
    *,
    case_slug: str,
    metadata: dict[str, Any],
    image_filenames: tuple[str, ...],
) -> None:
    known_filenames = set(image_filenames)
    if not known_filenames:
        return

    lead_image_filenames = metadata.get("lead_image_filenames", ())
    if lead_image_filenames is not None:
        if isinstance(lead_image_filenames, str) or not isinstance(
            lead_image_filenames,
            (list, tuple),
        ):
            raise _manifest_error(
                manifest_path,
                "'metadata.lead_image_filenames' must be a list of filenames.",
                case_slug=case_slug,
            )
        for filename in lead_image_filenames:
            if str(filename) not in known_filenames:
                raise _manifest_error(
                    manifest_path,
                    f"metadata.lead_image_filenames references unknown asset '{filename}'.",
                    case_slug=case_slug,
                )

    tab_specs = metadata.get("tab_specs", ())
    if tab_specs is None:
        return
    if not isinstance(tab_specs, (list, tuple)):
        raise _manifest_error(
            manifest_path,
            "'metadata.tab_specs' must be a list.",
            case_slug=case_slug,
        )
    for tab_spec in tab_specs:
        if not isinstance(tab_spec, dict):
            raise _manifest_error(
                manifest_path,
                "tab_specs entries must be mappings.",
                case_slug=case_slug,
            )
        referenced_filenames: list[str] = []
        filename = str(tab_spec.get("filename", "")).strip()
        if filename:
            referenced_filenames.append(filename)
        filenames = tab_spec.get("filenames", ())
        if filenames:
            if isinstance(filenames, str) or not isinstance(filenames, (list, tuple)):
                raise _manifest_error(
                    manifest_path,
                    "tab_specs.filenames must be a list of filenames.",
                    case_slug=case_slug,
                )
            referenced_filenames.extend(str(item) for item in filenames)
        for referenced_filename in referenced_filenames:
            if referenced_filename not in known_filenames:
                raise _manifest_error(
                    manifest_path,
                    f"metadata.tab_specs references unknown asset '{referenced_filename}'.",
                    case_slug=case_slug,
                )


def _validate_json_gallery_case_entry(
    manifest_path: Path,
    *,
    case_slug: str,
    merged_case: dict[str, Any],
) -> None:
    for field_name in (
        "slug",
        "title",
        "category",
        "deck",
        "summary",
        "reproduction_command",
        "generator",
    ):
        value = str(merged_case.get(field_name, "")).strip()
        if value == "":
            raise _manifest_error(
                manifest_path,
                f"required field '{field_name}' is missing or empty.",
                case_slug=case_slug,
            )

    category = str(merged_case["category"]).strip()
    if category not in CATEGORY_SPECS:
        raise _manifest_error(
            manifest_path,
            f"unknown category '{category}'.",
            case_slug=case_slug,
        )

    generator = str(merged_case["generator"]).strip()
    source_paths = merged_case.get("source_paths", ())
    if source_paths is not None:
        if isinstance(source_paths, str):
            raise _manifest_error(
                manifest_path,
                "'source_paths' must be a list of repository-relative paths.",
                case_slug=case_slug,
            )
        for path in source_paths:
            normalized = str(path).strip()
            if normalized == "":
                raise _manifest_error(
                    manifest_path,
                    "source_paths entries must be non-empty strings.",
                    case_slug=case_slug,
                )
            if generator == "copy_assets" and _contains_results_stable_path(normalized):
                raise _manifest_error(
                    manifest_path,
                    "copy_assets source_paths must not point to one local results_stable tree.",
                    case_slug=case_slug,
                )

    image_filenames = _validate_manifest_image_assets(
        manifest_path,
        case_slug=case_slug,
        image_assets_payload=merged_case.get("image_assets", ()),
        generator=generator,
    )
    if generator == "copy_assets" and not image_filenames:
        raise _manifest_error(
            manifest_path,
            "copy_assets cases must declare at least one image asset.",
            case_slug=case_slug,
        )

    metric_specs = merged_case.get("metric_specs", ())
    if metric_specs is not None and not isinstance(metric_specs, (list, tuple)):
        raise _manifest_error(
            manifest_path,
            "'metric_specs' must be a list.",
            case_slug=case_slug,
        )
    metadata = dict(merged_case.get("metadata", {}))
    _validate_manifest_metadata_references(
        manifest_path,
        case_slug=case_slug,
        metadata=metadata,
        image_filenames=image_filenames,
    )


def validate_gallery_specs(specs: tuple[GalleryCaseSpec, ...]) -> tuple[GalleryCaseSpec, ...]:
    seen_slugs: set[str] = set()
    for spec in specs:
        if spec.slug in seen_slugs:
            raise ValueError(f"Duplicate gallery slug detected: {spec.slug}")
        seen_slugs.add(spec.slug)
        if spec.category not in CATEGORY_SPECS:
            raise ValueError(f"Unknown gallery category on case {spec.slug}: {spec.category}")
        if spec.generator == "copy_assets":
            if not spec.image_assets:
                raise ValueError(f"copy_assets case {spec.slug} is missing image assets.")
            for asset in spec.image_assets:
                if asset.source_path is None or str(asset.source_path).strip() == "":
                    raise ValueError(
                        f"copy_assets case {spec.slug} is missing one image source_path."
                    )
                if _contains_results_stable_path(str(asset.source_path)):
                    raise ValueError(
                        f"copy_assets case {spec.slug} still references one results_stable asset."
                    )
            for source_path in spec.source_paths:
                if _contains_results_stable_path(str(source_path)):
                    raise ValueError(
                        f"copy_assets case {spec.slug} still references one results_stable source path."
                    )
    return specs


def load_json_gallery_case_specs(
    manifest_name: str,
    *,
    manifests_dir: Path | None = None,
) -> tuple[GalleryCaseSpec, ...]:
    """Load one small declarative gallery inventory from one manifests directory."""

    manifest_dir = manifests_dir or _DEFAULT_MANIFESTS_DIR
    manifest_path = manifest_dir / manifest_name
    manifest_repo_path = (Path("tools") / "doc_gallery" / "manifests" / manifest_name).as_posix()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{manifest_path.as_posix()} must define one top-level mapping.")
    defaults = dict(payload.get("defaults", {}))
    raw_cases = payload.get("cases", ())
    if not isinstance(raw_cases, list):
        raise TypeError(f"{manifest_path.as_posix()} must define a top-level 'cases' list.")

    specs: list[GalleryCaseSpec] = []
    seen_slugs: set[str] = set()
    for raw_case in raw_cases:
        if not isinstance(raw_case, dict):
            raise TypeError(f"{manifest_path.as_posix()} case entries must be mappings.")
        merged_case = {**defaults, **raw_case}
        default_metadata = dict(defaults.get("metadata", {}))
        merged_metadata = {**default_metadata, **dict(raw_case.get("metadata", {}))}
        merged_case["metadata"] = merged_metadata
        case_slug = str(merged_case.get("slug", "")).strip() or "<unknown>"
        if case_slug in seen_slugs:
            raise _manifest_error(
                manifest_path,
                f"duplicate case slug '{case_slug}'.",
                case_slug=case_slug,
            )
        seen_slugs.add(case_slug)
        _validate_json_gallery_case_entry(
            manifest_path,
            case_slug=case_slug,
            merged_case=merged_case,
        )

        image_assets = tuple(
            GalleryImageAsset(
                filename=str(asset["filename"]),
                caption=str(asset["caption"]),
                alt_text=str(asset["alt_text"]),
                source_path=(str(asset["source_path"]) if asset.get("source_path") else None),
            )
            for asset in merged_case.get("image_assets", ())
        )
        metric_specs = tuple(
            GalleryMetricSpec(
                label=str(metric["label"]),
                key=str(metric["key"]),
                formatter=_metric_formatter_from_payload(metric["formatter"]),
            )
            for metric in merged_case.get("metric_specs", ())
        )
        specs.append(
            GalleryCaseSpec(
                slug=str(merged_case["slug"]),
                title=str(merged_case["title"]),
                category=str(merged_case["category"]),
                deck=str(merged_case["deck"]),
                summary=str(merged_case["summary"]),
                what_it_shows=_coerce_str_tuple(
                    merged_case.get("what_it_shows", ()),
                    field_name="what_it_shows",
                ),
                reproduction_command=str(merged_case["reproduction_command"]),
                source_paths=(
                    manifest_repo_path,
                    *_coerce_str_tuple(
                        merged_case.get("source_paths", ()),
                        field_name="source_paths",
                    ),
                ),
                generator=str(merged_case["generator"]),
                image_assets=image_assets,
                metric_specs=metric_specs,
                case_setup=_coerce_str_tuple(
                    merged_case.get("case_setup", ()),
                    field_name="case_setup",
                ),
                key_parameters=_coerce_str_tuple(
                    merged_case.get("key_parameters", ()),
                    field_name="key_parameters",
                ),
                how_to_read=_coerce_str_tuple(
                    merged_case.get("how_to_read", ()),
                    field_name="how_to_read",
                ),
                next_steps=_coerce_str_tuple(
                    merged_case.get("next_steps", ()),
                    field_name="next_steps",
                ),
                reference_highlights=_coerce_str_tuple(
                    merged_case.get("reference_highlights", ()),
                    field_name="reference_highlights",
                ),
                equations_rst=_coerce_str_tuple(
                    merged_case.get("equations_rst", ()),
                    field_name="equations_rst",
                ),
                walkthrough_doc=(
                    str(merged_case["walkthrough_doc"])
                    if merged_case.get("walkthrough_doc")
                    else None
                ),
                walkthrough_title=(
                    str(merged_case["walkthrough_title"])
                    if merged_case.get("walkthrough_title")
                    else None
                ),
                metadata=merged_metadata,
            )
        )
    return tuple(specs)


__all__ = [
    "load_json_gallery_case_specs",
    "validate_gallery_specs",
]
