"""One finding of a check on a configuration document, in the one shape every producer gives.

The check of a document, the refusal of the loader, the preflight of a
calibration and the expansion of a ``[sites]`` project all give a
``Diagnostic``. It holds the key as the document spells it, a stable code, a
severity and what the validator said. The phrase of a code, in English and in
French, is read by the code from ``hydromodpy/schema/phrases.toml`` when a
diagnostic is written for a reader, so it is not copied into each one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Literal

Severity = Literal["error", "warning", "to_fill"]
"""How much a diagnostic weighs. ``to_fill`` is a required key not written yet."""

_INDEX = re.compile(r"\[(\d+)\]")


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One finding of a check, at one key of the document.

    ``path`` is the dotted key as the document spells it, ``flow.param.K.field``
    or ``export[0].variables``, and ``""`` for the whole document. ``code`` is one
    of the check codes, the keys of ``[check]`` in ``schema/phrases.toml``.
    ``detail`` is what the validator said about this case, in English, and
    ``help`` the description of the field at ``path`` when the model has one.
    ``keys`` holds the exact segments of the path when it was read from a
    validation error, so a key that holds a dot or a slash keeps its pointer.
    ``error_type`` is the Pydantic type of the fault when Pydantic raised it.
    """

    path: str
    code: str
    severity: Severity
    detail: str = ""
    help: str = ""
    line_number: int | None = None
    keys: tuple[str, ...] | None = None
    error_type: str = ""

    @property
    def parts(self) -> tuple[str, ...]:
        """Return the segments of the path, an index of a list as its digits."""
        if self.keys is not None:
            return self.keys
        if not self.path:
            return ()
        return tuple(_INDEX.sub(r".\1", self.path).split("."))

    @property
    def pointer(self) -> str:
        """Return the RFC 6901 JSON Pointer of the key, ``""`` for the whole document."""
        # Imported here: the error locator imports Pydantic, which a bare
        # ``import hydromodpy`` does not load, and this module is read by the
        # exceptions every package imports.
        from hydromodpy.core.toml_io.error_locator import json_pointer

        return json_pointer(self.parts)

    def with_severity(self, severity: Severity) -> Diagnostic:
        """Return this diagnostic with another severity, the rest kept."""
        return replace(self, severity=severity)

    def to_dict(self) -> dict[str, Any]:
        """Render the diagnostic as the record a refusal carries in ``details``.

        The keys ``pointer``, ``loc``, ``msg`` and ``type`` are those a refusal
        always carried. ``type`` is the Pydantic type when there is one, else the
        code. ``line`` is present only when the line is known.
        """
        payload: dict[str, Any] = {
            "pointer": self.pointer,
            "loc": self.path or "<root>",
            "msg": self.detail,
            "type": self.error_type or self.code,
            "code": self.code,
            "severity": self.severity,
            "help": self.help,
        }
        if self.line_number is not None:
            payload["line"] = self.line_number
        return payload

    def line(self) -> str:
        """Return the diagnostic as one printable line."""
        return f"{self.severity.upper():7} {self.path or '<document>'}: {self.detail}"


__all__ = ["Diagnostic", "Severity"]
