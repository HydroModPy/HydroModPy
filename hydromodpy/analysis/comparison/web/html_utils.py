"""Small HTML helpers for static comparison reports."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any, Iterable, Mapping


def safe(value: Any) -> str:
    """Escape a value for insertion in static HTML."""
    return html.escape(str(value if value is not None else ""))


def short(value: Any, *, limit: int = 80) -> str:
    """Return a compact string representation for report tables."""
    text = str(value if value is not None else "")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "..."


def relative(root: Path, path: Path) -> str:
    """Return a path relative to the comparison root when possible."""
    try:
        return Path(path).resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        return str(path)


def link_relative(web_dir: Path, path: Path) -> str:
    """Return a path usable from the HTML report location."""
    try:
        return Path(path).resolve().relative_to(web_dir.resolve()).as_posix()
    except Exception:
        try:
            import os

            return os.path.relpath(Path(path).resolve(), web_dir.resolve()).replace(
                "\\", "/"
            )
        except Exception:
            return str(path)


def render_table(
    rows: Iterable[Mapping[str, Any]],
    columns: list[tuple[str, str]],
    *,
    empty: str,
) -> str:
    """Render a compact static HTML table."""
    materialized = list(rows)
    if not materialized:
        return f'<p class="muted">{safe(empty)}</p>'
    header = "".join(f"<th>{safe(label)}</th>" for _, label in columns)
    body_rows: list[str] = []
    for row in materialized:
        cells = "".join(
            f"<td>{safe(short(row.get(key, '')))}</td>" for key, _ in columns
        )
        body_rows.append(f"<tr>{cells}</tr>")
    return (
        f"<table><thead><tr>{header}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody></table>"
    )


def render_links(*, root: Path, web_dir: Path, links: Iterable[Path]) -> str:
    """Render links to existing files."""
    blocks = []
    for path in links:
        if not path.exists():
            continue
        blocks.append(
            f'<p><a href="{safe(link_relative(web_dir, path))}">'
            f"{safe(relative(root, path))}</a></p>"
        )
    return "\n".join(blocks) if blocks else '<p class="muted">Aucun fichier cle.</p>'


__all__ = (
    "link_relative",
    "relative",
    "render_links",
    "render_table",
    "safe",
    "short",
)
