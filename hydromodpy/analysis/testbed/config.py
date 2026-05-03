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

from hydromodpy.core.config.toml_loader import load_toml_with_base_config

SUPPORTED_RUNNERS = {"mesh_catchment", "simulation"}
SUPPORTED_SUBJECTS = {"flow", "mesh"}
SUPPORTED_SUBJECT_RUNNERS = {
    "flow": {"simulation"},
    "mesh": {"mesh_catchment"},
}


def _require_mapping(value: object, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return value


def _require_text(value: object, *, label: str) -> str:
    text = "" if value is None else str(value).strip()
    if text == "":
        raise ValueError(f"{label} cannot be empty")
    return text


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _resolve_optional_path(base_dir: Path, raw_path: object) -> Path | None:
    text = _optional_text(raw_path)
    if text is None:
        return None
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _resolve_output_root(*, base_dir: Path, raw_value: object, testbed_id: str) -> Path:
    path = _resolve_optional_path(base_dir, raw_value)
    if path is not None:
        return path
    return (base_dir / "testbed" / testbed_id).resolve()


def _normalize_mapping(value: object, *, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return dict(value)


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
class TestbedConfig:
    """Validated configuration for one method testbed."""

    config_path: Path
    base_dir: Path
    id: str
    subject: str
    purpose: str
    output_root: Path
    execute: bool
    continue_on_error: bool
    base_config_path: Path | None
    runner: TestbedRunnerConfig
    variants: tuple[TestbedVariantConfig, ...]
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
        section = _require_mapping(raw_toml.get("testbed"), label="testbed")

        resolved_config_path = Path(config_path).expanduser().resolve()
        base_dir = resolved_config_path.parent
        testbed_id = (
            _optional_text(section.get("id"))
            or _optional_text(section.get("testbed_id"))
            or resolved_config_path.stem
        )
        subject = (_optional_text(section.get("subject")) or "mesh").lower()
        if subject not in SUPPORTED_SUBJECTS:
            raise ValueError(
                f"Unsupported testbed.subject '{subject}'. "
                f"Supported values: {', '.join(sorted(SUPPORTED_SUBJECTS))}."
            )

        runner_section = _normalize_mapping(section.get("runner"), label="testbed.runner")
        runner_type = (_optional_text(runner_section.get("type")) or "mesh_catchment").lower()
        if runner_type not in SUPPORTED_RUNNERS:
            raise ValueError(
                f"Unsupported testbed.runner.type '{runner_type}'. "
                f"Supported values: {', '.join(sorted(SUPPORTED_RUNNERS))}."
            )
        supported_subject_runners = SUPPORTED_SUBJECT_RUNNERS[subject]
        if runner_type not in supported_subject_runners:
            raise ValueError(
                f"testbed.subject='{subject}' requires runner.type to be one of "
                f"{', '.join(sorted(supported_subject_runners))}."
            )
        if subject == "flow" and _optional_text(section.get("base_config")) is None:
            raise ValueError(
                "testbed.subject='flow' requires testbed.base_config to point to a "
                "simulation TOML. Keep the testbed declaration outside the child "
                "simulation config."
            )

        raw_variants = section.get("variant", section.get("variants", []))
        if not isinstance(raw_variants, list) or not raw_variants:
            raise ValueError("testbed.variant must contain at least one item")

        variants: list[TestbedVariantConfig] = []
        seen_variant_ids: set[str] = set()
        for index, raw_variant in enumerate(raw_variants):
            variant_mapping = _require_mapping(
                raw_variant,
                label=f"testbed.variant[{index}]",
            )
            variant_id = _require_text(
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
                    label=_optional_text(variant_mapping.get("label")) or variant_id,
                    axis=_optional_text(variant_mapping.get("axis")),
                    enabled=bool(variant_mapping.get("enabled", True)),
                    overlay=_normalize_mapping(
                        variant_mapping.get("overlay"),
                        label=f"testbed.variant[{variant_id}].overlay",
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
            metric_mapping = _require_mapping(raw_metric, label=f"testbed.metric[{index}]")
            metric_name = _require_text(
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
                    source=_optional_text(metric_mapping.get("source")) or metric_name,
                    required=bool(metric_mapping.get("required", False)),
                )
            )

        return cls(
            config_path=resolved_config_path,
            base_dir=base_dir,
            id=testbed_id,
            subject=subject,
            purpose=_optional_text(section.get("purpose")) or "robustness",
            output_root=_resolve_output_root(
                base_dir=base_dir,
                raw_value=section.get("output_root"),
                testbed_id=testbed_id,
            ),
            execute=bool(section.get("execute", True)),
            continue_on_error=bool(section.get("continue_on_error", True)),
            base_config_path=_resolve_optional_path(base_dir, section.get("base_config")),
            runner=TestbedRunnerConfig(
                type=runner_type,
                no_display=bool(runner_section.get("no_display", True)),
            ),
            variants=tuple(variants),
            metrics=tuple(metrics),
        )

    @classmethod
    def from_file(cls, config_path: str | Path) -> TestbedConfig:
        """Load and validate one testbed TOML."""
        resolved_config_path = Path(config_path).expanduser().resolve()
        payload = load_toml_with_base_config(resolved_config_path)
        return cls.from_toml(payload, config_path=resolved_config_path)
