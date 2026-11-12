"""Role file of the constant-head (CHD) cells of a MODFLOW 6 build, on 4-cell grids.

The ocean, stream and lateral boundaries are merged in one CHD package, so the
budget holds a single CHD term. The build writes the cells of each role (a boolean
mask per role) beside the solver files, and a reader finds the stream share from
the run folder alone.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.core.exceptions import SolverInputError
from hydromodpy.solver.modflow6 import build as build_module
from hydromodpy.solver.modflow6.builders.boundary_conditions import (
    assemble_constant_head_stress_period_data,
)
from hydromodpy.solver.modflow_common.boundary_roles import (
    read_constant_head_roles,
    roles_path,
    write_constant_head_roles,
)
from hydromodpy.solver.modflow_common.observable_extraction import (
    excluded_release_records_for_model,
    release_packages_for_model,
)

N_CELLS = 4
NO_CELLS = np.zeros(N_CELLS, dtype=bool)
OCEAN_MASK = np.array([True, False, False, False])
STREAM_MASK = np.array([False, False, True, False])


def assembly_model(tmp_path: Path, *, nper: int = 2) -> SimpleNamespace:
    return SimpleNamespace(
        nper=nper, ncpl=N_CELLS, full_path=str(tmp_path), model_output_name="nancon"
    )


def test_stream_share_read_from_the_folder(tmp_path: Path) -> None:
    # The model below holds a CHD package and nothing else, as a process that
    # opens a finished run folder can rebuild it. That keeps the stream CHD in
    # the release union.
    write_constant_head_roles(
        tmp_path,
        "nancon",
        n_cells=N_CELLS,
        masks_by_role={"ocean": OCEAN_MASK, "stream": STREAM_MASK},
    )
    model = SimpleNamespace(chd=object(), full_path=str(tmp_path), model_output_name="nancon")

    packages = release_packages_for_model(model)

    assert [package.name for package in packages] == ["CHD"]
    np.testing.assert_array_equal(packages[0].cell_mask, STREAM_MASK)
    assert "CHD" not in excluded_release_records_for_model(model)


def test_assembly_declares_the_roles(tmp_path: Path) -> None:
    spd = assemble_constant_head_stress_period_data(
        assembly_model(tmp_path),
        ocean=({0: [[0, 0, 3.0]], 1: [[0, 0, 3.0]]}, OCEAN_MASK),
        stream=({0: [[0, 2, 9.0]], 1: [[0, 2, 9.0]]}, STREAM_MASK),
        side={0: [[0, 3, 5.0]], 1: [[0, 3, 5.0]]},
    )

    # Period 1 repeats period 0, and MF6 reuses the last PERIOD block.
    assert list(spd) == [0]
    assert spd[0] == [[0, 0, 3.0], [0, 2, 9.0], [0, 3, 5.0]]

    roles = read_constant_head_roles(tmp_path, "nancon")
    assert roles is not None
    np.testing.assert_array_equal(roles.mask_for("stream"), STREAM_MASK)
    np.testing.assert_array_equal(roles.mask_for("ocean"), OCEAN_MASK)


def test_cell_claimed_twice_keeps_builder_role(tmp_path: Path) -> None:
    # A stream cell on the domain edge is written by the stream builder, then
    # overwritten by the side builder. The surviving row has the lateral head,
    # but it is still a stream release, so the role comes from the mask.
    stream_mask = np.array([False, True, False, False])

    spd = assemble_constant_head_stress_period_data(
        assembly_model(tmp_path, nper=1),
        ocean=({0: []}, NO_CELLS),
        stream=({0: [[0, 1, 9.0]]}, stream_mask),
        side={0: [[0, 1, 5.0]]},
    )

    assert spd[0] == [[0, 1, 5.0]]
    roles = read_constant_head_roles(tmp_path, "nancon")
    assert roles is not None
    np.testing.assert_array_equal(roles.mask_for("stream"), stream_mask)


def test_no_constant_head_no_sidecar(tmp_path: Path) -> None:
    # A stale file would name cells of a package the run never built.
    spd = assemble_constant_head_stress_period_data(
        assembly_model(tmp_path, nper=1),
        ocean=({0: []}, NO_CELLS),
        stream=({0: []}, NO_CELLS),
        side={0: []},
    )

    assert not any(spd.values())
    assert not roles_path(tmp_path, "nancon").exists()


def test_output_stem_settled_before_use() -> None:
    # A role file written before the stem is set would carry another name than
    # the extractor asks for, and a real seepage would read as 0.0 with no error.
    # The build steps are read in the order run_pre_processing calls them.
    driver = ast.parse(inspect.getsource(build_module.run_pre_processing))
    steps = sorted(
        (node.lineno, node.func.id)
        for node in ast.walk(driver)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id.startswith(("_", "build_"))
    )
    tree = ast.parse("\n".join(inspect.getsource(getattr(build_module, name)) for _, name in steps))
    settled = [
        node.lineno
        for node in ast.walk(tree)
        for target in getattr(node, "targets", ())
        if isinstance(node, ast.Assign)
        and isinstance(target, ast.Attribute)
        and target.attr == "model_output_name"
    ]
    reads = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.ctx, ast.Load)
        and node.attr == "model_output_name"
    ]

    assert len(settled) == 1, f"the stem is assigned {len(settled)} times in the build"
    assert reads, "no read of the stem found; this gate would prove nothing"
    assert min(reads) > settled[0], (
        f"the stem is read at line {min(reads)} of the build and only settled at {settled[0]}"
    )


ROLE_REFUSALS = [
    pytest.param(
        6, {"stream": np.array([False, True, False])}, "covers 3 cells", id="mask too short"
    ),
    pytest.param(3, {"lagoon": np.array([False, True, False])}, "lagoon", id="undeclared role"),
]


@pytest.mark.parametrize(("n_cells", "masks", "match"), ROLE_REFUSALS)
def test_refusals(tmp_path: Path, n_cells: int, masks: dict, match: str) -> None:
    with pytest.raises(SolverInputError, match=match):
        write_constant_head_roles(tmp_path, "nancon", n_cells=n_cells, masks_by_role=masks)
    assert not roles_path(tmp_path, "nancon").exists()
