"""Configuration contract for the regional-lab launcher family."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, ValidationInfo, field_validator, model_validator

from hydromodpy.analysis.config_helpers import validate_optional_positive_int
from hydromodpy.analysis.testbed.site_selection_catalog import (
    SITE_SELECTION_CATALOG_CONTROL_KEYS,
    resolve_catalog_source,
)
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.toml_io.loader import load_toml_with_base_config


def _require_mapping(value: object, *, label: str) -> Mapping[str, Any]:
    """Validate that one raw value is a mapping."""
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return value


def _require_text(value: object, *, label: str) -> str:
    """Return one normalized non-empty text value."""
    text = str(value).strip()
    if text == "":
        raise ValueError(f"{label} cannot be empty")
    return text


def _optional_text(value: object) -> str | None:
    """Return one normalized optional text value."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_text_list(value: object, *, label: str) -> tuple[str, ...]:
    """Normalize one optional list of distinct text values."""
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{label} must be a list")
    out: list[str] = []
    seen: set[str] = set()
    for raw_item in value:
        item = str(raw_item).strip()
        if item == "":
            raise ValueError(f"{label} cannot contain empty values")
        normalized = item.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(item)
    return tuple(out)


def _normalize_text_mapping(
    value: object,
    *,
    label: str,
) -> tuple[tuple[str, str], ...]:
    """Normalize one optional mapping of text keys and values."""
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    out: list[tuple[str, str]] = []
    for raw_key, raw_value in value.items():
        key = str(raw_key).strip()
        mapped_value = str(raw_value).strip()
        if key == "":
            raise ValueError(f"{label} cannot contain empty keys")
        if mapped_value == "":
            raise ValueError(f"{label}[{key}] cannot be empty")
        out.append((key, mapped_value))
    out.sort(key=lambda item: item[0].lower())
    return tuple(out)


def _resolve_required_path(base_dir: Path | None, raw_path: object, *, label: str) -> Path:
    """Resolve one required path relative to the configuration file."""
    text = _require_text(raw_path, label=label)
    path = Path(text).expanduser()
    if not path.is_absolute():
        if base_dir is None:
            return path.resolve()
        path = base_dir / path
    return path.resolve()


def _resolve_optional_path(base_dir: Path | None, raw_path: object) -> Path | None:
    """Resolve one optional path relative to the configuration file."""
    text = _optional_text(raw_path)
    if text is None:
        return None
    path = Path(text).expanduser()
    if not path.is_absolute():
        if base_dir is None:
            return path.resolve()
        path = base_dir / path
    return path.resolve()


def _resolve_output_root(*, base_dir: Path, raw_value: object, lab_id: str) -> Path:
    """Resolve the regional-lab output root."""
    text = _optional_text(raw_value)
    if text is None:
        return (base_dir / "regional_lab" / lab_id).resolve()
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _reject_removed_execution_fields(raw_section: Mapping[str, Any]) -> None:
    """Reject regional-lab execution fields removed from the public contract."""
    if "execution_backend" in raw_section:
        raise ValueError(
            "regional_lab.execution_backend has been removed. "
            "regional_lab always uses the shared testbed runner provider."
        )
    for key in ("child_timeout_s", "python_executable"):
        if key in raw_section:
            raise ValueError(f"regional_lab.{key} has been removed from regional_lab execution.")


def _context_base_dir(info: ValidationInfo) -> Path | None:
    """Extract base_dir from the validation context, if any."""
    context = info.context
    if not isinstance(context, Mapping):
        return None
    raw = context.get("base_dir")
    if raw is None:
        return None
    return Path(raw)


