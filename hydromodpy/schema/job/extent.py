"""The spatial extent a job records: one box, in the CRS it was measured in.

A resource of ``inputset.json`` and the ``geometry`` of a job seal both name
an extent. They name it one way, ``{"crs": ..., "bbox": [...]}``, with the
box in its native CRS. No WGS84 copy is stored beside it: a view reprojects
the box itself, so the two can never disagree.

The extent is checked when it is built and when it is read back. Four finite
numbers, ``xmin < xmax`` and ``ymin < ymax``, and a CRS that :mod:`pyproj`
parses. A document that carries anything else, a second key included, is
refused rather than read in part.
"""

from __future__ import annotations

import math
import numbers
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

_KEYS = frozenset({"crs", "bbox"})


@dataclass(frozen=True, slots=True)
class SpatialExtent:
    """A bounding box and the CRS its coordinates are expressed in."""

    bbox: tuple[float, float, float, float]
    crs: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "bbox", _checked_bbox(self.bbox))
        _check_crs(self.crs)

    def to_document(self) -> dict[str, Any]:
        """Render the extent the way ``inputset.json`` and the seal store it."""
        return {"crs": self.crs, "bbox": list(self.bbox)}

    @classmethod
    def from_document(cls, document: Any) -> SpatialExtent:
        """Read an extent back, refusing any other shape."""
        if not isinstance(document, Mapping):
            raise ValueError(f"a spatial extent is a JSON object, not {document!r}")
        keys = set(document)
        if keys != _KEYS:
            raise ValueError(
                f"a spatial extent carries exactly the keys {sorted(_KEYS)}; "
                f"this one carries {sorted(keys)}"
            )
        return cls(bbox=document["bbox"], crs=document["crs"])


def _checked_bbox(value: Any) -> tuple[float, float, float, float]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) != 4:
        raise ValueError(f"a bbox is four numbers xmin, ymin, xmax, ymax, not {value!r}")
    coordinates: list[float] = []
    for raw in value:
        if isinstance(raw, bool) or not isinstance(raw, numbers.Real):
            raise ValueError(f"bbox {value!r} holds {raw!r}, which is not a number")
        number = float(raw)
        if not math.isfinite(number):
            raise ValueError(f"bbox {value!r} holds {raw!r}, which is not finite")
        coordinates.append(number)
    xmin, ymin, xmax, ymax = coordinates
    if xmin >= xmax or ymin >= ymax:
        raise ValueError(
            f"bbox {value!r} is empty or inverted; expected xmin < xmax and ymin < ymax"
        )
    return (xmin, ymin, xmax, ymax)


def _check_crs(value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"an extent names the CRS of its box, and {value!r} names none")
    from pyproj import CRS
    from pyproj.exceptions import CRSError

    try:
        CRS.from_user_input(value)
    except CRSError as exc:
        raise ValueError(f"CRS {value!r} cannot be parsed: {exc}") from exc


__all__ = ["SpatialExtent"]
