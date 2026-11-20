"""The line families of a mesh request, and the families its engine ignores."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from shapely.geometry import LineString, Polygon

from hydromodpy.mesh.mesh_config import MeshFamiliesConfig
from hydromodpy.mesh.planning.families import requested_families

pytestmark = pytest.mark.fast

DOMAIN = Polygon([(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)])
RIVER = LineString([(10.0, 0.0), (10.0, 100.0)])


def _family_config(engine: str, **families: str) -> Any:
    """A ``MeshConfig`` as the family table reads it, with an engine and its rules."""
    defaults = dict(
        rivers="cell", geology="none", lakes="none", barriers="none", watershed_boundary="none"
    )
    defaults.update(families)
    return SimpleNamespace(engine=engine, families=MeshFamiliesConfig(**defaults))


def _inputs(**members: Any) -> Any:
    """The planner inputs a family table reads, as plain attributes."""
    members.setdefault("river_trace", None)
    members.setdefault("lakes", ())
    members.setdefault("barriers", ())
    members.setdefault("watershed", None)
    members.setdefault("geology", None)
    members.setdefault("input_triangulation", None)
    return SimpleNamespace(**members)


def _trace(*lines: LineString) -> Any:
    return SimpleNamespace(lines=list(lines))


def test_a_family_an_engine_ignores_is_skipped_with_a_note() -> None:
    families, notes = requested_families(
        _family_config("catchment"), _inputs(river_trace=_trace(RIVER)), DOMAIN, pixel=10.0
    )

    assert families == ()
    assert len(notes) == 1
    assert "[mesh.families] rivers = 'cell'" in notes[0]
    assert "'catchment'" in notes[0]


def test_a_written_family_names_its_skip_even_without_its_source() -> None:
    families, notes = requested_families(
        _family_config("catchment", rivers="none", lakes="face"), _inputs(), DOMAIN, pixel=10.0
    )

    assert families == ()
    assert len(notes) == 1
    assert "lakes" in notes[0]


def test_a_family_outside_the_domain_gives_no_spec() -> None:
    outside = LineString([(-10.0, -10.0), (-10.0, -20.0)])
    families, notes = requested_families(
        _family_config("regular"), _inputs(river_trace=_trace(outside)), DOMAIN, pixel=10.0
    )

    assert families == ()
    assert notes == ()
