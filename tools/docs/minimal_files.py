"""A minimal valid file per section, built from the field registry.

Usage: python -m tools.docs.minimal_files REGISTRY.json

For each root section, the file holds the sections every file needs (the
required roots) and the required keys of the section, each with the first value
of ``Field(examples=...)``, its default, or the first value of its choice. A
table with several shapes takes its default shape. The file is then validated
by ``HydroModPyConfig.from_toml``: a section whose file does not validate keeps
the error, and the keys that had no value to show, so the gap is fixed in the
model. Nothing is read from an example project.
"""

from __future__ import annotations

import json
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any

import tomli_w

MISSING = object()
MAP_NAME = "main"


def toml_value(text: str | None) -> Any:
    """Parse the TOML literal the registry shows for a default or an example."""
    if text in (None, "", "not set", "(computed)") or str(text).startswith("(table"):
        return MISSING
    try:
        return tomllib.loads(f"x = {text}")["x"]
    except tomllib.TOMLDecodeError:
        return MISSING


def value_of(node: dict[str, Any]) -> Any:
    """The value a minimal file writes for a required key, or MISSING."""
    for text in node.get("examples") or []:
        value = toml_value(text)
        if value is not MISSING:
            return value
    value = toml_value(node.get("default"))
    if value is not MISSING:
        return value
    if node.get("literal"):
        return node["literal"][0]
    return MISSING


class Builder:
    def __init__(self, nodes: dict[str, dict[str, Any]]) -> None:
        self.nodes = nodes
        self.missing: list[str] = []

    def kids(self, path: str) -> list[str]:
        return [c for c in self.nodes[path].get("children", []) if not self.nodes[c].get("pseudo")]

    def shape(self, path: str) -> str | None:
        """The shape a union table takes: its default, or the first one."""
        node = self.nodes[path]
        details = node.get("variants_detail") or []
        if not details:
            return None
        disc = node.get("discriminator")
        tag = self.nodes.get(f"{path}.{disc}", {}) if disc else {}
        default = toml_value(tag.get("default"))
        values = [str(v["value"]) for v in details]
        return str(default) if str(default) in values else values[0]

    def table(self, path: str) -> dict[str, Any]:
        """The required content of one table."""
        node = self.nodes[path]
        if node.get("kind") == "map":
            item = self.kids(path)[0]
            return {MAP_NAME: self.table(item)}
        out: dict[str, Any] = {}
        shape = self.shape(path)
        disc = node.get("discriminator")
        if shape is not None and disc:
            tag = self.nodes.get(f"{path}.{disc}", {})
            literal = [v for v in tag.get("literal", []) if str(v) == shape]
            out[disc] = literal[0] if literal else shape
        for child in self.kids(path):
            cn = self.nodes[child]
            name = cn["name"]
            if shape is not None and cn.get("variants") and shape not in map(str, cn["variants"]):
                continue
            if name in out or not cn.get("required"):
                continue
            if cn.get("kind") == "leaf":
                value = value_of(cn)
                if value is MISSING:
                    self.missing.append(child)
                else:
                    out[name] = value
            elif cn.get("kind") == "array":
                out[name] = [self.table(child)]
            else:
                out[name] = self.table(child)
        return out

    def file(self, section: str) -> dict[str, Any]:
        """The required roots, then the required content of ``section``."""
        doc: dict[str, Any] = {}
        for root in self.nodes[""]["children"]:
            if self.nodes[root].get("required") or root == section:
                content = self.table(root)
                doc[root] = [content] if self.nodes[root].get("kind") == "array" else content
        return doc


def validate(text: str) -> str | None:
    """None when the file validates, else the first line of the refusal."""
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "minimal.toml"
        path.write_text(text)
        try:
            HydroModPyConfig.from_toml(path)
        except Exception as exc:
            lines = [line.strip() for line in str(exc).splitlines() if line.strip()]
            return " ".join(lines[:3])[:400] or type(exc).__name__
    return None


def build(nodes: dict[str, dict[str, Any]], *, check: bool = True) -> dict[str, dict[str, Any]]:
    """Section -> {toml, error, missing}. ``error`` is None for a valid file."""
    out = {}
    for section in nodes[""]["children"]:
        builder = Builder(nodes)
        doc = builder.file(section)
        text = tomli_w.dumps(doc)
        error = None
        if builder.missing:
            error = "no example or default for " + ", ".join(builder.missing)
        elif check:
            error = validate(text)
        out[section] = {"toml": text, "error": error, "missing": builder.missing}
    return out


def main() -> None:
    nodes = json.loads(Path(sys.argv[1]).read_text())["nodes"]
    for section, item in build(nodes).items():
        print(f"{section}: {'OK' if item['error'] is None else item['error']}")


if __name__ == "__main__":
    main()
