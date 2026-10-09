"""Catalogs of the reference: solvers, figures and data sources.

Each one is read from a registry of the code, never typed in a page:

- solvers: ``hydromodpy.solver.base.registry`` (pairs, capabilities, requirements);
- figures: ``hydromodpy.display`` (``FigureSpec``, the figure classes, their options);
- data sources: the ``source`` keys of the ``[data.<variable>]`` sections in the
  field registry, joined with ``hydromodpy.schema.sources`` (publisher, licence, hosts).

Usage: python -m tools.docs.catalogs OUT.json --fields REGISTRY.json
"""

from __future__ import annotations

import argparse
import dataclasses
import inspect
import json
import re
from pathlib import Path
from typing import Any


def _first_paragraph(doc: str | None) -> str:
    text = (doc or "").strip().split("\n\n", 1)[0]
    return " ".join(text.split())


# What a capability name tells a reader. The names come from the solver registry;
# the sentences say what a pair that declares one can do.
CAPABILITY_MEANING = {
    "flow": "Solves groundwater flow.",
    "flow:heads": "Writes the hydraulic heads.",
    "flow:budget": "Writes the water budget of the domain.",
    "flow:restart": "Starts from the state of an earlier run, read from [flow] restart_from.",
    "flow:spinup_cyclic": "Can repeat its own period to settle a state (spin-up).",
    "flow:surface_excess": "Writes the water that leaves the aquifer at the surface.",
    "transport": "Transports something through a flow solution.",
    "transport:concentration": "Writes solute concentrations.",
    "transport:particles": "Writes particle pathlines.",
}

# The executable each solver runs, by the name `hmp install-binaries --subset` takes.
# `hydromodpy.solver.modflow_common.binaries` knows the names; the pairing is read
# from the engine classes, which call ensure_solver_binary with one of them.
SOLVER_EXECUTABLE = {
    "modflow6": "mf6",
    "modflow6_prt": "mf6",
    "modflow_nwt": "mfnwt",
    "modpath": "mp6",
    "mt3dms": "mt3dusgs",
}


