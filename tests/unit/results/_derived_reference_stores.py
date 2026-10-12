"""Small synthetic run stores the derived fields are checked on.

Each store is built with store calls that exist at d5f485f88 and at HEAD, and
is deterministic: the base code and the current code read the very same store.
``fixtures/derived_at_d5f485f88/<kind>.npz`` holds what the base code derived
on each of them (``gen_reference_d5f485f88.py`` writes those files).

The stores are written in ``exact`` precision, so a derived field written then
read back by the base chain (``mass_seepage`` reads ``concentration_seepage``)
sees the values it wrote.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import numpy as np

from hydromodpy.core.descent import build_descent

NROW = 5
NCOL = 7
N_CELLS = NROW * NCOL
N_STEPS = 6
BAND_DEPTH_M = 0.5

STORE_KINDS = (
    "mf6",
    "mf6_no_descent",
    "boussinesq",
    "boussinesq_no_excess",
    "transport",
    "no_route",
)
"""The stores: MODFLOW 6 with D, without D, Boussinesq with and without surface excess,
MODFLOW 6 with a concentration, and a store that can route nothing."""

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "derived_at_d5f485f88"


def fixture_path(kind: str) -> Path:
    """Return the file holding what the base code derived on store ``kind``."""
    return FIXTURE_DIR / f"{kind}.npz"


def sim_id_of(kind: str) -> str:
    """Return the fixed run id of store ``kind``."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"hmp-derived-reference/{kind}"))


