"""The register of changes, rendered as tables from ``hydromodpy/schema/changes.toml``.

``hmp-changes-register`` takes one of ``bug``, ``default``, ``recipe`` or ``migration``
and renders every row of that table, in the order of the file. Nobody writes the page:
a row added to the register shows up on it at the next build.

A cell is plain text, never markup, because the text of a row is a changelog line that may
hold backticks, brackets or asterisks.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from docutils import nodes
from sphinx.util.docutils import SphinxDirective

from hydromodpy.schema import changes
from hydromodpy.schema.changes import Register

TABLES = ("bug", "default", "recipe", "migration")
CODE_COLUMN = {"bug": 0, "default": 0, "recipe": 0, "migration": 1}
"""The column of each table that is written as code: the id, or the form of a migration."""


def _show(value: Any) -> str:
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def _list(tokens: Sequence[str]) -> str:
    return ", ".join(tokens) or "none"


def _form(row: changes.Migration) -> str:
    if row.shape == "move":
        return f"{row.old} -> {row.new}"
    if row.shape == "value":
        return f"{row.key}: {_show(row.old_value)} -> {_show(row.new_value)}"
    return f"{row.old} (left)"


def _note(row: changes.Migration) -> str:
    parts = []
    if row.instead:
        parts.append(row.instead)
    if row.sealed == "drop":
        parts.append("A sealed run drops it.")
    return " ".join(parts) or "-"


def _refused_from(row: changes.Migration) -> str:
    """The version from which a live file is refused, ``-`` for a stored document."""
    if row.document != "config":
        return "-"
    return row.since if row.shape == "retire" else changes.removal_of(row.since)


def rows_of(table: str, register: Register) -> tuple[list[str], list[list[str]], list[int]]:
    """Return the head, the cells and the column widths of the table of *register*."""
    if table == "bug":
        head = ["Id", "Since", "Versions", "Quantities", "What changed"]
        cells = [[b.id, b.since, b.versions, _list(b.quantities), b.text] for b in register.bugs]
        return head, cells, [14, 6, 8, 14, 58]
    if table == "default":
        head = ["Id", "Since", "Edition", "Key", "Old", "New", "Quantities", "What changed"]
        cells = [
            [
                d.id,
                d.since,
                d.edition,
                d.key,
                _show(d.old),
                _show(d.new),
                _list(d.quantities),
                d.text,
            ]
            for d in register.defaults
        ]
        return head, cells, [12, 5, 6, 12, 6, 6, 10, 43]
    if table == "recipe":
        head = ["Id", "Since", "Effect", "Quantities", "What changed"]
        cells = [[r.id, r.since, r.effect, _list(r.quantities), r.text] for r in register.recipes]
        return head, cells, [18, 6, 8, 12, 56]
    if table == "migration":
        head = ["Document", "Form", "Since", "Refused from", "Note"]
        cells = [
            [m.document, _form(m), m.since, _refused_from(m), _note(m)] for m in register.migrations
        ]
        return head, cells, [9, 36, 7, 9, 39]
    raise ValueError(f"table must be one of {TABLES}, got {table!r}")


def _entry(text: str, *, code: bool) -> nodes.entry:
    inline: nodes.Node = nodes.literal(text, text) if code else nodes.Text(text)
    return nodes.entry("", nodes.paragraph("", "", inline))


def table_node(
    head: list[str], cells: list[list[str]], widths: list[int], code_column: int
) -> nodes.table:
    """Return a table whose cells are plain text, one column of them written as code."""
    table = nodes.table("", classes=["colwidths-given"])
    group = nodes.tgroup("", cols=len(head))
    table += group
    for width in widths:
        group += nodes.colspec(colwidth=width)
    header = nodes.thead()
    header += nodes.row("", *(_entry(name, code=False) for name in head))
    group += header
    body = nodes.tbody()
    for row in cells:
        body += nodes.row(
            "", *(_entry(text, code=index == code_column) for index, text in enumerate(row))
        )
    group += body
    return table


class RegisterDirective(SphinxDirective):
    """Every row of one table of the register of changes."""

    required_arguments = 1
    has_content = False

    def run(self) -> list[nodes.Node]:
        table = self.arguments[0]
        if table not in TABLES:
            raise self.error(f"hmp-changes-register takes one of {', '.join(TABLES)}")
        self.env.note_dependency(str(Path(changes.__file__).with_name(changes.REGISTER_FILENAME)))
        head, cells, widths = rows_of(table, changes.REGISTER)
        if not cells:
            return [nodes.paragraph(text="The register holds no row of this kind yet.")]
        return [table_node(head, cells, widths, CODE_COLUMN[table])]


def setup(app) -> dict[str, Any]:
    app.add_directive("hmp-changes-register", RegisterDirective)
    return {"version": "0.1", "parallel_read_safe": True, "parallel_write_safe": True}
