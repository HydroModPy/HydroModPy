"""Profile visibility tags and helpers.

Field-level metadata primitives consumed by the Pydantic introspection layer
to decide which fields show up in generated TOML templates, JSON schemas,
and Streamlit forms.
"""

from dataclasses import dataclass
from typing import Literal

from hydromodpy.core.config_kit.profile import Profile

ProfileName = Literal["user", "dev", "expert"]

#: Ordered mapping of profile names to their numeric threshold.
#: Aligned on Profile IntEnum values (1/2/3). A field is visible when
#: ``PROFILES[field_level] <= PROFILES[requested_profile]``.
PROFILES: dict[str, int] = {"user": 1, "dev": 2, "expert": 3}


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


__all__ = ["Profile", "VisibleWhen", "PROFILES", "ProfileName"]
