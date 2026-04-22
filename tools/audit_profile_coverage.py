"""Verify every Annotated Pydantic field in hydromodpy has a Profile tag.

Exits 1 with the list of uncovered fields on stderr. Used in CI to prevent
drift of the visibility classification introduced in v0.6.

The audit walks every :class:`HydroModelBase` subclass reachable from the
registered top-level configs and inspects their ``model_fields``. A field
is *covered* when its ``Annotated[...]`` metadata carries either a
:class:`Profile` enum or a legacy :class:`ParamLevel` dataclass (the shim
is still valid during the migration window).

When a field carries a forward-reference annotation, Pydantic's runtime
``metadata`` list is empty even if the source does tag the field. In that
case the audit falls back to an AST inspection of the class source to avoid
false positives.
"""
from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

import hydromodpy  # triggers registration of all sub-configs
from hydromodpy.core.config.base import HydroModelBase
from hydromodpy.core.config.param_level import ParamLevel
from hydromodpy.core.config.profile import Profile


def _runtime_has_profile(field_info) -> bool:
    metadata = getattr(field_info, "metadata", ())
    return any(isinstance(m, (Profile, ParamLevel)) for m in metadata)


def _ast_has_profile(src_file: Path, qualname: str, field_name: str) -> bool:
    """Return True if the source class body tags *field_name* with Profile/ParamLevel.

    Used as a fallback when runtime metadata is empty because the annotation
    is a :class:`typing.ForwardRef` string.
    """
    try:
        text = src_file.read_text(encoding="utf-8")
    except OSError:
        return False
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return False

    parts = qualname.split(".")
    parent: ast.AST = tree
    for part in parts:
        found = None
        for child in ast.iter_child_nodes(parent):
            if isinstance(child, ast.ClassDef) and child.name == part:
                found = child
                break
        if found is None:
            return False
        parent = found
    assert isinstance(parent, ast.ClassDef)

    for stmt in parent.body:
        if not (
            isinstance(stmt, ast.AnnAssign)
            and isinstance(stmt.target, ast.Name)
            and stmt.target.id == field_name
        ):
            continue
        ann = stmt.annotation
        if not (
            isinstance(ann, ast.Subscript)
            and isinstance(ann.value, ast.Name)
            and ann.value.id == "Annotated"
        ):
            return False
        slice_node = ann.slice
        if not isinstance(slice_node, ast.Tuple):
            return False
        for tag in slice_node.elts[1:]:
            if (
                isinstance(tag, ast.Attribute)
                and isinstance(tag.value, ast.Name)
                and tag.value.id == "Profile"
            ):
                return True
            if (
                isinstance(tag, ast.Call)
                and isinstance(tag.func, ast.Name)
                and tag.func.id == "ParamLevel"
            ):
                return True
        return False
    return False


def walk(cls=HydroModelBase, seen=None):
    seen = seen if seen is not None else set()
    for sub in cls.__subclasses__():
        if sub in seen:
            continue
        seen.add(sub)
        for field_name, info in sub.model_fields.items():
            if _runtime_has_profile(info):
                continue
            try:
                src_file = inspect.getsourcefile(sub)
            except TypeError:
                src_file = None
            if src_file is not None and _ast_has_profile(
                Path(src_file), sub.__qualname__, field_name
            ):
                continue
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
