"""
Flow Boundary Condition Normalizers
==================================

Normalization and canonicalization helpers for `[flow.bc]` payloads.

Responsibilities:
- normalize accepted TOML shapes into one flat BC mapping,
- enforce domain/type/value consistency rules,
- support canonical keys only.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from hydromodpy.core.units import (
    canonical_unit_short_form,
    parse_to_canonical_magnitude,
)
from hydromodpy.physics.flow.boundary_conditions import (
    ALLOWED_BC_APPLICATION_DOMAINS,
    DIRICHLET_BC_CANONICAL_DOMAINS,
    SIDE_DIRICHLET_BC_IDS,
    FlowBoundaryConditionConfig,
    FlowBoundaryForcingConfig,
)


def normalize_flow_boundary_conditions(
    value: Mapping[str, object] | None,
    *,
    location_prefix: str = "flow.bc",
) -> dict[str, object]:
    """
    Normalize one `[flow.bc]` payload into canonical boundary-condition mappings.

    Returns a flat dictionary keyed by normalized BC ids.
    """
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{location_prefix} must be a mapping payload")
    return _parse_flow_bc_sections(dict(value))


def _extract_explicit_boundary_units(payload: Mapping[str, object]) -> str | None:
    """Resolve explicitly declared units from payload (`units` > `unit`)."""
    if "units" in payload:
        return str(payload["units"])
    if "unit" in payload:
        return str(payload["unit"])
    return None


_BOUNDARY_UNIT_TARGETS: dict[str, tuple[str, str]] = {
    # default_units label -> (pint canonical target, error label)
    "m": ("m", "length"),
    "m2/s": ("m**2/s", "hydraulic-conductance"),
}


def _coerce_boundary_value_and_units(
    *,
    payload: Mapping[str, object],
    location_prefix: str,
    default_units: str,
) -> tuple[float, str]:
    if "value" not in payload:
        raise ValueError(f"{location_prefix}.value is required")
    target = _BOUNDARY_UNIT_TARGETS.get(default_units)
    if target is None:
        raise ValueError(f"Unsupported boundary unit target: {default_units}")
    canonical_unit, label = target
    value_si = parse_to_canonical_magnitude(
        payload["value"],
        location=f"{location_prefix}.value",
        canonical_unit=canonical_unit,
        explicit_unit=_extract_explicit_boundary_units(payload),
        length_label=label,
    )
    return value_si, default_units


def _normalize_dirichlet_forcing_units(
    *,
    payload: Mapping[str, object],
    location_prefix: str,
) -> str:
    explicit_units = _extract_explicit_boundary_units(payload)
    forcing_payload = payload.get("forcing")
    forcing_units: str | None = None
    if isinstance(forcing_payload, Mapping):
        raw_forcing_units = forcing_payload.get("units")
        if raw_forcing_units is not None:
            forcing_units = str(raw_forcing_units)
    if explicit_units is None and forcing_units is None:
        return "m"
    try:
        normalized_parent_units = (
            canonical_unit_short_form(explicit_units, canonical_unit="m", label="length")
            if explicit_units is not None
            else None
        )
        normalized_forcing_units = (
            canonical_unit_short_form(forcing_units, canonical_unit="m", label="length")
            if forcing_units is not None
            else None
        )
    except ValueError as exc:
        raise ValueError(
            f"{location_prefix}.units and {location_prefix}.forcing.units must be compatible with meters "
            "(for example m, cm, mm, km)."
        ) from exc
    if (
        normalized_parent_units is not None
        and normalized_forcing_units is not None
        and normalized_parent_units != normalized_forcing_units
    ):
        raise ValueError(f"{location_prefix}.units conflicts with {location_prefix}.forcing.units")
    return normalized_forcing_units or normalized_parent_units or "m"


def _canonicalize_dirichlet_bc_id(
    *,
    raw_bc_id: str,
    location_prefix: str,
) -> str:
    """Map one raw Dirichlet key to its canonical identifier."""
    bc_id = str(raw_bc_id).strip()
    if bc_id == "":
        raise ValueError(f"{location_prefix} cannot be empty")

    if bc_id in DIRICHLET_BC_CANONICAL_DOMAINS:
        return bc_id

    supported_keys = sorted(DIRICHLET_BC_CANONICAL_DOMAINS.keys())
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
    """Normalize one Dirichlet payload and validate inferred application domain."""
    canonical_bc_id = _canonicalize_dirichlet_bc_id(
        raw_bc_id=bc_id,
        location_prefix=location_prefix,
    )

    forcing_payload = _extract_boundary_forcing(
        payload=payload,
        location_prefix=location_prefix,
    )
    if forcing_payload is None:
        value, units = _coerce_boundary_value_and_units(
            payload=payload,
            location_prefix=location_prefix,
            default_units="m",
        )
    else:
        value = None
        source_units = _normalize_dirichlet_forcing_units(
            payload=payload,
            location_prefix=location_prefix,
        )
        units = "m"
        forcing_payload = dict(forcing_payload)
        forcing_payload["units"] = source_units
        if canonical_bc_id not in SIDE_DIRICHLET_BC_IDS:
            raise ValueError(
                f"{location_prefix}.forcing is only supported for side Dirichlet "
                "boundaries (north_side, south_side, east_side, west_side)"
            )

    raw_type = str(payload.get("type", "dirichlet")).strip().lower()
    if raw_type != "dirichlet":
        raise ValueError(f"{location_prefix}.type must be 'dirichlet'")

    # Domain is inferred from canonical key and must remain consistent if
    # explicitly provided by the user.
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
        "units": units,
        "type": "dirichlet",
        "data_value": data_value,
        "forcing": forcing_payload,
        "application_domain": application_domain,
        "support_label": _extract_support_label(payload=payload),
    }
    return FlowBoundaryConditionConfig.model_validate(normalized_payload).model_dump(mode="python")


def _normalize_drainage_boundary_payload(
    *,
    payload: Mapping[str, object],
    location_prefix: str,
    expected_type: str,
) -> dict[str, object]:
    """Normalize one drainage payload for Cauchy/Robin sections."""
    value, units = _coerce_boundary_value_and_units(
        payload=payload,
        location_prefix=location_prefix,
        default_units="m2/s",
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
        "units": units,
        "type": raw_type,
        "data_value": bool(payload.get("data_value", False)),
        "application_domain": application_domain,
        "support_label": _extract_support_label(payload=payload),
    }
    return FlowBoundaryConditionConfig.model_validate(normalized_payload).model_dump(mode="python")


def _normalize_generic_boundary_payload(
    *,
    bc_id: str,
    payload: Mapping[str, object],
    location_prefix: str,
) -> dict[str, object]:
    """Normalize one generic BC payload not handled by dedicated sections."""
    bc_type = str(payload.get("type", "dirichlet")).strip().lower() or "dirichlet"
    if bc_type not in {"dirichlet", "cauchy", "robin"}:
        raise ValueError(f"{location_prefix}.type must be one of: dirichlet, cauchy, robin")

    if "forcing" in payload:
        raise ValueError(
            f"{location_prefix}.forcing is only supported for canonical side Dirichlet "
            "keys under flow.bc.dirichlet or direct flow.bc.<side_id> entries"
        )

    default_units = "m2/s" if bc_type in {"cauchy", "robin"} else "m"
    value, units = _coerce_boundary_value_and_units(
        payload=payload,
        location_prefix=location_prefix,
        default_units=default_units,
    )
    normalized: dict[str, object] = {
        "id": bc_id,
        "value": value,
        "description": str(payload.get("description", f"Boundary condition '{bc_id}'")),
        "units": units,
        "type": bc_type,
        "data_value": bool(payload.get("data_value", False)),
        "support_label": _extract_support_label(payload=payload),
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


def _extract_boundary_forcing(
    *,
    payload: Mapping[str, object],
    location_prefix: str,
) -> dict[str, object] | None:
    """Validate and normalize an optional boundary forcing payload."""
    forcing = payload.get("forcing")
    if forcing is None:
        return None
    if "value" in payload and payload.get("value") is not None:
        raise ValueError(
            f"{location_prefix}.value and {location_prefix}.forcing are mutually exclusive"
        )
    if not isinstance(forcing, Mapping):
        raise TypeError(f"{location_prefix}.forcing must be a mapping")
    return FlowBoundaryForcingConfig.model_validate(dict(forcing)).model_dump(mode="python")


def _extract_support_label(
    *,
    payload: Mapping[str, object],
) -> str | None:
    """Return one optional explicit support label."""
    raw_value = payload.get("support_label")
    if raw_value is None:
        return None
    return str(raw_value)


def _parse_flow_bc_sections(bc_cfg: Mapping[str, object]) -> dict[str, object]:
    """
    Parse and normalize `[flow.bc]` entries into one flat mapping.

    Supported section-level precedence:
    - `[flow.bc.dirichlet.*]`
    - `[flow.bc.cauchy.drainage]`
    - `[flow.bc.robin.drainage]` (only if drainage was not already set)
    - direct `[flow.bc.<id>]` entries
    """
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

    # Direct entries are parsed last to preserve explicit section behavior.
    for raw_key, raw_payload in bc_cfg.items():
        key = str(raw_key).strip()
        if key == "":
            raise ValueError("flow.bc cannot contain empty keys")
        if key in {"dirichlet", "cauchy", "robin"}:
            continue
        if key == "drainage":
            raise ValueError(
                "flow.bc.drainage is no longer supported. "
                "Use flow.bc.cauchy.drainage or flow.bc.robin.drainage."
            )
        if not isinstance(raw_payload, Mapping):
            raise TypeError(f"flow.bc.{key} must be a mapping payload")

        if key in DIRICHLET_BC_CANONICAL_DOMAINS:
            if key in parsed:
                raise ValueError(f"Duplicate boundary condition entry for '{key}' in flow.bc")
            parsed[key] = _normalize_dirichlet_boundary_payload(
                bc_id=key,
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
