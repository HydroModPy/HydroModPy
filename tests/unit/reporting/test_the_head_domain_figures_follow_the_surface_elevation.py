"""The head series of the lower, middle and upper domain pick cells by surface elevation.

A synthetic run stores a surface that rises to the east in a mesh of nine cells
numbered in a shuffled order, so the cell index says nothing of the elevation.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import TracebackType
from typing import Any

import numpy as np
import pytest

from hydromodpy.reporting.comparison import domain_heads
from hydromodpy.reporting.comparison.domain_heads import (
    SKIPPED_FILENAME,
    pick_domain_thirds,
    write_domain_head_figures,
)
from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr

# Cell ``i`` sits at column ``_COLUMN[i]`` of a one-row strip.
_COLUMN = np.array([4, 8, 1, 6, 0, 3, 7, 2, 5])
_N_CELLS = _COLUMN.size
_SURFACE = 100.0 + 5.0 * _COLUMN
# Columns 0-2, 3-5 and 6-8 are the thirds. Their middle columns are 1, 4 and 7.
_MEDIAN_CELLS = {"low": 2, "mid": 0, "high": 6}


class _StoreSource:
    """The ``RunSource`` verbs the report reads, over a real ``fields.zarr``."""

    sim_id = "run"

    def __init__(self, fields: Path) -> None:
        self._fields = fields

    def open_zarr(self, sim_id: str | None = None) -> SimulationZarr:
        return SimulationZarr(self._fields)

    def fields_path_for(self, sim_id: str | None = None) -> Path:
        return self._fields

    def close(self) -> None:
        pass

    def __enter__(self) -> _StoreSource:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def _write_run(
    run_dir: Path,
    *,
    surface: str | None,
    head_offset: float = 0.0,
    n_cells: int = _N_CELLS,
) -> None:
    """Write a store whose cell ``i`` holds the head ``50 + i`` and rises by 0.5 per step.

    ``surface`` is ``"topography"``, ``"z_interfaces"`` or ``None`` for a store
    with no mesh group at all.
    """
    run_dir.mkdir(parents=True)
    store = SimulationZarr.create(run_dir / "fields.zarr", n_cells=n_cells, n_layers=1)
    if surface is not None:
        vertices = np.array(
            [
                [i + dx, dy, 0.0]
                for i in range(n_cells)
                for dx, dy in ((0, 0), (1, 0), (1, 1), (0, 1))
            ]
        )
        faces = np.arange(4 * n_cells, dtype="int32").reshape(n_cells, 4)
        elevation = _SURFACE[:n_cells]
        store.write_mesh(
            vertices=vertices,
            face_node_connectivity=faces,
            z_interfaces=np.stack([elevation, elevation - 10.0]),
            topography=elevation if surface == "topography" else None,
        )
    heads = 50.0 + np.arange(n_cells) + head_offset
    store.write_field_stack("watertable_elevation", np.stack([heads, heads + 0.5]))
    store.close()


def _head_map_rows(simulation_id: str) -> list[dict[str, str]]:
    return [
        {
            "simulation_id": simulation_id,
            "observable": "head_map_last",
            "support": "map",
            "time_index": "1",
            "elapsed_seconds": "",
            "value_index": str(cell),
            "value": str(50.0 + cell),
            "is_nodata": "False",
        }
        for cell in range(_N_CELLS)
    ]


def _comparison(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **runs: dict[str, Any]) -> tuple:
    """Write the runs, serve them as sources and return ``(manifest, drawn)``.

    ``drawn`` collects the rows given to the figure writer by profile.
    """
    sources: dict[str, _StoreSource] = {}
    simulations = []
    for name, options in runs.items():
        run_dir = tmp_path / name
        _write_run(run_dir, **options)
        sources[str(run_dir)] = _StoreSource(run_dir / "fields.zarr")
        simulations.append(
            {"id": name, "status": "completed", "run_dir": str(run_dir), "solver": "modflow6"}
        )
    drawn: dict[str, list[dict[str, Any]]] = {}

    def write_timeseries_figure(*, path: Path, observable_name: str, grouped_rows, **_: Any):
        drawn[observable_name] = grouped_rows
        path.write_bytes(b"png")
        return True

    monkeypatch.setattr(
        domain_heads, "open_run_source", lambda summary: sources.get(str(summary["run_dir"]))
    )
    monkeypatch.setattr(domain_heads, "write_timeseries_figure", write_timeseries_figure)
    manifest = {"reference_simulation": "ref", "simulations": simulations}
    return manifest, drawn


def test_the_thirds_are_cut_by_elevation_and_not_by_index() -> None:
    picks = pick_domain_thirds(_SURFACE, np.arange(_N_CELLS))

    assert [(profile_id, label) for profile_id, label, _ in picks] == [
        ("low", "lower domain"),
        ("mid", "middle domain"),
        ("high", "upper domain"),
    ]
    assert {profile_id: cell for profile_id, _, cell in picks} == _MEDIAN_CELLS
    by_index = [
        cell
        for _, _, cell in pick_domain_thirds(np.arange(_N_CELLS, dtype=float), np.arange(_N_CELLS))
    ]
    assert by_index != [cell for _, _, cell in picks]


def test_a_cell_without_an_elevation_or_a_head_is_not_in_a_third() -> None:
    surface = _SURFACE.copy()
    surface[4] = np.nan
    surface[7] = -9999.0
    active = np.array([0, 1, 2, 3, 4, 5, 6, 7])

    picks = pick_domain_thirds(surface, active)

    # Cells 2, 5, 0, 3, 6, 1 remain, in the order of their columns 1, 3, 4, 6, 7, 8.
    assert {profile_id: cell for profile_id, _, cell in picks} == {"low": 5, "mid": 3, "high": 1}


def test_fewer_than_three_cells_give_no_third() -> None:
    assert pick_domain_thirds(_SURFACE, np.array([0, 1])) == []


@pytest.mark.parametrize("surface", ["topography", "z_interfaces"])
def test_the_figures_draw_the_head_of_the_median_cell_of_each_third(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, surface: str
) -> None:
    manifest, drawn = _comparison(
        tmp_path,
        monkeypatch,
        ref={"surface": surface},
        other={"surface": surface, "head_offset": 10.0},
        coarser={"surface": surface, "n_cells": 5},
    )

    write_domain_head_figures(root=tmp_path, rows=_head_map_rows("ref"), manifest=manifest)

    assert set(drawn) == {f"head_domain_{profile}_series" for profile in _MEDIAN_CELLS}
    for profile, cell in _MEDIAN_CELLS.items():
        rows = drawn[f"head_domain_{profile}_series"]
        by_run = {
            run: [row["value"] for row in rows if row["simulation_id"] == run]
            for run in ("ref", "other", "coarser")
        }
        assert by_run["ref"] == pytest.approx([50.0 + cell, 50.5 + cell])
        assert by_run["other"] == pytest.approx([60.0 + cell, 60.5 + cell])
        # A run on another mesh has other cells under the same indices.
        assert by_run["coarser"] == []
    assert (tmp_path / "comparison_figures" / "head_domain_low_series__timeseries.png").is_file()
    assert not (tmp_path / SKIPPED_FILENAME).exists()


def test_a_run_without_surface_elevation_says_why_it_draws_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, drawn = _comparison(
        tmp_path, monkeypatch, ref={"surface": None}, other={"surface": None}
    )
    stale = tmp_path / "comparison_figures" / "head_domain_low_series__timeseries.png"
    stale.parent.mkdir()
    stale.write_bytes(b"png")

    write_domain_head_figures(root=tmp_path, rows=_head_map_rows("ref"), manifest=manifest)

    assert drawn == {}
    assert not stale.exists()
    note = json.loads((tmp_path / SKIPPED_FILENAME).read_text(encoding="utf-8"))
    assert note["reference_simulation"] == "ref"
    assert "mesh/topography" in note["reason"]
    assert "mesh/z_interfaces" in note["reason"]


def test_a_later_report_with_a_surface_removes_the_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, drawn = _comparison(
        tmp_path, monkeypatch, ref={"surface": "topography"}, other={"surface": "topography"}
    )
    (tmp_path / SKIPPED_FILENAME).write_text("{}\n", encoding="utf-8")

    write_domain_head_figures(root=tmp_path, rows=_head_map_rows("ref"), manifest=manifest)

    assert len(drawn) == 3
    assert not (tmp_path / SKIPPED_FILENAME).exists()