def solvers(nodes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per (process, solver) pair the registry knows."""
    from hydromodpy.solver.base import registry
    from hydromodpy.solver.modflow_common.binaries import available_solvers

    backend_values = {str(v) for v in nodes.get("solver.backend.backend", {}).get("literal") or []}
    fetchable = set(available_solvers())
    extractors = set(registry.list_extractor_pairs())
    rows = []
    for process, solver in sorted(registry.list_pairs()):
        cls = registry.get(process, solver)
        exe = SOLVER_EXECUTABLE.get(solver)
        if exe is not None and exe not in fetchable:
            raise ValueError(f"{solver}: executable {exe!r} is unknown to the binaries module")
        rows.append(
            {
                "process": process,
                "solver": solver,
                "capabilities": sorted(registry.capabilities(process, solver)),
                "requires": [list(pair) for pair in registry.required_bindings(process, solver)],
                "adapter": f"{cls.__module__}.{cls.__qualname__}",
                "summary": _first_paragraph(inspect.getdoc(cls)),
                "extractor": (process, solver) in extractors,
                "executable": exe,
                "backend_key": solver in backend_values and process == "flow",
            }
        )
    return rows


def parse_parameters(doc: str | None) -> dict[str, tuple[str, str]]:
    """The Parameters section of a numpydoc docstring: name -> (type, description)."""
    from tools.docs.api_registry import section_body

    out: dict[str, tuple[str, str]] = {}
    current: list[str] = []
    kind = ""
    desc: list[str] = []

    def flush() -> None:
        for name in current:
            out[name] = (kind, " ".join(desc).strip())

    for line in section_body(doc, "Parameters").splitlines():
        if line and not line.startswith((" ", "\t")):
            flush()
            head, _, kind = line.partition(":")
            current = [n.strip() for n in head.split(",") if n.strip()]
            kind = kind.strip()
            desc = []
        elif line.strip():
            desc.append(line.strip())
    flush()
    return out


def parse_options(doc: str | None) -> dict[str, str]:
    """The Options section of a figure docstring: option name -> description.

    An entry is a name in double backticks on its own line, then its text indented.
    """
    from tools.docs.api_registry import section_body

    out: dict[str, str] = {}
    name = ""
    for line in section_body(doc, "Options").splitlines():
        m = re.match(r"^``([^`]+)``\s*$", line)
        if m:
            name = m.group(1)
            out[name] = ""
        elif name and line.strip():
            out[name] = (out[name] + " " + line.strip()).strip()
    return out


def option_details(cls: type, names: set[str]) -> list[dict[str, Any]]:
    """Type, default and description of each option a figure class accepts.

    The description comes from the Options section of the class docstring, then
    from the Parameters section of ``plot`` or ``render``. The type and the
    default come from the signature.
    """
    found: dict[str, dict[str, Any]] = {}
    class_docs = parse_options(inspect.getdoc(cls))
    for method in ("plot", "render"):
        for klass in cls.__mro__:
            func = klass.__dict__.get(method)
            if func is None:
                continue
            docs = parse_parameters(inspect.getdoc(func))
            try:
                params = inspect.signature(func).parameters
            except (TypeError, ValueError):
                continue
            for param in params.values():
                # `time` is what the display layer resolves to the `timestep` argument.
                name = "time" if param.name == "timestep" and "time" in names else param.name
                if name not in names or name in found:
                    continue
                ann = param.annotation
                found[name] = {
                    "name": name,
                    "type": ""
                    if ann is inspect.Parameter.empty
                    else (ann if isinstance(ann, str) else inspect.formatannotation(ann)),
                    "default": None
                    if param.default is inspect.Parameter.empty
                    else repr(param.default),
                    "doc": class_docs.get(name)
                    or class_docs.get(param.name)
                    or docs.get(param.name, ("", ""))[1],
                }
    return [
        found.get(n, {"name": n, "type": "", "default": None, "doc": ""}) for n in sorted(names)
    ]


def figures() -> list[dict[str, Any]]:
    """One row per registered figure, with what it needs and the options it takes."""
    from hydromodpy.display import list_figures
    from hydromodpy.display.figure import BaseFigure
    from hydromodpy.display.figure_registry import figure_option_names, get

    rows = []
    for spec in list_figures():
        cls = type(get(spec.name))
        rows.append(
            {
                "name": spec.name,
                "title": spec.title,
                "kind": spec.kind,
                "former_names": list(spec.former_names),
                "required_fields": list(spec.required_fields),
                "optional_fields": list(spec.optional_fields),
                "required_tables": list(spec.required_tables),
                "required_solvers": list(spec.required_solvers),
                "options": sorted(figure_option_names(spec.name)),
                "option_details": option_details(cls, set(figure_option_names(spec.name))),
                "summary": _first_paragraph(inspect.getdoc(cls)),
                "own_availability_rule": cls.unavailable_reason
                is not BaseFigure.unavailable_reason,
                "availability_rule": _first_paragraph(inspect.getdoc(cls.unavailable_reason))
                if cls.unavailable_reason is not BaseFigure.unavailable_reason
                else "",
                "default_figsize": list(spec.default_figsize),
                "source": f"{cls.__module__}.{cls.__qualname__}",
            }
        )
    return sorted(rows, key=lambda r: (r["kind"], r["name"]))


# Fields the page lays out itself. Any other field of a source entry or of its
# licence is shown as it is, so a field added to the schema reaches the page
# without an edit here.
KNOWN_ENTRY_FIELDS = {"slug", "publisher", "licence", "basis", "hosts"}
KNOWN_LICENCE_FIELDS = {"spdx", "url", "attribution", "share_alike", "confidence"}


def _plain(value: Any) -> Any:
    """A JSON-friendly copy of a schema value."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_plain(v) for v in value]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _plain(getattr(value, f.name)) for f in dataclasses.fields(value)}
    return str(value)


def source_fields(entry: Any) -> dict[str, Any]:
    """Everything the source registry says about one source."""
    licence = entry.licence
    extra = {
        f.name: _plain(getattr(entry, f.name))
        for f in dataclasses.fields(entry)
        if f.name not in KNOWN_ENTRY_FIELDS and getattr(entry, f.name) not in (None, (), "", {})
    }
    licence_extra = {
        f.name: _plain(getattr(licence, f.name))
        for f in dataclasses.fields(licence)
        if f.name not in KNOWN_LICENCE_FIELDS and getattr(licence, f.name) not in (None, (), "", {})
    }
    return {
        "publisher": entry.publisher,
        "licence": licence.spdx,
        "licence_url": licence.url,
        "attribution": licence.attribution,
        "share_alike": bool(licence.share_alike),
        "confidence": licence.confidence,
        "basis": entry.basis,
        "downloads": list(entry.hosts),
        "extra": {**extra, **{f"licence {k}": v for k, v in licence_extra.items()}},
    }


def providers(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The sources grouped by publisher, with the sections each one feeds."""
    from hydromodpy.schema.sources import SOURCES

    feeds: dict[str, list[str]] = {}
    for row in rows:
        for src in row["sources"]:
            feeds.setdefault(src["value"], []).append(row["section"])
    groups: dict[str, list[dict[str, Any]]] = {}
    for slug, entry in SOURCES.items():
        key = entry.publisher or "Supplied or generated by the user"
        groups.setdefault(key, []).append(
            {"slug": slug, "feeds": sorted(feeds.get(slug, [])), **source_fields(entry)}
        )
    ordered = sorted(groups.items(), key=lambda kv: (kv[0].startswith("Supplied"), kv[0].lower()))
    return [{"publisher": name, "sources": srcs} for name, srcs in ordered]


def data_sources(nodes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per data variable: the sources its ``source`` key accepts, with their entry."""
    from hydromodpy.schema.sources import SOURCES

    pattern = re.compile(r"^data\.([a-z_]+)\.sources\.source$")
    rows = []
    for path, node in sorted(nodes.items()):
        m = pattern.match(path)
        if not m or node.get("kind") != "leaf":
            continue
        values = [str(v) for v in node.get("literal") or []]
        kinds: dict[str, str | None] = {}
        if not values:
            # A free-text source key names any source of the data-source port.
            from hydromodpy.data.source import registry as port

            values = ["custom"]
            for source_id in port.list_source_ids():
                kinds[source_id] = getattr(port.get(source_id), "payload_kind", None)
                values.append(source_id)
        docs = node.get("value_docs") or {}
        entries = []
        for value in values:
            entry = SOURCES.get(value)
            entries.append(
                {
                    "value": value,
                    "payload_kind": kinds.get(value),
                    "doc": docs.get(value, ""),
                    "known": entry is not None,
                    **(source_fields(entry) if entry else {}),
                }
            )
        rows.append(
            {
                "variable": m.group(1),
                "path": path,
                "section": f"data.{m.group(1)}",
                "default": node.get("default"),
                "free_text": bool(kinds),
                "description": node.get("summary") or "",
                "sources": entries,
            }
        )
    return rows


def build(nodes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    sources = data_sources(nodes)
    return {
        "solvers": solvers(nodes),
        "figures": figures(),
        "data_sources": sources,
        "providers": providers(sources),
        "capabilities": CAPABILITY_MEANING,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out")
    ap.add_argument("--fields", required=True)
    args = ap.parse_args()
    payload = build(json.loads(Path(args.fields).read_text())["nodes"])
    Path(args.out).write_text(json.dumps(payload, indent=1, ensure_ascii=False, default=str))
    print({k: len(v) for k, v in payload.items()})


if __name__ == "__main__":
    main()
