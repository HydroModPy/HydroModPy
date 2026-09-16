"""The catalogue reads a declaration, it does not guess from a name and a type.

A leaf used to be offered when it was a real number, showed to Profile.USER, and
its name was absent from a hand-written blocklist. That blocklist could go stale
without anything failing, and it was: ``min_slope``, ``stream_threshold_km2`` and
``min_thickness`` are scheme and geometry knobs that still surfaced as
calibratable. The gate here is that a leaf enters the catalogue only when its
field carries a :class:`~hydromodpy.core.config_kit.calibrable.Calibrable`
annotation, whatever its name.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from hydromodpy.calibration.targets import calibration_targets, targets_by_name
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.calibrable import Calibrable
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile


class _Reach(HydroModelBase):
    """A declared quantity next to an undeclared numeric sibling."""

    manning: Annotated[float, Profile.USER] = Field(
        default=0.03,
        json_schema_extra=field_metadata(calibrable=Calibrable(units="s/m^(1/3)")),
    )
    min_slope: Annotated[float, Profile.USER] = Field(default=1e-4)


class _SinksSources(HydroModelBase):
    reaches: Annotated[dict[str, _Reach], Profile.USER] = Field(default_factory=dict)


class _Flow(HydroModelBase):
    sinks_sources: Annotated[_SinksSources, Profile.USER] = Field(default_factory=_SinksSources)


class _Config:
    """The smallest thing the catalogue walks: something with a ``flow``."""

    def __init__(self, flow: _Flow) -> None:
        self.flow = flow


def _project() -> _Config:
    return _Config(_Flow(sinks_sources=_SinksSources(reaches={"r1": _Reach()})))


def test_an_annotated_leaf_is_in_the_catalogue() -> None:
    names = targets_by_name(calibration_targets(_project()))

    assert "r1.manning" in names


def test_an_unannotated_numeric_sibling_is_not() -> None:
    names = targets_by_name(calibration_targets(_project()))

    assert "r1.min_slope" not in names
    assert not any(target.path.endswith("min_slope") for target in calibration_targets(_project()))
