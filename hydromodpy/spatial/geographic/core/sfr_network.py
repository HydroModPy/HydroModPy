"""Delineate a MODFLOW 6 SFR reach network from DEM-derived flow products.

Turns the raster products built by :mod:`river_network` (the stream-link-id
raster, the D8 pointer, the flow accumulation and the corrected DEM) into an
ordered, explicitly-connected reach table -- the :class:`SfrReachTrace`.

The output is grid-independent geometry: each reach is a LineString (in the
projected model CRS) plus its hydraulic attributes (length, streambed top,
gradient, Strahler order, drainage area) and its signed connectivity to the other
reaches. The mapping of a reach onto the DISV solver mesh (the cellids) is done
later in the solver builder, because the SFR grid (MODFLOW DISV) generally
differs from the DEM raster grid; this module never imports flopy or the mesh.

Algorithm (no recursion, no segment renumbering -- a clean reach-only DAG):

1. Each stream link (one id in the link raster) is one reach candidate.
2. The downstream end of a link is its cell whose D8 neighbour leaves the link;
   following the pointer there gives the unique downstream reach (or the lake, or
   the model outlet).
3. A Kahn topological sort numbers the reaches downstream-increasing (``ifno``),
   so a reach always has a smaller ``ifno`` than the reach it feeds.
4. Per-reach geometry is sampled along the link's flow path; reach tops are
   conditioned to descend monotonically downstream so the solver never stalls on
   a flat or a reversed bed.

The network is lake-independent: pass ``lake_mask=None`` and every terminal reach
simply leaves the model.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np
from shapely.geometry import LineString

# WhiteboxTools D8 pointer encoding (esri_pntr=False): each cell stores the power
# of two pointing at its single downslope neighbour. Map a code to (drow, dcol).
_WBT_D8_OFFSETS: dict[int, tuple[int, int]] = {
    1: (0, 1),  # E
    2: (1, 1),  # SE
    4: (1, 0),  # S
    8: (1, -1),  # SW
    16: (0, -1),  # W
    32: (-1, -1),  # NW
    64: (-1, 0),  # N
    128: (-1, 1),  # NE
}


@dataclass(frozen=True, slots=True)
class SfrReachRow:
    """One delineated reach, downstream-increasing ``ifno`` (0-based).

    ``line`` is the reach polyline in the projected model CRS (head -> outlet).
    ``upstream`` / ``downstream`` hold the 0-based ``ifno`` of the connected
    reaches. ``is_terminal_to_lake`` flags the reach whose flow enters the lake;
    its outflow is handed to LAK by the solver builder through an MVR record.
    ``terminal_lake`` is the 1-based number of the lake that reach drains into
    (from the labeled lake mask), or ``None`` for a bare outlet that drains to no
    specific lake; the builder routes the MVR to it, falling back to the network
    ``outflow_to_lake`` when it is ``None``.
    """

    ifno: int
    line: LineString
    rlen: float
    rtp: float
    rgrd: float
    strahler: int
    area_km2: float
    upstream: tuple[int, ...]
    downstream: tuple[int, ...]
    is_terminal_to_lake: bool
    terminal_lake: int | None = None


@dataclass(frozen=True, slots=True)
class SfrReachTrace:
    """Ordered, explicitly-connected reach network for one SFR package."""

    reaches: tuple[SfrReachRow, ...]
    crs_wkt: str

    @property
    def reach_count(self) -> int:
        return len(self.reaches)


def _downstream_cell(row: int, col: int, d8: np.ndarray) -> tuple[int, int] | None:
    """Return the D8 neighbour of (row, col), or None at a pit / out of bounds."""
    code = int(d8[row, col])
    offset = _WBT_D8_OFFSETS.get(code)
    if offset is None:
        return None
    nrow, ncol = row + offset[0], col + offset[1]
    if 0 <= nrow < d8.shape[0] and 0 <= ncol < d8.shape[1]:
        return nrow, ncol
    return None


def _trace_downstream_target(
    outlet: tuple[int, int],
    d8: np.ndarray,
    link_id: np.ndarray,
    lake: np.ndarray | None,
    this_link: int,
    max_steps: int = 2000,
) -> tuple[str, tuple[int, int] | None]:
    """Follow the D8 path below a link outlet through non-stream gap cells.

    The WBT stream-link raster can drop cells (a link_id gap) between two links
    or just short of the lake, which would leave the reach a spurious inland
    outlet. Walking the D8 pointer past those gap cells reunites the fragment
    with its true continuation. Returns ('lake', cell), ('link', cell) at the
    first lake cell or different stream link reached, else ('none', None) when
    the path leaves the domain, hits a pit, or cycles.
    """
    step = _downstream_cell(outlet[0], outlet[1], d8)
    seen: set[tuple[int, int]] = set()
    steps = 0
    while step is not None and steps < max_steps:
        if step in seen:
            break
        seen.add(step)
        if lake is not None and lake[step]:
            return "lake", step
        lid = int(link_id[step])
        if lid > 0 and lid != this_link:
            return "link", step
        step = _downstream_cell(step[0], step[1], d8)
        steps += 1
    return "none", None


def _cell_xy(row: int, col: int, transform) -> tuple[float, float]:
    """Return the projected (x, y) centroid of a raster cell via its affine."""
    x, y = transform * (col + 0.5, row + 0.5)
    return float(x), float(y)


def _order_link_cells(cells: list[tuple[int, int]], d8: np.ndarray) -> list[tuple[int, int]]:
    """Order one link's cells from headwater to outlet by following the D8 path."""
    cell_set = set(cells)
    # The head cell has no in-link upstream (no other cell points into it).
    has_upstream = set()
    for cell in cells:
        nxt = _downstream_cell(cell[0], cell[1], d8)
        if nxt is not None and nxt in cell_set:
            has_upstream.add(nxt)
    heads = [cell for cell in cells if cell not in has_upstream]
    start = heads[0] if heads else cells[0]
    ordered: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    cur: tuple[int, int] | None = start
    while cur is not None and cur in cell_set and cur not in seen:
        ordered.append(cur)
        seen.add(cur)
        cur = _downstream_cell(cur[0], cur[1], d8)
    # Any cell not reached by the walk (disconnected fragment) is appended stably.
    for cell in cells:
        if cell not in seen:
            ordered.append(cell)
    return ordered


