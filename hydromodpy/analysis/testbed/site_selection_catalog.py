"""Helpers for consuming site-selection manifests as testbed catalogs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.schema.site_selection_manifest import (
    load_selection_manifest,
    manifest_output_path,
)

SITE_SELECTION_CATALOG_CONTROL_KEYS = (
    "from_site_selection_manifest",
    "output",
    "site_selection_output",
    "site_selection_output_key",
)


@dataclass(frozen=True)
class SiteSelectionCatalogSource:
    """Resolved catalog path plus optional site-selection provenance."""

    path: Path
    source_manifest_path: Path | None = None
    source_manifest_output_key: str | None = None


def resolve_catalog_source(
    *,
    base_dir: Path | None,
    mapping: Mapping[str, Any],
    catalog_label: str,
    default_output_key: str = "regional_lab_sites_csv",
) -> SiteSelectionCatalogSource:
    """Resolve a catalog path directly or through a site-selection manifest."""
    manifest_value = mapping.get("from_site_selection_manifest")
    if _optional_text(manifest_value) is None:
        return SiteSelectionCatalogSource(
            path=_resolve_required_path(
                base_dir,
                mapping.get("path"),
                label=f"{catalog_label}.path",
            )
        )
    if _optional_text(mapping.get("path")) is not None:
        raise ValueError(
            f"{catalog_label}.path and {catalog_label}.from_site_selection_manifest "
            "are mutually exclusive"
        )

    manifest_path = _resolve_required_path(
        base_dir,
        manifest_value,
        label=f"{catalog_label}.from_site_selection_manifest",
    )
    output_key = _manifest_output_key(mapping, default_output_key=default_output_key)

    manifest = load_selection_manifest(manifest_path)
    catalog_path = manifest_output_path(
        manifest,
        output_key,
        manifest_path=manifest_path,
    )
    if catalog_path is None:
        raw_outputs = manifest.get("outputs")
        available = (
            sorted(str(key) for key in raw_outputs) if isinstance(raw_outputs, Mapping) else []
        )
        suffix = "" if not available else f" Available outputs: {', '.join(available)}."
        raise ValueError(
            f"{catalog_label}.from_site_selection_manifest does not contain output "
            f"'{output_key}'.{suffix}"
        )
    if not catalog_path.is_file():
        raise FileNotFoundError(
            f"{catalog_label}.from_site_selection_manifest resolved output "
            f"'{output_key}' to a missing file: {catalog_path}"
        )
    return SiteSelectionCatalogSource(
        path=catalog_path,
        source_manifest_path=manifest_path,
        source_manifest_output_key=output_key,
    )


def _manifest_output_key(
    mapping: Mapping[str, Any],
    *,
    default_output_key: str,
) -> str:
    return (
        _optional_text(
            mapping.get(
                "site_selection_output_key",
                mapping.get("site_selection_output", mapping.get("output")),
            )
        )
        or default_output_key
    )


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _require_text(value: object, *, label: str) -> str:
    text = "" if value is None else str(value).strip()
    if text == "":
        raise ValueError(f"{label} cannot be empty")
    return text


def _resolve_required_path(base_dir: Path | None, raw_path: object, *, label: str) -> Path:
    text = _require_text(raw_path, label=label)
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() if base_dir is None else base_dir) / path
    return path.resolve()


__all__ = [
    "SITE_SELECTION_CATALOG_CONTROL_KEYS",
    "SiteSelectionCatalogSource",
    "resolve_catalog_source",
]
