# -*- coding: utf-8 -*-
"""Flow boundary-condition payload normalizers."""

from __future__ import annotations

from collections.abc import Mapping
from numbers import Real
from typing import cast

from hydromodpy.process.flow.boundary_conditions import (
    ALLOWED_BC_APPLICATION_DOMAINS,
    DIRICHLET_BC_CANONICAL_DOMAINS,
    DIRICHLET_BC_LEGACY_ALIASES,
    FlowBoundaryConditionConfig,
)


def normalize_flow_boundary_conditions(
    value: Mapping[str, object] | None,
    *,
    location_prefix: str = "flow.bc",
) -> dict[str, object]:
    """Normalize one `[flow.bc]` payload into canonical boundary-condition mappings."""
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{location_prefix} must be a mapping payload")
    return _parse_flow_bc_sections(dict(value))


def _coerce_numeric_boundary_value(*, value: object, location: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{location} must be a numeric value")
    return float(value)


def _normalize_boundary_units(
    payload: Mapping[str, object],
    *,
    default_units: str,
) -> str:
    if "units" in payload:
        return str(payload["units"])
    if "unit" in payload:
        return str(payload["unit"])
    return default_units


def _canonicalize_dirichlet_bc_id(
    *,
    raw_bc_id: str,
    location_prefix: str,
) -> str:
    bc_id = str(raw_bc_id).strip()
    if bc_id == "":
        raise ValueError(f"{location_prefix} cannot be empty")

    canonical_bc_id = DIRICHLET_BC_LEGACY_ALIASES.get(bc_id, bc_id)
    if canonical_bc_id in DIRICHLET_BC_CANONICAL_DOMAINS:
        return canonical_bc_id

    supported_keys = sorted(
        set(DIRICHLET_BC_CANONICAL_DOMAINS.keys()) | set(DIRICHLET_BC_LEGACY_ALIASES.keys())
    )
    supported_text = ", ".join(supported_keys)
    raise ValueError(
        f"{location_prefix} contains unsupported Dirichlet key '{bc_id}'. "
        f"Supported keys: {supported_text}"
    )


def _normalize_dirichlet_boundary_payload(
    *,
    bc_id: str,
    payload: Mapping[str, object],
    location_prefix: str,
) -> dict[str, object]:
    if "value" not in payload:
        raise ValueError(f"{location_prefix}.value is required")

    canonical_bc_id = _canonicalize_dirichlet_bc_id(
        raw_bc_id=bc_id,
        location_prefix=location_prefix,
    )

    value = _coerce_numeric_boundary_value(
        value=payload["value"],
        location=f"{location_prefix}.value",
    )

    raw_type = str(payload.get("type", "dirichlet")).strip().lower()
    if raw_type != "dirichlet":
        raise ValueError(f"{location_prefix}.type must be 'dirichlet'")

    inferred_application_domain = DIRICHLET_BC_CANONICAL_DOMAINS[canonical_bc_id]
    raw_application_domain = payload.get("application_domain")
    if raw_application_domain is None:
        application_domain = inferred_application_domain
    else:
        if not isinstance(raw_application_domain, str):
            raise TypeError(f"{location_prefix}.application_domain must be a string")
        application_domain = raw_application_domain.strip()
        if application_domain == "":
            raise ValueError(f"{location_prefix}.application_domain cannot be empty")
        if application_domain not in ALLOWED_BC_APPLICATION_DOMAINS:
            raise ValueError(
                f"{location_prefix}.application_domain contains an invalid value: {application_domain}"
            )
        if application_domain != inferred_application_domain:
            raise ValueError(
                f"{location_prefix}.application_domain='{application_domain}' "
                f"does not match inferred domain '{inferred_application_domain}' for key '{canonical_bc_id}'"
            )

    data_value = bool(payload.get("data_value", False))
    description = str(
        payload.get(
            "description",
            f"Dirichlet boundary condition '{canonical_bc_id}' on {application_domain}",
        )
    )
    if data_value and "(data_value=True)" not in description:
        description = f"{description} (data_value=True)"

    normalized_payload = {
        "id": canonical_bc_id,
        "value": value,
        "description": description,
        "units": _normalize_boundary_units(payload, default_units="m"),
        "type": "dirichlet",
        "data_value": data_value,
        "application_domain": application_domain,
    }
    return FlowBoundaryConditionConfig.model_validate(normalized_payload).model_dump(
        mode="python"
    )


def _normalize_drainage_boundary_payload(
    *,
    payload: Mapping[str, object],
    location_prefix: str,
    expected_type: str,
) -> dict[str, object]:
    if "value" not in payload:
        raise ValueError(f"{location_prefix}.value is required")

    value = _coerce_numeric_boundary_value(
        value=payload["value"],
        location=f"{location_prefix}.value",
    )

    raw_type = str(payload.get("type", expected_type)).strip().lower()
    if raw_type not in {"cauchy", "robin"}:
        raise ValueError(f"{location_prefix}.type must be 'cauchy' or 'robin'")

    raw_application_domain = payload.get("application_domain")
    if not isinstance(raw_application_domain, str):
        raise TypeError(f"{location_prefix}.application_domain must be a string")
    application_domain = raw_application_domain.strip()
    if application_domain == "":
        raise ValueError(f"{location_prefix}.application_domain cannot be empty")
    if application_domain not in ALLOWED_BC_APPLICATION_DOMAINS:
        raise ValueError(
            f"{location_prefix}.application_domain contains an invalid value: {application_domain}"
        )

    normalized_payload = {
        "id": "drainage",
        "value": value,
        "description": str(
            payload.get(
                "description",
                f"{raw_type.capitalize()} drainage boundary condition on {application_domain}",
            )
        ),
        "units": _normalize_boundary_units(payload, default_units="m2/s"),
        "type": raw_type,
        "data_value": bool(payload.get("data_value", False)),
        "application_domain": application_domain,
    }
    return FlowBoundaryConditionConfig.model_validate(normalized_payload).model_dump(
        mode="python"
    )


def _normalize_generic_boundary_payload(
    *,
    bc_id: str,
    payload: Mapping[str, object],
    location_prefix: str,
) -> dict[str, object]:
    if "value" not in payload:
        raise ValueError(f"{location_prefix}.value is required")

    value = _coerce_numeric_boundary_value(
        value=payload["value"],
        location=f"{location_prefix}.value",
    )
    bc_type = str(payload.get("type", "dirichlet")).strip().lower() or "dirichlet"
    if bc_type not in {"dirichlet", "cauchy", "robin"}:
        raise ValueError(f"{location_prefix}.type must be one of: dirichlet, cauchy, robin")

    default_units = "m2/s" if bc_type in {"cauchy", "robin"} else "m"
    normalized: dict[str, object] = {
        "id": bc_id,
        "value": value,
        "description": str(payload.get("description", f"Boundary condition '{bc_id}'")),
        "units": _normalize_boundary_units(payload, default_units=default_units),
        "type": bc_type,
        "data_value": bool(payload.get("data_value", False)),
    }

    raw_application_domain = payload.get("application_domain")
    if raw_application_domain is not None:
        if not isinstance(raw_application_domain, str):
            raise TypeError(f"{location_prefix}.application_domain must be a string")
        application_domain = raw_application_domain.strip()
        if application_domain == "":
            raise ValueError(f"{location_prefix}.application_domain cannot be empty")
        if application_domain not in ALLOWED_BC_APPLICATION_DOMAINS:
            raise ValueError(
                f"{location_prefix}.application_domain contains an invalid value: {application_domain}"
            )
        normalized["application_domain"] = application_domain

    return FlowBoundaryConditionConfig.model_validate(normalized).model_dump(mode="python")


def _parse_flow_bc_sections(bc_cfg: Mapping[str, object]) -> dict[str, object]:
    """Parse and normalize ``[flow.bc]`` entries into one flat mapping."""
    parsed: dict[str, dict[str, object]] = {}

    dirichlet_payload = bc_cfg.get("dirichlet")
    if dirichlet_payload is not None:
        if not isinstance(dirichlet_payload, Mapping):
            raise ValueError("flow.bc.dirichlet must be a mapping when provided")
        for raw_key, item in dirichlet_payload.items():
            key = str(raw_key).strip()
            if key == "":
                raise ValueError("flow.bc.dirichlet cannot contain empty keys")
            if item is None:
                continue
            if not isinstance(item, Mapping):
                raise ValueError(f"flow.bc.dirichlet.{key} must be a mapping")
            canonical_key = _canonicalize_dirichlet_bc_id(
                raw_bc_id=key,
                location_prefix=f"flow.bc.dirichlet.{key}",
            )
            if canonical_key in parsed:
                raise ValueError(
                    f"Duplicate Dirichlet entry for '{canonical_key}' in flow.bc.dirichlet"
                )
            parsed[canonical_key] = _normalize_dirichlet_boundary_payload(
                bc_id=canonical_key,
                payload=item,
                location_prefix=f"flow.bc.dirichlet.{key}",
            )

    cauchy_payload = bc_cfg.get("cauchy")
    if cauchy_payload is not None:
        if not isinstance(cauchy_payload, Mapping):
            raise ValueError("flow.bc.cauchy must be a mapping when provided")
        drainage_item = cauchy_payload.get("drainage")
        if drainage_item is not None:
            if not isinstance(drainage_item, Mapping):
                raise ValueError("flow.bc.cauchy.drainage must be a mapping")
            parsed["drainage"] = _normalize_drainage_boundary_payload(
                payload=drainage_item,
                location_prefix="flow.bc.cauchy.drainage",
                expected_type="cauchy",
            )

    robin_payload = bc_cfg.get("robin")
    if robin_payload is not None and "drainage" not in parsed:
        if not isinstance(robin_payload, Mapping):
            raise ValueError("flow.bc.robin must be a mapping when provided")
        drainage_item = robin_payload.get("drainage")
        if drainage_item is not None:
            if not isinstance(drainage_item, Mapping):
                raise ValueError("flow.bc.robin.drainage must be a mapping")
            parsed["drainage"] = _normalize_drainage_boundary_payload(
                payload=drainage_item,
                location_prefix="flow.bc.robin.drainage",
                expected_type="robin",
            )

    legacy_drainage = bc_cfg.get("drainage")
    if "drainage" not in parsed and isinstance(legacy_drainage, Mapping):
        parsed["drainage"] = _normalize_drainage_boundary_payload(
            payload=legacy_drainage,
            location_prefix="flow.bc.drainage",
            expected_type="cauchy",
        )

    for raw_key, raw_payload in bc_cfg.items():
        key = str(raw_key).strip()
        if key == "":
            raise ValueError("flow.bc cannot contain empty keys")
        if key in {"dirichlet", "cauchy", "robin", "drainage"}:
            continue
        if not isinstance(raw_payload, Mapping):
            raise TypeError(f"flow.bc.{key} must be a mapping payload")

        canonical_key = DIRICHLET_BC_LEGACY_ALIASES.get(key, key)
        if canonical_key in DIRICHLET_BC_CANONICAL_DOMAINS:
            if canonical_key in parsed:
                raise ValueError(f"Duplicate boundary condition entry for '{canonical_key}' in flow.bc")
            parsed[canonical_key] = _normalize_dirichlet_boundary_payload(
                bc_id=canonical_key,
                payload=raw_payload,
                location_prefix=f"flow.bc.{key}",
            )
        else:
            parsed[key] = _normalize_generic_boundary_payload(
                bc_id=key,
                payload=raw_payload,
                location_prefix=f"flow.bc.{key}",
            )

    return cast(dict[str, object], parsed)

