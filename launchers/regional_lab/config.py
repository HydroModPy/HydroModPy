"""Configuration contract for the regional-lab launcher family."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from hydromodpy.core.config.toml_loader import load_toml_with_base_config


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
    if not isinstance(value, list):
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


def _resolve_required_path(base_dir: Path, raw_path: object, *, label: str) -> Path:
    """Resolve one required path relative to the configuration file."""
    text = _require_text(raw_path, label=label)
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _resolve_optional_path(base_dir: Path, raw_path: object) -> Path | None:
    """Resolve one optional path relative to the configuration file."""
    text = _optional_text(raw_path)
    if text is None:
        return None
    path = Path(text).expanduser()
    if not path.is_absolute():
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


def _validate_optional_int(value: object, *, label: str) -> int | None:
    """Validate one optional positive integer."""
    if value is None:
        return None
    out = int(value)
    if out <= 0:
        raise ValueError(f"{label} must be >= 1")
    return out


@dataclass(frozen=True)
class RegionalLabCatalogConfig:
    """Normalized catalog-loading contract."""

    path: Path
    format: str
    site_id_field: str
    site_label_field: str | None
    cluster_id_field: str | None
    cluster_label_field: str | None
    cluster_family_field: str | None
    cluster_scale_field: str | None
    region_field: str | None
    source_selection_field: str | None
    status_field: str | None
    maturity_field: str | None
    x_field: str | None
    y_field: str | None
    area_km2_field: str | None
    tags_field: str | None
    enabled_field: str | None
    required_fields: tuple[str, ...]
    path_fields: tuple[str, ...]
    tag_separator: str


@dataclass(frozen=True)
class RegionalLabSelectionConfig:
    """Top-level site selection filters."""

    site_ids: tuple[str, ...]
    cluster_ids: tuple[str, ...]
    regions: tuple[str, ...]
    families: tuple[str, ...]
    scales: tuple[str, ...]
    statuses: tuple[str, ...]
    maturity_levels: tuple[str, ...]
    tags: tuple[str, ...]
    limit: int | None
    include_disabled: bool


@dataclass(frozen=True)
class RegionalLabClusterRuleConfig:
    """One explicit cluster enrichment rule applied on top of the site catalog."""

    id: str
    label: str
    enabled: bool
    priority: int
    selection: RegionalLabSelectionConfig
    field_equals: tuple[tuple[str, str], ...]
    set_cluster_id: str | None
    set_cluster_label: str | None
    set_cluster_family: str | None
    set_cluster_scale: str | None
    cluster_tags: tuple[str, ...]
    override_existing_cluster: bool


@dataclass(frozen=True)
class RegionalLabRecipeConfig:
    """One recipe expanded across selected sites."""

    id: str
    label: str
    launcher: str
    config_path_template: str
    enabled: bool
    selection: RegionalLabSelectionConfig
    required_fields: tuple[str, ...]


@dataclass(frozen=True)
class RegionalLabConfig:
    """Validated top-level configuration for one regional-lab run."""

    config_path: Path
    base_dir: Path
    lab_id: str
    output_root: Path
    execute: bool
    continue_on_error: bool
    validate_config_paths: bool
    resume_from_report: bool
    skip_completed_cases: bool
    python_executable: Path | None
    catalog: RegionalLabCatalogConfig
    selection: RegionalLabSelectionConfig
    cluster_rules: tuple[RegionalLabClusterRuleConfig, ...]
    recipes: tuple[RegionalLabRecipeConfig, ...]

    @classmethod
    def from_toml(
        cls,
        raw_toml: Mapping[str, Any],
        *,
        config_path: str | Path,
    ) -> "RegionalLabConfig":
        """Validate one raw TOML payload."""
        if not isinstance(raw_toml, Mapping):
            raise ValueError("configuration must be a mapping")
        raw_section = _require_mapping(
            raw_toml.get("regional_lab"),
            label="regional_lab",
        )

        resolved_config_path = Path(config_path).expanduser().resolve()
        base_dir = resolved_config_path.parent
        lab_id = _optional_text(raw_section.get("lab_id")) or resolved_config_path.stem
        output_root = _resolve_output_root(
            base_dir=base_dir,
            raw_value=raw_section.get("output_root"),
            lab_id=lab_id,
        )
        execute = bool(raw_section.get("execute", True))
        continue_on_error = bool(raw_section.get("continue_on_error", True))
        validate_config_paths = bool(raw_section.get("validate_config_paths", True))
        resume_from_report = bool(raw_section.get("resume_from_report", True))
        skip_completed_cases = bool(raw_section.get("skip_completed_cases", True))
        python_executable = _resolve_optional_path(
            base_dir,
            raw_section.get("python_executable"),
        )

        raw_catalog = _require_mapping(
            raw_section.get("catalog"),
            label="regional_lab.catalog",
        )
        catalog_format = (_optional_text(raw_catalog.get("format")) or "auto").lower()
        if catalog_format not in {"auto", "csv", "jsonl"}:
            raise ValueError("regional_lab.catalog.format must be one of: auto, csv, jsonl")
        tag_separator = _optional_text(raw_catalog.get("tag_separator")) or ";"
        if tag_separator == "":
            raise ValueError("regional_lab.catalog.tag_separator cannot be empty")
        catalog = RegionalLabCatalogConfig(
            path=_resolve_required_path(
                base_dir,
                raw_catalog.get("path"),
                label="regional_lab.catalog.path",
            ),
            format=catalog_format,
            site_id_field=_require_text(
                raw_catalog.get("site_id_field", "site_id"),
                label="regional_lab.catalog.site_id_field",
            ),
            site_label_field=_optional_text(raw_catalog.get("site_label_field", "site_label")),
            cluster_id_field=_optional_text(raw_catalog.get("cluster_id_field", "cluster_id")),
            cluster_label_field=_optional_text(
                raw_catalog.get("cluster_label_field", "cluster_label")
            ),
            cluster_family_field=_optional_text(
                raw_catalog.get("cluster_family_field", "cluster_family")
            ),
            cluster_scale_field=_optional_text(
                raw_catalog.get("cluster_scale_field", "cluster_scale")
            ),
            region_field=_optional_text(raw_catalog.get("region_field", "region_id")),
            source_selection_field=_optional_text(
                raw_catalog.get("source_selection_field", "source_selection_id")
            ),
            status_field=_optional_text(raw_catalog.get("status_field", "site_status")),
            maturity_field=_optional_text(raw_catalog.get("maturity_field", "maturity")),
            x_field=_optional_text(raw_catalog.get("x_field", "x")),
            y_field=_optional_text(raw_catalog.get("y_field", "y")),
            area_km2_field=_optional_text(raw_catalog.get("area_km2_field", "area_km2")),
            tags_field=_optional_text(raw_catalog.get("tags_field", "tags")),
            enabled_field=_optional_text(raw_catalog.get("enabled_field", "enabled")),
            required_fields=_normalize_text_list(
                raw_catalog.get("required_fields"),
                label="regional_lab.catalog.required_fields",
            ),
            path_fields=_normalize_text_list(
                raw_catalog.get("path_fields"),
                label="regional_lab.catalog.path_fields",
            ),
            tag_separator=tag_separator,
        )

        raw_selection = _require_mapping(
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
            rule_mapping = _require_mapping(
                raw_rule,
                label=f"regional_lab.cluster_rule[{index}]",
            )
            rule_id = _require_text(
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
                    label=_optional_text(rule_mapping.get("label")) or rule_id,
                    enabled=bool(rule_mapping.get("enabled", True)),
                    priority=int(rule_mapping.get("priority", 100)),
                    selection=_parse_selection(
                        rule_mapping,
                        label=f"regional_lab.cluster_rule[{rule_id}]",
                        include_disabled_default=True,
                    ),
                    field_equals=_normalize_text_mapping(
                        rule_mapping.get("field_equals"),
                        label=f"regional_lab.cluster_rule[{rule_id}].field_equals",
                    ),
                    set_cluster_id=_optional_text(rule_mapping.get("set_cluster_id")),
                    set_cluster_label=_optional_text(rule_mapping.get("set_cluster_label")),
                    set_cluster_family=_optional_text(rule_mapping.get("set_cluster_family")),
                    set_cluster_scale=_optional_text(rule_mapping.get("set_cluster_scale")),
                    cluster_tags=_normalize_text_list(
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
            recipe_mapping = _require_mapping(
                raw_recipe,
                label=f"regional_lab.recipe[{index}]",
            )
            recipe_id = _require_text(
                recipe_mapping.get("id"),
                label=f"regional_lab.recipe[{index}].id",
            )
            normalized_recipe_id = recipe_id.lower()
            if normalized_recipe_id in seen_recipe_ids:
                raise ValueError(f"Duplicate regional_lab.recipe id '{recipe_id}'")
            seen_recipe_ids.add(normalized_recipe_id)

            launcher = _require_text(
                recipe_mapping.get("launcher"),
                label=f"regional_lab.recipe[{recipe_id}].launcher",
            ).lower()
            if launcher not in {"simulation", "method-comparison"}:
                raise ValueError(
                    f"Unsupported regional_lab.recipe launcher '{launcher}'. "
                    "Use 'simulation' or 'method-comparison'."
                )

            recipes.append(
                RegionalLabRecipeConfig(
                    id=recipe_id,
                    label=_optional_text(recipe_mapping.get("label")) or recipe_id,
                    launcher=launcher,
                    config_path_template=_require_text(
                        recipe_mapping.get("config_path_template"),
                        label=f"regional_lab.recipe[{recipe_id}].config_path_template",
                    ),
                    enabled=bool(recipe_mapping.get("enabled", True)),
                    selection=_parse_selection(
                        recipe_mapping,
                        label=f"regional_lab.recipe[{recipe_id}]",
                        include_disabled_default=True,
                    ),
                    required_fields=_normalize_text_list(
                        recipe_mapping.get("required_fields"),
                        label=f"regional_lab.recipe[{recipe_id}].required_fields",
                    ),
                )
            )

        return cls(
            config_path=resolved_config_path,
            base_dir=base_dir,
            lab_id=lab_id,
            output_root=output_root,
            execute=execute,
            continue_on_error=continue_on_error,
            validate_config_paths=validate_config_paths,
            resume_from_report=resume_from_report,
            skip_completed_cases=skip_completed_cases,
            python_executable=python_executable,
            catalog=catalog,
            selection=selection,
            cluster_rules=tuple(cluster_rules),
            recipes=tuple(recipes),
        )

    @classmethod
    def from_file(cls, config_path: str | Path) -> "RegionalLabConfig":
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
        site_ids=_normalize_text_list(
            raw_mapping.get("site_ids"),
            label=f"{label}.site_ids",
        ),
        cluster_ids=_normalize_text_list(
            raw_mapping.get("cluster_ids"),
            label=f"{label}.cluster_ids",
        ),
        regions=_normalize_text_list(
            raw_mapping.get("regions"),
            label=f"{label}.regions",
        ),
        families=_normalize_text_list(
            raw_mapping.get("families"),
            label=f"{label}.families",
        ),
        scales=_normalize_text_list(
            raw_mapping.get("scales"),
            label=f"{label}.scales",
        ),
        statuses=_normalize_text_list(
            raw_mapping.get("statuses"),
            label=f"{label}.statuses",
        ),
        maturity_levels=_normalize_text_list(
            raw_mapping.get("maturity_levels"),
            label=f"{label}.maturity_levels",
        ),
        tags=_normalize_text_list(
            raw_mapping.get("tags"),
            label=f"{label}.tags",
        ),
        limit=_validate_optional_int(
            raw_mapping.get("limit"),
            label=f"{label}.limit",
        ),
        include_disabled=bool(raw_mapping.get("include_disabled", include_disabled_default)),
    )

