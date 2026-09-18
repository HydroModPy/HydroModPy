"""The role of a constant-head cell survives the model object that built it.

MODFLOW 6 merges the ocean, the stream and the lateral boundaries into one CHD
package, and the budget then holds a single CHD term. Which rows are a stream
is a fact of the build that no deck, budget or head file records, so the build
writes it beside the solver files. These tests hold the two properties that
makes it worth: it round-trips, and a reader gets the stream share with no live
flopy model anywhere in sight.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.core.exceptions import SolverInputError
from hydromodpy.solver.modflow_common.boundary_roles import (
    read_constant_head_roles,
    roles_path,
    write_constant_head_roles,
)
from hydromodpy.solver.modflow_common.observable_extraction import (
    excluded_release_records_for_model,
    release_packages_for_model,
)


def test_the_roles_round_trip_through_the_sidecar(tmp_path: Path) -> None:
    write_constant_head_roles(
        tmp_path,
        "nancon",
        n_cells=6,
        masks_by_role={
            "ocean": np.array([True, False, False, False, False, False]),
            "stream": np.array([False, False, True, True, False, False]),
        },
    )

    roles = read_constant_head_roles(tmp_path, "nancon")

    assert roles is not None
    assert roles.n_cells == 6
    np.testing.assert_array_equal(
        roles.mask_for("stream"), [False, False, True, True, False, False]
    )
    np.testing.assert_array_equal(
        roles.mask_for("ocean"), [True, False, False, False, False, False]
    )
    assert roles.has_role("stream") and roles.has_role("ocean")


def test_a_role_with_no_cell_is_declared_rather_than_omitted(tmp_path: Path) -> None:
    """Saying "this run built no ocean" is not saying nothing about the ocean."""
    write_constant_head_roles(
        tmp_path,
        "nancon",
        n_cells=3,
        masks_by_role={"stream": np.array([False, True, False])},
    )

    roles = read_constant_head_roles(tmp_path, "nancon")

    assert roles is not None
    assert roles.has_role("stream")
    assert not roles.has_role("ocean")
    assert "ocean" in roles.cells_by_role


def test_a_run_that_wrote_no_sidecar_reads_as_unknown(tmp_path: Path) -> None:
    assert read_constant_head_roles(tmp_path, "nancon") is None


def test_a_mask_that_does_not_cover_the_grid_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SolverInputError, match="covers 3 cells"):
        write_constant_head_roles(
            tmp_path,
            "nancon",
            n_cells=6,
            masks_by_role={"stream": np.array([False, True, False])},
        )


def test_an_undeclared_role_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SolverInputError, match="lagoon"):
        write_constant_head_roles(
            tmp_path,
            "nancon",
            n_cells=3,
            masks_by_role={"lagoon": np.array([False, True, False])},
        )
    assert not roles_path(tmp_path, "nancon").exists()


def test_the_stream_share_is_read_from_the_directory_alone(tmp_path: Path) -> None:
    """The point of the sidecar: the extractor needs the run, not the model.

    The object below carries a CHD package and nothing else -- no mask, no
    builder state, no flopy. It is what a process that opens a finished run
    directory can reconstruct, and it is enough to keep the stream CHD in the
    release union.
    """
    write_constant_head_roles(
        tmp_path,
        "nancon",
        n_cells=4,
        masks_by_role={
            "ocean": np.array([True, False, False, False]),
            "stream": np.array([False, False, True, False]),
        },
    )
    model = SimpleNamespace(
        chd=object(),
        full_path=str(tmp_path),
        model_output_name="nancon",
    )

    packages = release_packages_for_model(model)

    assert [package.name for package in packages] == ["CHD"]
    np.testing.assert_array_equal(packages[0].cell_mask, [False, False, True, False])
    assert "CHD" not in excluded_release_records_for_model(model)


def test_an_ocean_only_constant_head_stays_ruled_out(tmp_path: Path) -> None:
    """An ocean CHD is water leaving sideways, and counting it invents a stream."""
    write_constant_head_roles(
        tmp_path,
        "nancon",
        n_cells=4,
        masks_by_role={"ocean": np.array([True, True, False, False])},
    )
    model = SimpleNamespace(
        chd=object(),
        drn=object(),
        full_path=str(tmp_path),
        model_output_name="nancon",
    )

    excluded = excluded_release_records_for_model(model)

    assert {"CHD", "CONSTANT HEAD"} <= set(excluded)


def _assembly_model(tmp_path: Path, *, nper: int = 2, n_cells: int = 4) -> SimpleNamespace:
    return SimpleNamespace(
        nper=nper,
        ncpl=n_cells,
        full_path=str(tmp_path),
        model_output_name="nancon",
    )


def test_the_assembly_declares_the_roles_of_the_package_it_merges(tmp_path: Path) -> None:
    """The merge and the declaration are one call, so neither can be forgotten."""
    from hydromodpy.solver.modflow6.builders import assemble_constant_head_stress_period_data

    ocean_mask = np.array([True, False, False, False])
    stream_mask = np.array([False, False, True, False])

    spd = assemble_constant_head_stress_period_data(
        _assembly_model(tmp_path),
        ocean=({0: [[0, 0, 3.0]], 1: [[0, 0, 3.0]]}, ocean_mask),
        stream=({0: [[0, 2, 9.0]], 1: [[0, 2, 9.0]]}, stream_mask),
        side={0: [[0, 3, 5.0]], 1: [[0, 3, 5.0]]},
    )

    # Period 1 repeats period 0, and MF6 reuses the last PERIOD block.
    assert list(spd) == [0]
    assert spd[0] == [[0, 0, 3.0], [0, 2, 9.0], [0, 3, 5.0]]

    roles = read_constant_head_roles(tmp_path, "nancon")
    assert roles is not None
    np.testing.assert_array_equal(roles.mask_for("stream"), stream_mask)
    np.testing.assert_array_equal(roles.mask_for("ocean"), ocean_mask)


def test_a_cell_claimed_twice_keeps_its_builder_role(tmp_path: Path) -> None:
    """The row that survives the merge is not what the extractor needs.

    A stream cell on the domain edge is written by the stream builder and
    overwritten by the side builder, so the surviving CHD row carries the
    lateral head. The release it carries is still a stream release, which is
    why the declaration comes from the mask and not from the merged rows.
    """
    from hydromodpy.solver.modflow6.builders import assemble_constant_head_stress_period_data

    stream_mask = np.array([False, True, False, False])

    spd = assemble_constant_head_stress_period_data(
        _assembly_model(tmp_path, nper=1),
        ocean=({0: []}, np.zeros(4, dtype=bool)),
        stream=({0: [[0, 1, 9.0]]}, stream_mask),
        side={0: [[0, 1, 5.0]]},
    )

    assert spd[0] == [[0, 1, 5.0]]
    roles = read_constant_head_roles(tmp_path, "nancon")
    assert roles is not None
    np.testing.assert_array_equal(roles.mask_for("stream"), stream_mask)


def test_a_run_that_builds_no_constant_head_leaves_no_sidecar(tmp_path: Path) -> None:
    """No package, no declaration: a stale sidecar would name cells of a package
    the run never built."""
    from hydromodpy.solver.modflow6.builders import assemble_constant_head_stress_period_data

    spd = assemble_constant_head_stress_period_data(
        _assembly_model(tmp_path, nper=1),
        ocean=({0: []}, np.zeros(4, dtype=bool)),
        stream=({0: []}, np.zeros(4, dtype=bool)),
        side={0: []},
    )

    assert not any(spd.values())
    assert not roles_path(tmp_path, "nancon").exists()


def test_the_output_stem_is_settled_before_any_file_is_named_after_it() -> None:
    """The ordering the sidecar depends on, pinned where it can be seen.

    ``mf6_output_name`` collapses a stem that would push the solver path past
    the Windows limit to a hashed one. A sidecar written before that collapse
    carries the long name, the extractor asks for the short one, and the stream
    role silently reads as absent -- a real seepage becomes 0.0 with no error.
    The build therefore settles the stem once, before anything names a file.
    """
    import ast
    import inspect

    from hydromodpy.solver.modflow6 import build as build_module

    tree = ast.parse(inspect.getsource(build_module.run_pre_processing))
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
