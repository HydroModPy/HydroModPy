"""Configuration contract for method testbeds.

A testbed is an orchestration layer over child runners. It does not own the
scientific implementation of meshing, flow, or transport. It expands variants,
delegates to a runner, and gathers evidence artifacts.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.analysis.catalog import SUPPORTED_CATALOG_FORMATS
from hydromodpy.analysis.config_helpers import (
    normalize_mapping,
    normalize_text_list,
    normalize_text_mapping,
    optional_text,
    require_mapping,
    require_text,
    resolve_optional_path,
    resolve_required_path,
    validate_optional_positive_int,
)
from hydromodpy.analysis.testbed.profiles import (
    GENERIC_TESTBED_PROFILE,
    resolve_testbed_profile,
)
from hydromodpy.core.toml_io import load_toml_with_base_config

SUPPORTED_RUNNERS = {"comparison", "simulation"}
SUPPORTED_SUBJECTS = {"flow", "mesh", "transport"}
SUPPORTED_SUBJECT_RUNNERS = {
    "flow": {"comparison", "simulation"},
    "mesh": {"simulation"},
    "transport": {"comparison", "simulation"},
}

def _resolve_output_root(*, base_dir: Path, raw_value: object, testbed_id: str) -> Path:
    path = resolve_optional_path(base_dir, raw_value)
    if path is not None:
        return path
    return (base_dir / "testbed" / testbed_id).resolve()


@dataclass(frozen=True)
class TestbedRunnerConfig:
    """Child-runner selection for one testbed."""

    type: str
    no_display: bool


@dataclass(frozen=True)
class TestbedVariantConfig:
    """One concrete testbed variant."""

    id: str
    label: str
    axis: str | None
    enabled: bool
    overlay: dict[str, Any]


@dataclass(frozen=True)
class TestbedMetricConfig:
    """One metric extracted from a child-runner summary."""

    name: str
    source: str
    required: bool


@dataclass(frozen=True)
class TestbedCatalogConfig:
    """Catalog source used to generate testbed variants."""

    path: Path
    format: str
    id_field: str
    label_field: str | None
    axis_field: str | None
    enabled_field: str | None
    tags_field: str | None
    required_fields: tuple[str, ...]
    path_fields: tuple[str, ...]
    tag_separator: str
    field_equals: tuple[tuple[str, str], ...]
    tags: tuple[str, ...]
    exclude_tags: tuple[str, ...]
    include_disabled: bool
    limit: int | None


@dataclass(frozen=True)
class TestbedCatalogVariantConfig:
    """One variant-generation rule applied to rows from a testbed catalog."""

    id_template: str | None
    label_template: str | None
    axis_template: str | None
    enabled: bool
    overlay: dict[str, Any]
    required_fields: tuple[str, ...]
    field_equals: tuple[tuple[str, str], ...]
    tags: tuple[str, ...]
    exclude_tags: tuple[str, ...]
    limit: int | None


@dataclass(frozen=True)
class TestbedConfig:
    """Validated configuration for one method testbed."""

    config_path: Path
    base_dir: Path
    id: str
    profile: str
    subject: str
    purpose: str
    output_root: Path
    execute: bool
    continue_on_error: bool
    base_config_path: Path | None
    runner: TestbedRunnerConfig
    variants: tuple[TestbedVariantConfig, ...]
    catalog: TestbedCatalogConfig | None
    catalog_variants: tuple[TestbedCatalogVariantConfig, ...]
    metrics: tuple[TestbedMetricConfig, ...]

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
        requested_runner_type = (
            optional_text(runner_section.get("type")) or "simulation"
        ).lower()
        if requested_runner_type not in SUPPORTED_RUNNERS:
            raise ValueError(
                f"Unsupported testbed.runner.type '{requested_runner_type}'. "
                f"Supported values: {', '.join(sorted(SUPPORTED_RUNNERS))}."
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
                "point to the delegated child workflow TOML. Use a simulation TOML for "
                "runner.type='simulation' or a comparison TOML for "
                "runner.type='comparison'. Keep the testbed declaration outside the "
                "child config."
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
            catalog = TestbedCatalogConfig(
                path=resolve_required_path(
                    base_dir,
                    catalog_mapping.get("path"),
                    label="testbed.catalog.path",
                ),
                format=catalog_format,
                id_field=require_text(
                    catalog_mapping.get("id_field", "variant_id"),
                    label="testbed.catalog.id_field",
                ),
                label_field=optional_text(
                    catalog_mapping.get("label_field", "variant_label")
                ),
                axis_field=optional_text(catalog_mapping.get("axis_field", "axis")),
                enabled_field=optional_text(
                    catalog_mapping.get("enabled_field", "enabled")
                ),
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
            )

        raw_variants = section.get("variant", section.get("variants", []))
        raw_catalog_variants = section.get(
            "variant_from_catalog",
            section.get("catalog_variant", []),
        )
        if raw_variants is None:
            raw_variants = []
        if raw_catalog_variants is None:
            raw_catalog_variants = []
        if not isinstance(raw_variants, list):
            raise ValueError("testbed.variant must be a list when provided")
        if not isinstance(raw_catalog_variants, list):
            raise ValueError("testbed.variant_from_catalog must be a list when provided")
        if not raw_variants and not raw_catalog_variants:
            raise ValueError(
                "testbed.variant or testbed.variant_from_catalog must contain at least one item"
            )
        if raw_catalog_variants and catalog is None:
            raise ValueError(
                "testbed.variant_from_catalog requires a [testbed.catalog] section"
            )

        variants: list[TestbedVariantConfig] = []
        seen_variant_ids: set[str] = set()
        for index, raw_variant in enumerate(raw_variants):
            variant_mapping = require_mapping(
                raw_variant,
                label=f"testbed.variant[{index}]",
            )
            variant_id = require_text(
                variant_mapping.get("id"),
                label=f"testbed.variant[{index}].id",
            )
            normalized_id = variant_id.lower()
            if normalized_id in seen_variant_ids:
                raise ValueError(f"Duplicate testbed.variant id '{variant_id}'")
            seen_variant_ids.add(normalized_id)
            variants.append(
                TestbedVariantConfig(
                    id=variant_id,
                    label=optional_text(variant_mapping.get("label")) or variant_id,
                    axis=optional_text(variant_mapping.get("axis")),
                    enabled=bool(variant_mapping.get("enabled", True)),
                    overlay=normalize_mapping(
                        variant_mapping.get("overlay"),
                        label=f"testbed.variant[{variant_id}].overlay",
                    ),
                )
            )

        catalog_variants: list[TestbedCatalogVariantConfig] = []
        for index, raw_catalog_variant in enumerate(raw_catalog_variants):
            catalog_variant_mapping = require_mapping(
                raw_catalog_variant,
                label=f"testbed.variant_from_catalog[{index}]",
            )
            catalog_variants.append(
                TestbedCatalogVariantConfig(
                    id_template=optional_text(catalog_variant_mapping.get("id_template")),
                    label_template=optional_text(
                        catalog_variant_mapping.get("label_template")
                    ),
                    axis_template=optional_text(
                        catalog_variant_mapping.get("axis_template")
                    ),
                    enabled=bool(catalog_variant_mapping.get("enabled", True)),
                    overlay=normalize_mapping(
                        catalog_variant_mapping.get("overlay"),
                        label=f"testbed.variant_from_catalog[{index}].overlay",
                    ),
                    required_fields=normalize_text_list(
                        catalog_variant_mapping.get("required_fields"),
                        label=f"testbed.variant_from_catalog[{index}].required_fields",
                    ),
                    field_equals=normalize_text_mapping(
                        catalog_variant_mapping.get("field_equals"),
                        label=f"testbed.variant_from_catalog[{index}].field_equals",
                    ),
                    tags=normalize_text_list(
                        catalog_variant_mapping.get("tags"),
                        label=f"testbed.variant_from_catalog[{index}].tags",
                    ),
                    exclude_tags=normalize_text_list(
                        catalog_variant_mapping.get("exclude_tags"),
                        label=f"testbed.variant_from_catalog[{index}].exclude_tags",
                    ),
                    limit=validate_optional_positive_int(
                        catalog_variant_mapping.get("limit"),
                        label=f"testbed.variant_from_catalog[{index}].limit",
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
