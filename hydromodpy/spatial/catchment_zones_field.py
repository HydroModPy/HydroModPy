"""Catchment zonation object (3 classes: domain / buffer / core).

This object stores only semantic zone information and class values. It
intentionally does not duplicate georeferencing metadata already carried by
``Domain.surface_topo.support``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class CatchmentZonesField:
    """Compact 3-level zonation stored in ``Domain.zones``.

    Attributes
    ----------
    identifier:
        Stable field identifier used by runtime consumers.
    encoded_codes:
        2D code matrix aligned with domain support.
    encoded_to_zone:
        Mapping of class codes to semantic labels.
    nodata_code:
        Background/nodata class code.
    source_meta:
        Optional provenance metadata (paths, pipeline tag...).
    """

    identifier: str
    encoded_codes: np.ndarray
    encoded_to_zone: Mapping[int, str]
    nodata_code: int = 0
    source_meta: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        codes = np.asarray(self.encoded_codes, dtype=np.uint8)
        if codes.ndim != 2:
            raise ValueError("encoded_codes must be a 2D array")
        if codes.size == 0:
            raise ValueError("encoded_codes cannot be empty")

        mapping = {int(k): str(v).strip() for k, v in dict(self.encoded_to_zone).items()}
        if len(mapping) == 0:
            raise ValueError("encoded_to_zone cannot be empty")
        if any(code <= 0 for code in mapping):
            raise ValueError("encoded_to_zone keys must be positive integers")
        if any(name == "" for name in mapping.values()):
            raise ValueError("encoded_to_zone labels cannot be empty")

        nodata = int(self.nodata_code)
        allowed = set(mapping.keys()) | {nodata}
        present = set(np.unique(codes).astype(int).tolist())
        if not present.issubset(allowed):
            unknown = sorted(present.difference(allowed))
            raise ValueError(
                f"encoded_codes contains unknown class codes: {unknown}; allowed={sorted(allowed)}"
            )

        object.__setattr__(self, "encoded_codes", codes)
        object.__setattr__(self, "encoded_to_zone", mapping)
        object.__setattr__(self, "nodata_code", nodata)
        if self.source_meta is not None:
            object.__setattr__(
                self,
                "source_meta",
                {str(k): str(v) for k, v in dict(self.source_meta).items()},
            )

    @property
    def zone_keys(self) -> tuple[str, ...]:
        """Ordered tuple of zone labels (excluding nodata)."""
        return tuple(self.encoded_to_zone[k] for k in sorted(self.encoded_to_zone))

    @property
    def shape(self) -> tuple[int, int]:
        """Zone matrix shape."""
        return tuple(int(v) for v in self.encoded_codes.shape)

    def as_dict(self) -> dict[str, object]:
        """Return a lightweight metadata snapshot."""
        return {
            "id": str(self.identifier),
            "shape": self.shape,
            "nodata_code": int(self.nodata_code),
            "encoded_to_zone": dict(self.encoded_to_zone),
            "zone_keys": self.zone_keys,
            "source_meta": dict(self.source_meta) if self.source_meta is not None else None,
        }
