"""The line families of a mesh request, and the families its engine ignores."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from shapely.geometry import LineString, Polygon

from hydromodpy.mesh.planning.families import (
    LineFamilySpec,
    _skip_an_ignored_family,
    requested_families,
)

pytestmark = pytest.mark.fast

DOMAIN = Polygon([(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)])
RIVER = LineString([(10.0, 0.0), (10.0, 100.0)])


def _family_config(engine: str, **families: str) -> Any:
    """A ``MeshConfig`` as the family table reads it, with an engine and its rules."""
    from hydromodpy.mesh.mesh_config import MeshFamiliesConfig

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


class TestRequestedFamilies:
    def test_a_family_an_engine_that_meshes_it_reads_is_built(self) -> None:
        families, notes = requested_families(
            _family_config("regular"), _inputs(river_trace=_trace(RIVER)), DOMAIN, pixel=10.0
        )

        assert [(family.name, family.intent) for family in families] == [("rivers", "cell")]
        assert families[0].lines == (RIVER,)
        assert notes == ()

    def test_a_family_an_engine_ignores_is_skipped_with_a_note(self) -> None:
        families, notes = requested_families(
            _family_config("catchment"), _inputs(river_trace=_trace(RIVER)), DOMAIN, pixel=10.0
        )

        assert families == ()
        assert len(notes) == 1
        assert "[mesh.families] rivers = 'cell'" in notes[0]
        assert "'catchment'" in notes[0]

    def test_a_written_family_names_its_skip_even_without_its_source(self) -> None:
        families, notes = requested_families(
            _family_config("catchment", rivers="none", lakes="face"), _inputs(), DOMAIN, pixel=10.0
        )

        assert families == ()
        assert len(notes) == 1
        assert "lakes" in notes[0]

    def test_a_family_at_none_asks_for_nothing_and_names_no_skip(self) -> None:
        families, notes = requested_families(
            _family_config("catchment", rivers="none"), _inputs(), DOMAIN, pixel=10.0
        )

        assert families == ()
        assert notes == ()


class TestTheFamilyLinesAreClipped:
    def test_the_river_parts_outside_the_domain_go(self) -> None:
        crossing = LineString([(10.0, -10.0), (10.0, 50.0)])
        families, notes = requested_families(
            _family_config("regular"), _inputs(river_trace=_trace(crossing)), DOMAIN, pixel=10.0
        )

        assert [(family.name, family.intent) for family in families] == [("rivers", "cell")]
        assert isinstance(families[0], LineFamilySpec)
        assert families[0].lines == (LineString([(10.0, 0.0), (10.0, 50.0)]),)
        assert notes == ()

    def test_a_family_outside_the_domain_gives_no_spec(self) -> None:
        outside = LineString([(-10.0, -10.0), (-10.0, -20.0)])
        families, notes = requested_families(
            _family_config("regular"), _inputs(river_trace=_trace(outside)), DOMAIN, pixel=10.0
        )

        assert families == ()
        assert notes == ()


class TestSkipNotes:
    def test_the_skip_says_the_family_and_the_engine(self) -> None:
        notes: list[str] = []
        skipped = _skip_an_ignored_family(
            "watershed_boundary", "face", frozenset({"watershed_boundary"}), notes, "catchment"
        )
        assert skipped
        assert notes == [
            "[mesh.families] watershed_boundary = 'face' is skipped: the mesh engine "
            "'catchment' ignores the watershed boundary.",
        ]

    def test_a_value_none_builds_nothing_and_names_no_skip(self) -> None:
        notes: list[str] = []
        skipped = _skip_an_ignored_family("rivers", "none", frozenset({"rivers"}), notes, "x")
        assert not skipped
        assert notes == []

    def test_a_family_the_engine_does_not_ignore_is_left_to_its_rule(self) -> None:
        notes: list[str] = []
        skipped = _skip_an_ignored_family("rivers", "cell", frozenset({"lakes"}), notes, "x")
        assert not skipped
        assert notes == []
