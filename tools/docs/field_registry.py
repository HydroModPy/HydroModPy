"""The field registry: one entry per canonical TOML path of HydroModPyConfig.

Computed from the Pydantic models only. The documentation reads it to write the
parameter reference; nothing about a field is written anywhere else.

Usage:
    python -m tools.docs.field_registry OUT.json [--gates OUT.json] [--label TEXT]
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import enum
import inspect
import json
import re
import sys
import tomllib
import types
import typing
from collections import Counter, defaultdict
from pathlib import Path, PurePath
from typing import Any

import annotated_types as at
from pydantic import BaseModel
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined

from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.config_kit.profile import Profile

try:
    from hydromodpy.core.config_kit.visible_when import VisibleWhen
except ImportError:
    VisibleWhen = None
try:
    from hydromodpy.core.config_kit.calibrable import Calibrable
except ImportError:
    Calibrable = None

ROOT_TREE = Path(sys.modules["hydromodpy"].__path__[0]).parent

# ---------------------------------------------------------------- units

_QTY_UNITS = {
    "Length": "m",
    "Area": "m2",
    "Volume": "m3",
    "Time": "s",
    "FlowRate": "m3/s",
    "Velocity": "m/s",
    "HydraulicConductivity": "m/s",
    "SpecificStorage": "1/m",
    "SpecificYield": "-",
    "Dimensionless": "-",
    "LengthMeters": "m",
    "LengthMillimeters": "mm",
    "AreaSquareMeters": "m2",
    "VolumetricFlowM3PerSecond": "m3/s",
    "DurationSeconds": "s",
    "DurationDays": "day",
    "HydraulicConductivityMPerS": "m/s",
    "FluxDensityMPerS": "m/s",
}


def _clean_unit(text: str) -> str:
    return (
        str(text)
        .replace(" ** ", "**")
        .replace("**2", "2")
        .replace("**3", "3")
        .replace("meter", "m")
        .replace("second", "s")
        .replace(" / ", "/")
    )


def _quantity_markers() -> dict[int, tuple[str, str]]:
    """Map metadata object ids of the shared quantity types to (name, unit)."""
    markers: dict[int, tuple[str, str]] = {}
    import pkgutil

    import hydromodpy.core.units as units_pkg

    for info in pkgutil.iter_modules(units_pkg.__path__):
        try:
            mod = __import__(f"hydromodpy.core.units.{info.name}", fromlist=["x"])
        except Exception:
            continue
        for name in dir(mod):
            obj = getattr(mod, name)
            if typing.get_origin(obj) is not typing.Annotated:
                continue
            args = typing.get_args(obj)
            unit = _QTY_UNITS.get(name)
            for meta in args[1:]:
                pint_units = getattr(meta, "units", None)
                if unit is None and pint_units is not None and not callable(pint_units):
                    unit = _clean_unit(pint_units)
            if unit is None:
                continue
            for meta in args[1:]:
                markers[id(meta)] = (name, unit)
                func = getattr(meta, "func", None)
                if func is not None:
                    markers[id(func)] = (name, unit)
    return markers


QTY = _quantity_markers()

_SUFFIX_UNITS = [
    ("_mm_per_day", "mm/day"),
    ("_mm_day", "mm/day"),
    ("_m3s", "m3/s"),
    ("_m3_s", "m3/s"),
    ("_km2", "km2"),
    ("_m2", "m2"),
    ("_mm", "mm"),
    ("_km", "km"),
    ("_m", "m"),
    ("_days", "day"),
    ("_day", "day"),
    ("_hours", "h"),
    ("_s", "s"),
    ("_pct", "%"),
    ("_percent", "%"),
    ("_deg", "deg"),
]

# ---------------------------------------------------------------- typing helpers


def _strip_none(ann: Any) -> tuple[Any, bool]:
    origin = typing.get_origin(ann)
    if origin in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(ann) if a is not type(None)]
        optional = len(args) < len(typing.get_args(ann))
        if len(args) == 1:
            return args[0], optional
        return typing.Union[tuple(args)], optional  # noqa: UP007 - built from a runtime tuple
    return ann, False


def _unannotate(ann: Any) -> tuple[Any, list[Any]]:
    metas: list[Any] = []
    while typing.get_origin(ann) is typing.Annotated:
        args = typing.get_args(ann)
        ann = args[0]
        metas.extend(args[1:])
    return ann, metas


def _deep_metas(ann: Any) -> list[Any]:
    """Every Annotated metadata item found anywhere in the annotation."""
    out: list[Any] = []
    if typing.get_origin(ann) is typing.Annotated:
        args = typing.get_args(ann)
        out.extend(args[1:])
        out.extend(_deep_metas(args[0]))
    elif typing.get_origin(ann) in (typing.Union, types.UnionType):
        for a in typing.get_args(ann):
            out.extend(_deep_metas(a))
    return out


def _is_model(tp: Any) -> bool:
    return isinstance(tp, type) and issubclass(tp, BaseModel)


def _literal_values(ann: Any) -> list[Any]:
    ann, _ = _unannotate(ann)
    origin = typing.get_origin(ann)
    if origin is typing.Literal:
        return list(typing.get_args(ann))
    if origin in (typing.Union, types.UnionType):
        vals: list[Any] = []
        for a in typing.get_args(ann):
            if a is type(None):
                continue
            vals.extend(_literal_values(a))
        return vals
    if isinstance(ann, type) and issubclass(ann, enum.Enum):
        return [m.value for m in ann]
    return []


def _toml_lit(value: Any) -> str:
    if value is None:
        return "not set"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, enum.Enum):
        return _toml_lit(value.value)
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, PurePath):
        return json.dumps(str(value), ensure_ascii=False)
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [_toml_lit(v) for v in value]
        text = "[" + ", ".join(items) + "]"
        return text if len(text) <= 80 else "[" + ", ".join(items[:4]) + ", ...]"
    if isinstance(value, dict):
        if not value:
            return "{}"
        items = [f"{k} = {_toml_lit(v)}" for k, v in list(value.items())[:4]]
        more = ", ..." if len(value) > 4 else ""
        return "{ " + ", ".join(items) + more + " }"
    if isinstance(value, BaseModel):
        return "(table, all defaults)"
    magnitude = getattr(value, "magnitude", None)
    units = getattr(value, "units", None)
    if magnitude is not None and units is not None:
        return json.dumps(f"{magnitude:g} {_clean_unit(units)}")
    return repr(value)[:80]


def _scalar_form(tp: Any, unit: str | None, quantity: bool) -> str:
    tp, _ = _unannotate(tp)
    origin = typing.get_origin(tp)
    if origin is typing.Literal:
        return " | ".join(_toml_lit(v) for v in typing.get_args(tp))
    if isinstance(tp, type) and issubclass(tp, enum.Enum):
        return " | ".join(_toml_lit(m.value) for m in tp)
    if origin in (typing.Union, types.UnionType):
        parts = []
        for a in typing.get_args(tp):
            if a is type(None):
                continue
            form = _scalar_form(a, unit, quantity)
            if form not in parts:
                parts.append(form)
        return " or ".join(parts)
    if origin in (list, tuple, set, frozenset):
        args = [a for a in typing.get_args(tp) if a is not Ellipsis]
        inner = _scalar_form(args[0], unit, quantity) if args else "value"
        return f"list of {inner}"
    if origin is dict:
        args = typing.get_args(tp)
        inner = _scalar_form(args[1], unit, quantity) if len(args) == 2 else "value"
        return f"table {{ key = {inner} }}"
    if tp is bool:
        return "true | false"
    if tp is int:
        return "integer"
    if tp is float:
        if quantity and unit:
            return f'number or "<n> {unit}"'
        return "number"
    if tp is str:
        return "string"
    if isinstance(tp, type) and issubclass(tp, PurePath):
        return "path"
    if tp in (dt.date, dt.datetime):
        return 'date "YYYY-MM-DD"'
    if tp in (object, Any):
        if quantity and unit:
            return f'number or "<n> {unit}"'
        return "any value"
    name = getattr(tp, "__name__", str(tp))
    return name


def _children_models(ann: Any) -> tuple[str, list[type[BaseModel]]]:
    """Return (shape, models) for a field annotation.

    shape is "table", "map", "array", "union" or "" for a scalar.
    """
    ann, _ = _strip_none(ann)
    ann, _ = _unannotate(ann)
    origin = typing.get_origin(ann)
    if _is_model(ann):
        return "table", [ann]
    if origin in (typing.Union, types.UnionType):
        models = []
        for a in typing.get_args(ann):
            a, _ = _unannotate(a)
            if _is_model(a):
                models.append(a)
        if len(models) >= 2:
            return "union", models
        if len(models) == 1:
            return "table", models
        return "", []
    if origin in (list, tuple):
        args = [a for a in typing.get_args(ann) if a is not Ellipsis]
        if args:
            inner, _ = _unannotate(args[0])
            inner_shape, inner_models = _children_models(inner)
            if inner_shape in ("table", "union"):
                return "array", inner_models
        return "", []
    if origin is dict:
        args = typing.get_args(ann)
        if len(args) == 2:
            inner_shape, inner_models = _children_models(args[1])
            if inner_shape in ("table", "union"):
                return "map", inner_models
        return "", []
    return "", []


def _first_paragraph(text: str | None) -> str:
    if not text:
        return ""
    para = text.strip().split("\n\n")[0]
    return " ".join(para.split())


_ABBREV = {
    "e.g",
    "i.e",
    "etc",
    "vs",
    "cf",
    "approx",
    "fig",
    "eq",
    "resp",
    "incl",
    "nb",
    "no",
    "min",
    "max",
    "default",
}


def _first_sentence(text: str) -> str:
    """First sentence, not fooled by e.g., decimals, file names or parentheses."""
    text = " ".join((text or "").split())
    depth = 0
    for i, ch in enumerate(text):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        elif ch in ".!?" and depth == 0:
            nxt = text[i + 1 : i + 2]
            if nxt and nxt != " ":
                continue
            token = re.findall(r"[\w.]+$", text[:i])
            if token and token[0].lower() in _ABBREV:
                continue
            after = text[i + 2 : i + 3]
            if after and not (after.isupper() or after.isdigit() or after in "`'\"("):
                continue
            return text[: i + 1]
    return text


def _source_of(model: type[BaseModel]) -> str:
    try:
        file = inspect.getsourcefile(model)
        line = inspect.getsourcelines(model)[1]
        return f"{Path(file).relative_to(ROOT_TREE)}:{line}"
    except Exception:
        return model.__module__


def _discriminator(field: FieldInfo, models: list[type[BaseModel]]) -> str | None:
    disc = field.discriminator
    if isinstance(disc, str):
        return disc
    common = set(models[0].model_fields)
    for m in models[1:]:
        common &= set(m.model_fields)
    for name in sorted(common):
        vals = [tuple(_literal_values(m.model_fields[name].annotation)) for m in models]
        if all(len(v) == 1 for v in vals) and len({v[0] for v in vals}) == len(models):
            return name
    return None


def _default_of(field: FieldInfo) -> tuple[str | None, Any]:
    if field.default is not PydanticUndefined:
        return _toml_lit(field.default), field.default
    if field.default_factory is not None:
        try:
            value = field.default_factory()
        except TypeError:
            return "(computed)", None
        except Exception:
            return "(computed)", None
        return _toml_lit(value), value
    return None, None


# ---------------------------------------------------------------- registry

nodes: dict[str, dict[str, Any]] = {}
children: dict[str, list[str]] = defaultdict(list)


def anchor_of(path: str) -> str:
    return "p-" + re.sub(r"[^a-z0-9_]+", "-", path.lower().replace("<", "").replace(">", "")).strip(
        "-"
    )


def _add_child(parent: str, path: str) -> None:
    if path not in children[parent]:
        children[parent].append(path)


def _leaf_info(name: str, field: FieldInfo, path: str) -> dict[str, Any]:
    ann = field.annotation
    base, optional = _strip_none(ann)
    metas = list(field.metadata) + _deep_metas(ann)
    profile = next((m for m in metas if isinstance(m, Profile)), Profile.USER)
    extra = field.json_schema_extra if isinstance(field.json_schema_extra, dict) else {}
    unit, unit_source, quantity, qty_type = None, None, False, None
    for m in metas:
        hit = QTY.get(id(m)) or QTY.get(id(getattr(m, "func", None)))
        if hit:
            qty_type, unit = hit
            unit_source, quantity = "type", True
            break
    if extra.get("unit"):
        unit, unit_source = str(extra["unit"]), "metadata"
    calib = extra.get("calibrable")
    calib_info = None
    if Calibrable is not None and isinstance(calib, Calibrable):
        calib_info = {
            "bounds": list(calib.bounds) if calib.bounds else None,
            "transform": calib.transform,
            "prior": calib.prior,
            "units": calib.units,
        }
        if unit is None and calib.units:
            unit, unit_source = calib.units, "calibrable"
    if unit is None:
        for suffix, u in _SUFFIX_UNITS:
            if name.endswith(suffix):
                unit, unit_source = u, "name"
                break
    rng: dict[str, Any] = {}
    for m in metas:
        for attr in ("ge", "gt", "le", "lt", "multiple_of", "min_length", "max_length"):
            val = getattr(m, attr, None)
            if val is not None and isinstance(m, (at.BaseMetadata, at.Interval)):
                rng[attr] = val
        if isinstance(m, FieldInfo):
            for sub in m.metadata:
                for attr in ("ge", "gt", "le", "lt"):
                    val = getattr(sub, attr, None)
                    if val is not None:
                        rng[attr] = val
    when = []
    if VisibleWhen is not None:
        for m in metas:
            if isinstance(m, VisibleWhen):
                vals = m.values if isinstance(m.values, tuple) else (m.values,)
                when.append({"field": m.field, "values": list(vals), "source": "VisibleWhen"})
    default_text, default_value = _default_of(field)
    literal = _literal_values(base)
    desc = (field.description or "").strip()
    return {
        "path": path,
        "name": name,
        "kind": "leaf",
        "anchor": anchor_of(path),
        "profile": profile.name.lower(),
        "required": field.is_required(),
        "optional": optional,
        "default": default_text,
        "form": _scalar_form(base, unit, quantity),
        "python_type": re.sub(r"\b[\w.]+\.(\w+)", r"\1", str(ann).replace("typing.", ""))[:160],
        "unit": unit,
        "unit_source": unit_source,
        "quantity": quantity,
        "quantity_type": qty_type,
        "range": rng,
        "literal": [v if not isinstance(v, enum.Enum) else v.value for v in literal],
        "value_docs": extra.get("value_docs") or {},
        "examples": [_toml_lit(e) for e in (field.examples or [])],
        "calibrable": calib_info,
        "stability": extra.get("stability"),
        "label_fr": extra.get("display_name_fr"),
        "group": extra.get("group"),
        "when": when,
        "description": desc,
        "summary": _first_sentence(desc),
        "deprecated": bool(getattr(field, "deprecated", None)),
        "numeric": _unannotate(base)[0] in (int, float) or quantity,
    }


def walk(model: type[BaseModel], path: str, stack: tuple[type, ...], variant: dict | None) -> None:
    for name, field in model.model_fields.items():
        if getattr(field, "exclude", False):
            continue
        key = field.alias or name
        child_path = f"{path}.{key}" if path else key
        shape, models = _children_models(field.annotation)
        metas = list(field.metadata)
        profile = next((m for m in metas if isinstance(m, Profile)), Profile.USER)
        if not shape:
            info = _leaf_info(key, field, child_path)
            info["model"] = model.__name__
            info["source"] = _source_of(model)
            if variant:
                existing = nodes.get(child_path)
                if existing and existing.get("variants"):
                    existing["variants"].append(variant["value"])
                    if key == variant["field"]:
                        for v in info["literal"]:
                            if v not in existing["literal"]:
                                existing["literal"].append(v)
                        existing["form"] = " | ".join(json.dumps(v) for v in existing["literal"])
                    continue
                info["variants"] = [variant["value"]]
                info["variant_field"] = variant["field"]
                if key == variant["field"]:
                    info["is_tag"] = True
            nodes[child_path] = info
            _add_child(path, child_path)
            continue
        default_text, _ = _default_of(field)
        table = {
            "path": child_path,
            "name": key,
            "kind": shape,
            "anchor": anchor_of(child_path),
            "profile": profile.name.lower(),
            "required": field.is_required(),
            "default": default_text,
            "description": (field.description or "").strip(),
            "summary": _first_sentence(field.description or ""),
            "models": [m.__name__ for m in models],
            "doc": _first_paragraph(inspect.getdoc(models[0])) if len(models) == 1 else "",
            "source": _source_of(models[0]),
            "model": model.__name__,
        }
        if variant and child_path not in nodes:
            table["variants"] = [variant["value"]]
            table["variant_field"] = variant["field"]
        elif variant and nodes.get(child_path, {}).get("variants") is not None:
            nodes[child_path]["variants"].append(variant["value"])
        if child_path not in nodes:
            nodes[child_path] = table
            _add_child(path, child_path)
        target_path = child_path
        if shape == "map":
            placeholder = "<id>" if key == "param" else "<name>"
            target_path = f"{child_path}.{placeholder}"
            item_shape = "union" if len(models) > 1 else "table"
            nodes[target_path] = {
                **table,
                "path": target_path,
                "name": placeholder,
                "kind": item_shape,
                "anchor": anchor_of(target_path),
                "description": "",
                "summary": "",
                "required": False,
                "default": None,
                "is_map_item": True,
            }
            _add_child(child_path, target_path)
        if len(models) >= 2:
            disc = _discriminator(field, models)
            host = nodes[target_path]
            host["discriminator"] = disc
            host["variants_detail"] = []
            for m in models:
                tag = None
                if disc and disc in m.model_fields:
                    vals = _literal_values(m.model_fields[disc].annotation)
                    tag = vals[0] if vals else None
                req = [
                    (f.alias or n)
                    for n, f in m.model_fields.items()
                    if f.is_required() and n != disc and not getattr(f, "exclude", False)
                ]
                host["variants_detail"].append(
                    {
                        "value": tag if tag is not None else m.__name__,
                        "model": m.__name__,
                        "doc": _first_paragraph(inspect.getdoc(m)),
                        "required": req,
                        "source": _source_of(m),
                    }
                )
                if m in stack:
                    continue
                walk(
                    m,
                    target_path,
                    stack + (m,),
                    {"field": disc, "value": tag if tag is not None else m.__name__},
                )
        else:
            m = models[0]
            if m in stack:
                continue
            walk(m, target_path, stack + (m,), None)


def build() -> dict[str, Any]:
    nodes.clear()
    children.clear()
    nodes[""] = {"path": "", "name": "", "kind": "root", "anchor": "p-root"}
    walk(HydroModPyConfig, "", (HydroModPyConfig,), None)
    _known_keys()
    for path, node in nodes.items():
        node["children"] = children.get(path, [])
        node["section"] = path.split(".")[0] if path else ""
    return nodes


def _known_keys() -> None:
    """Named instances of flow.param.<id> from the code (units and physical bounds)."""
    try:
        from hydromodpy.physics.flow.flow_config import FlowConfig
        from hydromodpy.spatial.field.core.physical_bounds import PHYSICAL_BOUNDS
    except Exception:
        return
    units = getattr(FlowConfig, "_DEFAULT_PARAM_UNITS", {})
    known = {}
    for key, unit in units.items():
        bound = PHYSICAL_BOUNDS.get(key.lower())
        known[key] = {
            "unit": unit,
            "physical": [bound.lo, bound.hi] if bound else None,
            "physical_unit": bound.canonical_unit if bound else None,
            "label_en": bound.label if bound else None,
        }
    host = nodes.get("flow.param.<id>")
    if host is not None:
        host["known_keys"] = known
        host["known_keys_source"] = "FlowConfig._DEFAULT_PARAM_UNITS + PHYSICAL_BOUNDS"


# ---------------------------------------------------------------- path resolution

HEADER = re.compile(r"^\s*(\[\[?)\s*([^\]]+?)\s*(\]\]?)\s*(#.*)?$")
KEYLINE = re.compile(r"^\s*([A-Za-z0-9_\-\.\"]+)\s*=\s*(.*)$")


def resolve(concrete: str) -> str | None:
    """Map a concrete TOML path to its canonical registry path."""
    current = ""
    for seg in concrete.split("."):
        seg = seg.strip('"')
        for suffix in ("__append", "__delete"):
            if seg.endswith(suffix):
                seg = seg[: -len(suffix)]
        candidates = children.get(current, [])
        nxt = f"{current}.{seg}" if current else seg
        if nxt in candidates:
            current = nxt
            continue
        node = nodes.get(current)
        if node and node.get("kind") == "map" and candidates:
            current = candidates[0]
            continue
        return None
    return current


# ---------------------------------------------------------------- code mentions

PATH_TOKEN = re.compile(r"(?<![\w.])\[{0,2}([a-z][a-z0-9_]*(?:\.[A-Za-z0-9_<>]+)+)\]{0,2}")


def _table_of(canon: str) -> str:
    node = nodes.get(canon, {})
    return canon.rsplit(".", 1)[0] if node.get("kind") == "leaf" and "." in canon else canon


def scan_mentions(package_dir: Path, roots: set[str]) -> dict[str, list[dict[str, Any]]]:
    """Tables named together in the code, weighted by how close the two names are.

    Two paths in one string weigh 1. Two paths in one function weigh 1 / (k - 1), k being
    the number of tables that function names, so a function that lists every section
    weighs little; a string that lists many sections too. A link is kept from 0.6.
    """
    weight: dict[tuple[str, str], float] = defaultdict(float)
    evidence: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
    for py in sorted(package_dir.rglob("*.py")):
        try:
            tree = ast.parse(py.read_text(), filename=str(py))
        except (SyntaxError, UnicodeDecodeError):
            continue
        rel = str(py.relative_to(package_dir.parent))
        for scope in ast.walk(tree):
            if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            hits = []
            for sid, node in enumerate(
                n
                for n in ast.walk(scope)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
            ):
                for m in PATH_TOKEN.finditer(node.value):
                    token = m.group(1)
                    if token.split(".")[0] not in roots:
                        continue
                    canon = resolve(token)
                    if canon is None:
                        continue
                    hits.append(
                        (
                            canon,
                            _table_of(canon),
                            sid,
                            getattr(node, "lineno", scope.lineno),
                            " ".join(node.value.split())[:160],
                        )
                    )
            tables = {h[1] for h in hits}
            if len(tables) < 2 or len(tables) > 8:
                continue
            per_string: dict[int, set[str]] = defaultdict(set)
            for h in hits:
                per_string[h[2]].add(h[1])
            k = len(tables)
            for a_canon, a_table, a_sid, _, _ in hits:
                for b_canon, b_table, b_sid, b_line, b_text in hits:
                    if (
                        a_table == b_table
                        or a_table.startswith(b_table + ".")
                        or b_table.startswith(a_table + ".")
                    ):
                        continue
                    if a_sid == b_sid:
                        w = 1.0 / (len(per_string[a_sid]) - 1)
                    else:
                        w = 1.0 / (k - 1) if k <= 3 else 0.5 / (k - 1)
                    key = (a_table, b_canon)
                    weight[key] += w
                    if key not in evidence or w > evidence[key][0]:
                        evidence[key] = (
                            w,
                            {
                                "other": b_canon,
                                "file": rel,
                                "line": b_line,
                                "func": scope.name,
                                "text": b_text,
                            },
                        )
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (a, b), w in sorted(weight.items(), key=lambda kv: -kv[1]):
        if w < 0.6:
            continue
        if len(out[a]) < 6:
            item = dict(evidence[(a, b)][1])
            item["weight"] = round(w, 2)
            out[a].append(item)
    return dict(out)


# ---------------------------------------------------------------- gates

JARGON = re.compile(
    r"\b(runtime|backend|payload|dispatch|historical|legacy|kwargs?|callable|instance of)\b"
    r"|:class:|:attr:|:func:|:meth:|\b[A-Z][a-z]+[A-Z][A-Za-z]+(Config|Section|Model|Spec)\b"
)
CONDITION = re.compile(
    r"\b(only (when|if|used)|used when|required when|ignored unless|read only when|ignored when"
    r"|when \w+ (is|=))",
    re.IGNORECASE,
)


def gates(reg: dict[str, dict[str, Any]]) -> dict[str, Any]:
    per: dict[str, Counter] = defaultdict(Counter)
    for node in reg.values():
        if node.get("kind") != "leaf":
            continue
        sec = node["section"]
        user = node["profile"] == "user"
        c = per[sec]
        c["leaves"] += 1
        if not user:
            continue
        c["user"] += 1
        words = len(node["description"].split())
        if words == 0:
            c["G2_no_description"] += 1
        elif words < 6:
            c["G2_short_description"] += 1
        if node["numeric"] and not node["unit"]:
            c["G3_numeric_without_unit"] += 1
        if len(node["literal"]) >= 2 and not node["value_docs"]:
            c["G4_literal_without_value_docs"] += 1
        if CONDITION.search(node["description"]) and not node["when"] and not node.get("variants"):
            c["G5_condition_in_prose"] += 1
        if JARGON.search(node["description"]):
            c["G6_jargon"] += 1
        if not node.get("group"):
            c["G7_no_group"] += 1
    total = Counter()
    for c in per.values():
        total.update(c)
    return {"per_section": {k: dict(v) for k, v in sorted(per.items())}, "total": dict(total)}


def build_payload(label: str = "") -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the registry payload and the documentation gates."""
    reg = build()
    mentions = scan_mentions(ROOT_TREE / "hydromodpy", set(reg[""]["children"]))
    for path, items in mentions.items():
        if path in reg:
            reg[path]["co_mentions"] = items
    leaves = [n for n in reg.values() if n.get("kind") == "leaf"]
    payload = {
        "meta": {
            "label": label,
            "paths": len(reg) - 1,
            "leaves": len(leaves),
            "user_leaves": sum(1 for n in leaves if n["profile"] == "user"),
            "roots": reg[""]["children"],
        },
        "nodes": reg,
    }
    return payload, gates(reg)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out")
    ap.add_argument("--gates")
    ap.add_argument("--label", default="")
    args = ap.parse_args()
    payload, gate_counts = build_payload(args.label)
    Path(args.out).write_text(json.dumps(payload, indent=1, ensure_ascii=False, default=str))
    print(
        f"registry: {payload['meta']['paths']} paths, {payload['meta']['leaves']} leaves -> {args.out}"
    )
    if args.gates:
        Path(args.gates).write_text(json.dumps(gate_counts, indent=1))


if __name__ == "__main__":
    main()
