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
from collections.abc import Mapping, Sequence
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


def json_pointer(loc: Sequence[object]) -> str:
    """Render a Pydantic ``loc`` tuple as an RFC 6901 JSON Pointer.

    ``("flow", "param_list", 0, "kind")`` becomes ``/flow/param_list/0/kind``.
    An empty ``loc`` is the whole document, whose pointer is the empty string.
    ``~`` and ``/`` inside a key are escaped as the RFC requires, so a key
    holding a slash does not silently become two path segments.
    """
    parts = _normalise_loc(loc)
    if not parts:
        return ""
    escaped = [part.replace("~", "~0").replace("/", "~1") for part in parts]
    return "/" + "/".join(escaped)


def _descend(node: object, part: str) -> tuple[object, bool]:
    """Return the child of *node* named by *part*, and whether it was there."""
    if isinstance(node, Mapping):
        if part in node:
            return node[part], True
        return None, False
    if isinstance(node, Sequence) and not isinstance(node, (str, bytes)) and part.isdigit():
        position = int(part)
        if position < len(node):
            return node[position], True
    return None, False


def resolve_loc(loc: Sequence[object], document: object) -> tuple[str, ...]:
    """Drop the path segments Pydantic invents and the document does not have.

    A discriminated union makes Pydantic name the variant it selected: a field
    of ``[flow.ic]`` under ``type = "spinup_cyclic"`` is reported at
    ``("flow", "ic", "spinup_cyclic", "max_cycles")``. The document has no
    ``spinup_cyclic`` table — the tag and the field are siblings — so a pointer
    built from that ``loc`` addresses nothing.

    A segment is dropped only when the **next** one resolves in its place, so a
    key the document genuinely lacks is kept: a ``missing`` fault must point at
    where the key belongs. Once a segment cannot be resolved either way, the
    rest of the path is taken verbatim rather than guessed at.
    """
    parts = _normalise_loc(loc)
    resolved: list[str] = []
    node: object = document
    index = 0
    while index < len(parts):
        child, found = _descend(node, parts[index])
        if found:
            resolved.append(parts[index])
            node = child
            index += 1
            continue
        if index + 1 < len(parts):
            _, next_found = _descend(node, parts[index + 1])
            if next_found:
                index += 1
                continue
        resolved.extend(parts[index:])
        return tuple(resolved)
    return tuple(resolved)


def validation_error_details(
    error: ValidationError,
    *,
    loc_prefix: Sequence[str] = (),
    source_path: Path | str | None = None,
    text: str | None = None,
    document: object = None,
) -> tuple[dict[str, object], ...]:
    """Return one structured record per field fault, pointer included.

    The counterpart of :func:`format_validation_error`, which renders the same
    faults as a human paragraph. A caller outside this process cannot parse a
    paragraph: it needs the field, and that is what ``pointer`` carries.
    ``line`` is present only when the source text is available and the locator
    found the token, because a line number that is a guess is worse than none.
    """
    if text is None and source_path is not None:
        try:
            text = Path(source_path).read_text(encoding="utf-8-sig")
        except OSError:
            text = None

    records: list[dict[str, object]] = []
    for err in error.errors():
        loc = _document_loc(loc_prefix, err, document)
        record: dict[str, object] = {
            "pointer": json_pointer(loc),
            "loc": format_loc(loc) or "<root>",
            "msg": err.get("msg", ""),
            "type": err.get("type", ""),
        }
        line_no = locate_loc(text, loc) if text else None
        if line_no is not None:
            record["line"] = line_no
        records.append(record)
    return tuple(records)


def _document_loc(
    loc_prefix: Sequence[str],
    err: Mapping[str, object],
    document: object,
) -> tuple[str, ...]:
    """Return the path of one fault, as the document spells it."""
    loc = (*loc_prefix, *err.get("loc", ()))
    if document is None:
        return tuple(str(part) for part in loc)
    return resolve_loc(loc, document)


def format_validation_error(
    error: ValidationError,
    *,
    source_path: Path | str | None = None,
    text: str | None = None,
    loc_prefix: Sequence[str] = (),
    document: object = None,
) -> str:
    """Return a multi-line message mapping each error to a TOML location.

    ``loc_prefix`` names the table a caller validated a sub-mapping of. Pydantic
    reports a ``loc`` relative to what it was handed, so validating
    ``raw["calibration"]`` yields ``("objective",)`` and the locator would look
    for that key at the top of the file. Passing ``("calibration",)`` puts the
    error back where the reader wrote it.
    """
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
        loc = _document_loc(loc_prefix, err, document)
        msg = err.get("msg", "")
        rendered_loc = format_loc(loc) or "<root>"
        line_no = locate_loc(text, loc) if text else None
        prefix = f"{location_label}:{line_no}" if line_no else location_label
        out_lines.append(f"  {prefix}: {rendered_loc}: {msg}{_rendered_input(err)}")
    return "\n".join(out_lines)


_INPUT_BUDGET = 120


def _rendered_input(err: Mapping[str, object]) -> str:
    """Return ``" (input=...)"`` when naming the refused value helps.

    "Input should be 'steady' or 'transient'" does not say what was written. A
    whole section repeated back does not help either, so a value whose repr does
    not fit the budget is left out rather than truncated into something that
    looks like a value and is not one.
    """
    if "input" not in err:
        return ""
    rendered = repr(err["input"])
    return f" (input={rendered})" if len(rendered) <= _INPUT_BUDGET else ""


__all__ = [
    "format_loc",
    "format_validation_error",
    "json_pointer",
    "locate_loc",
    "resolve_loc",
    "validation_error_details",
]
