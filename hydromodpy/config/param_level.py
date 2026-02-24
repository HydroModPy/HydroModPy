"""Shared metadata tag for parameter visibility levels.

Used inside ``Annotated[...]`` on Pydantic config fields so that tooling
(TOML generator, future GUI) can filter parameters by audience.
"""

from dataclasses import dataclass
from typing import Literal

#: Ordered mapping of profile names to their numeric threshold.
#: A field is visible when ``PROFILES[field_level] <= PROFILES[requested_profile]``.
PROFILES: dict[str, int] = {"user": 0, "dev": 1, "expert": 2}

ProfileName = Literal["user", "dev", "expert"]


@dataclass(frozen=True)
class ParamLevel:
    """Metadata tag for parameter visibility level (user, dev, expert)."""

    level: ProfileName
