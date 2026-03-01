# -*- coding: utf-8 -*-
"""Flow sink/source payload normalizers."""

from __future__ import annotations

from collections.abc import Mapping

from hydromodpy.process.flow.sink_sources import FlowSinksSourcesConfig


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
