"""Fake sealed runs and observable specs for the comparison reader tests.

A fake run is a directory and a :class:`_FakeSource` standing for its
``fields.zarr``, whose root holds the ``mesh/`` group the cells are read from:
the readers take any object with the ``RunSource`` verbs.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest

import hydromodpy
from hydromodpy.analysis.comparison.config import (
    ComparisonObservable,
    ComparisonSimulation,
    ComparisonSpec,
)
from hydromodpy.results.storage.contract import FIELDS_STORE_NAME

# Structured-shape resolution needs the solver registry provider, which the
# deferred bootstrap installs only on first real use. Force it here so every
# importing test file gets it regardless of run order.
hydromodpy.bootstrap()

OUTLET_CELL_AREA_M2 = 10.0
CELL_CENTERS_X = (0.0, 10.0, 20.0)
CELL_AREAS_M2 = (5.0, OUTLET_CELL_AREA_M2, 7.0)
SIM_ID = "sim-test"


class _FakeMeshGroup(dict):
    """The ``mesh/`` group of a run: its arrays by name and an ``attrs`` mapping."""

    def __init__(self, vertices: np.ndarray, faces: np.ndarray) -> None:
        super().__init__(vertices=vertices, face_node_connectivity=faces)
        self.attrs: dict[str, Any] = {}


def _strip_mesh() -> _FakeMeshGroup:
    """Three rectangles on one line, 1 m high, centred and sized like the cells above."""
    vertices: list[list[float]] = []
    faces: list[list[int]] = []
    for center_x, area in zip(CELL_CENTERS_X, CELL_AREAS_M2, strict=True):
        half_width = area / 2.0
        first = len(vertices)
        vertices += [
            [center_x - half_width, -0.5, 0.0],
            [center_x + half_width, -0.5, 0.0],
            [center_x + half_width, 0.5, 0.0],
            [center_x - half_width, 0.5, 0.0],
        ]
        faces.append([first, first + 1, first + 2, first + 3])
    return _FakeMeshGroup(np.asarray(vertices, dtype=float), np.asarray(faces, dtype=np.int32))


class _FakeSource:
    """The ``RunSource`` verbs the readers use, over an in-memory field root."""

    sim_id = SIM_ID

    def __init__(self, run_dir: Path, root: dict[str, object]) -> None:
        self.run_dir = run_dir
        self._root = root
        self.closed = False

    def open_zarr(self, sim_id: str | None = None) -> SimpleNamespace:
        return SimpleNamespace(root=self._root, close=lambda: None)

    def fields_path_for(self, sim_id: str | None = None) -> Path:
        return self.run_dir / FIELDS_STORE_NAME

    def query_budget(self, sim_id: str | None = None, **_: Any) -> pd.DataFrame:
        return pd.DataFrame()

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> _FakeSource:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _serve_sources(monkeypatch: pytest.MonkeyPatch, sources: list[_FakeSource]) -> None:
    """Open each summary's run as the fake source of its ``run_dir``."""
    by_dir = {str(source.run_dir): source for source in sources}

    def open_run_source(summary: dict[str, Any]) -> _FakeSource | None:
        return by_dir.get(str(summary.get("run_dir", "")))

    for target in (
        "hydromodpy.analysis.comparison.runtime.run_source.open_run_source",
        "hydromodpy.analysis.comparison.runtime.mesh.open_run_source",
        "hydromodpy.analysis.comparison.visuals_payloads.open_run_source",
    ):
        monkeypatch.setattr(target, open_run_source)


def _spec_from_toml(path: Path) -> ComparisonSpec:
    """Read a short ``[comparison]`` TOML of a test into a ComparisonSpec."""
    section = tomllib.loads(path.read_text(encoding="utf-8"))["comparison"]
    simulations = [
        ComparisonSimulation(
            id=item["id"],
            label=item.get("label"),
            run_dir=Path(item.get("run_folder", path.parent)),
            solver=item.get("solver"),
            mesh_mode=item.get("mesh_mode", "unknown"),
        )
        for item in section["simulation"]
    ]
    return ComparisonSpec(
        comparison_id=section.get("comparison_id", path.stem),
        comparison_root=path.parent / "comparison_outputs",
        reference_simulation=section.get("reference_simulation"),
        simulation=simulations,
        observable=[ComparisonObservable.model_validate(item) for item in section["observable"]],
    )