class RegionalLabCatalogConfig(HydroModelBase):
    """Normalized catalog-loading contract."""

    path: Annotated[Path, Profile.USER] = Field(
        description="Resolved path to the site catalog (CSV or JSONL)."
    )
    format: Annotated[Literal["auto", "csv", "jsonl"], Profile.USER] = Field(
        default="auto",
        description="Catalog format. 'auto' infers from suffix.",
    )
    site_id_field: Annotated[str, Profile.USER] = Field(
        default="site_id",
        description="Catalog column carrying the site identifier.",
    )
    site_label_field: Annotated[str | None, Profile.USER] = Field(
        default="site_label",
        description="Catalog column carrying a human-readable site label.",
    )
    cluster_id_field: Annotated[str | None, Profile.USER] = Field(
        default="cluster_id",
        description="Catalog column carrying the cluster identifier.",
    )
    cluster_label_field: Annotated[str | None, Profile.USER] = Field(
        default="cluster_label",
        description="Catalog column carrying the cluster label.",
    )
    cluster_family_field: Annotated[str | None, Profile.USER] = Field(
        default="cluster_family",
        description="Catalog column carrying the cluster family name.",
    )
    cluster_scale_field: Annotated[str | None, Profile.USER] = Field(
        default="cluster_scale",
        description="Catalog column carrying the cluster spatial scale tag.",
    )
    region_field: Annotated[str | None, Profile.USER] = Field(
        default="region_id",
        description="Catalog column carrying the region identifier.",
    )
    source_selection_field: Annotated[str | None, Profile.USER] = Field(
        default="source_selection_id",
        description="Catalog column carrying the data-source selection identifier.",
    )
    status_field: Annotated[str | None, Profile.USER] = Field(
        default="site_status",
        description="Catalog column carrying the site lifecycle status.",
    )
    maturity_field: Annotated[str | None, Profile.USER] = Field(
        default="maturity",
        description="Catalog column carrying the site maturity level.",
    )
    x_field: Annotated[str | None, Profile.USER] = Field(
        default="x",
        description="Catalog column carrying the X coordinate (CRS units).",
    )
    y_field: Annotated[str | None, Profile.USER] = Field(
        default="y",
        description="Catalog column carrying the Y coordinate (CRS units).",
    )
    area_km2_field: Annotated[str | None, Profile.USER] = Field(
        default="area_km2",
        description="Catalog column carrying the catchment area in km^2.",
    )
    tags_field: Annotated[str | None, Profile.USER] = Field(
        default="tags",
        description="Catalog column carrying free-form tags joined by tag_separator.",
    )
    enabled_field: Annotated[str | None, Profile.USER] = Field(
        default="enabled",
        description="Catalog column flagging whether a site is active.",
    )
    required_fields: Annotated[tuple[str, ...], Profile.USER] = Field(
        default=(),
        description="Catalog columns that must be present and non-empty per row.",
    )
    path_fields: Annotated[tuple[str, ...], Profile.USER] = Field(
        default=(),
        description="Catalog columns whose values are resolved as filesystem paths.",
    )
    tag_separator: Annotated[str, Profile.USER] = Field(
        default=";",
        description="Separator splitting the tags column into individual tags.",
    )
    source_manifest_path: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description="Optional site-selection manifest used to resolve the site catalog.",
    )
    source_manifest_output_key: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Output key read from the site-selection manifest.",
    )

    @model_validator(mode="before")
    @classmethod
    def _bootstrap_catalog(cls, data: Any, info: ValidationInfo) -> Any:
        if not isinstance(data, Mapping):
            return data
        payload = dict(data)
        catalog_source = resolve_catalog_source(
            base_dir=_context_base_dir(info),
            mapping=payload,
            catalog_label="regional_lab.catalog",
        )
        for key in SITE_SELECTION_CATALOG_CONTROL_KEYS:
            payload.pop(key, None)
        payload["path"] = catalog_source.path
        if catalog_source.source_manifest_path is not None:
            payload["source_manifest_path"] = catalog_source.source_manifest_path
            payload["source_manifest_output_key"] = catalog_source.source_manifest_output_key
        return payload

    @field_validator("path", mode="before")
    @classmethod
    def _resolve_path(cls, value: object, info: ValidationInfo) -> Path:
        return _resolve_required_path(
            _context_base_dir(info),
            value,
            label="regional_lab.catalog.path",
        )

    @field_validator(
        "site_label_field",
        "cluster_id_field",
        "cluster_label_field",
        "cluster_family_field",
        "cluster_scale_field",
        "region_field",
        "source_selection_field",
        "status_field",
        "maturity_field",
        "x_field",
        "y_field",
        "area_km2_field",
        "tags_field",
        "enabled_field",
        mode="before",
    )
    @classmethod
    def _normalize_optional_field(cls, value: object) -> str | None:
        return _optional_text(value)

    @field_validator("required_fields", "path_fields", mode="before")
    @classmethod
    def _normalize_field_list(cls, value: object, info: ValidationInfo) -> tuple[str, ...]:
        return _normalize_text_list(value, label=f"regional_lab.catalog.{info.field_name}")

    @field_validator("tag_separator", mode="before")
    @classmethod
    def _normalize_tag_separator(cls, value: object) -> str:
        text = _optional_text(value)
        if text is None:
            return ";"
        if text == "":
            raise ValueError("regional_lab.catalog.tag_separator cannot be empty")
        return text

    @field_validator("format", mode="before")
    @classmethod
    def _normalize_format(cls, value: object) -> str:
        text = _optional_text(value)
        normalized = (text or "auto").lower()
        if normalized not in {"auto", "csv", "jsonl"}:
            raise ValueError("regional_lab.catalog.format must be one of: auto, csv, jsonl")
        return normalized

    @field_validator("site_id_field", mode="before")
    @classmethod
    def _normalize_site_id_field(cls, value: object) -> str:
        if value is None:
            return "site_id"
        return _require_text(value, label="regional_lab.catalog.site_id_field")


