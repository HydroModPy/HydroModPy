"""The one place workflow asks the product store, and the table of products.

A pipeline step computes a stage product (the mesh, the output of the soil
reservoir) and keeps it in ``.hmp/products/``, keyed by what it read and by
the code that computes it. ``ask`` is the only caller of the store on the path
of a run: it reads a present product, builds and stores a missing one, and
returns the built object in memory either way, so a store that fails on disk
never fails a run. ``ask`` records the key in ``setup.products`` only.
``write_products`` writes them into ``products.json`` of the run the solver
step prepares, so a facade verb called after a run never touches a sealed run.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

from hydromodpy.core.exceptions import MeshError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.run_state import WorkflowContext
from hydromodpy.results.manifest import is_sealed
from hydromodpy.results.products.cited import (
    CitedProduct,
    alive_keys,
    read_cited,
    write_cited,
)
from hydromodpy.results.products.key import product_key
from hydromodpy.results.products.store import ProductStore, products_root

if TYPE_CHECKING:
    from hydromodpy.catchment.algorithms.flow_products import TerrainSupply

logger = get_logger(__name__)

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ProductKind:
    """One kind of stage product and how it is written.

    ``package`` is the layer that computes it, and its closure enters the key.
    ``step`` is the pipeline step that asks for it. ``write`` drops the built
    object into a directory. The version of the stored format is the
    ``SCHEMA_VERSION`` of the codec module, which the key builder reads.
    """

    package: str
    step: str
    write: Callable[[Any, Path], None]


def _write_mesh(value: Any, directory: Path) -> None:
    from hydromodpy.mesh.stored import write_mesh

    write_mesh(value, directory)


def _write_soil(value: Any, directory: Path) -> None:
    from hydromodpy.model.forcing.soil_stored import write_soil_forcings

    write_soil_forcings(value, directory)


def _write_terrain(value: Any, directory: Path) -> None:
    from hydromodpy.catchment.algorithms.terrain_stored import write_terrain

    write_terrain(value, directory)


PRODUCT_KINDS: Mapping[str, ProductKind] = {
    "mesh": ProductKind(package="mesh", step="build_mesh", write=_write_mesh),
    "soil": ProductKind(package="model", step="load_data", write=_write_soil),
    "terrain": ProductKind(package="catchment", step="build_geographic", write=_write_terrain),
    "terrain_notched": ProductKind(
        package="catchment", step="build_geographic", write=_write_terrain
    ),
}
"""The stage products of a run, keyed by kind.

