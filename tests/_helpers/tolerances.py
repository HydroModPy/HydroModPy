"""Central tolerances helper.

Parses ``tests/TOLERANCES.md`` once and exposes:

- ``TOLERANCES``: a ``dict[str, float]`` keyed by a canonical metric slug
  built from ``"<Test / domain> :: <Metric>"`` (lowercase, no spaces).
- ``tol(metric_name)``: lookup helper. Supports either a full canonical
  slug or a substring match when unambiguous.

Only rows that carry a single parsable numerical tolerance are loaded.
Composite rows (e.g. ``rtol``/``atol`` pairs, multi-value envelopes,
slope intervals, hash equality) are intentionally skipped here; their
call sites keep their inline values until a follow-up migration adds
explicit canonical keys for them.

Single source of truth: ``tests/TOLERANCES.md``. Do not hard-code
tolerances elsewhere - use ``tol(...)``.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_TOLERANCES_MD: Path = Path(__file__).resolve().parents[1] / "TOLERANCES.md"

_NUMERIC_RE = re.compile(
    r"(?P<value>[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*(?P<unit>%|m2|km2|m|px)?"
)


def _slugify(label: str) -> str:
    """Lowercase, strip backticks, collapse whitespace and punctuation."""
    text = label.strip().lower()
    text = text.replace("`", "")
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def _extract_scalar(cell: str) -> float | None:
    """Return a single float from a markdown cell or None when ambiguous.

    Rules:
    - Strip backticks and whitespace.
    - Reject cells containing ``,`` or multiple numbers (composite).
    - Convert ``%`` to a fraction (1 % -> 0.01).
    - Reject ``n/a`` and units we do not normalise here.
    """
    raw = cell.strip().replace("`", "")
    if not raw or raw.lower() == "n/a":
        return None
    if "," in raw or "/" in raw or "[" in raw or "(" in raw:
        return None
    matches = list(_NUMERIC_RE.finditer(raw))
    if len(matches) != 1:
        return None
    match = matches[0]
    value = float(match.group("value"))
    unit = match.group("unit")
    if unit == "%":
        return value / 100.0
    return value


def _split_row(line: str) -> list[str]:
    """Split a markdown row by ``|``, preserving backtick-quoted spans.

    A literal ``|`` inside a backtick code span (e.g. ``|x|``) must not
    split the cell.
    """
    out: list[str] = []
    buf: list[str] = []
    in_code = False
    for ch in line:
        if ch == "`":
            in_code = not in_code
            buf.append(ch)
        elif ch == "|" and not in_code:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    out.append("".join(buf))
    return [c.strip() for c in out]


def _parse_table(md_text: str) -> dict[str, float]:
    """Parse the tolerances table into a flat dict."""
    out: dict[str, float] = {}
    in_table = False
    for raw_line in md_text.splitlines():
        line = raw_line.strip()
        if line.startswith("|") and "---" in line:
            in_table = True
            continue
        if not in_table:
            continue
        if not line.startswith("|"):
            in_table = False
            continue
        cells = _split_row(line)
        # Leading and trailing pipes produce empty edge cells.
        cells = [c for c in cells if c != ""] or cells
        if len(cells) < 4:
            continue
        domain, metric, tolerance = cells[1], cells[2], cells[3]
        scalar = _extract_scalar(tolerance)
        if scalar is None:
            continue
        key = f"{_slugify(domain)}__{_slugify(metric)}"
        out[key] = scalar
    return out


@lru_cache(maxsize=1)
def _load() -> dict[str, float]:
    return _parse_table(_TOLERANCES_MD.read_text(encoding="utf-8"))


TOLERANCES: dict[str, float] = _load()


def tol(metric_name: str) -> float:
    """Return the tolerance for a metric.

    ``metric_name`` may be:
    - the exact canonical slug ``<domain>__<metric>``.
    - a substring matching exactly one canonical key.

    Raises ``KeyError`` when nothing matches or when the substring is
    ambiguous.
    """
    table = _load()
    if metric_name in table:
        return table[metric_name]
    needle = _slugify(metric_name)
    if needle in table:
        return table[needle]
    candidates = [k for k in table if needle in k]
    if len(candidates) == 1:
        return table[candidates[0]]
    if not candidates:
        raise KeyError(f"No tolerance matches {metric_name!r}")
    raise KeyError(f"Ambiguous tolerance for {metric_name!r}: {sorted(candidates)}")


__all__ = ["TOLERANCES", "tol"]
