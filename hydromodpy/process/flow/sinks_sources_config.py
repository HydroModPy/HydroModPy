# -*- coding: utf-8 -*-
"""
Flow Sink/Source Normalizers
============================

Normalization entry point for `[flow.sinks_sources]` payloads.

The heavy validation of nested well payloads is delegated to
`FlowSinksSourcesConfig` (Pydantic schema).
"""

from __future__ import annotations

from collections.abc import Mapping

from hydromodpy.process.flow.sinks_sources import FlowSinksSourcesConfig


def normalize_flow_sinks_sources(
    value: FlowSinksSourcesConfig | Mapping[str, object] | None,
    *,
    location_prefix: str = "flow.sinks_sources",
) -> FlowSinksSourcesConfig:
    """
    Normalize one sinks/sources payload into `FlowSinksSourcesConfig`.

    Validation of `wells` content is delegated to the Pydantic schema.
    """
    if value is None:
        return FlowSinksSourcesConfig()
    if isinstance(value, FlowSinksSourcesConfig):
        return value
    if not isinstance(value, Mapping):
        raise ValueError(f"{location_prefix} must be a mapping payload")
    return FlowSinksSourcesConfig.model_validate(dict(value))
