"""Map Pydantic ``ValidationError`` paths back to TOML source lines.

Pydantic emits errors with a tuple ``loc`` such as
``("flow", "param_list", 0, "kind")``. When the payload comes from a TOML
file, this module turns that tuple into a ``file:line`` pointer so users
can jump straight to the offending section.

The lookup is heuristic: it does not require ``tomlkit`` and works on the
raw text. It scans for ``[section.subsection]`` headers and ``key =``
assignments, falling back to the closest known location when an exact match
is not found.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

_HEADER_RE = re.compile(r"^\s*\[\[?(?P<name>[^\]]+)\]?\]\s*(?:#.*)?$")
_ASSIGNMENT_RE = re.compile(r"^\s*(?P<key>[A-Za-z_][A-Za-z0-9_\-]*)\s*=")


def _normalise_loc(loc: Sequence[object]) -> list[str]:
    return [str(part) for part in loc]


def _section_path(loc: Sequence[str]) -> str:
    section_parts: list[str] = []
    has_digit = False
    for part in loc:
        if part.isdigit():
            has_digit = True
            break
        section_parts.append(part)
    if has_digit:
        return ".".join(section_parts)
    return ".".join(section_parts[:-1]) if section_parts else ""


def _find_header_line(lines: Sequence[str], section: str) -> int | None:
    if not section:
        return None
    for index, line in enumerate(lines, start=1):
        match = _HEADER_RE.match(line)
        if match and match.group("name").strip() == section:
            return index
    return None


def _find_key_line(lines: Sequence[str], header_line: int | None, key: str) -> int | None:
    start = header_line or 0
    for index in range(start, len(lines)):
        line = lines[index]
        if _HEADER_RE.match(line):
            if index + 1 == header_line:
                continue
            if header_line is not None and index + 1 != header_line:
                break
        match = _ASSIGNMENT_RE.match(line)
        if match and match.group("key") == key:
            return index + 1
    return None


def locate_loc(text: str, loc: Sequence[object]) -> int | None:
    """Return the 1-based line number for the deepest known token in *loc*."""
    parts = _normalise_loc(loc)
    if not parts:
        return None

    lines = text.splitlines()
    section = _section_path(parts)
    header_line = _find_header_line(lines, section) if section else None

    leaf = parts[-1]
    if leaf.isdigit():
        return header_line

    key_line = _find_key_line(lines, header_line, leaf)
    return key_line or header_line


def format_loc(loc: Sequence[object]) -> str:
    """Render a Pydantic ``loc`` tuple as ``a.b[0].c``."""
    parts = _normalise_loc(loc)
    rendered: list[str] = []
    for part in parts:
        if part.isdigit():
            rendered.append(f"[{part}]")
        else:
            rendered.append(f".{part}" if rendered else part)
    return "".join(rendered)


def format_validation_error(
    error: ValidationError,
    *,
    source_path: Path | str | None = None,
    text: str | None = None,
) -> str:
    """Return a multi-line message mapping each error to a TOML location."""
    if text is None and source_path is not None:
        try:
            text = Path(source_path).read_text(encoding="utf-8-sig")
        except OSError:
            text = None

    location_label = str(source_path) if source_path is not None else "<config>"
    out_lines = [
        f"{error.error_count()} validation error(s) in {location_label}:",
    ]
    for err in error.errors():
        loc = err.get("loc", ())
        msg = err.get("msg", "")
        rendered_loc = format_loc(loc) or "<root>"
        line_no = locate_loc(text, loc) if text else None
        prefix = f"{location_label}:{line_no}" if line_no else location_label
        out_lines.append(f"  {prefix}: {rendered_loc}: {msg}")
    return "\n".join(out_lines)


__all__ = [
    "format_loc",
    "format_validation_error",
    "locate_loc",
]
