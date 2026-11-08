"""The generated river network A: its rasters, its window and its projection onto the cells.

The rasters of A are chosen once for a run, read on a window around the mesh,
and projected in two stages. ``channel_exits`` reads the cell numbers of the
pixels, ``pin_channel`` reads the active columns and the lakes of a backend.
The last test keeps the one-stage projection that the two stages replace, and
compares both on seeded random cases.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from rasterio.transform import from_origin

from hydromodpy.catchment.drainage.channel_tree import (
    ChannelExits,
    ChannelTree,
    active_channel_raster,
    channel_exits,
    channel_raster_paths,
    pin_channel,
    read_channel_tree,
)
from hydromodpy.catchment.terrain.d8 import d8_receivers
from hydromodpy.catchment.terrain.port import D8_WBT_OFFSETS
from hydromodpy.model.domain.geometry import ChannelRasters, channel_rasters_for_run

SHAPE = (5, 5)
LINK = "dem_stream_link_id_full.tif"
STREAMS = "dem_streams_full.tif"
POINTER = "dem_direc.tif"
ACCUMULATION = "dem_acc_cells.tif"
_CODE_OF_STEP = {step: code for code, step in D8_WBT_OFFSETS.items()}


# -- The rasters a run reads -------------------------------------------------


def _write(path: Path, data: np.ndarray) -> None:
    import rasterio

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype=data.dtype,
        transform=from_origin(0.0, 10.0 * data.shape[0], 10.0, 10.0),
    ) as dst:
        dst.write(data, 1)


def _write_network(folder: Path) -> None:
    """A along row 2 of the link raster, with a pointer and an accumulation."""
    link = np.zeros(SHAPE, dtype=np.int32)
    link[2, 1:4] = 1
    _write(folder / LINK, link)
    _write(folder / POINTER, np.ones(SHAPE, dtype=np.int32))
    _write(folder / ACCUMULATION, np.ones(SHAPE, dtype=np.float32))


def _geographic(folder: Path | None = None, *, enabled: bool = True, **clipped: object):
    return SimpleNamespace(
        correcflow_path=None if folder is None else str(folder),
        river_network_enabled=enabled,
        **clipped,
    )


@pytest.mark.parametrize("geographic", [None, SimpleNamespace(), _geographic(enabled=False)])
def test_a_run_without_a_folder_a_clipped_raster_or_the_step_has_no_rasters(geographic) -> None:
    assert channel_rasters_for_run(geographic) is None


def test_a_run_whose_step_ran_but_left_no_folder_says_so() -> None:
    rasters = channel_rasters_for_run(_geographic(enabled=True))

    assert rasters == ChannelRasters(
        enabled=True, link=None, pointer=None, accumulation=None, clipped=()
    )


@pytest.mark.parametrize("enabled", [True, False])
def test_the_three_full_extent_paths_are_named_whether_or_not_the_files_exist(
    tmp_path: Path, enabled: bool
) -> None:
    rasters = channel_rasters_for_run(_geographic(tmp_path, enabled=enabled))

    assert rasters == ChannelRasters(
        enabled=enabled,
        link=str(tmp_path / STREAMS),
        pointer=str(tmp_path / POINTER),
        accumulation=str(tmp_path / ACCUMULATION),
        clipped=(),
    )
    assert channel_raster_paths(tmp_path) == (
        rasters.link,
        rasters.pointer,
        rasters.accumulation,
    )
    assert rasters.link == active_channel_raster(tmp_path)


def test_the_link_raster_is_the_one_the_rule_of_every_reader_picks(tmp_path: Path) -> None:
    _write_network(tmp_path)

    assert channel_rasters_for_run(_geographic(tmp_path)).link == str(tmp_path / LINK)
    assert channel_raster_paths(tmp_path)[0] == str(tmp_path / LINK)


def test_only_the_clipped_rasters_that_exist_are_kept_link_first(tmp_path: Path) -> None:
    link, streams = tmp_path / "link.tif", tmp_path / "streams.tif"
    _write(link, np.ones(SHAPE, dtype=np.int32))
    _write(streams, np.ones(SHAPE, dtype=np.int32))
    missing = str(tmp_path / "gone.tif")

    both = channel_rasters_for_run(
        _geographic(river_stream_link_id_tif=str(link), river_streams_tif=str(streams))
    )
    only_streams = channel_rasters_for_run(
        _geographic(river_stream_link_id_tif=missing, river_streams_tif=str(streams))
    )
    none = channel_rasters_for_run(
        _geographic(enabled=False, river_stream_link_id_tif=missing, river_streams_tif=None)
    )

    assert both.clipped == (str(link), str(streams))
    assert only_streams.clipped == (str(streams),)
    assert none is None


def test_a_link_raster_older_than_the_stream_raster_is_not_the_network(tmp_path: Path) -> None:
    _write_network(tmp_path)
    streams = np.zeros(SHAPE, dtype=np.int32)
    streams[3, 1:4] = 1
    _write(tmp_path / STREAMS, streams)
    moment = os.path.getmtime(tmp_path / STREAMS) - 60.0
    os.utime(tmp_path / LINK, (moment, moment))

    assert active_channel_raster(tmp_path) == str(tmp_path / STREAMS)
    assert channel_rasters_for_run(_geographic(tmp_path)).link == str(tmp_path / STREAMS)


def test_the_pruned_streams_are_the_network_when_the_link_raster_is_missing(
    tmp_path: Path,
) -> None:
    _write(tmp_path / STREAMS, np.zeros(SHAPE, dtype=np.int32))
    _write(tmp_path / "dem_streams_pruned_full.tif", np.zeros(SHAPE, dtype=np.int32))
    moment = os.path.getmtime(tmp_path / STREAMS) + 60.0
    os.utime(tmp_path / "dem_streams_pruned_full.tif", (moment, moment))

    assert active_channel_raster(tmp_path) == str(tmp_path / "dem_streams_pruned_full.tif")


# -- The window around the mesh ------------------------------------------------


def test_the_tree_is_read_on_a_window_around_the_mesh(tmp_path: Path) -> None:
    import rasterio

    shape = (20, 30)
    transform = from_origin(-100.0, 200.0, 10.0, 10.0)
    link = np.zeros(shape, dtype=np.int32)
    link[5, 12] = 7
    profile = {
        "driver": "GTiff",
        "height": shape[0],
        "width": shape[1],
        "count": 1,
        "transform": transform,
    }
    paths = {}
    for name, data in (
        ("link", link),
        ("pointer", np.full(shape, 2, dtype=np.int32)),
        ("acc", np.arange(np.prod(shape), dtype=np.float32).reshape(shape)),
    ):
        paths[name] = tmp_path / f"{name}.tif"
        with rasterio.open(paths[name], "w", dtype=data.dtype, **profile) as dst:
            dst.write(data, 1)

    tree = read_channel_tree(
        link_tif=str(paths["link"]),
        pointer_tif=str(paths["pointer"]),
        accumulation_tif=str(paths["acc"]),
        bounds=(0.0, 100.0, 50.0, 150.0),
    )

    # Mesh bounds cover columns 10..14 and rows 5..9, plus one pixel of margin.
    assert tree.link.shape == (7, 7)
    assert tree.transform.c == pytest.approx(-10.0) and tree.transform.f == pytest.approx(160.0)
    assert np.argwhere(tree.link).tolist() == [[1, 3]]

    with rasterio.open(
        tmp_path / "shifted.tif", "w", dtype="int32", **{**profile, "width": shape[1] + 1}
    ) as dst:
        dst.write(np.zeros((shape[0], shape[1] + 1), dtype=np.int32), 1)
    with pytest.raises(ValueError, match="misaligned"):
        read_channel_tree(
            link_tif=str(paths["link"]),
            pointer_tif=str(tmp_path / "shifted.tif"),
            accumulation_tif=str(paths["acc"]),
            bounds=(0.0, 100.0, 50.0, 150.0),
        )


# -- The projection of A onto the cells ---------------------------------------


def _tree(shape: tuple[int, int], path: list[tuple[int, int]]) -> ChannelTree:
    """A raster tree along ``path`` (raster rows from the north), accumulation growing down it."""
    link = np.zeros(shape, dtype=bool)
    pointer = np.zeros(shape, dtype=np.int64)
    accumulation = np.ones(shape, dtype=float)
    for index, (row, col) in enumerate(path):
        link[row, col] = True
        accumulation[row, col] = 10.0 + index
        if index + 1 < len(path):
            nxt = path[index + 1]
            pointer[row, col] = _CODE_OF_STEP[(nxt[0] - row, nxt[1] - col)]
    return ChannelTree(
        link=link, pointer=pointer, accumulation=accumulation, transform=from_origin(0, 10, 1, 1)
    )


def _grid_labels(nrow: int, ncol: int) -> np.ndarray:
    """One cell per pixel, numbered row after row from the north, like a structured mesh."""
    return np.arange(nrow * ncol, dtype=np.int32).reshape(nrow, ncol)


def _cell(ncol: int, raster_row: int, col: int) -> int:
    return raster_row * ncol + col


def _project(tree, labels, *, routable=None, lake_of=None):
    n = labels.size if routable is None else routable.size
    exits = channel_exits(tree, labels, n_cells=n)
    return pin_channel(
        exits,
        routable=np.ones(n, dtype=bool) if routable is None else routable,
        lake_of=np.full(n, -1) if lake_of is None else lake_of,
    )


def test_a_staircase_of_a_pins_each_cell_to_the_next_one_on_a() -> None:
    nrow = ncol = 8
    path = [(1, 1), (1, 2), (2, 2), (2, 3), (3, 3), (3, 4), (4, 4), (5, 5), (6, 6)]
    cells = [_cell(ncol, r, c) for r, c in path]

    pinned, channel = _project(_tree((nrow, ncol), path), _grid_labels(nrow, ncol))

    assert np.flatnonzero(channel).tolist() == sorted(cells)
    assert [int(pinned[c]) for c in cells] == cells[1:] + [-1]
    assert np.all(pinned[~channel] == -1)


def test_the_exits_say_what_the_cells_hold_before_any_backend_choice() -> None:
    nrow, ncol = 6, 3
    path = [(r, 1) for r in range(1, 5)]
    cells = [_cell(ncol, r, c) for r, c in path]

    exits = channel_exits(_tree((nrow, ncol), path), _grid_labels(nrow, ncol), n_cells=nrow * ncol)

    assert exits.n_cells == nrow * ncol
    assert np.flatnonzero(exits.holds_a).tolist() == cells
    assert [int(exits.next_cell[c]) for c in cells] == cells[1:] + [-1]
    # The pointer of the last pixel of A is a pit, so it enters no other cell.
    assert exits.next_on_a[cells[:-1]].all() and not exits.next_on_a[cells[-1]]
    assert np.all(exits.next_cell[~exits.holds_a] == -1)
    for values in (exits.holds_a, exits.next_cell, exits.next_on_a):
        assert not values.flags.writeable


def test_the_exits_of_a_tree_with_no_pixel_take_an_empty_array_of_numbers() -> None:
    tree = _tree((4, 4), [])

    exits = channel_exits(tree, np.empty((0, 0), dtype=np.int32), n_cells=16)
    pinned, channel = pin_channel(exits, routable=np.ones(16, bool), lake_of=np.full(16, -1))

    assert exits.n_cells == 16 and not exits.holds_a.any()
    assert np.all(exits.next_cell == -1)
    assert np.all(pinned == -1) and not channel.any()


def test_a_tree_with_pixels_needs_a_raster_of_numbers_of_its_own_shape() -> None:
    tree = _tree((4, 4), [(1, 1), (2, 1)])

    with pytest.raises(ValueError, match="cell numbers have shape"):
        channel_exits(tree, np.empty((0, 0), dtype=np.int32), n_cells=16)


def test_pixels_outside_the_mesh_or_beyond_its_cells_hold_no_cell() -> None:
    nrow = ncol = 5
    labels = _grid_labels(nrow, ncol)
    labels[2, 2] = -1
    labels[3, 2] = nrow * ncol + 4
    path = [(1, 2), (2, 2), (3, 2), (4, 2)]

    pinned, channel = _project(_tree((nrow, ncol), path), labels, routable=np.ones(25, bool))

    assert np.flatnonzero(channel).tolist() == [_cell(ncol, 1, 2), _cell(ncol, 4, 2)]
    assert np.all(pinned == -1)


def test_a_leaves_through_a_lake_so_the_cell_above_it_is_an_outlet_of_a() -> None:
    nrow, ncol = 8, 5
    path = [(r, 2) for r in range(1, 7)]
    n = nrow * ncol
    lake_cell = _cell(ncol, 3, 2)
    lake_of = np.full(n, -1)
    lake_of[lake_cell] = 0
    above, below = _cell(ncol, 2, 2), _cell(ncol, 4, 2)

    pinned, channel = _project(
        _tree((nrow, ncol), path),
        _grid_labels(nrow, ncol),
        routable=np.ones(n, dtype=bool),
        lake_of=lake_of,
    )

    assert not channel[lake_cell]
    assert pinned[lake_cell] == -1
    assert lake_cell not in pinned.tolist()
    assert pinned[above] == -1
    assert channel[below] and pinned[below] == _cell(ncol, 5, 2)


def test_a_cell_off_the_graph_is_neither_a_channel_nor_a_pin() -> None:
    nrow, ncol = 6, 3
    path = [(r, 1) for r in range(1, 5)]
    n = nrow * ncol
    routable = np.ones(n, dtype=bool)
    off = _cell(ncol, 3, 1)
    routable[off] = False

    pinned, channel = _project(
        _tree((nrow, ncol), path), _grid_labels(nrow, ncol), routable=routable
    )

    assert not channel[off]
    assert pinned[_cell(ncol, 2, 1)] == -1
    assert off not in pinned.tolist()


@pytest.mark.parametrize("closed_by", ["inactive_column", "lake"])
def test_the_same_exits_give_other_pins_when_the_backend_closes_the_next_cell(
    closed_by: str,
) -> None:
    nrow, ncol = 6, 3
    path = [(r, 1) for r in range(1, 5)]
    n = nrow * ncol
    exits = channel_exits(_tree((nrow, ncol), path), _grid_labels(nrow, ncol), n_cells=n)
    cells = [_cell(ncol, r, c) for r, c in path]
    open_pinned, _ = pin_channel(exits, routable=np.ones(n, bool), lake_of=np.full(n, -1))
    routable, lake_of = np.ones(n, dtype=bool), np.full(n, -1)
    if closed_by == "lake":
        lake_of[cells[2]] = 1
    else:
        routable[cells[2]] = False

    pinned, channel = pin_channel(exits, routable=routable, lake_of=lake_of)

    assert [int(open_pinned[c]) for c in cells[:3]] == cells[1:4]
    assert not channel[cells[2]]
    assert pinned[cells[1]] == -1, "the pin onto the closed cell goes"
    assert pinned[cells[0]] == cells[1], "the pin between open cells stays"
    assert pinned[cells[3]] == -1, "the last pixel of A enters a cell that is not on A"


def test_a_lake_cell_stays_routable_for_the_graph_but_is_never_a_channel_cell() -> None:
    nrow, ncol = 5, 3
    path = [(r, 1) for r in range(0, 5)]
    n = nrow * ncol
    lake = _cell(ncol, 2, 1)
    lake_of = np.full(n, -1)
    lake_of[lake] = 0

    pinned, channel = _project(
        _tree((nrow, ncol), path),
        _grid_labels(nrow, ncol),
        routable=np.ones(n, dtype=bool),
        lake_of=lake_of,
    )

    assert not channel[lake]
    assert pinned[_cell(ncol, 3, 1)] == _cell(ncol, 4, 1)


def test_a_pointer_that_closes_a_loop_is_refused() -> None:
    nrow = ncol = 4
    tree = _tree((nrow, ncol), [(1, 1), (1, 2), (2, 2), (2, 1)])
    tree.pointer[2, 1] = _CODE_OF_STEP[(-1, 0)]  # back to (1, 1)

    with pytest.raises(ValueError, match="closes a loop"):
        _project(tree, _grid_labels(nrow, ncol))


def test_the_exits_and_the_masks_must_describe_the_same_cells() -> None:
    exits = channel_exits(_tree((4, 4), [(1, 1), (2, 1)]), _grid_labels(4, 4), n_cells=16)

    with pytest.raises(ValueError, match="hold 16 cells"):
        pin_channel(exits, routable=np.ones(15, bool), lake_of=np.full(16, -1))
    with pytest.raises(ValueError, match="one entry per cell"):
        ChannelExits(np.zeros(3, bool), np.zeros(4, int), np.zeros(3, bool))


def _brick_labels(nrow: int, n_bricks: int) -> np.ndarray:
    """Pixel numbers of rows of 2 x 1 bricks, every other row shifted by half a brick.

    One pixel is one metre, so a brick is two pixels wide. Mesh row 0 is the south
    row and raster row 0 the north one. A brick of a shifted row meets the bricks
    of the next row by a face only, like the cells of a Voronoi mesh.
    """
    width = 2 * n_bricks
    labels = np.zeros((nrow, width), dtype=np.int32)
    number = 0
    for mesh_row in range(nrow):
        edges = (
            list(range(0, width + 1, 2)) if mesh_row % 2 == 0 else [0, *range(1, width, 2), width]
        )
        for x0, x1 in zip(edges[:-1], edges[1:], strict=True):
            labels[nrow - 1 - mesh_row, x0:x1] = number
            number += 1
    return labels


def test_on_a_brick_mesh_a_runs_down_pinned_bricks() -> None:
    nrow, n_bricks = 8, 4
    labels = _brick_labels(nrow, n_bricks)
    n = int(labels.max()) + 1
    # A runs south down raster column 3, from row 1 to row 6.
    path = [(r, 3) for r in range(1, 7)]
    bricks = [int(labels[r, c]) for r, c in path]

    pinned, channel = _project(
        _tree((nrow, 2 * n_bricks), path), labels, routable=np.ones(n, dtype=bool)
    )

    assert len(set(bricks)) == len(bricks)
    assert np.flatnonzero(channel).tolist() == sorted(bricks)
    assert [int(pinned[b]) for b in bricks] == bricks[1:] + [-1]


# -- The two stages against the one stage they replace -------------------------


def _one_stage_projection(tree, labels, *, routable, lake_of):
    """``project_channel_tree`` as it stood before the two stages, the numbers given as an array."""
    on_graph = np.asarray(routable, dtype=bool).reshape(-1)
    lakes = np.asarray(lake_of, dtype=int).reshape(-1)
    n_cells = int(on_graph.size)
    pinned = np.full(n_cells, -1, dtype=int)
    channel = np.zeros(n_cells, dtype=bool)
    nrows, ncols = tree.link.shape
    if nrows == 0 or ncols == 0 or not np.any(tree.link):
        return pinned, channel

    labels = np.where(labels < n_cells, labels, -1)
    can_hold = on_graph & (lakes < 0)
    a_pixels = np.flatnonzero(tree.link.reshape(-1))
    a_labels = labels.reshape(-1)[a_pixels]
    keep = a_labels >= 0
    keep[keep] = can_hold[a_labels[keep]]
    a_pixels, a_labels = a_pixels[keep], a_labels[keep]
    if a_pixels.size == 0:
        return pinned, channel
    channel[a_labels] = True

    accumulation = tree.accumulation.reshape(-1)
    order = np.lexsort((accumulation[a_pixels], a_labels))
    sorted_labels = a_labels[order]
    last = np.r_[sorted_labels[1:] != sorted_labels[:-1], True]
    exit_pixel = dict(
        zip(sorted_labels[last].tolist(), a_pixels[order][last].tolist(), strict=True)
    )

    receivers = d8_receivers(tree.pointer, pit="none")
    flat_labels = labels.reshape(-1)
    flat_link = tree.link.reshape(-1)
    max_steps = nrows * ncols
    for cell, pixel in exit_pixel.items():
        current = int(pixel)
        for _ in range(max_steps):
            current = int(receivers[current])
            if current < 0:
                break
            other = int(flat_labels[current])
            if other == cell:
                continue
            if other >= 0 and flat_link[current] and channel[other]:
                pinned[cell] = other
            break
    state = np.zeros(pinned.size, dtype=np.int8)
    for start in np.flatnonzero(pinned >= 0).tolist():
        walk: list[int] = []
        cell = start
        while cell >= 0 and state[cell] == 0:
            state[cell] = 1
            walk.append(cell)
            cell = int(pinned[cell])
        if cell >= 0 and state[cell] == 1:
            raise ValueError(
                f"The channel tree A closes a loop through cell {cell} on the mesh: its D8 "
                "pointer and its accumulation disagree."
            )
        state[walk] = 2
    return pinned, channel


def _steepest_pointer(dem: np.ndarray) -> np.ndarray:
    nrows, ncols = dem.shape
    pointer = np.zeros(dem.shape, dtype=np.int64)
    best = np.zeros(dem.shape)
    for code, (d_row, d_col) in D8_WBT_OFFSETS.items():
        shifted = np.full(dem.shape, np.inf)
        r0, r1 = max(0, -d_row), min(nrows, nrows - d_row)
        c0, c1 = max(0, -d_col), min(ncols, ncols - d_col)
        shifted[r0:r1, c0:c1] = dem[r0 + d_row : r1 + d_row, c0 + d_col : c1 + d_col]
        drop = (dem - shifted) / np.hypot(d_row, d_col)
        better = drop > best
        pointer[better] = code
        best[better] = drop[better]
    return pointer


def _accumulation(pointer: np.ndarray, dem: np.ndarray) -> np.ndarray:
    receivers = d8_receivers(pointer, pit="none")
    accumulated = np.ones(pointer.size)
    for pixel in np.argsort(-dem.reshape(-1), kind="stable"):
        if receivers[pixel] >= 0:
            accumulated[receivers[pixel]] += accumulated[pixel]
    return accumulated.reshape(pointer.shape)


def _random_case(rng: np.random.Generator, kind: str):
    """A tree, cell numbers, a routable mask and lake numbers, with numbers off the mesh.

    ``dem`` cases carry the pointer and the accumulation of a random surface.
    The others carry any pointer, link and accumulation, which a loop may close.
    """
    nrows, ncols = int(rng.integers(1, 40)), int(rng.integers(1, 40))
    n_cells = int(rng.integers(1, 60))
    block = int(rng.integers(1, 6))
    coarse = rng.integers(-1, n_cells + 3, size=(nrows // block + 1, ncols // block + 1))
    labels = np.kron(coarse, np.ones((block, block), dtype=int))[:nrows, :ncols].astype(np.int32)
    if kind == "dem":
        dem = (
            rng.random((nrows, ncols))
            + np.add.outer(np.arange(nrows), np.arange(ncols)) * rng.random()
        )
        pointer = _steepest_pointer(dem)
        accumulation = _accumulation(pointer, dem)
        link = accumulation >= np.quantile(accumulation, rng.uniform(0.3, 1.0))
    else:
        pointer = rng.choice([0, 1, 2, 4, 8, 16, 32, 64, 128, -32768], size=(nrows, ncols))
        accumulation = rng.integers(0, 5, size=(nrows, ncols)).astype(float)
        link = rng.random((nrows, ncols)) < rng.uniform(0.0, 1.0)
    routable = rng.random(n_cells) < rng.uniform(0.2, 1.0)
    lake_of = np.where(rng.random(n_cells) < rng.uniform(0.0, 0.3), rng.integers(0, 3, n_cells), -1)
    tree = ChannelTree(link=link, pointer=pointer, accumulation=accumulation, transform=None)
    return tree, labels, n_cells, routable, lake_of


def _outcome(function, *args, **kwargs):
    try:
        return "ok", function(*args, **kwargs)
    except ValueError as exc:
        return "refused", str(exc)


def _two_stages(tree, labels, *, n_cells, routable, lake_of):
    exits = channel_exits(tree, labels, n_cells=n_cells)
    return pin_channel(exits, routable=routable, lake_of=lake_of)


def test_the_two_stages_give_the_pins_of_the_one_stage_on_seeded_random_cases() -> None:
    rng = np.random.default_rng(20261107)
    counts = {"equal": 0, "refused_by_both": 0, "pins": 0, "channel_cells": 0, "total": 0}
    for number in range(1200):
        tree, labels, n_cells, routable, lake_of = _random_case(
            rng, "dem" if number % 2 else "random"
        )
        before = _outcome(_one_stage_projection, tree, labels, routable=routable, lake_of=lake_of)
        after = _outcome(
            _two_stages, tree, labels, n_cells=n_cells, routable=routable, lake_of=lake_of
        )
        counts["total"] += 1
        assert after[0] == before[0], f"case {number} is {before[0]} before and {after[0]} after"
        if before[0] == "refused":
            assert after[1] == before[1], f"case {number} is refused with another message"
            counts["refused_by_both"] += 1
            continue
        np.testing.assert_array_equal(after[1][0], before[1][0], err_msg=f"pins of case {number}")
        np.testing.assert_array_equal(
            after[1][1], before[1][1], err_msg=f"channel of case {number}"
        )
        counts["equal"] += 1
        counts["pins"] += int((before[1][0] >= 0).sum())
        counts["channel_cells"] += int(before[1][1].sum())

    assert counts["total"] >= 200
    assert counts["refused_by_both"] > 0, "no case closes a loop, so the refusal is not compared"
    assert counts["pins"] > 1000 and counts["channel_cells"] > 1000