def _quad_mesh() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return vertices, face-node connectivity and centroids of the unit quad grid."""
    nodes_per_row = NCOL + 1
    rows = np.arange(NROW)[:, None]
    cols = np.arange(NCOL)[None, :]
    corner = (rows * nodes_per_row + cols).reshape(-1)
    connectivity = np.column_stack(
        [corner, corner + 1, corner + nodes_per_row + 1, corner + nodes_per_row]
    )
    xx, yy = np.meshgrid(np.arange(NCOL + 1, dtype="float64"), np.arange(NROW + 1, dtype="float64"))
    vertices = np.column_stack([xx.ravel(), yy.ravel(), np.zeros(xx.size)])
    cell_rows, cell_cols = np.divmod(np.arange(N_CELLS), NCOL)
    centroids = np.column_stack([cell_cols + 0.5, cell_rows + 0.5]).astype(float)
    return vertices, connectivity.astype("int32"), centroids


def _top(rng: np.random.Generator) -> np.ndarray:
    """A valley that opens to the last row, with a little noise so no two cells tie."""
    rows, cols = np.divmod(np.arange(N_CELLS), NCOL)
    valley = 0.8 * np.abs(cols - NCOL // 2) + 0.6 * (NROW - 1 - rows)
    return 20.0 + valley + rng.uniform(0.0, 0.05, N_CELLS)


def _heads(rng: np.random.Generator, top: np.ndarray, n_layers: int) -> np.ndarray:
    """Heads around the surface: some cells above it, a few dry in the first layer."""
    depth = rng.uniform(-0.4, 2.0, (N_STEPS, N_CELLS))
    head = np.repeat((top - depth)[:, None, :], n_layers, axis=1)
    head -= 0.5 * np.arange(n_layers)[None, :, None]
    if n_layers > 1:
        head[:, 0, [3, 11]] = np.nan
        head[2, 0, 20] = np.nan
    head[4, -1, 7] = np.nan
    return head


def _budget(
    rng: np.random.Generator, n_layers: int, *, solver_terms: bool
) -> dict[str, np.ndarray]:
    """Budget terms with MODFLOW signs: outflow negative. Some cells positive or NaN."""
    shape = (N_STEPS, n_layers, N_CELLS)
    drain = -rng.uniform(0.0, 2e-3, shape)
    drain[:, :, ::5] = 0.0
    drain[1, :, 4] = 1e-4
    drain[3, 0, 9] = np.nan
    # One step whose every drain value is positive: the fallback of the sign convention.
    drain[4] = np.abs(drain[4]) + 1e-5
    budget = {"drain": drain, "recharge": rng.uniform(0.0, 1e-4, shape)}
    if solver_terms:
        mover = -rng.uniform(0.0, 5e-4, shape)
        mover[:, :, ::3] = 0.0
        budget["drain_to_mover"] = mover
        budget["stream"] = rng.uniform(-3e-3, 1e-3, shape)
        constant_head = rng.uniform(-1e-3, 1e-3, shape)
        constant_head[2, :, 6] = np.nan
        budget["constant_head_stream"] = constant_head
    return budget


def _write_descent(store, top: np.ndarray) -> None:
    vertices, connectivity, centroids = _quad_mesh()
    built = build_descent(
        top,
        connectivity,
        vertices=vertices,
        centroids=centroids,
        routable=np.ones(N_CELLS, dtype=bool),
    )
    store.write_descent(
        receiver=built.receiver,
        surface=built.surface,
        base_level=built.base_level,
        constant_head=built.constant_head,
        raised=built.raised,
        channel=built.channel,
        pinned=built.pinned,
        attrs={},
    )


def build_store(kind: str, catalog) -> str:
    """Write store ``kind`` in ``catalog`` and return its run id.

    ``mf6`` is a two-layer MODFLOW 6 run with its mesh, its D, a drain, a
    drain-to-mover, a stream and a constant-head term, and a drain band.
    ``mf6_no_descent`` is the same without D. ``boussinesq`` is a one-layer run
    with a top and no face connectivity, its D, a ``boussinesq_state`` group and
    a surface excess; ``boussinesq_no_excess`` lacks the excess, so the seepage
    falls back to the geometric criterion. ``transport`` is ``mf6`` with a
    concentration. ``no_route`` has no D and no mesh topology, and takes its
    surface from ``z_interfaces``.
    """
    if kind not in STORE_KINDS:
        raise ValueError(f"unknown store {kind!r}: expected one of {STORE_KINDS}")
    rng = np.random.default_rng(sum(map(ord, kind)))
    boussinesq = kind.startswith("boussinesq")
    n_layers = 1 if boussinesq else 2
    top = _top(rng)
    sim_id = sim_id_of(kind)
    registered = catalog.register_simulation(
        sim_id,
        project="derived-reference",
        solver="boussinesq" if boussinesq else "modflow6",
        n_cells=N_CELLS,
        n_layers=n_layers,
        n_timesteps=N_STEPS,
    )
    registered.zarr.close()
    # Without a top, the surface is z_interfaces[0]: put it where some heads reach it.
    surface = top.mean() if kind == "no_route" else top.max() + 1.0
    z_interfaces = surface - 10.0 * np.arange(n_layers + 1)
    head = _heads(rng, top, n_layers)
    budget = _budget(rng, n_layers, solver_terms=not boussinesq)

    store = catalog.open_zarr(sim_id)
    try:
        if boussinesq:
            store.write_topography(top, z_interfaces=z_interfaces, n_cells=N_CELLS, n_layers=1)
            _write_descent(store, top)
            head = head[:, 0, :]
            budget = {name: values[:, 0, :] for name, values in budget.items()}
            budget["surface_excess"] = np.where(
                rng.uniform(size=(N_STEPS, N_CELLS)) < 0.3, 1e-4, 0.0
            )
            budget["surface_excess"][1, 5] = -2e-5
            store.root.create_group("boussinesq_state")
            if kind == "boussinesq_no_excess":
                del budget["surface_excess"]
        else:
            vertices, connectivity, _ = _quad_mesh()
            with_topography = kind != "no_route"
            store.write_mesh(
                vertices,
                connectivity,
                z_interfaces,
                topography=top if with_topography else None,
            )
            if kind in ("mf6", "transport"):
                _write_descent(store, top)
            store.drain_band_depth_m = BAND_DEPTH_M
        store.write_field_stack("head", head)
        for name, values in budget.items():
            store.write_field_stack(name, values, subgroup="budget")
        if kind == "transport":
            concentration = rng.uniform(0.0, 5.0, (N_STEPS, n_layers, N_CELLS))
            concentration[:, 0, 2] = np.nan
            store.write_field_stack("concentration", concentration)
    finally:
        store.close()
    return sim_id
