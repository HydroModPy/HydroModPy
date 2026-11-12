"""The forms of a pre-release, converted in memory when a reader meets them.

A sealed file is never rewritten. A run sealed under ``manifest_version = 3``
and an ``identity`` block that still carries ``config_hash`` are read by
applying the ``[[migration]]`` rows of ``schema/changes.toml`` to a copy of the
payload, then handing that copy to the model of today. :func:`run_seal_v3`
also lifts the version and names the profile; :func:`identity_block` drops the
key that left.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from hydromodpy.results.storage.contract import RUN_INPUTS_FILENAME
from hydromodpy.schema.changes import Rule, apply_rows
from hydromodpy.schema.seal import SEAL_VERSION

RUN_PROFILE: Final[str] = "run"
"""The profile of a seal that covers a run directory."""


def _inputs_artifact_role(document: dict[str, Any]) -> None:
    """Give the ``inputs`` role to ``inputs.json``, and no other entry a role it did not have.

    The value row renames ``other`` to ``inputs`` on every artifact, because a
    path cannot say which entry carries the file name; this rule names it, and
    puts back the role of every other entry.
    """
    entries = document.get("artifacts")
    if not isinstance(entries, list):
        return
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        if entry.get("path") == RUN_INPUTS_FILENAME:
            if entry.get("role") == "other":
                entry["role"] = "inputs"
        elif entry.get("role") == "inputs":
            entry["role"] = "other"


RULES: dict[str, Rule] = {"inputs_artifact_role": _inputs_artifact_role}
"""The rules of the run seal rows whose paths cannot say the whole change."""


def run_seal_v3(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return the payload of a version 3 run seal as the version 4 model reads it."""
    document = apply_rows("manifest", payload, rules=RULES)
    document["manifest_version"] = SEAL_VERSION
    document.setdefault("profile", RUN_PROFILE)
    return document


def identity_block(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return an identity block with the keys a pre-release wrote and this version retired dropped."""
    return apply_rows("identity", payload)


__all__ = ["RULES", "RUN_PROFILE", "identity_block", "run_seal_v3"]
