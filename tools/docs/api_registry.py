"""Build the registry of the public Python API and of the command line.

Everything comes from the package: ``hydromodpy.__all__``, signatures, docstrings,
the argparse parser of ``hmp``, and the calls the CLI commands make to the API.

Usage:
    python -m tools.docs.api_registry OUT.json --fields REGISTRY.json
"""

from __future__ import annotations

import argparse
import ast
import inspect
import json
import re
import sys
import types
from pathlib import Path
from typing import Any

from pydantic import BaseModel

import hydromodpy as hmp

TREE = Path(hmp.__path__[0]).parent
SECTION = re.compile(r"^([A-Z][A-Za-z ]+)\n-{3,}\s*$", re.M)


def first_line(doc: str | None) -> str:
    return " ".join((doc or "").strip().split("\n\n")[0].split())


def sections(doc: str | None) -> list[str]:
    return SECTION.findall(doc or "")


def source_of(obj: Any) -> str:
    try:
        file = inspect.getsourcefile(obj)
        line = inspect.getsourcelines(obj)[1]
        return f"{Path(file).relative_to(TREE)}:{line}"
    except (TypeError, OSError, ValueError):
        return ""


def signature_of(obj: Any) -> str:
    try:
        return str(inspect.signature(obj))
    except (TypeError, ValueError):
        return ""


def return_names(fn: Any) -> list[str]:
    try:
        ann = inspect.signature(fn).return_annotation
    except (TypeError, ValueError):
        return []
    text = ann if isinstance(ann, str) else getattr(ann, "__name__", str(ann))
    return re.findall(r"\b([A-Z][A-Za-z0-9_]+)\b", text)


def type_checking_names(module: types.ModuleType) -> tuple[dict[str, str], dict[str, str]]:
    """Names imported or aliased under ``if TYPE_CHECKING:`` in a module: name -> module, alias -> text."""
    imports: dict[str, str] = {}
    aliases: dict[str, str] = {}
    try:
        tree = ast.parse(Path(module.__file__).read_text())
    except (OSError, TypeError, SyntaxError):
        return imports, aliases
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.unparse(node.test):
            for stmt in node.body:
                if isinstance(stmt, ast.ImportFrom) and stmt.module:
                    for alias in stmt.names:
                        imports[alias.asname or alias.name] = stmt.module
                elif (
                    isinstance(stmt, ast.Assign)
                    and len(stmt.targets) == 1
                    and isinstance(stmt.targets[0], ast.Name)
                ):
                    text = ast.unparse(stmt.value)
                    for short, full in (
                        ("gpd.", "geopandas."),
                        ("xr.", "xarray."),
                        ("pd.", "pandas."),
                        ("np.", "numpy."),
                    ):
                        text = text.replace(short, full)
                    aliases[stmt.targets[0].id] = text
    return imports, aliases


def resolve_class(name: str, fn: Any) -> Any:
    module = sys.modules.get(fn.__module__)
    for obj in (getattr(module, name, None), getattr(hmp, name, None)):
        if inspect.isclass(obj) and obj.__module__.startswith("hydromodpy"):
            return obj
    if module is not None:
        imports, _ = type_checking_names(module)
        if name in imports:
            try:
                obj = getattr(__import__(imports[name], fromlist=[name]), name, None)
            except Exception:
                obj = None
            if inspect.isclass(obj):
                return obj
    found = {
        id(cls): cls
        for mod_name, mod in list(sys.modules.items())
        if mod_name.startswith("hydromodpy") and mod is not None
        for cls in [getattr(mod, name, None)]
        if inspect.isclass(cls) and cls.__module__.startswith("hydromodpy")
    }
    if len(found) == 1:
        return next(iter(found.values()))
    if module is not None:
        try:
            hints = inspect.get_annotations(fn, eval_str=True)
        except Exception:
            hints = {}
        ret = hints.get("return")
        for cand in getattr(ret, "__args__", (ret,)) or ():
            if (
                inspect.isclass(cand)
                and cand.__name__ == name
                and cand.__module__.startswith("hydromodpy")
            ):
                return cand
    return None


def members_of(cls: Any) -> list[dict[str, Any]]:
    out = []
    skip_owners = {object, BaseModel, Exception, BaseException, dict, tuple, list}
    for name in sorted(m for m in dir(cls) if not m.startswith("_")):
        owner = next((k for k in cls.__mro__ if name in vars(k)), None)
        if owner in skip_owners or owner is None:
            continue
        raw_attr = vars(owner)[name]
        if isinstance(raw_attr, property):
            kind, doc = "property", inspect.getdoc(raw_attr)
        elif isinstance(raw_attr, (classmethod, staticmethod)) or inspect.isfunction(raw_attr):
            kind, doc = "method", inspect.getdoc(getattr(cls, name, None))
        else:
            kind, doc = "attribute", ""
        out.append(
            {
                "name": name,
                "kind": kind,
                "summary": first_line(doc),
                "owner": f"{owner.__module__}.{owner.__qualname__}",
            }
        )
    return out


