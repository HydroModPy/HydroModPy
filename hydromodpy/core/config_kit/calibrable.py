"""The annotation that marks a configuration field calibrable.

It lives in the kernel, and that placement is the whole point. The annotation
used to sit in ``calibration/``, a layer that ``physics`` and ``spatial`` are
forbidden to import, so no hydraulic property could ever carry it and the
discovery walk written to collect them returned nothing on every configuration
in the repository. A mechanism and a mechanism nobody can reach are not the same
thing.

Here, any layer that declares a field can say what a search would need to know
about it: the physical range, the space to sample in, the prior, the unit. What
reads those declarations still lives in ``calibration/``; only the vocabulary is
shared, which is what a kernel is for.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Calibrable:
    """What a search needs to know about one field, declared where the field is.

    Usage::

        from hydromodpy.core.config_kit.calibrable import Calibrable
        from hydromodpy.core.config_kit.field_metadata import field_metadata

        k_aquifer: float = Field(
            default=1e-4,
            json_schema_extra=field_metadata(
                calibrable=Calibrable(
                    bounds=(1e-7, 1e-2),
                    transform="log",
                    prior="log_uniform",
                    units="m/s",
                ),
            ),
        )
    """

    bounds: tuple[float, float] | None = None
    """The range a search may move within. ``None`` says the field is calibrable
    but its range belongs to the site, so the file has to state it."""

    transform: str = "identity"
    """``identity``, ``log`` or ``logit``: the space the sampling walks in."""

    prior: str = "uniform"
    """``uniform``, ``log_uniform`` or ``normal``."""

    units: str | None = None
    description: str = ""

    is_the_value_of_its_instance: bool = False
    """Whether this leaf IS the quantity of the entry that carries it.

    ``flow.param.K.field.value`` is the value OF ``K``, so the search names it
    ``K`` and not ``K.value``. A lake's ``bedleak`` is one property among
    several and names itself ``<lake>.bedleak``. Declaring it here rather than
    deducing it from "this instance happens to carry one searchable leaf today"
    keeps the name stable: adding a second property to an entry must not rename
    the first one under a file that already calibrates it.
    """

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly record for a schema export or a catalogue."""
        return {
            "bounds": list(self.bounds) if self.bounds else None,
            "transform": self.transform,
            "prior": self.prior,
            "units": self.units,
            "description": self.description,
            "is_the_value_of_its_instance": self.is_the_value_of_its_instance,
        }


__all__ = ["Calibrable"]
