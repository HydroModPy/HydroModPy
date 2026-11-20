"""The listing of what can be drawn, and the ``--opt NAME=VALUE`` items of a figure."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.display import catalog_figures
from hydromodpy.display.presets import PRESETS
from hydromodpy.display.request import FRAMES, SPECIALS


class HeldRun:
    """A run that holds the water table and the discharge of one gauge, nothing else."""

    def has_field(self, name: str) -> bool:
        return name == "watertable_elevation"

    def stations(self, name: str) -> list[str]:
        return ["gauge"] if name == "discharge" else []


class OneRunCatalog:
    def __init__(self, root) -> None:
        self.root = root

    def __enter__(self):
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def resolve(self, sim_ref: str) -> str:
        return "sim-001"

    def __getitem__(self, sid: str) -> HeldRun:
        return HeldRun()


def _by_name(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row["name"]: row for row in rows}


def test_listing_comes_from_the_tables() -> None:
    rows = catalog_figures.figure_listing()
    named = _by_name(rows)

    assert {row["name"] for row in rows if row["kind"] == "preset"} == set(PRESETS) - set(SPECIALS)
    assert {row["name"] for row in rows if row["kind"] == "special"} == set(SPECIALS)
    assert {row["name"] for row in rows if row["kind"] == "frame"} == set(FRAMES)
    assert {row["status"] for row in rows} == {""}
    assert named["watertable_depth"]["frame"] == "map"
    assert (named["discharge"]["frame"], named["discharge"]["unit"]) == ("series", "m3 s-1")
    assert named["simulation.solver"]["frame"] == "table"
    assert named["hydrograph"]["detail"] == "holes: time, variable, station, scale"
    assert named["network_comparison"]["frame"] == "run"
    assert "variable" in named["map"]["detail"].split(", ")


def test_listing_marks_what_a_run_holds(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("hydromodpy.results.catalog.facade.Catalog", OneRunCatalog)
    monkeypatch.setattr(
        "hydromodpy.core.state.result_dirs.resolve_project_root", lambda start: tmp_path
    )

    named = _by_name(catalog_figures.figure_listing("abc", workspace=tmp_path))

    assert named["watertable_elevation"]["status"] == "held"
    assert named["discharge"]["status"] == "held"
    assert named["head"]["status"] == "not in this run"
    assert named["simulation.solver"]["status"] == "checked when drawn"
    assert named["particle_tracks"]["status"] == "checked when drawn"
    assert named["hydrograph"]["status"].startswith("missing: ")
    assert "discharge" not in named["hydrograph"]["status"]


def test_listing_reads_the_presets_of_the_run(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("hydromodpy.results.catalog.facade.Catalog", OneRunCatalog)
    monkeypatch.setattr(
        "hydromodpy.core.state.result_dirs.resolve_project_root", lambda start: tmp_path
    )
    own = {"mine": PRESETS["hydrograph"]}

    rows = catalog_figures.figure_listing("abc", workspace=tmp_path, presets_of=lambda run: own)

    assert [row["name"] for row in rows if row["kind"] == "preset"] == ["mine"]
