"""Legacy alias. Prefer :class:`hydromodpy.core.config.profile.Profile`.

Kept as a pure re-export so existing ``Annotated[..., ParamLevel("user")]``
call sites still type-check during the migration window. Slated for removal
in v0.7.

``VisibleWhen`` remains defined here (unchanged from v0.5) — it is not part
of the Profile migration.
"""
from dataclasses import dataclass
from typing import Literal

from hydromodpy.core.config.profile import Profile

ProfileName = Literal["user", "dev", "expert"]

#: Ordered mapping of profile names to their numeric threshold.
#: Aligned on Profile IntEnum values (1/2/3). A field is visible when
#: ``PROFILES[field_level] <= PROFILES[requested_profile]`` — ordering preserved
#: from the v0.5 0/1/2 encoding.
PROFILES: dict[str, int] = {"user": 1, "dev": 2, "expert": 3}

_STR_TO_PROFILE: dict[str, Profile] = {
    "user": Profile.USER,
    "dev": Profile.DEV,
    "expert": Profile.EXPERT,
}


@dataclass(frozen=True)
class ParamLevel:
    """Deprecated legacy tag; resolves to a :class:`Profile` enum.

    Example::

        catch_def: Annotated[str, ParamLevel("user")] = "dem"

    Prefer ``Profile.USER`` directly in new code.
    """

    level: ProfileName

    def as_profile(self) -> Profile:
        """Return the equivalent :class:`Profile` enum value."""
        return _STR_TO_PROFILE[self.level]


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


__all__ = ["Profile", "ParamLevel", "VisibleWhen", "PROFILES", "ProfileName"]
