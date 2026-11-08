"""Hydraulic properties of a MODFLOW 6 model: K, Kv, Sy, Ss, ``k33`` and the K tensor."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.model.properties.property_table import K_TENSOR_PROPERTIES
from hydromodpy.solver.modflow_common.property_mapping import MODFLOW_PROPERTIES
from hydromodpy.solver.modflow_common.property_mapping import (
    resolve_flow_property_arrays as resolve_flat_flow_property_arrays,
)

logger = get_logger(__name__)

MODFLOW6_PROPERTIES = (*MODFLOW_PROPERTIES, *K_TENSOR_PROPERTIES)
"""MODFLOW 6 reads the whole K tensor: K, Kv as K33, K22 and the three angles."""

K_TENSOR_NPF_NAMES = ("k22", "angle1", "angle2", "angle3")
"""The NPF arrays of the K tensor past ``k`` and ``k33``, named as FloPy names them."""


def resolve_flow_property_arrays(
    *,
    profiles: Mapping[str, object],
    domain: object,
    solver_mesh,
    required_properties: frozenset[str] | set[str] | None = None,
    optional_fill_values: Mapping[str, float] | None = None,
    runtime_property_overrides: Mapping[str, object] | None = None,
) -> dict[str, np.ndarray]:
    """Map K, Kv, Sy, Ss, K22 and the three angles onto a MODFLOW 6 solver mesh.

    ``profiles`` is ``Model.properties.profiles``.

    The flat arrays of the shared mapping, in the grid shape of the mesh: a
    regular grid gives ``(nlay, nrow, ncol)`` and ``(nrow, ncol)``, the shape
    ``build.py`` reads back through ``SolverMesh.flatten_from_grid``; any other
    mesh keeps ``(nlay, n_cells)`` and ``(n_cells,)``.
    """
    flat = resolve_flat_flow_property_arrays(
        profiles=profiles,
        domain=domain,
        solver_mesh=solver_mesh,
        required_properties=required_properties,
        optional_fill_values=optional_fill_values,
        runtime_property_overrides=runtime_property_overrides,
        properties=MODFLOW6_PROPERTIES,
    )
    return {name: solver_mesh.reshape_to_grid(values) for name, values in flat.items()}


_VKA_WARNED: set[float] = set()


def resolve_k33_field(
    hk: np.ndarray,
    kv_field: np.ndarray | None,
    vka: float,
    *,
    label: str = "flow.parameters",
) -> np.ndarray:
    """Return the per-cell vertical conductivity ``k33`` for the NPF package.

    Vertical anisotropy is grid-aligned and needs no XT3D. A direct per-cell ``Kv``
    field wins when provided, otherwise ``k33 = kh / vka`` with the uniform vertical
    anisotropy ratio. The two are mutually exclusive. ``Kv`` unlike ``vka`` is never a
    mode-switched number, which removes the classic ratio-versus-value footgun. A
    direct field is checked against ``Kh`` because ``Kv > Kh`` is physically unusual.
    """
    hk = np.asarray(hk, dtype=float)
    ratio = float(vka)
    if kv_field is not None:
        if ratio != 1.0:
            raise ConfigError(
                f"{label}: a per-cell Kv field and a non-unit vertical anisotropy ratio "
                f"vka={ratio} both set the vertical conductivity. Provide one or the other."
            )
        kv = np.asarray(kv_field, dtype=float)
        if kv.shape != hk.shape:
            raise ConfigError(
                f"{label}: Kv field shape {kv.shape} does not match Kh shape {hk.shape}."
            )
        exceed = int(np.count_nonzero(kv > hk * (1.0 + 1e-9)))
        if exceed:
            logger.warning(
                "%s: Kv exceeds Kh in %d cell(s); vertical conductivity above horizontal "
                "is physically unusual.",
                label,
                exceed,
            )
        return kv
    if ratio <= 0.0:
        raise ConfigError(f"{label}: vka must be > 0, got {ratio}.")
    if ratio not in _VKA_WARNED:
        if ratio < 1.0:
            logger.warning(
                "%s: vka=%s < 1 means Kv > Kh, which is physically unusual.", label, ratio
            )
        elif ratio > 1.0e4:
            logger.warning("%s: vka=%s is an extreme vertical anisotropy ratio.", label, ratio)
        _VKA_WARNED.add(ratio)
    return hk / ratio


def k_tensor_npf_kwargs(model) -> dict[str, np.ndarray]:
    """The K22 and angle arrays the flow sets, keyed as NPF takes them.

    A property the flow leaves out is not written, so MODFLOW 6 applies its own
    default: K22 equal to K, and every angle zero. MODFLOW 6 refuses ANGLE2
    without ANGLE3 and the reverse, and reads them after ANGLE1, so an angle2 or an
    angle3 writes the three angles, a missing one as zero.
    """
    kwargs = {
        name: values
        for name in K_TENSOR_NPF_NAMES
        if (values := getattr(model, name, None)) is not None
    }
    tilt = [kwargs[name] for name in ("angle2", "angle3") if name in kwargs]
    if tilt:
        for name in ("angle1", "angle2", "angle3"):
            kwargs.setdefault(name, np.zeros_like(np.asarray(tilt[0], dtype=float)))
    return kwargs


__all__ = [
    "K_TENSOR_NPF_NAMES",
    "MODFLOW6_PROPERTIES",
    "k_tensor_npf_kwargs",
    "resolve_flow_property_arrays",
    "resolve_k33_field",
]
