"""Shared metadata tags for parameter visibility and conditional display.

Used inside ``Annotated[...]`` on Pydantic config fields so that tooling
(TOML generator, Streamlit UI) can filter parameters by audience and
conditionally show/hide fields based on sibling values.

Example::

    catch_def: Annotated[str, ParamLevel("user")] = "dem"
    x_outlet: Annotated[Optional[float], ParamLevel("user"), VisibleWhen("catch_def", "from_outlet_coord")] = None

The ``VisibleWhen`` tag tells the UI: only show ``x_outlet`` when the
sibling field ``catch_def`` equals ``"from_outlet_coord"``.  Multiple
allowed values can be passed as a tuple.
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


@dataclass(frozen=True)
class VisibleWhen:
    """Metadata tag for conditional field visibility.

    Attached to a field via ``Annotated[..., VisibleWhen("sibling", "value")]``.
    The field should only be shown when the sibling field in the same model
    has one of the specified values.

    Parameters
    ----------
    field : str
        Name of the sibling field to check.
    values : str or tuple of str
        Accepted value(s) that make this field visible.
    """

    field: str
    values: str | tuple[str, ...]

    def matches(self, current_value: object) -> bool:
        """Return True if *current_value* matches the visibility condition."""
        allowed = self.values if isinstance(self.values, tuple) else (self.values,)
        return current_value in allowed