class RegionalLabSelectionConfig(HydroModelBase):
    """Top-level site selection filters."""

    site_ids: Annotated[tuple[str, ...], Profile.USER] = Field(
        default=(),
        description="Whitelist of site identifiers to keep. Empty means no filter.",
    )
    cluster_ids: Annotated[tuple[str, ...], Profile.USER] = Field(
        default=(),
        description="Whitelist of cluster identifiers to keep. Empty means no filter.",
    )
    regions: Annotated[tuple[str, ...], Profile.USER] = Field(
        default=(),
        description="Whitelist of region identifiers to keep. Empty means no filter.",
    )
    families: Annotated[tuple[str, ...], Profile.USER] = Field(
        default=(),
        description="Whitelist of cluster family names to keep. Empty means no filter.",
    )
    scales: Annotated[tuple[str, ...], Profile.USER] = Field(
        default=(),
        description="Whitelist of cluster scale tags to keep. Empty means no filter.",
    )
    statuses: Annotated[tuple[str, ...], Profile.USER] = Field(
        default=(),
        description="Whitelist of site lifecycle statuses to keep. Empty means no filter.",
    )
    maturity_levels: Annotated[tuple[str, ...], Profile.USER] = Field(
        default=(),
        description="Whitelist of site maturity levels to keep. Empty means no filter.",
    )
    tags: Annotated[tuple[str, ...], Profile.USER] = Field(
        default=(),
        description="Required tags. A site must carry every tag listed here to pass.",
    )
    limit: Annotated[int | None, Profile.USER] = Field(
        default=None,
        description="Maximum number of sites to retain after filtering. None disables.",
    )
    include_disabled: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="If True, also keep sites flagged as disabled in the catalog.",
    )

    @field_validator(
        "site_ids",
        "cluster_ids",
        "regions",
        "families",
        "scales",
        "statuses",
        "maturity_levels",
        "tags",
        mode="before",
    )
    @classmethod
    def _normalize_selection_list(cls, value: object, info: ValidationInfo) -> tuple[str, ...]:
        return _normalize_text_list(value, label=f"selection.{info.field_name}")

    @field_validator("limit", mode="before")
    @classmethod
    def _normalize_limit(cls, value: object) -> int | None:
        return validate_optional_positive_int(value, label="selection.limit")


