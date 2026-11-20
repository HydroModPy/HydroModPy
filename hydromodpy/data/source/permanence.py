"""Whether water flows all year: the column a mapped network or water body carries.

A source that knows it writes one canonical column, ``permanence``, next to its
own attributes. The layers above read that column and never the provider's
vocabulary, so a consumer of the permanent network does not know which
provider drew it, and a provider does not know who reads it.

The name has ten letters on purpose: the reference network is still written as
a shapefile, whose field names stop at ten, and ``persistence`` would arrive
as ``persistenc``.
"""

from __future__ import annotations

from typing import Final, Literal

PERMANENCE_COLUMN: Final = "permanence"

Permanence = Literal["permanent", "intermittent", "ephemeral", "dry", "unknown"]

PERMANENT: Final = "permanent"
INTERMITTENT: Final = "intermittent"
EPHEMERAL: Final = "ephemeral"
DRY: Final = "dry"
UNKNOWN: Final = "unknown"

PERMANENCE_VALUES: Final[tuple[str, ...]] = (PERMANENT, INTERMITTENT, EPHEMERAL, DRY, UNKNOWN)
"""Every value the column may hold. A provider value with no match is ``unknown``.

``ephemeral`` and ``dry`` are rare in the French reference (33 and 426 reaches
out of three million) and are kept apart rather than folded into
``intermittent``: merging them is a reader's decision, not a loader's.
"""

__all__ = [
    "DRY",
    "EPHEMERAL",
    "INTERMITTENT",
    "PERMANENCE_COLUMN",
    "PERMANENCE_VALUES",
    "PERMANENT",
    "UNKNOWN",
    "Permanence",
]
