"""Overrides of a document given on a command line or in the environment.

``hmp run --set geographic.catchment.x_outlet=389285.91`` and the
``HMP_SET_<key>`` variables both name a key of the document by a dotted path
(:mod:`hydromodpy.core.toml_io.paths`) and give its value as TOML text. This
module turns them into payloads :func:`hydromodpy.core.toml_io.merge.merge_toml_payloads`
applies last. The plan of a ``[sites]`` project renders them into each case,
and a worker launched by the plan refuses them: the hash of the plan is the
hash of the case.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterable, Mapping
from typing import Any

from hydromodpy.core.toml_io.paths import assign, parse

ENV_SET_PREFIX = "HMP_SET_"
"""Prefix of the environment variables read as overrides."""

ENV_PATH_SEPARATOR = "__"
"""What stands for a dot in the name of an environment variable."""


def parse_override_value(text: str) -> Any:
    """Return *text* read as a TOML value, or the text itself when it is not one."""
    stripped = text.strip()
    try:
        return tomllib.loads(f"value = {stripped}\n")["value"]
    except tomllib.TOMLDecodeError:
        return text


def set_overrides(items: Iterable[str]) -> dict[str, Any]:
    """Return the payload of repeated ``--set PATH=VALUE`` items."""
    payload: dict[str, Any] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"--set expects PATH=VALUE, got {item!r}")
        dotted_path, raw_value = item.split("=", 1)
        assign(payload, parse(dotted_path.strip()), parse_override_value(raw_value))
    return payload


def env_set_names(env: Mapping[str, str]) -> list[str]:
    """Return the names of the ``HMP_SET_*`` variables *env* holds, sorted."""
    return sorted(name for name in env if name.startswith(ENV_SET_PREFIX))


def env_overrides(env: Mapping[str, str]) -> dict[str, Any]:
    """Return the payload of the ``HMP_SET_*`` variables of *env*.

    Windows upper-cases the name of a variable and TOML keys are case
    sensitive, so the key is lower-cased: the keys of a project file are.
    """
    payload: dict[str, Any] = {}
    for name in env_set_names(env):
        dotted_path = name[len(ENV_SET_PREFIX) :].lower().replace(ENV_PATH_SEPARATOR, ".")
        assign(payload, parse(dotted_path), parse_override_value(env[name]))
    return payload


__all__ = [
    "ENV_PATH_SEPARATOR",
    "ENV_SET_PREFIX",
    "env_overrides",
    "env_set_names",
    "parse_override_value",
    "set_overrides",
]