def class_entry(name: str, cls: Any, kind: str) -> dict[str, Any]:
    entry = {
        "name": name,
        "kind": kind,
        "qualname": f"{cls.__module__}.{cls.__qualname__}",
        "summary": first_line(inspect.getdoc(cls)),
        "source": source_of(cls),
        "sections": sections(inspect.getdoc(cls)),
        "public_members": sorted(m for m in dir(cls) if not m.startswith("_")),
    }
    if kind in ("result", "engine"):
        entry["members"] = members_of(cls)
    if kind == "config":
        tags = {}
        for fname, field in getattr(cls, "model_fields", {}).items():
            if fname in ("source", "kind", "type", "mode", "catch_def"):
                args = getattr(field.annotation, "__args__", ())
                if (
                    getattr(field.annotation, "__origin__", None) is not None
                    and len(args) == 1
                    and isinstance(args[0], str)
                ):
                    tags[fname] = args[0]
                elif (
                    isinstance(field.default, str)
                    and str(field.annotation).startswith("typing.Literal")
                    and len(args) == 1
                ):
                    tags[fname] = field.default
        entry["tags"] = tags
    return entry


# ---------------------------------------------------------------- command line


def walk_parser(
    parser: argparse.ArgumentParser, path: list[str], parent_help: str = ""
) -> list[dict[str, Any]]:
    out = []
    args = []
    subs = []
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            helps = {a.dest: a.help for a in action._choices_actions}
            for name, sub in action.choices.items():
                subs.append({"name": name, "help": helps.get(name) or ""})
                out.extend(walk_parser(sub, path + [name], helps.get(name) or ""))
            continue
        if isinstance(action, argparse._HelpAction) or action.help == argparse.SUPPRESS:
            continue
        metavar = action.metavar
        if isinstance(metavar, tuple):
            shown = " ".join(metavar)
        elif metavar:
            shown = metavar
        elif action.option_strings and action.nargs != 0:
            shown = action.dest.upper()
        else:
            shown = None
        if shown and action.nargs in ("+", "*"):
            shown = f"{shown} [{shown} ...]" if action.nargs == "+" else f"[{shown} ...]"
        elif shown and action.nargs == "?":
            shown = f"[{shown}]"
        args.append(
            {
                "flags": list(action.option_strings)
                or [metavar if isinstance(metavar, str) else action.dest],
                "positional": not action.option_strings,
                "metavar": shown if action.option_strings else None,
                "help": action.help or "",
                "default": None
                if action.default in (None, argparse.SUPPRESS)
                else repr(action.default),
                "choices": [str(c) for c in action.choices] if action.choices else None,
                "required": bool(action.required),
            }
        )
    usage = " ".join(parser.format_usage().split())
    usage = re.sub(r"^usage:\s*", "", usage)
    out.insert(
        0,
        {
            "path": path,
            "usage": usage,
            "description": parser.description or parent_help or "",
            "epilog": parser.epilog or "",
            "arguments": args,
            "subcommands": subs,
        },
    )
    return out


def exit_codes() -> list[dict[str, Any]]:
    """EXIT_* constants of the CLI and the exceptions exit_code_for maps onto each."""
    import importlib

    helpers = importlib.import_module("hydromodpy.cli.helpers")
    codes = {
        name: value
        for name, value in vars(helpers).items()
        if name.startswith("EXIT_") and isinstance(value, int)
    }
    source = Path(helpers.__file__).read_text()
    tree = ast.parse(source)
    mapped: dict[str, list[str]] = {name: [] for name in codes}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "exit_code_for":
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Tuple)
                    and len(sub.elts) == 2
                    and isinstance(sub.elts[1], ast.Name)
                    and sub.elts[1].id in codes
                ):
                    mapped[sub.elts[1].id].append(ast.unparse(sub.elts[0]))
                if (
                    isinstance(sub, ast.If)
                    and isinstance(sub.test, ast.Call)
                    and getattr(sub.test.func, "id", "") == "isinstance"
                ):
                    ret = next((s for s in sub.body if isinstance(s, ast.Return)), None)
                    if (
                        ret is not None
                        and isinstance(ret.value, ast.Name)
                        and ret.value.id in codes
                    ):
                        mapped[ret.value.id].append(ast.unparse(sub.test.args[1]))
    comments = {}
    lines = source.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^(EXIT_[A-Z_]+)\s*=", line)
        if m and "#" in line:
            comments[m.group(1)] = line.split("#", 1)[1].strip()
    return [
        {
            "name": name,
            "code": value,
            "exceptions": sorted(set(mapped.get(name, []))),
            "comment": comments.get(name, ""),
        }
        for name, value in sorted(codes.items(), key=lambda kv: kv[1])
    ]


