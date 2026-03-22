from __future__ import annotations

import numpy as np

from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing._gmsh_driver import (
    add_ring_loop,
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
