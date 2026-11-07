"""Layer bottoms and ``idomain`` of a layering, from shares of the column or from one base per layer.

With shares of the column (``constant``, ``decay``, ``list``) every valid cell is
active. A layering by surfaces gives each layer its base: a thickness below the
layer above, a depth below the terrain, an elevation, or a raster. The last layer
ends on the base of the aquifer. The interfaces are computed first, each base kept
between the base of the aquifer and the base of the layer above. The pinch-out
then acts on a cell thinner than the minimum thickness of its layer:

- ``pass_through``: the cell becomes a vertical pass-through (``idomain = -1``)
  with no thickness, and the nearest active cell below it, or above it at the
  base of the column, takes its thickness. The column keeps its top and base.
- ``keep_min_thickness``: the base of the layer moves down to keep the minimum
  thickness, and the layers below with it, the base of the aquifer included.

Every function works on arrays of cells of any shape, a flat mesh or a grid.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.model.domain.layers_config import SurfaceLayerConfig, VerticalGridConfig

logger = get_logger(__name__)


@dataclass(frozen=True)
class LayerStack:
    """Layer bottoms and ``idomain`` of a stack, both of shape ``(nlay, *cells)``."""

    botm: np.ndarray
    idomain: np.ndarray


def base_interfaces(
    *,
    top: np.ndarray,
    bottom: np.ndarray,
    layers: Sequence[SurfaceLayerConfig],
    bases: Mapping[str, np.ndarray],
) -> np.ndarray:
    """Return the ``(nlay + 1, *cells)`` interfaces the layer bases give, before any pinch-out.

    Each base is kept between the base of the aquifer and the base of the layer
    above, so the interfaces never rise. ``bases`` maps the name of a
    ``[[data.layer_base.sources]]`` raster to its values on the cells.

    Raises
    ------
    ValueError
        When a layer reads a raster ``bases`` does not hold, or a raster without
        a value on a cell.
    """
    top = np.asarray(top, dtype=float)
    bottom = np.asarray(bottom, dtype=float)
    interfaces = [top]
    above = top
    for layer in layers[:-1]:
        raw = _raw_base(layer, top=top, above=above, bases=bases)
        missing = ~np.isfinite(raw)
        if missing.any():
            raise ValueError(
                f"The base of layer {layer.name!r} has no value on {int(missing.sum())} "
                "cell(s) of the domain. The raster must cover the whole domain."
            )
        above = np.minimum(np.maximum(raw, bottom), above)
        interfaces.append(above)
    interfaces.append(np.minimum(bottom, above))
    return np.stack(interfaces)


def _raw_base(
    layer: SurfaceLayerConfig,
    *,
    top: np.ndarray,
    above: np.ndarray,
    bases: Mapping[str, np.ndarray],
) -> np.ndarray:
    """Return the base one layer table gives, before it is kept inside the column."""
    if layer.thickness is not None:
        return above - float(layer.thickness)
    if layer.depth is not None:
        return top - float(layer.depth)
    if layer.elevation is not None:
        return np.full_like(top, float(layer.elevation))
    if layer.surface not in bases:
        raise ValueError(
            f"layer {layer.name!r} reads the base surface {layer.surface!r}, and the "
            f"domain holds {sorted(bases) or 'none'}. Declare it under "
            "[[data.layer_base.sources]]."
        )
    return np.asarray(bases[layer.surface], dtype=float).reshape(top.shape)


def pinch_out(
    interfaces: np.ndarray,
    min_thickness: Sequence[float],
    *,
    mode: str,
) -> LayerStack:
    """Apply the pinch-out to the interfaces of valid cells; return the stack.

    ``min_thickness`` holds one value per layer. In ``pass_through`` mode a column
    whose every layer is thin keeps its thickest layer active.
    """
    z = np.array(interfaces, dtype=float, copy=True)
    nlay = z.shape[0] - 1
    minimum = np.asarray(min_thickness, dtype=float).reshape((nlay,) + (1,) * (z.ndim - 1))
    if mode == "keep_min_thickness":
        moved = np.zeros(z.shape[1:], dtype=bool)
        for k in range(nlay):
            floor = z[k] - minimum[k]
            low = z[k + 1] > floor
            moved |= low
            z[k + 1] = np.where(low, floor, z[k + 1])
        if moved.any():
            logger.info(
                "Layer surfaces: %d column(s) hold a layer thinner than its min_thickness; "
                "the bases below move down to keep it.",
                int(moved.sum()),
            )
        return LayerStack(botm=z[1:], idomain=np.ones(z[1:].shape, dtype=int))
    if mode != "pass_through":
        raise ValueError(f"Unsupported pinch_out {mode!r}: 'pass_through' or 'keep_min_thickness'.")

    thickness = z[:-1] - z[1:]
    active = thickness >= minimum
    # A column with no layer left keeps its thickest one.
    empty = ~active.any(axis=0)
    if empty.any():
        thickest = np.argmax(thickness, axis=0)
        for k in range(nlay):
            active[k] |= empty & (thickest == k)
    # A thin layer with an active layer below gives it its thickness: its base rises to its top.
    for k in range(nlay):
        below = active[k + 1 :].any(axis=0)
        rises = ~active[k] & below
        z[k + 1] = np.where(rises, z[k], z[k + 1])
    # A thin layer at the base gives it to the active layer above: its top falls to its base.
    for k in range(nlay - 1, -1, -1):
        below = active[k + 1 :].any(axis=0)
        falls = ~active[k] & ~below
        z[k] = np.where(falls, z[k + 1], z[k])
    n_pinched = int((~active).sum())
    if n_pinched:
        logger.info(
            "Layer surfaces: %d cell(s) thinner than the min_thickness of their layer "
            "become vertical pass-through cells (idomain -1).",
            n_pinched,
        )
    return LayerStack(botm=z[1:], idomain=np.where(active, 1, -1))


def surface_layer_stack(
    *,
    top: np.ndarray,
    bottom: np.ndarray,
    invalid: np.ndarray,
    layers: Sequence[SurfaceLayerConfig],
    bases: Mapping[str, np.ndarray],
    mode: str,
    nodata: float,
) -> LayerStack:
    """Return the stack of a layering by surfaces; invalid cells get ``nodata`` and ``idomain`` 0."""
    invalid = np.asarray(invalid, dtype=bool)
    valid = ~invalid
    # A raster sample at the nodata sentinel is a missing value, never an elevation.
    cells = {}
    for name, values in bases.items():
        sample = np.asarray(values, dtype=float)[valid]
        cells[name] = np.where(sample <= float(nodata), np.nan, sample)
    interfaces = base_interfaces(
        top=np.asarray(top, dtype=float)[valid],
        bottom=np.asarray(bottom, dtype=float)[valid],
        layers=layers,
        bases=cells,
    )
    stack = pinch_out(interfaces, [layer.min_thickness for layer in layers], mode=mode)
    nlay = len(layers)
    botm = np.full((nlay,) + invalid.shape, float(nodata))
    idomain = np.zeros((nlay,) + invalid.shape, dtype=int)
    botm[:, valid] = stack.botm
    idomain[:, valid] = stack.idomain
    return LayerStack(botm=botm, idomain=idomain)


def layer_stack(
    *,
    top: np.ndarray,
    bottom: np.ndarray,
    invalid: np.ndarray,
    vertical_config: VerticalGridConfig,
    bases: Mapping[str, np.ndarray] | None = None,
    nodata: float,
) -> LayerStack:
    """Return the layer bottoms and the ``idomain`` of the cells, shape ``(nlay, *cells)``.

    ``top`` and ``bottom`` are the top and the base of the aquifer, ``invalid``
    the cells outside the domain, which get ``nodata`` and ``idomain`` 0. With
    shares of the column (``constant``, ``decay``, ``list``) the bottom of layer
    ``k`` is ``top - (top - bottom) * allp[k]``, with ``allp`` the cumulative
    share, and every valid cell is active. With ``surfaces`` each layer ends on
    its own base, ``bases`` holding the rasters it reads by name, and a thin
    cell pinches out (:func:`surface_layer_stack`).
    """
    top = np.asarray(top, dtype=float)
    bottom = np.asarray(bottom, dtype=float)
    invalid = np.asarray(invalid, dtype=bool)
    if vertical_config.genmtd_lay == "surfaces":
        return surface_layer_stack(
            top=top,
            bottom=bottom,
            invalid=invalid,
            layers=vertical_config.layer or [],
            bases=bases or {},
            mode=vertical_config.pinch_out,
            nodata=nodata,
        )
    allp, nlay = layer_proportions(
        genmtd_lay=vertical_config.genmtd_lay,
        nlay=vertical_config.nlay,
        lay_decay=vertical_config.lay_decay,
        lay_proportions=vertical_config.lay_proportions,
    )
    shape = (nlay,) + (1,) * top.ndim
    botm = top[None, ...] - ((top - bottom)[None, ...] * np.asarray(allp).reshape(shape))
    botm[:, invalid] = float(nodata)
    idomain = np.broadcast_to(np.where(invalid, 0, 1), botm.shape).astype(int)
    return LayerStack(botm=botm, idomain=idomain)


def coerce_vertical_config(
    vertical_config: VerticalGridConfig | Mapping[str, object] | None,
) -> VerticalGridConfig:
    """Return the vertical config of a config object, a mapping or ``None`` (defaults)."""
    if vertical_config is None:
        return VerticalGridConfig()
    if isinstance(vertical_config, VerticalGridConfig):
        return vertical_config
    if isinstance(vertical_config, Mapping):
        return VerticalGridConfig.from_mapping(vertical_config)
    raise TypeError("vertical_config must be None, VerticalGridConfig, or a mapping of values.")


def layer_proportions(
    *,
    genmtd_lay: str,
    nlay: int | None = None,
    lay_decay: float | None = None,
    lay_proportions: list[float] | None = None,
) -> tuple[np.ndarray, int]:
    """
    Compute cumulative vertical proportions (`allp`) and layer count (`nlay`).

    Returned convention
    -------------------
    - `allp` is a 1D cumulative array in ]0, 1], one value per model layer.
    - `allp[k]` is the fraction of total vertical distance `(top - bottom)`
      reached at the bottom of layer `k`.
    - The last value is always ~1.0, so the last computed layer bottom
      matches the provided bottom surface.

    Examples
    --------
    - `constant, nlay=4` -> `[0.25, 0.50, 0.75, 1.00]`
    - `list, [0.1, 0.2, 0.3, 0.4]` -> cumulative `[0.1, 0.3, 0.6, 1.0]`
    - `decay` -> increasing thickness with depth (for `lay_decay > 1`)
    """
    if genmtd_lay == "list":
        arr = np.asarray(lay_proportions, dtype=float)
        return np.cumsum(arr), int(arr.size)

    if genmtd_lay == "constant":
        nlay_int = int(nlay)
        return np.arange(1, nlay_int + 1, dtype=float) / nlay_int, nlay_int

    if genmtd_lay == "decay":
        nlay_int = int(nlay)
        decay = float(lay_decay)
        idx = np.arange(1, nlay_int + 1, dtype=float)
        allp = (1 - decay**idx) / (1 - decay**nlay_int)
        return allp, nlay_int

    raise ValueError(f"Unsupported genmtd_lay '{genmtd_lay}'. Allowed: list, constant, decay.")


def assert_bottom_below_top(*, top: np.ndarray, bot: np.ndarray, nodata: float) -> None:
    """Ensure vertical order is physically consistent: bottom < top on valid cells."""
    valid = np.isfinite(top) & np.isfinite(bot) & (top > float(nodata)) & (bot > float(nodata))
    if not np.any(valid):
        raise ValueError("No finite overlapping valid cells found between top and bottom surfaces.")
    violations = bot[valid] >= top[valid]
    if np.any(violations):
        n_bad = int(np.count_nonzero(violations))
        total = int(violations.size)
        max_delta = float(np.max(bot[valid] - top[valid]))
        raise ValueError(
            "Bottom surface must be strictly below top surface on valid cells "
            f"({n_bad}/{total} violations, max(bot-top)={max_delta:.6g})."
        )


__all__ = [
    "LayerStack",
    "assert_bottom_below_top",
    "base_interfaces",
    "coerce_vertical_config",
    "layer_proportions",
    "layer_stack",
    "pinch_out",
    "surface_layer_stack",
]
