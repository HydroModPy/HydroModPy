"""Shared metadata tag for parameter visibility levels.

Used inside ``Annotated[...]`` on Pydantic config fields so that tooling
(TOML generator, future GUI) can filter parameters by audience.
"""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ParamLevel:
    """Metadata tag for parameter visibility level (user, dev, expert)."""

    level: Literal["user", "dev", "expert"]
