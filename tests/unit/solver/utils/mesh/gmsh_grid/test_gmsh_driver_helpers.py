from __future__ import annotations

import numpy as np

from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing._gmsh_driver import (
    add_ring_loop,
    build_runtime_planar_mesh_from_gmsh,
)


class _FakeOcc:
    def __init__(self) -> None:
        self._next_point = 1
        self._next_line = 100
        self.points: list[tuple[float, float, float, float]] = []
        self.lines: list[tuple[int, int]] = []
        self.loops: list[list[int]] = []

    def addPoint(self, x: float, y: float, z: float, point_size: float) -> int:
        tag = self._next_point
        self._next_point += 1
        self.points.append((float(x), float(y), float(z), float(point_size)))
        return tag

    def addLine(self, point_tag_0: int, point_tag_1: int) -> int:
        tag = self._next_line
        self._next_line += 1
        self.lines.append((int(point_tag_0), int(point_tag_1)))
        return tag

    def addCurveLoop(self, oriented_curve_tags: list[int]) -> int:
        self.loops.append([int(tag) for tag in oriented_curve_tags])
        return len(self.loops)


class _FakeLiveMeshApi:
    def getNodes(self):
        return (
            np.asarray([10, 20, 30, 40], dtype=int),
            np.asarray(
                [
                    0.0,
                    0.0,
                    0.0,
                    1.0,
                    0.0,
                    0.0,
                    1.0,
                    1.0,
                    0.0,
                    0.0,
                    1.0,
                    0.0,
                ],
                dtype=float,
            ),
            np.asarray([], dtype=float),
        )

    def getElements(self, dim: int = -1):
        assert dim == 2
        return (
            np.asarray([2], dtype=int),
            (np.asarray([101, 102], dtype=int),),
            (np.asarray([10, 20, 30, 10, 30, 40], dtype=int),),
        )


class _FakeLiveModel:
    def __init__(self) -> None:
        self.mesh = _FakeLiveMeshApi()


class _FakeLiveGmsh:
    def __init__(self) -> None:
        self.model = _FakeLiveModel()


def test_add_ring_loop_skips_nearly_zero_length_segments() -> None:
    occ = _FakeOcc()
    ring_coords = np.asarray(
        [
            [0.0, 0.0],
            [1.0e-10, 0.0],
            [1.0, 0.0],
            [0.0, 1.0],
            [0.0, 0.0],
        ],
        dtype=float,
    )

    loop_tag, curve_tags = add_ring_loop(
        occ,
        ring_coords,
        point_registry={},
        line_registry={},
        point_size=1.0,
        tolerance=1.0e-6,
    )

    assert loop_tag == 1
    assert len(curve_tags) == 3
    assert len(occ.lines) == 3


def test_build_runtime_planar_mesh_from_gmsh_reads_live_session() -> None:
    mesh = build_runtime_planar_mesh_from_gmsh(
        _FakeLiveGmsh(),
        source_path="C:/tmp/runtime_mesh.msh",
    )

    assert mesh.n_nodes == 4
    assert mesh.n_cells == 2
    assert mesh.cell_type == "triangle"
    assert mesh.source_path is not None
    assert str(mesh.source_path).endswith("runtime_mesh.msh")