def _write_simulation_comparison_config(path: Path, run_folder: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "[comparison]",
                'comparison_id = "demo_compare"',
                "",
                "[[comparison.simulation]]",
                'id = "mf6_demo"',
                'solver = "modflow6"',
                'mesh_mode = "voronoi"',
                f'run_folder = "{run_folder.as_posix()}"',
                "",
                "[[comparison.observable]]",
                'name = "head_at_point"',
                'variable = "watertable_elevation"',
                'support = "point"',
                "x = 10.0",
                "y = 0.0",
                'time = "last"',
                'unit = "m"',
                "",
                "[[comparison.observable]]",
                'name = "outlet_flux"',
                'variable = "outlet_flux"',
                'support = "outlet"',
                "cell_index = 1",
                'time = "last"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_fake_run_folder(
    run_folder: Path,
    *,
    head_offset: float = 0.0,
    accumulation_offset: float = 0.0,
) -> _FakeSource:
    run_folder.mkdir(parents=True, exist_ok=True)
    return _FakeSource(
        run_folder,
        {
            "mesh": _strip_mesh(),
            "watertable_elevation": np.asarray(
                [
                    np.asarray([10.0, 20.0, 30.0]) + head_offset,
                    np.asarray([11.0, 21.0, 31.0]) + head_offset,
                ],
                dtype=float,
            ),
            "accumulation_flux": np.asarray(
                [
                    np.asarray([0.1, 0.4, 0.2]) + accumulation_offset,
                    np.asarray([0.3, 0.8, 0.5]) + accumulation_offset,
                ],
                dtype=float,
            ),
            "seepage_mask": np.asarray(
                [
                    np.asarray([0.0, 1.0, 0.0]),
                    np.asarray([1.0, 1.0, 0.0]),
                ],
                dtype=float,
            ),
        },
    )


def _write_direct_outlet_run_folder(run_folder: Path, *, outlet_value: float) -> _FakeSource:
    run_folder.mkdir(parents=True, exist_ok=True)
    return _FakeSource(
        run_folder,
        {
            "outlet_discharge_east_side_m3_s": np.asarray(
                [[outlet_value], [outlet_value + 0.25]],
                dtype=float,
            )
        },
    )


def _write_boussinesq_run_folder(
    run_folder: Path,
    *,
    residual_history_m3_s: np.ndarray | None = None,
) -> _FakeSource:
    run_folder.mkdir(parents=True, exist_ok=True)
    state = {
        "recharge_rate_history_m_s": np.asarray(
            [[1.0e-8, 2.0e-8, 1.5e-8], [2.0e-8, 1.0e-8, 2.5e-8]],
            dtype=float,
        ),
        "well_flux_history_m3_s": np.asarray(
            [[-0.01, -0.02, 0.0], [-0.01, -0.015, 0.0]],
            dtype=float,
        ),
        "head_history_m": np.asarray(
            [[10.0, 11.0, 12.0], [10.5, 11.25, 12.5]],
            dtype=float,
        ),
        "saturation_excess_history_m_s": np.asarray(
            [[0.0, 0.02, 0.01], [0.01, 0.03, 0.0]],
            dtype=float,
        ),
        "dry_deficit_history_m_s": np.asarray(
            [
                [0.0, 0.0, 0.0],
                [0.0, 0.005, 0.0],
            ],
            dtype=float,
        ),
        "drainage_flux_history_m3_s": np.asarray(
            [
                [0.05, 0.15, 0.07],
                [0.08, 0.3, 0.1],
            ],
            dtype=float,
        ),
        "period_lengths_seconds": np.asarray([3600.0], dtype=float),
    }
    if residual_history_m3_s is not None:
        state["residual_history_m3_s"] = np.asarray(residual_history_m3_s, dtype=float)
    return _FakeSource(run_folder, {"mesh": _strip_mesh(), "boussinesq_state": state})


def _expected_outlet_flux(value_m_per_day: float) -> float:
    return value_m_per_day * OUTLET_CELL_AREA_M2 / 86400.0
