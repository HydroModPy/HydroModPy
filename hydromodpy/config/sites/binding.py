"""``[sites.bind]``: a config key filled from a table column, typed by the key.

A bind line maps a quoted dotted path (:mod:`hydromodpy.core.toml_io.paths`)
to one column, or to a list of columns for a list key. The path is checked
against the schema of the configuration when the plan is built, so an
unknown key is refused with its nearest neighbours before any table is read.
A cell is read by the type of the target field and never converted beyond
that: ``"389285.910"`` becomes a float for a float key and stays text for a
text key. An empty cell leaves the key unbound.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import BaseModel, TypeAdapter, ValidationError
from pydantic.fields import FieldInfo

from hydromodpy.config.sites.tables import CellOrigin, Table, TableRow, is_empty_cell
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.toml_io.paths import (
    DottedPath,
    UnknownPathError,
    assign,
    parse,
    resolve_field,
)


class BindingError(ConfigError):
    """A bind line names a key the schema has not, or a column no table has."""


class CellError(ConfigError):
    """A cell cannot be read by the type of the key it is bound to."""

    def __init__(self, origin: CellOrigin, target: DottedPath, message: str) -> None:
        super().__init__(f"{origin} -> {target}: {message}")
        self.origin = origin
        self.target = target
        self.detail = message


@dataclass(frozen=True, slots=True)
class Binding:
    """One bind line, resolved against the schema."""

    path: DottedPath
    columns: tuple[str, ...]
    field: FieldInfo

    @property
    def is_list(self) -> bool:
        """Whether the line binds a list of columns."""
        return len(self.columns) > 1


@dataclass(frozen=True, slots=True)
class BoundValue:
    """One value a row gave a case, with the cell it came from."""

    path: DottedPath
    origin: CellOrigin
    value: Any

    def covers(self, loc: str) -> bool:
        """Whether a validation location names this key or a key under it."""
        here = str(self.path)
        return loc == here or loc.startswith(here + ".")


def resolve_bindings(
    bind: Mapping[str, str | Sequence[str]],
    *,
    schema: type[BaseModel],
    where: str,
) -> list[Binding]:
    """Check every bind line against *schema* and return the bindings.

    A key the schema has not raises :class:`BindingError` with the nearest
    field names; a key that is a table is refused too, since a cell holds a
    value. *where* names the file of the ``[sites.bind]`` table in messages.
    """
    bindings: list[Binding] = []
    for key, columns in bind.items():
        try:
            path = parse(key)
            field = resolve_field(schema, path)
        except UnknownPathError as exc:
            raise BindingError(f"{where}: [sites.bind] {exc}") from exc
        except ValueError as exc:
            raise BindingError(f"{where}: [sites.bind] {key!r}: {exc}") from exc
        if _names_a_model(field):
            raise BindingError(
                f"{where}: [sites.bind] {path} is a table, and a cell holds a value; bind "
                "the keys of the table one by one."
            )
        names = (columns,) if isinstance(columns, str) else tuple(str(name) for name in columns)
        bindings.append(Binding(path=path, columns=names, field=field))
    return bindings


def check_columns(bindings: Sequence[Binding], tables: Sequence[Table], *, where: str) -> None:
    """Refuse a bound column no table has, or one that two tables share."""
    seen: dict[str, list[str]] = {}
    for table in tables:
        for column in table.columns:
            seen.setdefault(column, []).append(table.label)
    shared = sorted(column for column, labels in seen.items() if len(labels) > 1)
    if shared:
        labels = " and ".join(sorted({label for table in tables for label in [table.label]}))
        raise BindingError(
            f"{where}: column(s) {', '.join(shared)} present in both {labels}; a column "
            "belongs to one table."
        )
    for binding in bindings:
        missing = [column for column in binding.columns if column not in seen]
        if missing:
            tables_named = ", ".join(table.label for table in tables) or "no table"
            raise BindingError(
                f"{where}: [sites.bind] {binding.path} names column(s) "
                f"{', '.join(missing)}, found in {tables_named}."
            )
        owners = {seen[column][0] for column in binding.columns}
        if len(owners) > 1:
            raise BindingError(
                f"{where}: [sites.bind] {binding.path} binds columns of two tables "
                f"({', '.join(sorted(owners))}); bind columns of one table."
            )


def bindings_of_table(bindings: Sequence[Binding], table: Table) -> list[Binding]:
    """Return the bindings whose columns belong to *table*."""
    return [b for b in bindings if all(column in table.columns for column in b.columns)]


def render_row(
    bindings: Sequence[Binding], row: TableRow, table: Table
) -> tuple[dict[str, Any], list[BoundValue]]:
    """Render the cells of *row* into a payload, and return what was bound.

    A binding whose cells are all empty is skipped. A list binding with some
    cells empty and others filled is refused: a list is bound whole.
    """
    payload: dict[str, Any] = {}
    bound: list[BoundValue] = []
    for binding in bindings:
        cells = [row.cells.get(column) for column in binding.columns]
        empty = [is_empty_cell(cell) for cell in cells]
        origin = row.origin(table, binding.columns[0])
        if all(empty):
            continue
        if any(empty):
            blank = [c for c, e in zip(binding.columns, empty, strict=True) if e]
            raise CellError(
                origin, binding.path, f"column(s) {', '.join(blank)} empty; fill every cell or none"
            )
        value = render_cells(binding, cells, origin)
        assign(payload, binding.path, value)
        bound.append(BoundValue(path=binding.path, origin=origin, value=value))
    return payload, bound


def render_cells(binding: Binding, cells: Sequence[Any], origin: CellOrigin) -> Any:
    """Read the cells of one binding by the type of its key.

    A text cell is first read as a TOML value (a number, a boolean, a date,
    an array); when the key accepts that value it is kept, otherwise the text
    itself is tried. What the key accepts neither way raises
    :class:`CellError` with the message of the schema.
    """
    adapter = _adapter(binding.field)
    candidates = _candidates(cells, is_list=binding.is_list)
    message = ""
    for candidate in candidates:
        try:
            adapter.validate_python(candidate)
        except ValidationError as exc:
            message = "; ".join(error["msg"] for error in exc.errors()) or str(exc)
            continue
        return candidate
    raise CellError(origin, binding.path, message or "no value")


def _candidates(cells: Sequence[Any], *, is_list: bool) -> list[Any]:
    """Return the values to try, typed first, then as written."""
    if is_list:
        typed = [_as_toml_value(cell) for cell in cells]
        written = [cell for cell in cells]
        out = [typed]
        if written != typed:
            out.append(written)
        return out
    cell = cells[0]
    typed = _as_toml_value(cell)
    return [typed] if typed is cell else [typed, cell]


def _as_toml_value(cell: Any) -> Any:
    """Return a text cell read as one TOML value, or the cell itself."""
    if not isinstance(cell, str):
        return cell
    try:
        return tomllib.loads(f"value = {cell.strip()}\n")["value"]
    except tomllib.TOMLDecodeError:
        return cell


def _adapter(field: FieldInfo) -> TypeAdapter[Any]:
    """Return the validator of one field, its constraints included."""
    annotation = field.annotation
    if field.metadata:
        annotation = Annotated[(annotation, *field.metadata)]  # type: ignore[valid-type]
    return TypeAdapter(annotation)


def _names_a_model(field: FieldInfo) -> bool:
    """Whether the field holds a model, or a table of models, which a cell cannot."""
    from hydromodpy.core.config_kit.introspect import iter_basemodels

    return bool(iter_basemodels(field.annotation))


__all__ = [
    "Binding",
    "BindingError",
    "BoundValue",
    "CellError",
    "bindings_of_table",
    "check_columns",
    "render_cells",
    "render_row",
    "resolve_bindings",
]
