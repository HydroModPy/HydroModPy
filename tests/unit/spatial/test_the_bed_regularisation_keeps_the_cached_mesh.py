"""Toggling the bed regularisation keeps the cached mesh.

The bed regularisation writes the surface the model top is sampled from,
after the mesh inputs are built. The mesh cache key leaves it out, so a run
with the option on hits the mesh of a run with it off, and both keep the key
every cached mesh had before the section existed.
"""

from __future__ import annotations

from types import SimpleNamespace

from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.spatial.mesh.mesh_cache import compute_mesh_cache_key

_RIVER = {"enabled": True, "threshold_mode": "cells", "threshold_cells": 50}


class _Dump:
    """A configuration whose dump is a given payload."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def model_dump(self, mode: str | None = None) -> dict:
        return dict(self._payload)


def _geographic(**bed) -> GeographicConfig:
    return GeographicConfig.from_outlet(
        x=1.0, y=2.0, dem="dem.tif", river_network=_RIVER, bed_regularization=bed
    )


def _key(geographic: object) -> str:
    return compute_mesh_cache_key(
        section_data=_Dump({"size": 80}),
        geographic_cfg=geographic,
        domain_cfg=_Dump({"buffer": 10}),
        constraints_mode="rivers_only",
        extra_size_fields=(),
        domain_geographic=SimpleNamespace(regional_dem_path=None),
    )


def test_the_bed_regularisation_keeps_the_cached_mesh() -> None:
    off = _geographic(enabled=False)
    on = _geographic(enabled=True, min_slope=5.0e-4)
    before_the_section = off.model_dump(mode="json")
    before_the_section.pop("bed_regularization")

    assert _key(on) == _key(off) == _key(_Dump(before_the_section))


def test_another_geographic_field_still_moves_the_key() -> None:
    assert _key(_geographic(enabled=False)) != _key(
        GeographicConfig.from_outlet(
            x=1.0, y=3.0, dem="dem.tif", river_network=_RIVER, bed_regularization={}
        )
    )
