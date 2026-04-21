"""Canonical field registry for HydroModPy simulation outputs.

A single source of truth that maps each public field name (used by figures,
CLI exports and the Python API) to its Zarr storage path and a CF-1.11
metadata bundle (standard_name, long_name, units, cell_methods, coordinates,
grid_mapping).

Downstream code (Zarr writers, xarray exporters, display modules) reads from
this registry so that the same field is described identically no matter which
layer produces or consumes it. Spec refs: ``architecture_cible/13_coherence_globale.md``
§1.3 and ``architecture_cible/04_storage_ideal.md`` §3.

The registry is intentionally small and explicit: when a new field is
introduced, add it here so every layer picks up the CF metadata for free.
"""

from __future__ import annotations

from dataclasses import dataclass

# Supported shape literals, exposed as constants so callers don't have to
# remember the exact strings. These are CF / UGRID shape signatures.
SHAPE_TIME_LAYER_FACE = "time_layer_face"
SHAPE_TIME_FACE = "time_face"
SHAPE_LAYER_FACE = "layer_face"
SHAPE_FACE = "face"
SHAPE_PARTICLES = "particles"

_SHAPE_TO_COORDINATES = {
    SHAPE_TIME_LAYER_FACE: "time layer face",
    SHAPE_TIME_FACE: "time face",
    SHAPE_LAYER_FACE: "layer face",
    SHAPE_FACE: "face",
    SHAPE_PARTICLES: "time particle",
}


@dataclass(frozen=True, slots=True)
class FieldDescriptor:
    """CF-1.11 compliant descriptor for a canonical HydroModPy field.

    Parameters
    ----------
    public_name:
        The name exposed to users in figures, exports, and the Python API.
    zarr_path:
        Relative Zarr path inside the simulation store (e.g. ``head`` or
        ``derived/watertable_depth``).
    standard_name:
        CF-1.11 ``standard_name`` attribute.
    long_name:
        Human-readable description (``long_name`` attribute).
    units:
        udunits / pint-compatible unit string (``units`` attribute). Use
        ``"1"`` for dimensionless quantities.
    shape:
        Canonical shape signature (one of the ``SHAPE_*`` constants).
    cell_methods:
        CF ``cell_methods`` attribute describing aggregation semantics.
    grid_mapping:
        Name of the CF ``grid_mapping`` variable in the Zarr store
        (defaults to ``"crs"``).
    derived_by:
        Either ``"solver"`` (written by a solver adapter) or ``"core"``
        (derived by :mod:`hydromodpy.results.derived`).
    description:
        Free-form description used as fallback when the CF long_name is
        insufficient.
    """

    public_name: str
    zarr_path: str
    standard_name: str
    long_name: str
    units: str
    shape: str
    cell_methods: str = "time: point area: mean"
    grid_mapping: str = "crs"
    derived_by: str = "core"
    description: str = ""

    @property
    def coordinates(self) -> str:
        """CF ``coordinates`` attribute derived from :attr:`shape`."""
        return _SHAPE_TO_COORDINATES.get(self.shape, self.shape)


FIELD_REGISTRY: dict[str, FieldDescriptor] = {}


def get(name: str) -> FieldDescriptor:
    """Return the :class:`FieldDescriptor` registered under ``name``.

    Raises :class:`KeyError` with the full list of available names when the
    lookup fails, which makes typos immediately actionable.
    """
    try:
        return FIELD_REGISTRY[name]
    except KeyError:
        available = ", ".join(sorted(FIELD_REGISTRY))
        raise KeyError(
            f"Field '{name}' is not registered. Available fields: {available}"
        ) from None


def has(name: str) -> bool:
    """Return True when ``name`` is registered."""
    return name in FIELD_REGISTRY


def all_names() -> list[str]:
    """Return the sorted list of registered public names."""
    return sorted(FIELD_REGISTRY)


def all_zarr_paths() -> list[str]:
    """Return the sorted list of registered Zarr paths."""
    return sorted(desc.zarr_path for desc in FIELD_REGISTRY.values())


def cf_attrs(name: str) -> dict[str, str]:
    """Return a dict of CF-1.11 attributes for the given public name.

    The resulting mapping is suitable for ``zarr.Array.attrs.update(...)``
    or as an xarray ``attrs=`` argument when exporting.
    """
    desc = get(name)
    return {
        "standard_name": desc.standard_name,
        "long_name": desc.long_name,
        "units": desc.units,
        "cell_methods": desc.cell_methods,
        "grid_mapping": desc.grid_mapping,
        "coordinates": desc.coordinates,
    }


__all__ = [
    "SHAPE_TIME_LAYER_FACE",
    "SHAPE_TIME_FACE",
    "SHAPE_LAYER_FACE",
    "SHAPE_FACE",
    "SHAPE_PARTICLES",
    "FieldDescriptor",
    "FIELD_REGISTRY",
    "get",
    "has",
    "all_names",
    "all_zarr_paths",
    "cf_attrs",
]