class RegionalLabClusterRuleConfig(HydroModelBase):
    """One explicit cluster enrichment rule applied on top of the site catalog."""

    id: Annotated[str, Profile.USER] = Field(description="Unique rule identifier.")
    label: Annotated[str, Profile.USER] = Field(description="Human-readable rule label.")
    enabled: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="If False, the rule is parsed but skipped during enrichment.",
    )
    priority: Annotated[int, Profile.USER] = Field(
        default=100,
        description="Application order (lower runs first) when several rules match.",
    )
    selection: Annotated[RegionalLabSelectionConfig, Profile.USER] = Field(
        description="Site filters (ids, regions, families, tags) restricting which sites the rule applies to.",
    )
    field_equals: Annotated[tuple[tuple[str, str], ...], Profile.USER] = Field(
        default=(),
        description="Column equality constraints applied on top of selection (key=value).",
    )
    set_cluster_id: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Cluster id to assign to matched sites. None leaves it untouched.",
    )
    set_cluster_label: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Cluster label to assign to matched sites. None leaves it untouched.",
    )
    set_cluster_family: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Cluster family to assign to matched sites. None leaves it untouched.",
    )
    set_cluster_scale: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Cluster scale tag to assign to matched sites. None leaves it untouched.",
    )
    cluster_tags: Annotated[tuple[str, ...], Profile.USER] = Field(
        default=(),
        description="Extra tags appended to the cluster of matched sites.",
    )
    override_existing_cluster: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="If True, overwrite cluster fields already set on matched sites.",
    )

    @model_validator(mode="before")
    @classmethod
    def _bootstrap_rule(cls, data: Any) -> Any:
        if not isinstance(data, Mapping):
            return data
        payload = dict(data)
        rule_id = payload.get("id")
        if rule_id is not None:
            text_id = _require_text(rule_id, label="regional_lab.cluster_rule.id")
            payload["id"] = text_id
            if "label" not in payload or payload.get("label") is None:
                payload["label"] = text_id
            else:
                payload["label"] = _optional_text(payload["label"]) or text_id
        if "selection" not in payload:
            payload["selection"] = _extract_selection_payload(
                payload, include_disabled_default=True
            )
        for key in _SELECTION_KEYS:
            payload.pop(key, None)
        return payload

    @field_validator("id", mode="before")
    @classmethod
    def _normalize_id(cls, value: object) -> str:
        return _require_text(value, label="regional_lab.cluster_rule.id")

    @field_validator(
        "set_cluster_id",
        "set_cluster_label",
        "set_cluster_family",
        "set_cluster_scale",
        mode="before",
    )
    @classmethod
    def _normalize_optional(cls, value: object) -> str | None:
        return _optional_text(value)

    @field_validator("cluster_tags", mode="before")
    @classmethod
    def _normalize_cluster_tags(cls, value: object) -> tuple[str, ...]:
        return _normalize_text_list(value, label="regional_lab.cluster_rule.cluster_tags")

    @field_validator("field_equals", mode="before")
    @classmethod
    def _normalize_field_equals(cls, value: object) -> tuple[tuple[str, str], ...]:
        return _normalize_text_mapping(value, label="regional_lab.cluster_rule.field_equals")


