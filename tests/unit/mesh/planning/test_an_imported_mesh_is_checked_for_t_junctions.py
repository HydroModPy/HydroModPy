"""A triangulation read from a ``.msh`` file is refused on a T-junction.

A vertex that lies inside the edge of a triangle that does not hold it leaves a
boundary edge inside the domain, closed to flow. The message gives where. Two
vertices at the same place cut the same crack and are reported, not refused.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.spatial.mesh.planning.input_mesh import (
    check_triangulation,
    read_input_triangulation,
)

# A 100 m square cut into a lower and an upper half along y = 50. The lower half
# is two triangles; the upper half is three, with a vertex at (50, 50) that the
# lower triangles do not hold.
_T_VERTICES = np.array(
    [
        [0.0, 0.0],
        [100.0, 0.0],
        [100.0, 50.0],
        [0.0, 50.0],
        [50.0, 50.0],
        [0.0, 100.0],
        [100.0, 100.0],
    ]
)
_T_TRIANGLES = np.array([[0, 1, 2], [0, 2, 3], [3, 4, 5], [4, 6, 5], [4, 2, 6]])


def _square(*, duplicate: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """Four triangles around a centre node; ``duplicate`` gives the last two their own centre."""
    vertices = [[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0], [50.0, 50.0]]
    triangles = [[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4]]
    if duplicate:
        vertices.append([50.0, 50.0])
        triangles[2:] = [[2, 3, 5], [3, 0, 5]]
    return np.array(vertices), np.array(triangles)


def test_a_conforming_triangulation_passes(caplog) -> None:
    vertices, triangles = _square()
    with caplog.at_level("WARNING"):
        check_triangulation(vertices, triangles, source="square")
    assert caplog.text == ""


def test_a_t_junction_is_refused_with_its_coordinates() -> None:
    with pytest.raises(MeshRequestError, match=r"T-junctions\), at \(50\.000, 50\.000\)"):
        check_triangulation(_T_VERTICES, _T_TRIANGLES, source="t-mesh")


def test_duplicate_vertices_are_reported_and_kept(caplog) -> None:
    vertices, triangles = _square(duplicate=True)
    with caplog.at_level("WARNING"):
        check_triangulation(vertices, triangles, source="cracked")
    assert "1 pairs of vertices" in caplog.text
    assert "(50.000, 50.000)" in caplog.text


def test_the_reader_runs_the_check(tmp_path: Path) -> None:
    nodes = "\n".join(f"{i + 1} {x} {y} 0" for i, (x, y) in enumerate(_T_VERTICES.tolist()))
    elements = "\n".join(
        f"{i + 1} 2 2 1 1 {a + 1} {b + 1} {c + 1}" for i, (a, b, c) in enumerate(_T_TRIANGLES)
    )
    path = tmp_path / "t.msh"
    path.write_text(
        "$MeshFormat\n2.2 0 8\n$EndMeshFormat\n"
        f"$Nodes\n{len(_T_VERTICES)}\n{nodes}\n$EndNodes\n"
        f"$Elements\n{len(_T_TRIANGLES)}\n{elements}\n$EndElements\n",
        encoding="utf-8",
    )
    with pytest.raises(MeshRequestError, match="T-junction"):
        read_input_triangulation(path)
