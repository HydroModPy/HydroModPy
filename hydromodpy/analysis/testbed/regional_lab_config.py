"""Configuration contract for the regional-lab launcher family."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field

from hydromodpy.analysis.config_helpers import (
    normalize_text_list,
    normalize_text_mapping,
    optional_text,
    require_mapping,
    require_text,
    resolve_required_path,
    validate_optional_positive_int,
)
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.toml_io.loader import load_toml_with_base_config


def _resolve_output_root(*, base_dir: Path, raw_value: object, lab_id: str) -> Path:
    """Resolve the regional-lab output root."""
    text = optional_text(raw_value)
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
            raise ValueError(
                f"regional_lab.{key} has been removed from regional_lab execution."
            )


class RegionalLabCatalogConfig(HydroModelBase):
    """Normalized catalog-loading contract."""

    model_config = ConfigDict(extra="forbid")

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


class RegionalLabSelectionConfig(HydroModelBase):
    """Top-level site selection filters."""

    model_config = ConfigDict(extra="forbid")

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


class RegionalLabClusterRuleConfig(HydroModelBase):
    """One explicit cluster enrichment rule applied on top of the site catalog."""

    model_config = ConfigDict(extra="forbid")

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
    selection: Annotated[RegionalLabSelectionConfig, Profile.USER]
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


class RegionalLabRecipeConfig(HydroModelBase):
    """One recipe expanded across selected sites."""

    model_config = ConfigDict(extra="forbid")

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
    selection: Annotated[RegionalLabSelectionConfig, Profile.USER]
    required_fields: Annotated[tuple[str, ...], Profile.USER] = Field(
        default=(),
        description="Catalog columns that must be present per site for this recipe.",
    )
    allowed_platforms: Annotated[tuple[str, ...], Profile.USER] = Field(
        default=(),
        description="Platforms (linux, darwin, windows) on which the recipe may run.",
    )


class RegionalLabConfig(HydroModelBase):
    """Validated top-level configuration for one regional-lab run."""

    model_config = ConfigDict(extra="forbid")

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
    catalog: Annotated[RegionalLabCatalogConfig, Profile.USER]
    selection: Annotated[RegionalLabSelectionConfig, Profile.USER]
    cluster_rules: Annotated[tuple[RegionalLabClusterRuleConfig, ...], Profile.USER] = Field(
        default=(),
        description="Optional cluster enrichment rules applied on top of the catalog.",
    )
    recipes: Annotated[tuple[RegionalLabRecipeConfig, ...], Profile.USER]

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
        raw_section = require_mapping(source, label="regional_lab")

        resolved_config_path = Path(config_path).expanduser().resolve()
        base_dir = resolved_config_path.parent
        lab_id = optional_text(raw_section.get("lab_id")) or resolved_config_path.stem
        output_root = _resolve_output_root(
            base_dir=base_dir,
            raw_value=raw_section.get("output_root"),
            lab_id=lab_id,
        )
        _reject_removed_execution_fields(raw_section)

        raw_catalog = require_mapping(
            raw_section.get("catalog"),
            label="regional_lab.catalog",
        )
        catalog_format = (optional_text(raw_catalog.get("format")) or "auto").lower()
        if catalog_format not in {"auto", "csv", "jsonl"}:
            raise ValueError("regional_lab.catalog.format must be one of: auto, csv, jsonl")
        tag_separator = optional_text(raw_catalog.get("tag_separator")) or ";"
        if tag_separator == "":
            raise ValueError("regional_lab.catalog.tag_separator cannot be empty")
        catalog = RegionalLabCatalogConfig(
            path=resolve_required_path(
                base_dir,
                raw_catalog.get("path"),
                label="regional_lab.catalog.path",
            ),
            format=catalog_format,
            site_id_field=require_text(
                raw_catalog.get("site_id_field", "site_id"),
                label="regional_lab.catalog.site_id_field",
            ),
            site_label_field=optional_text(raw_catalog.get("site_label_field", "site_label")),
            cluster_id_field=optional_text(raw_catalog.get("cluster_id_field", "cluster_id")),
            cluster_label_field=optional_text(
                raw_catalog.get("cluster_label_field", "cluster_label")
            ),
            cluster_family_field=optional_text(
                raw_catalog.get("cluster_family_field", "cluster_family")
            ),
            cluster_scale_field=optional_text(
                raw_catalog.get("cluster_scale_field", "cluster_scale")
            ),
            region_field=optional_text(raw_catalog.get("region_field", "region_id")),
            source_selection_field=optional_text(
                raw_catalog.get("source_selection_field", "source_selection_id")
            ),
            status_field=optional_text(raw_catalog.get("status_field", "site_status")),
            maturity_field=optional_text(raw_catalog.get("maturity_field", "maturity")),
            x_field=optional_text(raw_catalog.get("x_field", "x")),
            y_field=optional_text(raw_catalog.get("y_field", "y")),
            area_km2_field=optional_text(raw_catalog.get("area_km2_field", "area_km2")),
            tags_field=optional_text(raw_catalog.get("tags_field", "tags")),
            enabled_field=optional_text(raw_catalog.get("enabled_field", "enabled")),
            required_fields=normalize_text_list(
                raw_catalog.get("required_fields"),
                label="regional_lab.catalog.required_fields",
            ),
            path_fields=normalize_text_list(
                raw_catalog.get("path_fields"),
                label="regional_lab.catalog.path_fields",
            ),
            tag_separator=tag_separator,
        )

        raw_selection = require_mapping(
            raw_section.get("selection", {}),
            label="regional_lab.selection",
        )
        selection = _parse_selection(
            raw_selection,
            label="regional_lab.selection",
            include_disabled_default=False,
        )

        raw_cluster_rules = raw_section.get("cluster_rule", [])
        if not isinstance(raw_cluster_rules, list):
            raise ValueError("regional_lab.cluster_rule must be a list when provided")

        cluster_rules: list[RegionalLabClusterRuleConfig] = []
        seen_cluster_rule_ids: set[str] = set()
        for index, raw_rule in enumerate(raw_cluster_rules):
            rule_mapping = require_mapping(
                raw_rule,
                label=f"regional_lab.cluster_rule[{index}]",
            )
            rule_id = require_text(
                rule_mapping.get("id"),
                label=f"regional_lab.cluster_rule[{index}].id",
            )
            normalized_rule_id = rule_id.lower()
            if normalized_rule_id in seen_cluster_rule_ids:
                raise ValueError(f"Duplicate regional_lab.cluster_rule id '{rule_id}'")
            seen_cluster_rule_ids.add(normalized_rule_id)
            cluster_rules.append(
                RegionalLabClusterRuleConfig(
                    id=rule_id,
                    label=optional_text(rule_mapping.get("label")) or rule_id,
                    enabled=bool(rule_mapping.get("enabled", True)),
                    priority=int(rule_mapping.get("priority", 100)),
                    selection=_parse_selection(
                        rule_mapping,
                        label=f"regional_lab.cluster_rule[{rule_id}]",
                        include_disabled_default=True,
                    ),
                    field_equals=normalize_text_mapping(
                        rule_mapping.get("field_equals"),
                        label=f"regional_lab.cluster_rule[{rule_id}].field_equals",
                    ),
                    set_cluster_id=optional_text(rule_mapping.get("set_cluster_id")),
                    set_cluster_label=optional_text(rule_mapping.get("set_cluster_label")),
                    set_cluster_family=optional_text(rule_mapping.get("set_cluster_family")),
                    set_cluster_scale=optional_text(rule_mapping.get("set_cluster_scale")),
                    cluster_tags=normalize_text_list(
                        rule_mapping.get("cluster_tags"),
                        label=f"regional_lab.cluster_rule[{rule_id}].cluster_tags",
                    ),
                    override_existing_cluster=bool(
                        rule_mapping.get("override_existing_cluster", False)
                    ),
                )
            )

        raw_recipes = raw_section.get("recipe", [])
        if not isinstance(raw_recipes, list) or not raw_recipes:
            raise ValueError("regional_lab.recipe must contain at least one item")

        recipes: list[RegionalLabRecipeConfig] = []
        seen_recipe_ids: set[str] = set()
        for index, raw_recipe in enumerate(raw_recipes):
            recipe_mapping = require_mapping(
                raw_recipe,
                label=f"regional_lab.recipe[{index}]",
            )
            recipe_id = require_text(
                recipe_mapping.get("id"),
                label=f"regional_lab.recipe[{index}].id",
            )
            normalized_recipe_id = recipe_id.lower()
            if normalized_recipe_id in seen_recipe_ids:
                raise ValueError(f"Duplicate regional_lab.recipe id '{recipe_id}'")
            seen_recipe_ids.add(normalized_recipe_id)

            launcher = require_text(
                recipe_mapping.get("launcher"),
                label=f"regional_lab.recipe[{recipe_id}].launcher",
            ).lower()
            if launcher not in {"simulation", "comparison"}:
                raise ValueError(
                    f"Unsupported regional_lab.recipe launcher '{launcher}'. "
                    "Use 'simulation' or 'comparison'."
                )

            recipes.append(
                RegionalLabRecipeConfig(
                    id=recipe_id,
                    label=optional_text(recipe_mapping.get("label")) or recipe_id,
                    launcher=launcher,
                    config_path_template=require_text(
                        recipe_mapping.get("config_path_template"),
                        label=f"regional_lab.recipe[{recipe_id}].config_path_template",
                    ),
                    enabled=bool(recipe_mapping.get("enabled", True)),
                    selection=_parse_selection(
                        recipe_mapping,
                        label=f"regional_lab.recipe[{recipe_id}]",
                        include_disabled_default=True,
                    ),
                    required_fields=normalize_text_list(
                        recipe_mapping.get("required_fields"),
                        label=f"regional_lab.recipe[{recipe_id}].required_fields",
                    ),
                    allowed_platforms=normalize_text_list(
                        recipe_mapping.get("allowed_platforms"),
                        label=f"regional_lab.recipe[{recipe_id}].allowed_platforms",
                    ),
                )
            )

        return cls(
            config_path=resolved_config_path,
            base_dir=base_dir,
            lab_id=lab_id,
            output_root=output_root,
            execute=bool(raw_section.get("execute", True)),
            continue_on_error=bool(raw_section.get("continue_on_error", True)),
            validate_config_paths=bool(raw_section.get("validate_config_paths", True)),
            resume_from_report=bool(raw_section.get("resume_from_report", True)),
            skip_completed_cases=bool(raw_section.get("skip_completed_cases", True)),
            catalog=catalog,
            selection=selection,
            cluster_rules=tuple(cluster_rules),
            recipes=tuple(recipes),
        )

    @classmethod
    def from_file(cls, config_path: str | Path) -> RegionalLabConfig:
        """Load and validate one TOML configuration file."""
        resolved_config_path = Path(config_path).expanduser().resolve()
        payload = load_toml_with_base_config(resolved_config_path)
        return cls.from_toml(payload, config_path=resolved_config_path)


def _parse_selection(
    raw_mapping: Mapping[str, Any],
    *,
    label: str,
    include_disabled_default: bool,
) -> RegionalLabSelectionConfig:
    """Parse the common site-selection contract."""
    return RegionalLabSelectionConfig(
        site_ids=normalize_text_list(
            raw_mapping.get("site_ids"),
            label=f"{label}.site_ids",
        ),
        cluster_ids=normalize_text_list(
            raw_mapping.get("cluster_ids"),
            label=f"{label}.cluster_ids",
        ),
        regions=normalize_text_list(
            raw_mapping.get("regions"),
            label=f"{label}.regions",
        ),
        families=normalize_text_list(
            raw_mapping.get("families"),
            label=f"{label}.families",
        ),
        scales=normalize_text_list(
            raw_mapping.get("scales"),
            label=f"{label}.scales",
        ),
        statuses=normalize_text_list(
            raw_mapping.get("statuses"),
            label=f"{label}.statuses",
        ),
        maturity_levels=normalize_text_list(
            raw_mapping.get("maturity_levels"),
            label=f"{label}.maturity_levels",
        ),
        tags=normalize_text_list(
            raw_mapping.get("tags"),
            label=f"{label}.tags",
        ),
        limit=validate_optional_positive_int(
            raw_mapping.get("limit"),
            label=f"{label}.limit",
        ),
        include_disabled=bool(raw_mapping.get("include_disabled", include_disabled_default)),
    )