class RegionalLabRecipeConfig(HydroModelBase):
    """One recipe expanded across selected sites."""

    id: Annotated[str, Profile.USER] = Field(description="Unique recipe identifier.")
    label: Annotated[str, Profile.USER] = Field(description="Human-readable recipe label.")
    launcher: Annotated[Literal["simulation", "comparison"], Profile.USER] = Field(
        description="Child launcher dispatched per site."
    )
    config_path_template: Annotated[str, Profile.USER] = Field(
        description="Template producing the child config path from a site context."
    )
    enabled: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="If False, the recipe is parsed but skipped during dispatch.",
    )
    selection: Annotated[RegionalLabSelectionConfig, Profile.USER] = Field(
        description="Site filters restricting which sites this recipe expands over.",
    )
    required_fields: Annotated[tuple[str, ...], Profile.USER] = Field(
        default=(),
        description="Catalog columns that must be present per site for this recipe.",
    )
    allowed_platforms: Annotated[tuple[str, ...], Profile.USER] = Field(
        default=(),
        description="Platforms (linux, darwin, windows) on which the recipe may run.",
    )

    @model_validator(mode="before")
    @classmethod
    def _bootstrap_recipe(cls, data: Any) -> Any:
        if not isinstance(data, Mapping):
            return data
        payload = dict(data)
        recipe_id = payload.get("id")
        if recipe_id is not None:
            text_id = _require_text(recipe_id, label="regional_lab.recipe.id")
            payload["id"] = text_id
            if "label" not in payload or payload.get("label") is None:
                payload["label"] = text_id
            else:
                payload["label"] = _optional_text(payload["label"]) or text_id
        if "selection" not in payload:
            payload["selection"] = _extract_selection_payload(
                payload, include_disabled_default=True
            )
        for key in _SELECTION_KEYS:
            payload.pop(key, None)
        return payload

    @field_validator("id", mode="before")
    @classmethod
    def _normalize_id(cls, value: object) -> str:
        return _require_text(value, label="regional_lab.recipe.id")

    @field_validator("config_path_template", mode="before")
    @classmethod
    def _normalize_template(cls, value: object) -> str:
        return _require_text(value, label="regional_lab.recipe.config_path_template")

    @field_validator("launcher", mode="before")
    @classmethod
    def _normalize_launcher(cls, value: object) -> str:
        text = _require_text(value, label="regional_lab.recipe.launcher").lower()
        if text not in {"simulation", "comparison"}:
            raise ValueError(
                f"Unsupported regional_lab.recipe launcher '{text}'. "
                "Use 'simulation' or 'comparison'."
            )
        return text

    @field_validator("required_fields", "allowed_platforms", mode="before")
    @classmethod
    def _normalize_recipe_list(cls, value: object, info: ValidationInfo) -> tuple[str, ...]:
        return _normalize_text_list(value, label=f"regional_lab.recipe.{info.field_name}")


_SELECTION_KEYS: frozenset[str] = frozenset(
    {
        "site_ids",
        "cluster_ids",
        "regions",
        "families",
        "scales",
        "statuses",
        "maturity_levels",
        "tags",
        "limit",
        "include_disabled",
    }
)


def _extract_selection_payload(
    raw_mapping: Mapping[str, Any],
    *,
    include_disabled_default: bool,
) -> dict[str, Any]:
    """Extract the embedded site-selection sub-payload from a parent mapping."""
    payload: dict[str, Any] = {}
    for key in _SELECTION_KEYS:
        if key in raw_mapping:
            payload[key] = raw_mapping[key]
    payload.setdefault("include_disabled", include_disabled_default)
    return payload


