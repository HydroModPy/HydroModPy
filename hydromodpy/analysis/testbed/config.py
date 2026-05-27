"""Configuration contract for method testbeds.

A testbed is an orchestration layer over child runners. It does not own the
scientific implementation of meshing, flow, or transport. It expands cases,
delegates to a runner, and gathers evidence artifacts.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from hydromodpy.analysis.catalog import SUPPORTED_CATALOG_FORMATS
from hydromodpy.analysis.config_helpers import (
    normalize_mapping,
    normalize_text_list,
    normalize_text_mapping,
    optional_text,
    require_mapping,
    require_text,
    resolve_optional_path,
    validate_optional_positive_int,
)
from hydromodpy.analysis.testbed.contracts import available_testbed_runner_types
from hydromodpy.analysis.testbed.profiles import (
    GENERIC_TESTBED_PROFILE,
    resolve_testbed_profile,
)
from hydromodpy.analysis.testbed.site_selection_catalog import resolve_catalog_source
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.toml_io import load_toml_with_base_config

SUPPORTED_RUNNERS = {"calibration", "comparison", "simulation"}
SUPPORTED_SUBJECTS = {"flow", "mesh", "transport"}
SUPPORTED_SUBJECT_RUNNERS = {
    "flow": {"calibration", "comparison", "simulation"},
    "mesh": {"simulation"},
    "transport": {"comparison", "simulation"},
}


def _resolve_output_root(*, base_dir: Path, raw_value: object, testbed_id: str) -> Path:
    path = resolve_optional_path(base_dir, raw_value)
    if path is not None:
        return path
    return (base_dir / "testbed" / testbed_id).resolve()


class TestbedRunnerConfig(HydroModelBase):
    """Child-runner selection for one testbed."""

    type: Annotated[str, Profile.USER] = Field(
        description="Runner identifier dispatched for every variant (comparison, simulation)."
    )
    no_display: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Disable interactive display in child runners.",
    )


class TestbedVariantConfig(HydroModelBase):
    """One concrete executable testbed case."""

    id: Annotated[str, Profile.USER] = Field(description="Stable case identifier.")
    label: Annotated[str, Profile.USER] = Field(description="Human-readable case label.")
    axis: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Optional axis tag used to group cases in reports.",
    )
    enabled: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Toggle to skip a case without removing it from the config.",
    )
    overlay: Annotated[dict[str, Any], Profile.USER] = Field(
        default_factory=dict,
        description="TOML overlay merged into the child-runner base config.",
    )


class TestbedMetricConfig(HydroModelBase):
    """One metric extracted from a child-runner summary."""

    name: Annotated[str, Profile.USER] = Field(description="Metric column name.")
    source: Annotated[str, Profile.USER] = Field(
        description="Dotted path into the child-runner summary."
    )
    required: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="When true, a missing metric fails the variant.",
    )


class TestbedCatalogConfig(HydroModelBase):
    """Catalog source used to generate testbed cases."""

    path: Annotated[Path, Profile.USER] = Field(
        description="Resolved path to the case catalog (CSV or JSONL)."
    )
    format: Annotated[str, Profile.USER] = Field(
        default="auto",
        description="Catalog format. 'auto' infers from the file suffix.",
    )
    id_field: Annotated[str, Profile.USER] = Field(
        default="variant_id",
        description="Column carrying the variant identifier.",
    )
    label_field: Annotated[str | None, Profile.USER] = Field(
        default="variant_label",
        description="Column carrying a human-readable variant label.",
    )
    axis_field: Annotated[str | None, Profile.USER] = Field(
        default="axis",
        description="Column carrying the optional axis tag.",
    )
    enabled_field: Annotated[str | None, Profile.USER] = Field(
        default="enabled",
        description="Column flagging whether a row is active.",
    )
    tags_field: Annotated[str | None, Profile.USER] = Field(
        default="tags",
        description="Column carrying free-form tags joined by tag_separator.",
    )
    required_fields: Annotated[tuple[str, ...], Profile.USER] = Field(
        default=(),
        description="Columns that must be present and non-empty per row.",
    )
    path_fields: Annotated[tuple[str, ...], Profile.USER] = Field(
        default=(),
        description="Columns whose values are resolved as filesystem paths.",
    )
    tag_separator: Annotated[str, Profile.USER] = Field(
        default=";",
        description="Separator splitting the tags column into individual tags.",
    )
    field_equals: Annotated[tuple[tuple[str, str], ...], Profile.USER] = Field(
        default=(),
        description="Per-field equality filters applied during catalog selection.",
    )
    tags: Annotated[tuple[str, ...], Profile.USER] = Field(
        default=(),
        description="Whitelist of tags. Empty disables the filter.",
    )
    exclude_tags: Annotated[tuple[str, ...], Profile.USER] = Field(
        default=(),
        description="Blacklist of tags applied after the whitelist.",
    )
    include_disabled: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="When true, rows flagged as disabled are kept.",
    )
    limit: Annotated[int | None, Profile.USER] = Field(
        default=None,
        description="Optional cap on the number of selected rows.",
    )
    source_manifest_path: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description="Optional site-selection manifest used to resolve the catalog path.",
    )
    source_manifest_output_key: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Output key read from the site-selection manifest.",
    )


class TestbedCatalogVariantConfig(HydroModelBase):
    """One case-generation rule applied to rows from a testbed catalog."""

    id_template: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Format string evaluated against catalog row fields to derive the case id.",
    )
    label_template: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Format string used to derive the case label.",
    )
    axis_template: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Format string used to derive the optional axis tag.",
    )
    enabled: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Toggle to skip the rule without removing it from the config.",
    )
    overlay: Annotated[dict[str, Any], Profile.USER] = Field(
        default_factory=dict,
        description="TOML overlay rendered against each catalog row.",
    )
    required_fields: Annotated[tuple[str, ...], Profile.USER] = Field(
        default=(),
        description="Catalog columns that must be present and non-empty per row.",
    )
    field_equals: Annotated[tuple[tuple[str, str], ...], Profile.USER] = Field(
        default=(),
        description="Per-field equality filters applied while expanding rows.",
    )
    tags: Annotated[tuple[str, ...], Profile.USER] = Field(
        default=(),
        description="Whitelist of tags applied during rule expansion.",
    )
    exclude_tags: Annotated[tuple[str, ...], Profile.USER] = Field(
        default=(),
        description="Blacklist of tags applied during rule expansion.",
    )
    limit: Annotated[int | None, Profile.USER] = Field(
        default=None,
        description="Optional cap on the number of cases generated by the rule.",
    )


TestbedCaseConfig = TestbedVariantConfig
TestbedCatalogCaseConfig = TestbedCatalogVariantConfig


def _select_case_items(
    section: Mapping[str, Any],
    *,
    canonical_key: str,
    legacy_key: str,
) -> tuple[Any, str]:
    canonical_value = section.get(canonical_key)
    legacy_value = section.get(legacy_key)
    canonical_label = f"testbed.{canonical_key}"
    legacy_label = f"testbed.{legacy_key}"
    if canonical_value is not None and legacy_value is not None:
        raise ValueError(
            f"Use only {canonical_label}; {legacy_label} is a legacy spelling and "
            "cannot be combined with the canonical case spelling."
        )
    if canonical_value is not None:
        return canonical_value, canonical_label
    return legacy_value, legacy_label


class TestbedConfig(HydroModelBase):
    """Validated configuration for one method testbed."""

    config_path: Annotated[Path, Profile.USER] = Field(
        description="Resolved path of the TOML file that produced this config."
    )
    base_dir: Annotated[Path, Profile.USER] = Field(
        description="Directory used to resolve relative paths."
    )
    id: Annotated[str, Profile.USER] = Field(description="Stable testbed identifier.")
    profile: Annotated[str, Profile.USER] = Field(description="Selected testbed profile.")
    subject: Annotated[str, Profile.USER] = Field(
        description="High-level subject covered by the testbed (flow, mesh, transport)."
    )
    purpose: Annotated[str, Profile.USER] = Field(
        description="Stated purpose of the testbed (robustness, sensitivity, ...)."
    )
    output_root: Annotated[Path, Profile.USER] = Field(
        description="Directory where testbed artifacts are written."
    )
    execute: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="When false, child configs are materialized but not executed.",
    )
    continue_on_error: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="When false, the first failure aborts the testbed.",
    )
    base_config_path: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description="Optional child workflow TOML used as the variant base config.",
    )
    runner: Annotated[TestbedRunnerConfig, Profile.USER] = Field(
        description="Child-runner selection for every variant."
    )
    variants: Annotated[tuple[TestbedVariantConfig, ...], Profile.USER] = Field(
        default=(),
        description="Explicit variants declared in the TOML.",
    )
    catalog: Annotated[TestbedCatalogConfig | None, Profile.USER] = Field(
        default=None,
        description="Optional catalog source used to expand variants from rows.",
    )
    catalog_variants: Annotated[tuple[TestbedCatalogVariantConfig, ...], Profile.USER] = Field(
        default=(),
        description="Variant-generation rules applied to catalog rows.",
    )
    metrics: Annotated[tuple[TestbedMetricConfig, ...], Profile.USER] = Field(
        default=(),
        description="Metrics extracted from each child-runner summary.",
    )

    @property
    def cases(self) -> tuple[TestbedVariantConfig, ...]:
        """Canonical public alias for explicit executable cases."""
        return self.variants

    @property
    def catalog_cases(self) -> tuple[TestbedCatalogVariantConfig, ...]:
        """Canonical public alias for catalog-backed case generation rules."""
        return self.catalog_variants

    @classmethod
    def from_toml(
        cls,
        raw_toml: Mapping[str, Any],
        *,
        config_path: str | Path,
    ) -> TestbedConfig:
        """Validate one raw TOML payload."""
        if not isinstance(raw_toml, Mapping):
            raise ValueError("configuration must be a mapping")
        section = require_mapping(raw_toml.get("testbed"), label="testbed")
        profile = resolve_testbed_profile(raw_toml)
        if profile != GENERIC_TESTBED_PROFILE:
            raise ValueError(
                f"testbed.profile='{profile}' is handled by the testbed profile "
                "dispatcher, not by the generic TestbedConfig parser."
            )

        resolved_config_path = Path(config_path).expanduser().resolve()
        base_dir = resolved_config_path.parent
        testbed_id = (
            optional_text(section.get("id"))
            or optional_text(section.get("testbed_id"))
            or resolved_config_path.stem
        )
        subject = (optional_text(section.get("subject")) or "mesh").lower()
        if subject not in SUPPORTED_SUBJECTS:
            raise ValueError(
                f"Unsupported testbed.subject '{subject}'. "
                f"Supported values: {', '.join(sorted(SUPPORTED_SUBJECTS))}."
            )

        runner_section = normalize_mapping(section.get("runner"), label="testbed.runner")
        requested_runner_type = (optional_text(runner_section.get("type")) or "simulation").lower()
        available_runner_types = set(available_testbed_runner_types())
        if requested_runner_type not in available_runner_types:
            raise ValueError(
                f"Unsupported testbed.runner.type '{requested_runner_type}'. "
                f"Supported values: {', '.join(sorted(available_runner_types))}."
            )
        runner_type = requested_runner_type
        supported_subject_runners = SUPPORTED_SUBJECT_RUNNERS[subject]
        if runner_type not in supported_subject_runners:
            raise ValueError(
                f"testbed.subject='{subject}' requires runner.type to be one of "
                f"{', '.join(sorted(supported_subject_runners))}."
            )
        if subject in {"flow", "transport"} and optional_text(section.get("base_config")) is None:
            raise ValueError(
                f"testbed.runner.type='{runner_type}' requires testbed.base_config to "
                "point to the delegated child workflow TOML. Keep the testbed "
                "declaration outside the child config."
            )

        raw_catalog = section.get("catalog")
        catalog: TestbedCatalogConfig | None = None
        if raw_catalog is not None:
            catalog_mapping = require_mapping(raw_catalog, label="testbed.catalog")
            catalog_format = (optional_text(catalog_mapping.get("format")) or "auto").lower()
            if catalog_format not in SUPPORTED_CATALOG_FORMATS:
                raise ValueError("testbed.catalog.format must be one of: auto, csv, jsonl")
            tag_separator = optional_text(catalog_mapping.get("tag_separator")) or ";"
            if tag_separator == "":
                raise ValueError("testbed.catalog.tag_separator cannot be empty")
            catalog_source = resolve_catalog_source(
                base_dir=base_dir,
                mapping=catalog_mapping,
                catalog_label="testbed.catalog",
            )
            catalog = TestbedCatalogConfig(
                path=catalog_source.path,
                format=catalog_format,
                id_field=require_text(
                    catalog_mapping.get("id_field", "variant_id"),
                    label="testbed.catalog.id_field",
                ),
                label_field=optional_text(catalog_mapping.get("label_field", "variant_label")),
                axis_field=optional_text(catalog_mapping.get("axis_field", "axis")),
                enabled_field=optional_text(catalog_mapping.get("enabled_field", "enabled")),
                tags_field=optional_text(catalog_mapping.get("tags_field", "tags")),
                required_fields=normalize_text_list(
                    catalog_mapping.get("required_fields"),
                    label="testbed.catalog.required_fields",
                ),
                path_fields=normalize_text_list(
                    catalog_mapping.get("path_fields"),
                    label="testbed.catalog.path_fields",
                ),
                tag_separator=tag_separator,
                field_equals=normalize_text_mapping(
                    catalog_mapping.get("field_equals"),
                    label="testbed.catalog.field_equals",
                ),
                tags=normalize_text_list(
                    catalog_mapping.get("tags"),
                    label="testbed.catalog.tags",
                ),
                exclude_tags=normalize_text_list(
                    catalog_mapping.get("exclude_tags"),
                    label="testbed.catalog.exclude_tags",
                ),
                include_disabled=bool(catalog_mapping.get("include_disabled", False)),
                limit=validate_optional_positive_int(
                    catalog_mapping.get("limit"),
                    label="testbed.catalog.limit",
                ),
                source_manifest_path=catalog_source.source_manifest_path,
                source_manifest_output_key=catalog_source.source_manifest_output_key,
            )

        raw_variants, variant_label = _select_case_items(
            section,
            canonical_key="case",
            legacy_key="variant",
        )
        raw_catalog_variants, catalog_variant_label = _select_case_items(
            section,
            canonical_key="case_from_catalog",
            legacy_key="variant_from_catalog",
        )
        if raw_variants is None:
            raw_variants = []
        if raw_catalog_variants is None:
            raw_catalog_variants = []
        if not isinstance(raw_variants, list):
            raise ValueError(f"{variant_label} must be a list when provided")
        if not isinstance(raw_catalog_variants, list):
            raise ValueError(f"{catalog_variant_label} must be a list when provided")
        if not raw_variants and not raw_catalog_variants:
            raise ValueError(
                "testbed.case or testbed.case_from_catalog must contain at least one item"
            )
        if raw_catalog_variants and catalog is None:
            raise ValueError(f"{catalog_variant_label} requires a [testbed.catalog] section")

        variants: list[TestbedVariantConfig] = []
        seen_variant_ids: set[str] = set()
        for index, raw_variant in enumerate(raw_variants):
            variant_mapping = require_mapping(
                raw_variant,
                label=f"{variant_label}[{index}]",
            )
            variant_id = require_text(
                variant_mapping.get("id"),
                label=f"{variant_label}[{index}].id",
            )
            normalized_id = variant_id.lower()
            if normalized_id in seen_variant_ids:
                raise ValueError(f"Duplicate testbed.case id '{variant_id}'")
            seen_variant_ids.add(normalized_id)
            variants.append(
                TestbedVariantConfig(
                    id=variant_id,
                    label=optional_text(variant_mapping.get("label")) or variant_id,
                    axis=optional_text(variant_mapping.get("axis")),
                    enabled=bool(variant_mapping.get("enabled", True)),
                    overlay=normalize_mapping(
                        variant_mapping.get("overlay"),
                        label=f"{variant_label}[{variant_id}].overlay",
                    ),
                )
            )

        catalog_variants: list[TestbedCatalogVariantConfig] = []
        for index, raw_catalog_variant in enumerate(raw_catalog_variants):
            catalog_variant_mapping = require_mapping(
                raw_catalog_variant,
                label=f"{catalog_variant_label}[{index}]",
            )
            catalog_variants.append(
                TestbedCatalogVariantConfig(
                    id_template=optional_text(catalog_variant_mapping.get("id_template")),
                    label_template=optional_text(catalog_variant_mapping.get("label_template")),
                    axis_template=optional_text(catalog_variant_mapping.get("axis_template")),
                    enabled=bool(catalog_variant_mapping.get("enabled", True)),
                    overlay=normalize_mapping(
                        catalog_variant_mapping.get("overlay"),
                        label=f"{catalog_variant_label}[{index}].overlay",
                    ),
                    required_fields=normalize_text_list(
                        catalog_variant_mapping.get("required_fields"),
                        label=f"{catalog_variant_label}[{index}].required_fields",
                    ),
                    field_equals=normalize_text_mapping(
                        catalog_variant_mapping.get("field_equals"),
                        label=f"{catalog_variant_label}[{index}].field_equals",
                    ),
                    tags=normalize_text_list(
                        catalog_variant_mapping.get("tags"),
                        label=f"{catalog_variant_label}[{index}].tags",
                    ),
                    exclude_tags=normalize_text_list(
                        catalog_variant_mapping.get("exclude_tags"),
                        label=f"{catalog_variant_label}[{index}].exclude_tags",
                    ),
                    limit=validate_optional_positive_int(
                        catalog_variant_mapping.get("limit"),
                        label=f"{catalog_variant_label}[{index}].limit",
                    ),
                )
            )

        raw_metrics = section.get("metric", section.get("metrics", []))
        if raw_metrics is None:
            raw_metrics = []
        if not isinstance(raw_metrics, list):
            raise ValueError("testbed.metric must be a list when provided")
        metrics: list[TestbedMetricConfig] = []
        seen_metric_names: set[str] = set()
        for index, raw_metric in enumerate(raw_metrics):
            metric_mapping = require_mapping(raw_metric, label=f"testbed.metric[{index}]")
            metric_name = require_text(
                metric_mapping.get("name"),
                label=f"testbed.metric[{index}].name",
            )
            normalized_metric = metric_name.lower()
            if normalized_metric in seen_metric_names:
                raise ValueError(f"Duplicate testbed.metric name '{metric_name}'")
            seen_metric_names.add(normalized_metric)
            metrics.append(
                TestbedMetricConfig(
                    name=metric_name,
                    source=optional_text(metric_mapping.get("source")) or metric_name,
                    required=bool(metric_mapping.get("required", False)),
                )
            )

        return cls(
            config_path=resolved_config_path,
            base_dir=base_dir,
            id=testbed_id,
            profile=profile,
            subject=subject,
            purpose=optional_text(section.get("purpose")) or "robustness",
            output_root=_resolve_output_root(
                base_dir=base_dir,
                raw_value=section.get("output_root"),
                testbed_id=testbed_id,
            ),
            execute=bool(section.get("execute", True)),
            continue_on_error=bool(section.get("continue_on_error", True)),
            base_config_path=resolve_optional_path(base_dir, section.get("base_config")),
            runner=TestbedRunnerConfig(
                type=runner_type,
                no_display=bool(runner_section.get("no_display", True)),
            ),
            variants=tuple(variants),
            catalog=catalog,
            catalog_variants=tuple(catalog_variants),
            metrics=tuple(metrics),
        )

    @classmethod
    def from_file(cls, config_path: str | Path) -> TestbedConfig:
        """Load and validate one testbed TOML."""
        resolved_config_path = Path(config_path).expanduser().resolve()
        payload = load_toml_with_base_config(resolved_config_path)
        return cls.from_toml(payload, config_path=resolved_config_path)
