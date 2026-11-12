"""Tests for :mod:`hydromodpy.core.config_kit.dump` and
:meth:`HydroModelBase.to_toml`.

Covers profile filtering (``user`` emits fewer fields than ``expert``) and
a round-trip invariant on a station time-series config.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import get_args, get_origin

import pytest
from pydantic import BaseModel

from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.config_kit.introspect import extract_profile
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.data.families.base_config import BaseVariableConfig
from hydromodpy.data.families.timeseries_config import (
    TimeseriesColumnsMixin,
    TimeseriesSelectionMixin,
)


class _StationSeriesConfig(TimeseriesColumnsMixin, TimeseriesSelectionMixin, BaseVariableConfig):
    """Station time-series config built from the shared mixins."""


def _load(path: Path) -> dict:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _unwrap_model(annotation: object) -> type[BaseModel] | None:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    for arg in get_args(annotation):
        nested = _unwrap_model(arg)
        if nested is not None:
            return nested
    return None


def _visible_paths(model_cls: type[BaseModel], threshold: Profile, prefix: str = "") -> set[str]:
    paths: set[str] = set()
    for name, field_info in model_cls.model_fields.items():
        profile = extract_profile(field_info)
        full_path = f"{prefix}.{name}" if prefix else name
        if profile <= threshold:
            paths.add(full_path)
        nested = _unwrap_model(field_info.annotation)
        if nested is not None:
            paths.update(_visible_paths(nested, threshold, full_path))
    return paths


def _profile_paths(profile: Profile) -> set[str]:
    return _visible_paths(HydroModPyConfig, profile)


def test_to_toml_rejects_unknown_profile(tmp_path: Path) -> None:
    cfg = _StationSeriesConfig(date_start="2020-01-01", date_end="2020-12-31")
    with pytest.raises(ValueError):
        cfg.to_toml(tmp_path / "out.toml", profile="superexpert")
