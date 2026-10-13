"""Build the registry of the public Python API and of the command line.

Everything comes from the package: ``hydromodpy.__all__``, signatures, docstrings,
the argparse parser of ``hmp``, and the calls the CLI commands make to the API.

Usage:
    python -m tools.docs.api_registry OUT.json --fields REGISTRY.json
"""

from __future__ import annotations

import argparse
import ast
import functools
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
        return f"{Path(file).relative_to(TREE).as_posix()}:{line}"
    except (TypeError, OSError, ValueError):
        return ""


def signature_of(obj: Any) -> str:
    try:
        return str(inspect.signature(obj))
    except (TypeError, ValueError):
        return ""


def return_annotation(fn: Any) -> str:
    """The return annotation as written, or an empty string when there is none."""
    try:
        ann = inspect.signature(fn).return_annotation
    except (TypeError, ValueError):
        return ""
    if ann is inspect.Signature.empty:
        return ""
    return ann if isinstance(ann, str) else inspect.formatannotation(ann)


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
            # A class of another package (matplotlib's Figure) gets no page here.
            if inspect.isclass(obj) and obj.__module__.startswith("hydromodpy"):
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


def attribute_docs(owner: type) -> dict[str, str]:
    """Docstrings written under the attributes of a class: name -> text.

    The string literal (or ``#:`` comment) under a field, the form autodoc
    renders for an attribute. A class whose source cannot be read gives none.
    """
    from sphinx.pycode import ModuleAnalyzer

    try:
        found = ModuleAnalyzer.for_module(owner.__module__).find_attr_docs()
    except Exception:
        return {}
    return {
        attr: "\n".join(lines).strip()
        for (scope, attr), lines in found.items()
        if scope == owner.__qualname__
    }


