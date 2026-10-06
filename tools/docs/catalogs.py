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
import inspect
import json
import re
from pathlib import Path
from typing import Any


def _first_paragraph(doc: str | None) -> str:
    text = (doc or "").strip().split("\n\n", 1)[0]
    return " ".join(text.split())


def solvers() -> list[dict[str, Any]]:
    """One row per (process, solver) pair the registry knows."""
    from hydromodpy.solver.base import registry

    extractors = set(registry.list_extractor_pairs())
    rows = []
    for process, solver in sorted(registry.list_pairs()):
        cls = registry.get(process, solver)
        rows.append(
            {
                "process": process,
                "solver": solver,
                "capabilities": sorted(registry.capabilities(process, solver)),
                "requires": [list(pair) for pair in registry.required_bindings(process, solver)],
                "adapter": f"{cls.__module__}.{cls.__qualname__}",
                "summary": _first_paragraph(inspect.getdoc(cls)),
                "extractor": (process, solver) in extractors,
            }
        )
    return rows


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
                "summary": _first_paragraph(inspect.getdoc(cls)),
                "own_availability_rule": cls.unavailable_reason
                is not BaseFigure.unavailable_reason,
                "source": f"{cls.__module__}.{cls.__qualname__}",
            }
        )
    return sorted(rows, key=lambda r: (r["kind"], r["name"]))


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
                    "publisher": entry.publisher if entry else None,
                    "licence": entry.licence.spdx if entry else None,
                    "licence_url": entry.licence.url if entry else None,
                    "confidence": entry.licence.confidence if entry else None,
                    "downloads": list(entry.hosts) if entry else [],
                    "known": entry is not None,
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
    return {"solvers": solvers(), "figures": figures(), "data_sources": data_sources(nodes)}


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
