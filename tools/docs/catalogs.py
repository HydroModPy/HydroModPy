"""Catalogs of the reference: solvers, figures and data sources.

Each one is read from a registry of the code, never typed in a page:

- solvers: ``hydromodpy.solver.base.registry`` (the attributes each backend declares);
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
    """One row per backend the solver registry serves, with the attributes it declares."""
    from hydromodpy.solver.base.registry import extractors, solvers
    from hydromodpy.solver.modflow_common.binaries import available_solvers

    backend_values = set(solvers.names("flow", shipped_only=True))
    fetchable = set(available_solvers())
    read_back = set(extractors.names())
    rows = []
    # A key is never split: the process and the solver are read off the class.
    for key in solvers.names():
        cls = solvers.get(key)
        process, solver = cls.process_type, cls.name
        exe = SOLVER_EXECUTABLE.get(solver)
        if exe is not None and exe not in fetchable:
            raise ValueError(f"{solver}: executable {exe!r} is unknown to the binaries module")
        rows.append(
            {
                "process": process,
                "solver": solver,
                "category": cls.category,
                "geometry": cls.geometry,
                "accepted_meshes": sorted(cls.accepted_meshes),
                "writes": list(cls.writes),
                "reads": list(cls.reads),
                "supports": sorted(cls.supports),
                "requires": [list(pair) for pair in cls.requires],
                "adapter": f"{cls.__module__}.{cls.__qualname__}",
                "summary": _first_paragraph(inspect.getdoc(cls)),
                "extractor": key in read_back,
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


def option_details(cls: type) -> list[dict[str, Any]]:
    """Type, default, unit and description of each option a figure class accepts.

    All of it is declared on the parameter that takes the option, read by
    :func:`hydromodpy.display.figure.options_of`.
    """
    from hydromodpy.display.figure import options_of

    return [
        {
            "name": o.name,
            "type": o.type,
            "default": o.default,
            "unit": o.unit,
            "doc": o.description,
            "python_only": o.python_only,
        }
        for o in options_of(cls)
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
                "option_details": option_details(cls),
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
            from hydromodpy.data.source.registry import data_sources

            values = ["custom"]
            for source_id in data_sources.names():
                kinds[source_id] = getattr(data_sources.get(source_id), "payload_kind", None)
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