def _link_outlet_cell(
    ordered_cells: list[tuple[int, int]], d8: np.ndarray, cell_set: set[tuple[int, int]]
) -> tuple[int, int]:
    """Return the link's outlet cell (its D8 neighbour leaves the link)."""
    for cell in reversed(ordered_cells):
        nxt = _downstream_cell(cell[0], cell[1], d8)
        if nxt is None or nxt not in cell_set:
            return cell
    return ordered_cells[-1]


def delineate_sfr_reaches(
    *,
    link_id: np.ndarray,
    d8: np.ndarray,
    acc: np.ndarray,
    dem: np.ndarray,
    transform,
    crs_wkt: str,
    dem_res_m: float,
    strahler: np.ndarray | None = None,
    lake_mask: np.ndarray | None = None,
    min_slope: float = 1e-4,
    min_reach_length_m: float = 0.0,
) -> SfrReachTrace:
    """Delineate an ordered SFR reach network from aligned flow-product rasters.

    All arrays share one (rows, cols) grid and the ``transform`` affine. ``link_id``
    marks stream cells with a positive link id (0 / negative = non-stream).
    ``acc`` is the D8 flow accumulation in cell counts. ``lake_mask`` (optional)
    labels lake cells with the 1-based lake number (0 elsewhere); a plain boolean
    mask also works (every lake then reads as lake 1). The reach flowing into a
    lake is flagged terminal-to-lake and tagged with that lake number.
    """
    if link_id.shape != d8.shape or link_id.shape != dem.shape:
        raise ValueError("link_id, d8 and dem must share one grid shape.")
    cell_area_km2 = float(dem_res_m) * float(dem_res_m) / 1_000_000.0
    lake_label = None if lake_mask is None else np.asarray(lake_mask)
    lake = None if lake_label is None else (lake_label > 0)

    # 1. Group stream cells by link id.
    cells_by_link: dict[int, list[tuple[int, int]]] = {}
    rows, cols = np.where(link_id > 0)
    for row, col in zip(rows.tolist(), cols.tolist(), strict=True):
        cells_by_link.setdefault(int(link_id[row, col]), []).append((row, col))
    if not cells_by_link:
        raise ValueError("No stream cells (link_id > 0); cannot delineate an SFR network.")

    # 2. Per-link geometry + the downstream link (or lake / model outlet). A
    # link whose flow path ENTERS the lake footprint is truncated at the entry
    # cell (the raster network continues through / below a reservoir, but the
    # reach must stop at the shoreline and hand its flow to the lake); a link
    # entirely inside the lake is dropped.
    info: dict[int, dict] = {}
    downstream_link: dict[int, int | None] = {}
    terminal_to_lake: dict[int, bool] = {}
    terminal_lake_of: dict[int, int | None] = {}
    for link, cells in cells_by_link.items():
        ordered = _order_link_cells(cells, d8)
        truncated_at_lake = False
        truncation_lake_cell: tuple[int, int] | None = None
        if lake is not None:
            kept: list[tuple[int, int]] = []
            for cell in ordered:
                if lake[cell]:
                    truncated_at_lake = True
                    truncation_lake_cell = cell
                    break
                kept.append(cell)
            ordered = kept
        if not ordered:
            continue
        cell_set = set(ordered)
        outlet = ordered[-1] if truncated_at_lake else _link_outlet_cell(ordered, d8, cell_set)
        head = ordered[0]
        coords = [_cell_xy(r, c, transform) for r, c in ordered]
        if len(coords) == 1:
            nxt = _downstream_cell(outlet[0], outlet[1], d8)
            tail = (
                _cell_xy(*nxt, transform)
                if nxt is not None
                else (coords[0][0] + dem_res_m, coords[0][1])
            )
            coords = [coords[0], tail]
        line = LineString(coords)
        rlen = max(float(line.length), float(dem_res_m))
        top_head = float(dem[head])
        top_outlet = float(dem[outlet])
        rgrd = max((top_head - top_outlet) / rlen, float(min_slope))
        order_val = 1 if strahler is None else int(max(1, int(strahler[outlet])))
        area_km2 = float(acc[outlet]) * cell_area_km2

        nxt = _downstream_cell(outlet[0], outlet[1], d8)
        is_lake = bool(lake is not None and nxt is not None and lake[nxt])
        if truncated_at_lake or is_lake:
            downstream_link[link] = None
            terminal_to_lake[link] = True
            # Tag the specific lake this reach drains into (1-based label) so the
            # builder can route the MVR per terminal reach instead of per network.
            lake_cell = truncation_lake_cell if truncated_at_lake else nxt
            if lake_label is not None and lake_cell is not None:
                terminal_lake_of[link] = int(lake_label[lake_cell])
        elif nxt is not None and int(link_id[nxt]) > 0 and int(link_id[nxt]) != link:
            downstream_link[link] = int(link_id[nxt])
            terminal_to_lake[link] = False
        else:
            # The immediate D8 neighbour is a non-stream gap cell (or None). Follow
            # the D8 path through the gap: WBT link rasters drop cells between links
            # and short of the lake, so a fragment that looks like an inland outlet
            # usually continues to its true downstream link or to the lake a few
            # cells on. Only a path that genuinely leaves the domain is a true bare
            # outlet, and that leaves the model by EXT-OUTFLOW (not teleported to
            # the lake from mid-catchment).
            kind, target = _trace_downstream_target(outlet, d8, link_id, lake, link)
            if kind == "lake":
                downstream_link[link] = None
                terminal_to_lake[link] = True
                if lake_label is not None and target is not None:
                    terminal_lake_of[link] = int(lake_label[target])
            elif kind == "link":
                downstream_link[link] = int(link_id[target])
                terminal_to_lake[link] = False
            else:
                # A genuine bare outlet: the D8 path leaves the domain / pits without
                # reaching a link or lake. The solver mover builder decides its fate
                # (nearest lake in a lake-coupled catchment, else EXT-OUTFLOW), where
                # the final reach geometry and the lake cells are known.
                downstream_link[link] = None
                terminal_to_lake[link] = False

        info[link] = {
            "line": line,
            "rlen": rlen,
            "rtp": top_outlet,
            "rgrd": rgrd,
            "strahler": order_val,
            "area_km2": area_km2,
        }

    # 2b. Prune short reaches (re-link their upstream to their downstream).
    if float(min_reach_length_m) > 0.0:
        _prune_short_links(
            info, downstream_link, terminal_to_lake, terminal_lake_of, float(min_reach_length_m)
        )

    # 3. Upstream adjacency + Kahn topological order, downstream-increasing.
    upstream_links: dict[int, list[int]] = {link: [] for link in info}
    for link, down in downstream_link.items():
        if down is not None and down in upstream_links:
            upstream_links[down].append(link)
    order = _topological_downstream_order(info, downstream_link, upstream_links)

    ifno_of = {link: ifno for ifno, link in enumerate(order)}

    # 4. Monotone-downhill conditioning of reach tops along the order.
    rtp = {link: info[link]["rtp"] for link in order}
    drop = float(dem_res_m) * float(min_slope)
    for link in order:
        down = downstream_link.get(link)
        if down is not None and down in rtp and rtp[down] >= rtp[link]:
            rtp[down] = rtp[link] - drop

    reaches: list[SfrReachRow] = []
    for link in order:
        data = info[link]
        down = downstream_link.get(link)
        # A downstream link dropped at delineation (entirely inside the lake)
        # leaves no reach to connect to.
        downstream_ids = () if down is None or down not in ifno_of else (ifno_of[down],)
        upstream_ids = tuple(sorted(ifno_of[u] for u in upstream_links[link]))
        reaches.append(
            SfrReachRow(
                ifno=ifno_of[link],
                line=data["line"],
                rlen=data["rlen"],
                rtp=rtp[link],
                rgrd=data["rgrd"],
                strahler=data["strahler"],
                area_km2=data["area_km2"],
                upstream=upstream_ids,
                downstream=downstream_ids,
                is_terminal_to_lake=bool(terminal_to_lake.get(link, False)),
                terminal_lake=terminal_lake_of.get(link),
            )
        )
    return SfrReachTrace(reaches=tuple(reaches), crs_wkt=str(crs_wkt))


