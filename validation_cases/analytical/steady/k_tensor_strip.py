"""Uniform flow along a strip whose K tensor axes leave the grid axes.

Shared by the plan-view case (MODFLOW 6 ANGLE1) and the vertical-section case
(ANGLE2). Both hold one head on each end of a long strip and no flow across its
sides. ``s`` runs along the strip and ``t`` across it. In the plane (s, t) the
tensor reads ``K_ss``, ``K_tt`` and ``K_st``.

Far from the ends the exact head is linear, ``h = h_c + g (s + r t)``. The
flux across the sides is zero, so ``r = -K_st / K_tt``. The flux along the
strip is ``K_eff g`` with ``K_eff = det K / K_tt``. The end effects decay like
``exp(-d / l)`` with ``l = w sqrt(det K) / (pi K_tt)``, ``w`` the strip width:
in the coordinates ``s - (K_st / K_tt) t`` the problem is orthotropic with
Neumann sides. The rotation of the tensor is the one of Bear (1972).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

TENSOR_FIELDS = (
    "hydraulic_conductivity",
    "hydraulic_conductivity_k22",
    "hydraulic_conductivity_k33",
    "conductivity_tensor_angle1",
    "conductivity_tensor_angle2",
    "conductivity_tensor_angle3",
)
"""Tensor arrays a MODFLOW 6 run stores beside its heads, as given to NPF."""


@dataclass(frozen=True, slots=True)
class StripTensor:
    """The conductivity tensor in the plane of the strip, in m/s."""

    k_ss: float
    k_tt: float
    k_st: float

    @property
    def gradient_ratio(self) -> float:
        """dh/dt over dh/ds of the exact head far from the ends."""
        return -self.k_st / self.k_tt

    @property
    def effective_conductivity(self) -> float:
        """Flux along the strip per unit head gradient along it, in m/s."""
        return (self.k_ss * self.k_tt - self.k_st**2) / self.k_tt


def rotated_strip_tensor(k_first: float, k_second: float, angle_deg: float) -> StripTensor:
    """Turn the first principal axis by ``angle_deg`` from +s toward +t."""
    a = np.radians(float(angle_deg))
    c, s = np.cos(a), np.sin(a)
    return StripTensor(
        k_ss=float(k_first * c * c + k_second * s * s),
        k_tt=float(k_first * s * s + k_second * c * c),
        k_st=float((k_first - k_second) * s * c),
    )


@dataclass(frozen=True, slots=True)
class StoredStrip:
    """What one run stored.

    ``x`` and ``y`` are in meters from the south-west corner, ``z`` is the
    elevation of the cell centers. Arrays are ``(nlay, n_cells)``.
    ``constant_head`` is the flow across the constant-head cells, in m3/s,
    positive into the aquifer.
    """

    heads: np.ndarray
    constant_head: np.ndarray
    x: np.ndarray
    y: np.ndarray
    z: np.ndarray
    polygons: list[np.ndarray]
    tensor: dict[str, np.ndarray]


def load_stored_strip(result) -> StoredStrip:
    """Read the last heads, the constant-head flows, the cells and the tensor of a run."""
    sz = result.store.open_zarr(result.sim_id)
    try:
        root = sz.root
        heads = np.asarray(root["head"][-1], dtype=float)
        constant_head = np.asarray(root["budget"]["constant_head"][-1], dtype=float)
        mesh = root["mesh"]
        vertices = np.asarray(mesh["vertices"][:], dtype=float)[:, :2]
        faces = np.asarray(mesh["face_node_connectivity"][:], dtype=int)
        face_x = np.asarray(mesh["face_x"][:], dtype=float)
        face_y = np.asarray(mesh["face_y"][:], dtype=float)
        interfaces = np.asarray(mesh["z_interfaces"][:], dtype=float)
        derived = root["derived"]
        tensor = {
            name: np.asarray(derived[name][:], dtype=float)
            for name in TENSOR_FIELDS
            if name in derived
        }
    finally:
        sz.close()
    x0, y0 = vertices[:, 0].min(), vertices[:, 1].min()
    origin = np.array([x0, y0])
    return StoredStrip(
        heads=np.atleast_2d(heads),
        constant_head=np.atleast_2d(constant_head),
        x=face_x - x0,
        y=face_y - y0,
        z=0.5 * (interfaces[:-1] + interfaces[1:]),
        polygons=[vertices[row[row >= 0]] - origin for row in faces],
        tensor=tensor,
    )


def _fit_plane(s: np.ndarray, t: np.ndarray, h: np.ndarray) -> np.ndarray:
    """Least-squares ``h = a + b s + c t``; returns ``(a, b, c)``."""
    design = np.column_stack([np.ones(s.size), s, t])
    coef, *_ = np.linalg.lstsq(design, h, rcond=None)
    return coef


def _fit_along_direction(s: np.ndarray, t: np.ndarray, h: np.ndarray, ratio: float) -> np.ndarray:
    """Least-squares ``h = a + g (s + ratio t)``; returns ``(a, g)``."""
    design = np.column_stack([np.ones(s.size), s + ratio * t])
    coef, *_ = np.linalg.lstsq(design, h, rcond=None)
    return coef


def _end_flows(stored: StoredStrip) -> tuple[float, float]:
    """Flow into the west end and out of the east end, in m3/s."""
    west = np.isclose(stored.x, stored.x.min())
    east = np.isclose(stored.x, stored.x.max())
    return float(stored.constant_head[:, west].sum()), float(-stored.constant_head[:, east].sum())


@dataclass(frozen=True, slots=True)
class StripFit:
    """The heads of a window and the end flows against the exact uniform flow.

    ``gradient_along_strip`` is fitted: it depends on the end effects, which
    have no closed form. ``gradient_ratio_error`` and ``flow_error`` are
    relative, ``head_max_error`` in m over the window. ``reference_heads`` has
    the shape of the heads given.
    """

    gradient_along_strip: float
    gradient_ratio_numerical: float
    gradient_ratio_error: float
    reference_heads: np.ndarray
    head_max_error: float
    head_drop_across: float
    flow_reference_m3_s: float
    west_inflow_m3_s: float
    east_outflow_m3_s: float
    flow_error: float


def fit_strip(
    *,
    tensor: StripTensor,
    stored: StoredStrip,
    s: np.ndarray,
    t: np.ndarray,
    window: np.ndarray,
    cross_section_m2: float,
) -> StripFit:
    """Fit the window heads and check the direction of their gradient and the end flows.

    ``s``, ``t`` and ``window`` have the shape of ``stored.heads``.
    """
    heads = stored.heads
    _, slope_s, slope_t = _fit_plane(s[window], t[window], heads[window])
    ratio_ref = tensor.gradient_ratio
    ratio_num = float(slope_t / slope_s)
    level, gradient = _fit_along_direction(s[window], t[window], heads[window], ratio_ref)
    reference = level + gradient * (s + ratio_ref * t)
    flow_ref = tensor.effective_conductivity * (-gradient) * cross_section_m2
    west, east = _end_flows(stored)
    return StripFit(
        gradient_along_strip=float(gradient),
        gradient_ratio_numerical=ratio_num,
        gradient_ratio_error=abs(ratio_num / ratio_ref - 1.0),
        reference_heads=reference,
        head_max_error=float(np.max(np.abs(heads[window] - reference[window]))),
        head_drop_across=abs(ratio_ref * gradient) * float(np.ptp(t[window])),
        flow_reference_m3_s=float(flow_ref),
        west_inflow_m3_s=west,
        east_outflow_m3_s=east,
        flow_error=max(abs(west / flow_ref - 1.0), abs(east / flow_ref - 1.0)),
    )


def tensor_mismatch(stored: StoredStrip, declared: dict[str, float]) -> float:
    """Largest gap between the stored tensor arrays and the declared values.

    Relative to a non-zero value, absolute for a zero one (an angle in degrees).
    """
    gaps = []
    for name, value in declared.items():
        if name not in stored.tensor:
            return np.inf
        scale = abs(float(value)) or 1.0
        gaps.append(float(np.max(np.abs(stored.tensor[name] - float(value)))) / scale)
    return max(gaps, default=0.0)


__all__ = [
    "TENSOR_FIELDS",
    "StoredStrip",
    "StripFit",
    "StripTensor",
    "fit_strip",
    "load_stored_strip",
    "rotated_strip_tensor",
    "tensor_mismatch",
]
