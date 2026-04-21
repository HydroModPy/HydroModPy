"""Verify every Annotated Pydantic field in hydromodpy has a Profile tag.

Exits 1 with the list of uncovered fields on stderr. Used in CI to prevent
drift of the visibility classification introduced in v0.6.

The audit walks every :class:`HydroModelBase` subclass reachable from the
registered top-level configs and inspects their ``model_fields``. A field
is *covered* when its ``Annotated[...]`` metadata carries either a
:class:`Profile` enum or a legacy :class:`ParamLevel` dataclass (the shim
is still valid during the migration window).
"""
from __future__ import annotations

import sys

import hydromodpy  # triggers registration of all sub-configs
from hydromodpy.core.config.base import HydroModelBase
from hydromodpy.core.config.param_level import ParamLevel
from hydromodpy.core.config.profile import Profile


def _has_profile(field_info) -> bool:
    metadata = getattr(field_info, "metadata", ())
    return any(isinstance(m, (Profile, ParamLevel)) for m in metadata)


def walk(cls=HydroModelBase, seen=None):
    seen = seen if seen is not None else set()
    for sub in cls.__subclasses__():
        if sub in seen:
            continue
        seen.add(sub)
        for field_name, info in sub.model_fields.items():
            if not _has_profile(info):
                yield f"{sub.__module__}.{sub.__qualname__}.{field_name}"
        yield from walk(sub, seen)


def main() -> int:
    missing = sorted(set(walk()))
    for entry in missing:
        print(entry, file=sys.stderr)
    print(
        f"\n{len(missing)} field(s) missing Profile metadata",
        file=sys.stderr,
    )
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