class RegionalLabConfig(HydroModelBase):
    """Validated top-level configuration for one regional-lab run."""

    config_path: Annotated[Path, Profile.USER] = Field(
        description="Resolved path to the source TOML file."
    )
    base_dir: Annotated[Path, Profile.USER] = Field(
        description="Directory used to resolve relative paths."
    )
    lab_id: Annotated[str, Profile.USER] = Field(description="Regional-lab identifier.")
    output_root: Annotated[Path, Profile.USER] = Field(
        description="Directory where lab artifacts are written."
    )
    execute: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="If False, the planner runs but no child workflows are launched.",
    )
    continue_on_error: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="If True, keep dispatching siblings after a child failure.",
    )
    validate_config_paths: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="If True, ensure each rendered child config path exists before run.",
    )
    resume_from_report: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="If True, replay the previous report to skip already-completed cases.",
    )
    skip_completed_cases: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="If True, do not re-run cases marked as completed in the report.",
    )
    catalog: Annotated[RegionalLabCatalogConfig, Profile.USER] = Field(
        description="Site catalog source declaring the columns and filters used to enumerate runs.",
    )
    selection: Annotated[RegionalLabSelectionConfig, Profile.USER] = Field(
        description="Top-level site selection filters applied before cluster rules and recipes.",
    )
    cluster_rules: Annotated[tuple[RegionalLabClusterRuleConfig, ...], Profile.USER] = Field(
        default=(),
        description="Optional cluster enrichment rules applied on top of the catalog.",
    )
    recipes: Annotated[tuple[RegionalLabRecipeConfig, ...], Profile.USER] = Field(
        description="Per-recipe expansion plans declaring which child launchers run on which sites.",
    )

    @model_validator(mode="before")
    @classmethod
    def _bootstrap_lab(cls, data: Any, info: ValidationInfo) -> Any:
        if not isinstance(data, Mapping):
            return data
        payload = dict(data)
        base_dir = _context_base_dir(info)

        config_path_value = payload.get("config_path")
        if config_path_value is not None and base_dir is None:
            base_dir = Path(config_path_value).parent
        if base_dir is not None:
            payload.setdefault("base_dir", base_dir)

        lab_id = _optional_text(payload.get("lab_id"))
        if lab_id is None and config_path_value is not None:
            lab_id = Path(config_path_value).stem
        if lab_id is not None:
            payload["lab_id"] = lab_id

        output_root_raw = _optional_text(payload.get("output_root"))
        if output_root_raw is None and base_dir is not None and lab_id is not None:
            payload["output_root"] = (base_dir / "regional_lab" / lab_id).resolve()
        elif output_root_raw is not None:
            payload["output_root"] = _resolve_required_path(
                base_dir, output_root_raw, label="regional_lab.output_root"
            )

        if "selection" not in payload:
            payload["selection"] = _extract_selection_payload(
                payload, include_disabled_default=False
            )

        cluster_rules = payload.pop("cluster_rule", None)
        if cluster_rules is not None and "cluster_rules" not in payload:
            payload["cluster_rules"] = cluster_rules

        recipes = payload.pop("recipe", None)
        if recipes is not None and "recipes" not in payload:
            payload["recipes"] = recipes

        for key in _SELECTION_KEYS - {"include_disabled"}:
            payload.pop(key, None)

        return payload

    @field_validator("cluster_rules", mode="before")
    @classmethod
    def _normalize_cluster_rules(cls, value: object) -> Any:
        if value is None:
            return ()
        if not isinstance(value, (list, tuple)):
            raise ValueError("regional_lab.cluster_rule must be a list when provided")
        seen: set[str] = set()
        out: list[Any] = []
        for index, raw_rule in enumerate(value):
            mapping = _require_mapping(raw_rule, label=f"regional_lab.cluster_rule[{index}]")
            rule_id = _require_text(
                mapping.get("id"), label=f"regional_lab.cluster_rule[{index}].id"
            )
            normalized = rule_id.lower()
            if normalized in seen:
                raise ValueError(f"Duplicate regional_lab.cluster_rule id '{rule_id}'")
            seen.add(normalized)
            out.append(mapping)
        return tuple(out)

    @field_validator("recipes", mode="before")
    @classmethod
    def _normalize_recipes(cls, value: object) -> Any:
        if not isinstance(value, (list, tuple)) or not value:
            raise ValueError("regional_lab.recipe must contain at least one item")
        seen: set[str] = set()
        out: list[Any] = []
        for index, raw_recipe in enumerate(value):
            mapping = _require_mapping(raw_recipe, label=f"regional_lab.recipe[{index}]")
            recipe_id = _require_text(mapping.get("id"), label=f"regional_lab.recipe[{index}].id")
            normalized = recipe_id.lower()
            if normalized in seen:
                raise ValueError(f"Duplicate regional_lab.recipe id '{recipe_id}'")
            seen.add(normalized)
            out.append(mapping)
        return tuple(out)

    @classmethod
    def from_toml(
        cls,
        raw_toml: Mapping[str, Any],
        *,
        config_path: str | Path,
    ) -> RegionalLabConfig:
        """Validate one raw TOML payload."""
        if not isinstance(raw_toml, Mapping):
            raise ValueError("configuration must be a mapping")
        source = raw_toml.get("regional_lab") if "regional_lab" in raw_toml else raw_toml
        section = _require_mapping(source, label="regional_lab")
        _reject_removed_execution_fields(section)

        resolved_config_path = Path(config_path).expanduser().resolve()
        base_dir = resolved_config_path.parent

        payload = dict(section)
        payload.setdefault("config_path", resolved_config_path)
        payload.setdefault("base_dir", base_dir)

        return cls.model_validate(payload, context={"base_dir": base_dir})

    @classmethod
    def from_file(cls, config_path: str | Path) -> RegionalLabConfig:
        """Load and validate one TOML configuration file."""
        resolved_config_path = Path(config_path).expanduser().resolve()
        payload = load_toml_with_base_config(resolved_config_path)
        return cls.from_toml(payload, config_path=resolved_config_path)