def members_of(cls: Any) -> list[dict[str, Any]]:
    out = []
    skip_owners = {object, BaseModel, Exception, BaseException, dict, tuple, list}
    attr_docs: dict[type, dict[str, str]] = {}
    for name in sorted(m for m in dir(cls) if not m.startswith("_")):
        owner = next((k for k in cls.__mro__ if name in vars(k)), None)
        if owner in skip_owners or owner is None:
            continue
        raw_attr = vars(owner)[name]
        if isinstance(raw_attr, (property, functools.cached_property)):
            kind, doc = "property", inspect.getdoc(raw_attr)
        elif isinstance(raw_attr, (classmethod, staticmethod)) or inspect.isfunction(raw_attr):
            kind, doc = "method", inspect.getdoc(getattr(cls, name, None))
        else:
            if owner not in attr_docs:
                attr_docs[owner] = attribute_docs(owner)
            kind, doc = "attribute", attr_docs[owner].get(name, "")
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
                "dest": action.dest,
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
    handler = parser.get_default("_handler")
    out.insert(
        0,
        {
            "path": path,
            "handler": f"{handler.__module__}:{handler.__qualname__}" if handler else "",
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


# ---------------------------------------------------------------- docstring sections


def section_body(doc: str | None, title: str) -> str:
    """The text of one numpydoc section of ``doc``, or an empty string."""
    text = doc or ""
    marks = list(SECTION.finditer(text))
    for i, m in enumerate(marks):
        if m.group(1).strip() == title:
            end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
            return text[m.end() : end].strip("\n")
    return ""


def returns_doc(doc: str | None) -> str:
    """The type line of the Returns section, as the docstring writes it."""
    for line in section_body(doc, "Returns").splitlines():
        if line.strip() and not line.startswith((" ", "\t")):
            return " ".join(line.split())
    return ""


def raises_doc(doc: str | None) -> list[str]:
    """The exception names of the Raises section."""
    return [
        line.strip()
        for line in section_body(doc, "Raises").splitlines()
        if line.strip() and not line.startswith((" ", "\t"))
    ]


def params_of(fn: Any) -> list[dict[str, Any]]:
    """Named parameters of a callable: name, kind, default text."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return []
    out = []
    for p in sig.parameters.values():
        out.append(
            {
                "name": p.name,
                "kind": p.kind.name.lower(),
                "default": None if p.default is inspect.Parameter.empty else repr(p.default),
            }
        )
    return out


def popped_keywords(fn: Any) -> list[str]:
    """Keyword names a function takes out of its ``**kwargs`` with ``kwargs.pop("name")``."""
    try:
        tree = ast.parse(inspect.getsource(fn).lstrip())
    except (OSError, TypeError, SyntaxError):
        return []
    found: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "pop"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and node.args[0].value not in found
        ):
            found.append(node.args[0].value)
    return found


# ---------------------------------------------------------------- exceptions


CODE_TABLE_MODULE = "hydromodpy.core.exceptions"


@functools.cache
def package_sources() -> tuple[tuple[str, str, ast.Module], ...]:
    """Every module of the package: its dotted name, its top-level package and its tree."""
    root = Path(hmp.__path__[0])
    out = []
    for path in sorted(root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text())
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        rel = path.relative_to(root).parts
        dotted = path.relative_to(root.parent).with_suffix("").parts
        if dotted[-1] == "__init__":
            dotted = dotted[:-1]
        out.append((".".join(dotted), rel[0].removesuffix(".py") if rel else "", tree))
    return tuple(out)


def exception_modules(codes: list[dict[str, Any]]) -> list[str]:
    """The modules that define an exception of the package, the code table first.

    A class counts when it derives from ``HydroModPyError`` or from a class that
    ``exit_code_for`` maps, directly or through other classes of the package. The
    source is read, so a module that adds one needs no edit here.
    """
    known = {"HydroModPyError"} | {
        name for e in codes for expr in e["exceptions"] for name in re.findall(r"\w+", expr)
    }
    defs = [
        (module, node.name, {ast.unparse(b).rsplit(".", 1)[-1] for b in node.bases})
        for module, _package, tree in package_sources()
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
    ]
    grew = True
    while grew:
        grew = False
        for _module, name, bases in defs:
            if name not in known and bases & known:
                known.add(name)
                grew = True
    found = {module for module, name, _bases in defs if name in known}
    return [CODE_TABLE_MODULE, *sorted(found - {CODE_TABLE_MODULE})]


def raise_sites(names: set[str]) -> dict[str, dict[str, int]]:
    """For each exception name, the top-level packages that raise it and how often."""
    counts: dict[str, dict[str, int]] = {n: {} for n in names}
    for _module, package, tree in package_sources():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise) or node.exc is None:
                continue
            target = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
            name = (
                target.id
                if isinstance(target, ast.Name)
                else target.attr
                if isinstance(target, ast.Attribute)
                else None
            )
            if name in counts:
                counts[name][package] = counts[name].get(package, 0) + 1
    return counts


def exceptions(codes: list[dict[str, Any]], verbs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every exception of the package with its code, parent, exit code and raise sites."""
    import importlib

    from hydromodpy.core.exceptions import HydroModPyError

    helpers = importlib.import_module("hydromodpy.cli.helpers")
    exit_names = {e["code"]: e["name"] for e in codes}
    classes: list[type[BaseException]] = []
    for module_name in exception_modules(codes):
        module = importlib.import_module(module_name)
        for obj in vars(module).values():
            if (
                inspect.isclass(obj)
                and issubclass(obj, BaseException)
                and obj.__module__ == module_name
                and obj not in classes
                and (module_name != CODE_TABLE_MODULE or issubclass(obj, HydroModPyError))
            ):
                classes.append(obj)
    names = {c.__name__ for c in classes}
    sites = raise_sites(names)
    documented: dict[str, list[str]] = {n: [] for n in names}
    for v in verbs:
        for dotted in v.get("raises", []):
            short = dotted.rsplit(".", 1)[-1]
            if short in documented and v["name"] not in documented[short]:
                documented[short].append(v["name"])
    out = []
    for cls in classes:
        try:
            exit_code = helpers.exit_code_for(cls.__new__(cls))
        except Exception:
            exit_code = None
        parents = [b for b in cls.__bases__ if b in classes or b is HydroModPyError]
        by_package = sorted(sites[cls.__name__].items(), key=lambda kv: (-kv[1], kv[0]))
        out.append(
            {
                "name": cls.__name__,
                "module": cls.__module__,
                "code": getattr(cls, "code", None),
                "own_code": "code" in vars(cls),
                "parent": parents[0].__name__ if parents else None,
                "bases": [b.__name__ for b in cls.__bases__],
                "title": " ".join((inspect.getdoc(cls) or "").split("\n\n")[0].split()),
                "exit_code": exit_code,
                "exit_name": exit_names.get(exit_code, ""),
                "raised_in": [{"package": p, "count": n} for p, n in by_package],
                "documented_by": sorted(documented[cls.__name__]),
                "source": source_of(cls),
            }
        )
    return out


# ---------------------------------------------------------------- keywords against flags


def keyword_table(verb: str, commands: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The keyword arguments of ``hmp.<verb>`` set against the flags of ``hmp <verb>``."""
    fn = getattr(hmp, verb, None)
    command = next((c for c in commands if c["path"] == ["hmp", verb.replace("_", "-")]), None)
    if fn is None or command is None or command["subcommands"]:
        return None
    params = params_of(fn)
    named = [p for p in params[1:] if p["kind"] == "keyword_only"]
    has_var_kw = any(p["kind"] == "var_keyword" for p in params)
    forwarded = popped_keywords(fn)
    workflows: dict[str, list[dict[str, Any]]] = {}
    object_form: list[dict[str, Any]] = []
    if verb == "run":
        from hydromodpy.project.dispatch.workflow import DISPATCH
        from hydromodpy.project.facade import Project

        for name, runner in DISPATCH.items():
            workflows[name] = [p for p in params_of(runner)[1:] if p["kind"] == "keyword_only"]
        object_form = [p for p in params_of(Project.simulate) if p["kind"] == "keyword_only"]
    keywords: dict[str, dict[str, Any]] = {}

    def add(name: str, default: str | None, where: str) -> None:
        row = keywords.setdefault(name, {"keyword": name, "default": default, "where": []})
        if row["default"] is None:
            row["default"] = default
        row["where"].append(where)

    for p in named:
        add(p["name"], p["default"], "signature")
    for name in forwarded:
        add(name, None, "consumed")
    for workflow, plist in workflows.items():
        for p in plist:
            add(p["name"], p["default"], f"workflow:{workflow}")
    for p in object_form:
        add(p["name"], p["default"], "object")
    flags = [a for a in command["arguments"] if not a["positional"]]
    rows = []
    used: set[str] = set()
    for kw, row in keywords.items():
        flag = next((a for a in flags if a["dest"] == kw), None)
        invert = False
        if flag is None:
            flag = next((a for a in flags if a["dest"] == f"no_{kw}"), None)
            invert = flag is not None
        if flag is not None:
            used.add(flag["dest"])
        rows.append(
            {
                "keyword": kw,
                "default": row["default"],
                "where": row["where"],
                "flag": flag["flags"] if flag else [],
                "inverse": invert,
            }
        )
    return {
        "verb": verb,
        "command": " ".join(command["path"]),
        "rows": rows,
        "cli_only": [a["flags"] for a in flags if a["dest"] not in used],
        "workflows": {k: [p["name"] for p in v] for k, v in workflows.items()},
        "object_form_var_keyword": verb == "run",
        "has_var_keyword": has_var_kw,
    }


# ---------------------------------------------------------------- exit codes of each command


def command_exit_codes(
    commands: list[dict[str, Any]], codes: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Exit codes each command sets itself, read from the code its handler runs.

    The handler and the functions of its own module it calls are scanned for
    ``sys.exit(...)`` and ``raise SystemExit(...)``, and so are the functions of
    ``cli/helpers.py`` it calls. A ``sys.exit(exit_code_for(exc))`` is reported
    as the mapped exit, whose code is the one of the exception class.
    """
    import importlib

    by_name = {e["name"]: e["code"] for e in codes}
    helpers = importlib.import_module("hydromodpy.cli.helpers")
    helper_funcs = {
        n.name: n
        for n in ast.parse(Path(helpers.__file__).read_text()).body
        if isinstance(n, ast.FunctionDef)
    }

    def value_of(arg: ast.AST) -> tuple[int | None, bool]:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, int):
            return arg.value, False
        name = arg.id if isinstance(arg, ast.Name) else getattr(arg, "attr", None)
        if name in by_name:
            return by_name[name], False
        if isinstance(arg, ast.Call):
            fname = getattr(arg.func, "id", getattr(arg.func, "attr", ""))
            if fname == "exit_code_for":
                return None, True
        return None, False

    result: dict[str, dict[str, Any]] = {}
    for c in commands:
        if not c["handler"]:
            continue
        module_name, _, func_name = c["handler"].partition(":")
        module = importlib.import_module(module_name)
        try:
            tree = ast.parse(Path(module.__file__).read_text())
        except (OSError, TypeError, SyntaxError):
            continue
        funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        seen: set[str] = set()
        queue = [funcs[func_name]] if func_name in funcs else []
        direct: set[int] = set()
        mapped = False
        while queue:
            fn = queue.pop()
            if id(fn) in seen:
                continue
            seen.add(id(fn))
            for node in ast.walk(fn):
                call = node if isinstance(node, ast.Call) else None
                if call is not None:
                    target = call.func
                    is_exit = (
                        isinstance(target, ast.Attribute)
                        and target.attr == "exit"
                        and getattr(target.value, "id", "") == "sys"
                    ) or (isinstance(target, ast.Name) and target.id in ("SystemExit", "exit"))
                    if is_exit and call.args:
                        code, is_mapped = value_of(call.args[0])
                        if code is not None:
                            direct.add(code)
                        mapped = mapped or is_mapped
                    elif isinstance(target, ast.Name):
                        callee = funcs.get(target.id) or helper_funcs.get(target.id)
                        if callee is not None and id(callee) not in seen:
                            queue.append(callee)
                elif isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
                    if getattr(node.exc.func, "id", "") == "SystemExit" and node.exc.args:
                        code, is_mapped = value_of(node.exc.args[0])
                        if code is not None:
                            direct.add(code)
                        mapped = mapped or is_mapped
        result[" ".join(c["path"])] = {"codes": sorted(direct), "mapped": mapped}
    return result


# ---------------------------------------------------------------- how the objects relate


def produced_by(
    classes: list[dict[str, Any]], verbs: list[dict[str, Any]]
) -> dict[str, list[dict[str, str]]]:
    """For each result class, the functions and methods whose return annotation names it."""
    names = {c["name"] for c in classes if c["kind"] == "result"}
    found: dict[str, list[dict[str, str]]] = {n: [] for n in names}
    for v in verbs:
        for r in v.get("returns", []):
            if r["name"] in found:
                found[r["name"]].append({"call": f"hmp.{v['name']}()", "owner": ""})
    for c in classes:
        if c["kind"] != "result" or "qualname" not in c:
            continue
        module_name, _, qual = c["qualname"].rpartition(".")
        cls = getattr(sys.modules.get(module_name), qual, None)
        if cls is None:
            continue
        for member in c.get("members", []):
            if member["kind"] != "method":
                continue
            fn = inspect.getattr_static(cls, member["name"], None)
            fn = getattr(fn, "__func__", fn)
            ann = return_annotation(fn) if callable(fn) else ""
            for target in names:
                if target != c["name"] and re.search(rf"\b{target}\b", ann):
                    found[target].append(
                        {"call": f"{c['name']}.{member['name']}()", "owner": c["name"]}
                    )
    return found


def session_figure() -> str:
    """A registered figure to show in the minimal session."""
    from hydromodpy.display import list_figures

    names = [spec.name for spec in list_figures()]
    return "flux_timeseries" if "flux_timeseries" in names else names[0]


def read_rules() -> list[str]:
    """The bullet lines of the ``hmp.read`` docstring that say what comes back per kind."""
    doc = inspect.getdoc(hmp.read) or ""
    lines: list[str] = []
    for line in doc.splitlines():
        if line.startswith("- "):
            lines.append(line[2:].strip())
        elif lines and line.startswith("  ") and line.strip():
            lines[-1] += " " + line.strip()
        elif lines and not line.strip():
            break
    return lines


# ---------------------------------------------------------------- members by task


# A class page lists its members by what a reader does with them. The group of
# a member comes from the mixin that defines it, so a new method lands in a
# sensible group on its own; ``BY_NAME`` moves the few that read better elsewhere.
TASKS: dict[str, dict[str, Any]] = {
    "Catalog": {
        "order": [
            "Open a catalog",
            "Find runs",
            "Read results",
            "Tags and notes",
            "Trash and delete",
            "Export and import",
            "Calibration sessions",
            "Inspect the index",
            "Record a run",
        ],
        "by_owner": {
            "Catalog": "Open a catalog",
            "DiscoveryMixin": "Find runs",
            "ReadsMixin": "Read results",
            "LifecycleMixin": "Trash and delete",
            "PackageIOMixin": "Export and import",
            "SchemaDiscoveryMixin": "Inspect the index",
            "RegistrationMixin": "Record a run",
            "WritesMixinDuckDB": "Record a run",
            "WritesMixinParquet": "Record a run",
            "WritesMixinZarr": "Record a run",
        },
        "by_name": {
            "read": "Read results",
            "load_dataset": "Read results",
            "sql": "Inspect the index",
            "list_simulations": "Find runs",
            "simulations": "Find runs",
            "frame": "Find runs",
            "sims_with_tag": "Tags and notes",
            "add_tag": "Tags and notes",
            "remove_tag": "Tags and notes",
            "write_tags": "Tags and notes",
            "add_note": "Tags and notes",
            "rename_simulation": "Tags and notes",
            "export": "Export and import",
            "list_exports": "Export and import",
            "record_export": "Export and import",
            "calibration_iterations": "Calibration sessions",
            "calibration_sessions": "Calibration sessions",
            "delete_calibration_session": "Calibration sessions",
            "list_orphan_calibration_sessions": "Calibration sessions",
            "sessions": "Calibration sessions",
            "list_running": "Find runs",
            "list_stale_running": "Find runs",
            "close": "Open a catalog",
            "cleanup": "Open a catalog",
            "finalize": "Record a run",
            "open_zarr": "Read results",
            "get_provenance": "Read results",
            "list_geographic_features": "Read results",
            "list_tracked_files": "Read results",
        },
        "intro": {
            "Open a catalog": "Constructors, the paths a catalog owns, and the handle itself.",
            "Find runs": "Resolve a reference, list runs, and pick the best, worst or latest.",
            "Read results": "Fields, time series, budgets, features and provenance of a run.",
            "Tags and notes": "Label a run, annotate it, rename it.",
            "Trash and delete": "Move a run to the trash, restore it, purge it for good.",
            "Export and import": "Write the files of a run, or move runs between workspaces as archives.",
            "Calibration sessions": "The sessions a calibration leaves in the catalog and their iterations.",
            "Inspect the index": "Tables, columns, metrics and stations of the index, and plain SQL.",
            "Record a run": "What the pipeline calls to write a run into the catalog. A script that only reads results does not need these.",
        },
    },
    "Run": {
        "order": [
            "The run itself",
            "Fields, rasters and mesh",
            "Tables and time series",
            "Hydrographic network",
        ],
        "by_owner": {
            "Run": "The run itself",
            "RunGeographicMixin": "Fields, rasters and mesh",
            "RunTimeseriesMixin": "Tables and time series",
            "RunHydrographicMixin": "Hydrographic network",
        },
        "by_name": {},
        "intro": {},
    },
}


def group_members(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Order the members of a class page by task; empty when the class has no task plan."""
    plan = TASKS.get(entry["name"])
    if plan is None:
        return []
    groups: dict[str, list[dict[str, Any]]] = {t: [] for t in plan["order"]}
    for m in entry.get("members", []):
        owner = m["owner"].rsplit(".", 1)[-1]
        title = plan["by_name"].get(m["name"]) or plan["by_owner"].get(owner)
        if title is None or title not in groups:
            raise ValueError(
                f"{entry['name']}.{m['name']} (defined in {owner}) belongs to no task group: "
                "update TASKS in tools/docs/api_registry.py"
            )
        groups[title].append(m)
    return [
        {
            "title": t,
            "intro": plan["intro"].get(t, ""),
            "members": sorted(ms, key=lambda m: m["name"]),
        }
        for t, ms in groups.items()
        if ms
    ]


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
                "annotation": return_annotation(obj),
                "returns_doc": returns_doc(doc),
                "raises": raises_doc(doc),
                "params": params_of(obj),
            }
            _, aliases = type_checking_names(sys.modules[obj.__module__])
            # Aliases a signature names (PathLike, ConfigLike...), with what they stand for.
            entry["type_aliases"] = [
                {"name": alias, "alias": aliases[alias]}
                for alias in sorted(aliases)
                if re.search(rf"\b{re.escape(alias)}\b", entry["signature"])
            ]
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

    for c in classes:
        if c["kind"] in ("result", "engine"):
            c["groups"] = group_members(c)

    codes = exit_codes()
    command_names = {c["path"][1] for c in commands if len(c["path"]) == 2}
    keyword_tables = {
        v["name"]: t
        for v in verbs
        if v["name"].replace("_", "-") in command_names
        for t in [keyword_table(v["name"], commands)]
        if t is not None
    }
    payload = {
        "version": getattr(hmp, "__version__", ""),
        "all_names": list(public),
        "verbs": verbs,
        "helpers": helpers,
        "classes": classes,
        "modules": modules,
        "commands": commands,
        "cli_to_verbs": twins,
        "exit_codes": codes,
        "command_exit_codes": command_exit_codes(commands, codes),
        "exceptions": exceptions(codes, verbs),
        "keyword_tables": keyword_tables,
        "produced_by": produced_by(classes, verbs),
        "read_rules": read_rules(),
        "session_figure": session_figure(),
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