def verbs_called(command_module: types.ModuleType, verbs: set[str]) -> list[str]:
    """Verbs of hydromodpy._api a CLI command calls, read from its source."""
    files = []
    path = Path(command_module.__file__)
    files = sorted(path.parent.rglob("*.py")) if path.name == "__init__.py" else [path]
    found: list[str] = []
    workers = (
        Path(command_module.__file__).parents[1 if path.name != "__init__.py" else 2] / "_workers"
    )
    extra = []
    for f in files:
        for node in ast.walk(ast.parse(f.read_text())):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith("hydromodpy.cli._workers")
            ):
                target = workers / (node.module.rsplit(".", 1)[-1] + ".py")
                if node.module == "hydromodpy.cli._workers":
                    for alias in node.names:
                        cand = workers / f"{alias.name}.py"
                        if cand.exists():
                            extra.append(cand)
                elif target.exists():
                    extra.append(target)
    files = files + [f for f in extra if f not in files]
    for f in files:
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            name = None
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in ("hmp", "hydromodpy", "_api", "api")
            ):
                name = node.attr
            elif isinstance(node, ast.ImportFrom) and node.module in (
                "hydromodpy",
                "hydromodpy._api",
            ):
                for alias in node.names:
                    if alias.name in verbs and alias.name not in found:
                        found.append(alias.name)
            if name in verbs and name not in found:
                found.append(name)
    return found


def build(nodes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Return the API and CLI payload; ``nodes`` is the field registry."""
    model_paths: dict[str, list[str]] = {}
    for path, node in nodes.items():
        for name in node.get("models", []) or []:
            model_paths.setdefault(name, []).append(path)
        if node.get("kind") == "root":
            continue

    public = list(getattr(hmp, "__all__", []))
    verbs, helpers, classes, modules = [], [], [], []
    for name in public:
        obj = getattr(hmp, name, None)
        if inspect.ismodule(obj):
            modules.append(
                {"name": name, "qualname": obj.__name__, "summary": first_line(inspect.getdoc(obj))}
            )
        elif inspect.isclass(obj):
            if issubclass(obj, BaseModel):
                kind = "config"
            elif obj.__module__.startswith(("hydromodpy.results", "hydromodpy.project")):
                kind = "result"
            else:
                kind = "engine"
            entry = class_entry(name, obj, kind)
            if kind == "config":
                entry["toml"] = sorted(model_paths.get(obj.__name__, []), key=len)[:3]
            classes.append(entry)
        elif inspect.isfunction(obj):
            doc = inspect.getdoc(obj)
            entry = {
                "name": name,
                "qualname": f"{obj.__module__}.{obj.__qualname__}",
                "signature": signature_of(obj),
                "summary": first_line(doc),
                "sections": sections(doc),
                "source": source_of(obj),
                "returns": [],
            }
            _, aliases = type_checking_names(sys.modules[obj.__module__])
            for rname in return_names(obj):
                if rname in aliases:
                    entry["returns"].append({"name": rname, "alias": aliases[rname]})
                    continue
                cls = resolve_class(rname, obj)
                if cls is not None:
                    entry["returns"].append(
                        {"name": rname, "qualname": f"{cls.__module__}.{cls.__qualname__}"}
                    )
            (verbs if obj.__module__ == "hydromodpy._api" else helpers).append(entry)

    # classes returned by verbs that are not in __all__ still get a page
    known = {c["qualname"] for c in classes}
    for v in verbs:
        for r in v["returns"]:
            if "qualname" not in r:
                continue
            if r["qualname"] not in known:
                module_name, _, qual = r["qualname"].rpartition(".")
                cls = getattr(sys.modules.get(module_name), qual, None)
                if cls is not None:
                    entry = class_entry(r["name"], cls, "result")
                    entry["outside_all"] = True
                    classes.append(entry)
                    known.add(r["qualname"])

    import importlib

    cli_main = importlib.import_module("hydromodpy.cli.main")
    from hydromodpy.cli.commands import ALL_COMMANDS

    sys.argv[0] = "hmp"
    parser = cli_main._build_parser()
    commands = walk_parser(parser, ["hmp"])
    verb_names = {v["name"] for v in verbs}
    twins = {}
    for mod in ALL_COMMANDS:
        called = verbs_called(mod, verb_names)
        if called:
            twins[getattr(mod, "NAME", mod.__name__.rsplit(".", 1)[-1])] = called

    payload = {
        "version": getattr(hmp, "__version__", ""),
        "verbs": verbs,
        "helpers": helpers,
        "classes": classes,
        "modules": modules,
        "commands": commands,
        "cli_to_verbs": twins,
        "exit_codes": exit_codes(),
        "toml_kinds": {p: n.get("kind") for p, n in nodes.items() if p},
    }
    return payload


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out")
    ap.add_argument("--fields", required=True)
    args = ap.parse_args()
    payload = build(json.loads(Path(args.fields).read_text())["nodes"])
    Path(args.out).write_text(json.dumps(payload, indent=1, ensure_ascii=False, default=str))
    print(
        f"api: {len(payload['verbs'])} verbs, {len(payload['classes'])} classes, {len(payload['commands'])} commands"
    )


if __name__ == "__main__":
    main()
