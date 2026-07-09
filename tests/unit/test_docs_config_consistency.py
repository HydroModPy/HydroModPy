"""Self-checks for the auto-generated configuration reference.

The doc generator (``tools/doc_config``) walks ``HydroModPyConfig`` and
emits TOML snippets, recipes, and a JSON Schema bundle. This test module
guards the contract between Pydantic, the generated TOML, and the
exported schema:

* the exported schema is a valid JSON Schema 2020-12 document,
* every per-section starter snippet parses as TOML,
* every annotated section block in ``complete_toml.rst`` parses as TOML,
* every ``code-block:: toml`` snippet inside ``recipes.rst`` parses as
  TOML and only references TOML sections that exist in the schema.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Iterable
from pathlib import Path

import pytest
from jsonschema.validators import Draft202012Validator
from pydantic import BaseModel

from hydromodpy.config import HydroModPyConfig
from tools.doc_config.generate import (
    _render_starter_snippet,
    _unwrap,
    export_openapi_wrapper,
    export_schema,
    export_search_index,
)

ROOT = Path(__file__).resolve().parents[2]
REFERENCE_DIR = ROOT / "docs" / "source" / "user_guide" / "config_reference"
SCHEMA_PATH = ROOT / "docs" / "source" / "_static" / "hydromodpy-schema.json"
OPENAPI_PATH = ROOT / "docs" / "source" / "_static" / "hydromodpy-openapi.json"
SEARCH_INDEX_PATH = ROOT / "docs" / "source" / "_static" / "hmp-config-search.json"


_TOML_BLOCK_RE = re.compile(
    r"\.\. code-block:: toml\s*\n((?:(?:[ \t]+[^\n]*|\s*)\n)+?)(?=^\S|\Z)",
    flags=re.MULTILINE,
)


def _extract_toml_blocks(text: str) -> list[str]:
    """Return every TOML payload from a Sphinx ``code-block:: toml`` directive."""
    blocks: list[str] = []
    for match in _TOML_BLOCK_RE.finditer(text):
        raw = match.group(1).rstrip("\n")
        lines = raw.splitlines()
        if not lines:
            continue
        prefix = re.match(r"^[ \t]*", lines[0]).group(0)
        if not prefix:
            blocks.append(raw)
            continue
        dedented = "\n".join(
            line[len(prefix) :] if line.startswith(prefix) else line for line in lines
        )
        blocks.append(dedented)
    return blocks


def _top_level_sections(model: type[BaseModel]) -> set[str]:
    out: set[str] = set()
    for name, field in model.model_fields.items():
        inner = _unwrap(field.annotation)
        if isinstance(inner, type) and issubclass(inner, BaseModel):
            out.add(name)
    return out


def _walk_payload_keys(payload: object, prefix: str = "") -> Iterable[str]:
    if isinstance(payload, dict):
        for key, value in payload.items():
            full = f"{prefix}.{key}" if prefix else key
            yield full
            yield from _walk_payload_keys(value, full)
    elif isinstance(payload, list):
        for item in payload:
            yield from _walk_payload_keys(item, prefix)


# ---------------------------------------------------------------------------
# Schema-level checks
# ---------------------------------------------------------------------------


def test_exported_schema_is_valid_json_schema_2020_12(tmp_path: Path) -> None:
    schema_path = export_schema(tmp_path / "hydromodpy-schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)


def test_committed_schema_matches_generated(tmp_path: Path) -> None:
    fresh = export_schema(tmp_path / "hydromodpy-schema.json")
    expected = json.loads(fresh.read_text(encoding="utf-8"))
    committed = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert committed == expected, (
        "docs/source/_static/hydromodpy-schema.json is stale. "
        "Run `python -m tools.doc_config` to refresh."
    )


def test_committed_openapi_wrapper_matches_generated(tmp_path: Path) -> None:
    fresh = export_openapi_wrapper(tmp_path / "hydromodpy-openapi.json")
    expected = json.loads(fresh.read_text(encoding="utf-8"))
    committed = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
    assert committed == expected, (
        "docs/source/_static/hydromodpy-openapi.json is stale. "
        "Run `python -m tools.doc_config` to refresh."
    )


def test_committed_search_index_matches_generated(tmp_path: Path) -> None:
    fresh = export_search_index(HydroModPyConfig.model_fields, tmp_path / "hmp-config-search.json")
    expected = json.loads(fresh.read_text(encoding="utf-8"))
    committed = json.loads(SEARCH_INDEX_PATH.read_text(encoding="utf-8"))
    assert committed == expected, (
        "docs/source/_static/hmp-config-search.json is stale. "
        "Run `python -m tools.doc_config` to refresh."
    )


# ---------------------------------------------------------------------------
# TOML round-trip checks for the auto-generated snippets
# ---------------------------------------------------------------------------


SECTION_NAMES = sorted(
    name
    for name, field in HydroModPyConfig.model_fields.items()
    if isinstance(_unwrap(field.annotation), type)
    and issubclass(_unwrap(field.annotation), BaseModel)
)


@pytest.mark.parametrize("section", SECTION_NAMES)
def test_starter_snippet_parses_as_toml(section: str) -> None:
    field = HydroModPyConfig.model_fields[section]
    model = _unwrap(field.annotation)
    snippet = "\n".join(_render_starter_snippet(section, model))
    parsed = tomllib.loads(snippet)
    assert section in parsed, f"Starter snippet for [{section}] did not yield a top-level table."


def test_complete_toml_blocks_parse(tmp_path: Path) -> None:
    text = (REFERENCE_DIR / "complete_toml.rst").read_text(encoding="utf-8")
    blocks = _extract_toml_blocks(text)
    assert blocks, "complete_toml.rst must expose at least one TOML block."
    failures: list[str] = []
    for index, block in enumerate(blocks):
        try:
            tomllib.loads(block)
        except tomllib.TOMLDecodeError as exc:
            failures.append(f"block #{index}: {exc}")
    assert not failures, "Generated complete_toml blocks did not parse:\n" + "\n".join(failures)


# ---------------------------------------------------------------------------
# Recipes guard
# ---------------------------------------------------------------------------


def test_recipes_blocks_parse_and_reference_known_sections() -> None:
    text = (REFERENCE_DIR / "recipes.rst").read_text(encoding="utf-8")
    blocks = _extract_toml_blocks(text)
    assert blocks, "recipes.rst must expose at least one TOML block."
    known_top = _top_level_sections(HydroModPyConfig) | {"workflow"}
    parse_failures: list[str] = []
    schema_failures: list[str] = []
    for index, block in enumerate(blocks):
        try:
            payload = tomllib.loads(block)
        except tomllib.TOMLDecodeError as exc:
            parse_failures.append(f"block #{index}: {exc}\n--- snippet ---\n{block}\n--- end ---")
            continue
        if not isinstance(payload, dict):
            continue
        for key in payload.keys():
            if key not in known_top:
                schema_failures.append(
                    f"block #{index}: top-level [{key}] is not a HydroModPyConfig section"
                )
    assert not parse_failures, "Recipes contain non-parseable TOML:\n" + "\n\n".join(parse_failures)
    assert not schema_failures, "Recipes reference unknown top-level sections:\n" + "\n".join(
        schema_failures
    )
