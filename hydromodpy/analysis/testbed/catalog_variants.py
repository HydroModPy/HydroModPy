"""Catalog-backed case expansion for method testbeds."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from hydromodpy.analysis.catalog import (
    CatalogLoadSpec,
    CatalogRow,
    CatalogRowSelector,
    load_catalog_rows,
    normalize_required_field_names,
    normalize_text,
    select_catalog_rows,
)
from hydromodpy.analysis.testbed.config import (
    TestbedCaseConfig,
    TestbedCatalogCaseConfig,
    TestbedCatalogConfig,
)

_SINGLE_FIELD_TEMPLATE = re.compile(r"^\{([^{}]+)\}$")
_INTEGER_TEMPLATE = re.compile(r"^[+-]?\d+$")
_FLOAT_TEMPLATE = re.compile(
    r"^[+-]?(?:(?:\d+\.\d*)|(?:\d*\.\d+))(?:[eE][+-]?\d+)?$|^[+-]?\d+[eE][+-]?\d+$"
)


def _coerce_catalog_scalar(value: Any) -> Any:
    """Preserve useful TOML scalar types when a template is one catalog field."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    lowered = text.lower()
    if lowered in {"true", "yes", "y", "on"}:
        return True
    if lowered in {"false", "no", "n", "off"}:
        return False
    if _INTEGER_TEMPLATE.fullmatch(text):
        return int(text)
    if _FLOAT_TEMPLATE.fullmatch(text):
        return float(text)
    return value


def _catalog_selector(catalog: TestbedCatalogConfig) -> CatalogRowSelector:
    return CatalogRowSelector(
        field_equals=catalog.field_equals,
        tags=catalog.tags,
        exclude_tags=catalog.exclude_tags,
        enabled_field=catalog.enabled_field,
        include_disabled=catalog.include_disabled,
        limit=catalog.limit,
    )


def _template_selector(rule: TestbedCatalogCaseConfig) -> CatalogRowSelector:
    return CatalogRowSelector(
        field_equals=rule.field_equals,
        tags=rule.tags,
        exclude_tags=rule.exclude_tags,
        include_disabled=True,
        limit=rule.limit,
    )


def _format_template(template: str, context: Mapping[str, Any], *, label: str) -> str:
    try:
        return template.format_map(context)
    except KeyError as exc:
        missing_key = str(exc).strip("'")
        raise ValueError(f"{label} references unknown catalog field '{missing_key}'") from exc


def _render_template_value(value: Any, context: Mapping[str, Any], *, label: str) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _render_template_value(
                child_value,
                context,
                label=f"{label}.{key}",
            )
            for key, child_value in value.items()
        }
    if isinstance(value, list):
        return [_render_template_value(item, context, label=f"{label}[]") for item in value]
    if not isinstance(value, str):
        return value

    single_match = _SINGLE_FIELD_TEMPLATE.fullmatch(value)
    if single_match:
        field_name = single_match.group(1)
        if field_name not in context:
            raise ValueError(f"{label} references unknown catalog field '{field_name}'")
        return _coerce_catalog_scalar(context[field_name])
    return _format_template(value, context, label=label)


def _catalog_field_value(
    row: CatalogRow,
    *,
    field_name: str | None,
    fallback_field_name: str | None = None,
) -> str | None:
    if field_name is None:
        return None
    value = normalize_text(row.raw.get(field_name))
    if value is None and fallback_field_name is not None:
        return normalize_text(row.raw.get(fallback_field_name))
    return value


def _case_from_row(
    row: CatalogRow,
    *,
    catalog: TestbedCatalogConfig,
    rule: TestbedCatalogCaseConfig,
) -> TestbedCaseConfig:
    context = row.build_template_context(tag_separator=catalog.tag_separator)
    missing_fields = normalize_required_field_names(
        context,
        field_names=rule.required_fields,
    )
    if missing_fields:
        raise ValueError(
            "testbed.case_from_catalog row is missing required field(s): "
            + ", ".join(missing_fields)
        )

    if rule.id_template is not None:
        case_id = _format_template(
            rule.id_template,
            context,
            label="testbed.case_from_catalog.id_template",
        )
    else:
        case_id = _catalog_field_value(
            row,
            field_name=catalog.id_field,
            fallback_field_name="variant_id" if catalog.id_field == "case_id" else None,
        )
    if case_id is None:
        raise ValueError(
            "testbed catalog row is missing the configured case identifier field "
            f"'{catalog.id_field}'"
        )

    if rule.label_template is not None:
        label = _format_template(
            rule.label_template,
            context,
            label=f"testbed.case_from_catalog[{case_id}].label_template",
        )
    else:
        label = (
            _catalog_field_value(
                row,
                field_name=catalog.label_field,
                fallback_field_name=(
                    "variant_label" if catalog.label_field == "case_label" else None
                ),
            )
            or case_id
        )

    if rule.axis_template is not None:
        axis = _format_template(
            rule.axis_template,
            context,
            label=f"testbed.case_from_catalog[{case_id}].axis_template",
        )
    else:
        axis = _catalog_field_value(row, field_name=catalog.axis_field)

    overlay = _render_template_value(
        rule.overlay,
        context,
        label=f"testbed.case_from_catalog[{case_id}].overlay",
    )
    if not isinstance(overlay, dict):
        raise ValueError(f"testbed.case_from_catalog[{case_id}].overlay must render to a mapping")
    return TestbedCaseConfig(
        id=case_id,
        label=label,
        axis=axis,
        enabled=True,
        overlay=overlay,
    )


def expand_catalog_cases(
    *,
    catalog: TestbedCatalogConfig | None,
    rules: Sequence[TestbedCatalogCaseConfig],
) -> tuple[TestbedCaseConfig, ...]:
    """Expand configured catalog rows into concrete testbed cases."""
    if catalog is None or not rules:
        return ()

    tag_fields = () if catalog.tags_field is None else (catalog.tags_field,)
    rows = load_catalog_rows(
        CatalogLoadSpec(
            path=catalog.path,
            format=catalog.format,
            required_fields=catalog.required_fields,
            path_fields=catalog.path_fields,
            tag_fields=tag_fields,
            tag_separator=catalog.tag_separator,
            allow_empty=True,
            source_label="testbed catalog",
        )
    )
    rows = select_catalog_rows(rows, selector=_catalog_selector(catalog))

    cases: list[TestbedCaseConfig] = []
    for rule in rules:
        if not rule.enabled:
            continue
        for row in select_catalog_rows(rows, selector=_template_selector(rule)):
            cases.append(_case_from_row(row, catalog=catalog, rule=rule))
    return tuple(cases)


expand_catalog_variants = expand_catalog_cases