def _prune_short_links(
    info: dict[int, dict],
    downstream_link: dict[int, int | None],
    terminal_to_lake: dict[int, bool],
    terminal_lake_of: dict[int, int | None],
    min_length_m: float,
) -> None:
    """Drop reaches shorter than ``min_length_m``, re-linking around them."""
    short = [link for link, data in info.items() if data["rlen"] < min_length_m]
    for link in short:
        down = downstream_link.get(link)
        for upstream, target in downstream_link.items():
            if target == link:
                downstream_link[upstream] = down
                if down is None:
                    terminal_to_lake[upstream] = terminal_to_lake.get(link, False)
                    terminal_lake_of[upstream] = terminal_lake_of.get(link)
        info.pop(link, None)
        downstream_link.pop(link, None)
        terminal_to_lake.pop(link, None)
        terminal_lake_of.pop(link, None)


def _topological_downstream_order(
    info: dict[int, dict],
    downstream_link: dict[int, int | None],
    upstream_links: dict[int, list[int]],
) -> list[int]:
    """Kahn topological sort so upstream reaches precede their downstream reach."""
    indegree = {link: len(upstream_links[link]) for link in info}
    queue = deque(sorted(link for link, deg in indegree.items() if deg == 0))
    order: list[int] = []
    while queue:
        link = queue.popleft()
        order.append(link)
        down = downstream_link.get(link)
        if down is not None and down in indegree:
            indegree[down] -= 1
            if indegree[down] == 0:
                queue.append(down)
    if len(order) != len(info):
        # A cycle should not occur on a D8 tree; fall back to a stable order.
        order = list(info)
    return order


