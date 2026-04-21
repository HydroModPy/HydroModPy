# -*- coding: utf-8 -*-
"""
Base Module: Sink/Source Normalization Helpers
==============================================

Provides utility functions to convert raw configuration payloads into validated
`SinkSource` instances.
"""

from __future__ import annotations

from collections.abc import Mapping

from hydromodpy.physics.base.sinks_sources import SinkSource


def normalize_sink_source_payload(
    value: object,
    *,
    default_id: str = "sink_source",
    location_prefix: str = "process.sinks_sources",
) -> SinkSource:
    """Normalize one generic sink/source payload into `SinkSource`."""
    if isinstance(value, SinkSource):
        return value
    if not isinstance(value, Mapping):
        raise TypeError(f"{location_prefix} must be a mapping payload")

    payload = dict(value)
    payload.setdefault("id", default_id)
    if "units" not in payload and "unit" in payload:
        payload["units"] = payload["unit"]
    return SinkSource.model_validate(payload)