The two terrain kinds hold the same three rasters, the notched one built on the
crossing notch, because the store never writes over a product.
"""


def terrain_supply(ctx: WorkflowContext) -> TerrainSupply:
    """Return the store-backed provider the geographic build hands to the pipeline.

    The key reads the DEM digest, the processing facts of the request, the
    terrain engine and the code of ``catchment``, and the codec is the stored
    format version. On a miss the store writes the built stack, on a hit it is
    read back into the request's output folder.
    """
    from hydromodpy.catchment.algorithms.flow_products import FlowProducts, TerrainRequest
    from hydromodpy.catchment.algorithms.terrain_stored import SCHEMA_VERSION, read_terrain

    def supply(request: TerrainRequest, build: Callable[[], FlowProducts]) -> FlowProducts:
        kind = "terrain_notched" if request.notched else "terrain"
        entry = PRODUCT_KINDS[kind]
        key = product_key(
            kind,
            codec=SCHEMA_VERSION,
            package=entry.package,
            inputs={"dem": request.dem_sha256},
            processing=request.processing(),
            engine=dict(request.engine),
        )
        return ask(
            ctx,
            kind,
            key=key,
            build=build,
            read=lambda directory: read_terrain(directory, request),
        )

    return supply


def ask(
    ctx: WorkflowContext,
    kind: str,
    *,
    key: str,
    build: Callable[[], T],
    read: Callable[[Path], T],
    rebuild_differs: bool = False,
) -> T:
    """Return the product ``kind`` of ``key``, building it on a miss.

    A resumed run first asks the store for the key its ``products.json`` cites
    for the kind, and says so when it differs from the recomputed one. A
    present product is read; an unreadable one is discarded and counts as a
    miss. On a miss the step builds the object from the current inputs, and
    the product is stored and cited under the recomputed ``key``, never under
    the cited one, whose description it may not match. ``rebuild_differs`` is
    True for a builder that cannot rebuild bit for bit, and a resume that
    rebuilds such a product says so. Outside a lightweight trial the store
    keeps the product under the workspace cap.
    """
    entry = PRODUCT_KINDS[kind]
    store = _store_for(ctx)
    cited = None
    if ctx.execution.resumed and ctx.run_dir is not None:
        cited = _cited_key(ctx.run_dir, kind)
        if cited is not None and cited != key:
            logger.info("products.resume kind=%s recomputed=%s cited=%s", kind, key, cited)
            value = _read_present(store, kind, cited, read)
            if value is not None:
                _cite(ctx, kind, cited)
                return value[0]
            logger.warning(
                "products.cited_gone kind=%s cited=%s: built again under %s", kind, cited, key
            )

    value = _read_present(store, kind, key, read)
    if value is not None:
        _cite(ctx, kind, key)
        return value[0]

    built = build()
    if ctx.execution.resumed and rebuild_differs:
        logger.warning(
            "The stored product of this request is gone (%s, %s); building again "
            "gives one that differs from the one the earlier results were computed on.",
            kind,
            cited or key,
        )
    if store is not None and not ctx.execution.lightweight:
        try:
            store.put(key, kind, lambda directory: entry.write(built, directory))
        except OSError:
            logger.warning(
                "products.store_failed kind=%s key=%s: the product is kept in memory only.",
                kind,
                key,
            )
        else:
            _evict(ctx, store, key)
    _cite(ctx, kind, key)
    return built


def _read_present(
    store: ProductStore | None, kind: str, key: str, read: Callable[[Path], T]
) -> tuple[T] | None:
    """Read the product of ``key`` when the store holds it, discarding an unreadable one."""
    if store is None or (hit := store.get(key)) is None:
        return None
    try:
        return (read(hit),)
    except (MeshError, ValueError, OSError):
        logger.warning("products.unreadable kind=%s key=%s", kind, key)
        store.discard(key)
        return None


def _evict(ctx: WorkflowContext, store: ProductStore, key: str) -> None:
    """Evict down to the cap, keeping every key a running run cites.

    A running run whose ``products.json`` cannot be read may cite any key, so
    nothing is evicted then.
    """
    try:
        alive = alive_keys(ctx.cfg.workspace.project_root)
    except ValueError as exc:
        logger.warning("products.evict_skipped: a running run cites unreadable products (%s)", exc)
        return
    store.evict(ctx.cfg.workspace.products_cap_mb * 1_000_000, keep=alive | {key})


def _cited_key(run_dir: Path, kind: str) -> str | None:
    for product in read_cited(run_dir):
        if product.kind == kind:
            return product.key
    return None


def _store_for(ctx: WorkflowContext) -> ProductStore | None:
    if ctx.setup.workspace is None:
        return None
    return ProductStore(products_root(ctx.cfg.workspace.project_root))


def _cite(ctx: WorkflowContext, kind: str, key: str) -> None:
    """Record ``kind: key`` in a new mapping, never edited in place."""
    ctx.setup.products = {**ctx.setup.products, kind: key}


def write_products(ctx: WorkflowContext) -> None:
    """Write ``products.json`` of the run ``ctx`` prepares, from ``setup.products``.

    The solver step calls it once the run directory is bound, so a run whose
    prefix was built in memory, a resumed run and a promoted trial all cite the
    products they computed on. A context that asked for none writes nothing,
    and a sealed run is never written.
    """
    if ctx.run_dir is None or not ctx.setup.products:
        return
    if is_sealed(ctx.run_dir):
        logger.warning("products.sealed run=%s: products.json left as sealed", ctx.run_dir)
        return
    write_cited(
        ctx.run_dir,
        [CitedProduct(kind=kind, key=key) for kind, key in ctx.setup.products.items()],
    )


__all__ = ["PRODUCT_KINDS", "ProductKind", "ask", "terrain_supply", "write_products"]