def build_sfr_reach_trace_from_products(
    *,
    stream_link_id_full_tif: str,
    d8_pointer_tif: str,
    flow_acc_cells_tif: str,
    dem_correc_tif: str,
    dem_res_m: float,
    stream_order_strahler_full_tif: str | None = None,
    lake_polygons: list | None = None,
    watershed_polygons: list | None = None,
    min_slope: float = 1e-4,
    min_reach_length_m: float = 0.0,
) -> SfrReachTrace:
    """Read the FULL DEM-grid flow rasters and delineate the SFR reach trace.

    All four rasters must share one affine and shape (the clipped per-watershed
    rasters have a different extent and are rejected). ``lake_polygons`` (model
    CRS) are rasterized onto the grid so the reach flowing into a lake is
    flagged terminal-to-lake. ``watershed_polygons`` (model CRS) restrict the
    stream links to the modelled catchment: the full-grid link raster covers
    the whole regional DEM and the out-of-watershed links belong to other
    catchments, outside the solver mesh.
    """
    import rasterio
    from rasterio import features

    arrays: dict[str, np.ndarray] = {}
    reference: tuple[str, object, tuple[int, int]] | None = None
    transform = None
    crs_wkt = ""
    sources = {
        "stream_link_id_full": stream_link_id_full_tif,
        "d8_pointer": d8_pointer_tif,
        "flow_acc_cells": flow_acc_cells_tif,
        "dem_correc": dem_correc_tif,
    }
    if stream_order_strahler_full_tif is not None:
        sources["stream_order_strahler_full"] = stream_order_strahler_full_tif
    for name, path in sources.items():
        with rasterio.open(path) as dataset:
            data = dataset.read(1)
            if reference is None:
                reference = (name, dataset.transform, data.shape)
                transform = dataset.transform
                crs_wkt = "" if dataset.crs is None else dataset.crs.to_wkt()
            elif dataset.transform != reference[1] or data.shape != reference[2]:
                raise ValueError(
                    f"SFR delineation rasters are misaligned: '{name}' ({path}) does "
                    f"not share the grid of '{reference[0]}'. Use the *_full.tif "
                    "DEM-grid products, never the clipped per-watershed rasters."
                )
            arrays[name] = data

    lake_mask = None
    polygons = [polygon for polygon in (lake_polygons or []) if polygon is not None]
    if polygons:
        # Burn each lake with its 1-based number (its position in lake_polygons,
        # which the caller passes in LAK packagedata order) so each reach can be
        # tagged with the specific lake it drains into. A later lake wins on the
        # rare overlap, which is harmless for the disjoint footprints SFR sees.
        lake_mask = features.rasterize(
            ((polygon, index) for index, polygon in enumerate(polygons, start=1)),
            out_shape=reference[2],
            transform=transform,
            fill=0,
            dtype="int32",
        )

    link_id = np.nan_to_num(arrays["stream_link_id_full"], nan=0.0).astype(int)
    catchment = [polygon for polygon in (watershed_polygons or []) if polygon is not None]
    if catchment:
        watershed_mask = features.rasterize(
            ((polygon, 1) for polygon in catchment),
            out_shape=reference[2],
            transform=transform,
            fill=0,
            dtype="uint8",
        ).astype(bool)
        link_id = np.where(watershed_mask, link_id, 0)

    return delineate_sfr_reaches(
        link_id=link_id,
        d8=np.nan_to_num(arrays["d8_pointer"], nan=0.0).astype(int),
        acc=np.nan_to_num(arrays["flow_acc_cells"], nan=0.0),
        dem=arrays["dem_correc"].astype(float),
        transform=transform,
        crs_wkt=crs_wkt,
        dem_res_m=float(dem_res_m),
        strahler=(
            np.nan_to_num(arrays["stream_order_strahler_full"], nan=0.0).astype(int)
            if "stream_order_strahler_full" in arrays
            else None
        ),
        lake_mask=lake_mask,
        min_slope=float(min_slope),
        min_reach_length_m=float(min_reach_length_m),
    )


__all__ = [
    "SfrReachRow",
    "SfrReachTrace",
    "build_sfr_reach_trace_from_products",
    "delineate_sfr_reaches",
]
