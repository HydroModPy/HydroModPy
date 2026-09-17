"""Generate the machine-readable process description of every capability.

Three sources, and no JSON is written by hand:

* the **capability declaration** -- identity, title, outputs, declared
  exceptions, environment variables it reads;
* the **Pydantic request model**, through ``config.schema_export``, which
  already emits Draft 2020-12 and already preserves the metadata a frontend
  consumes;
* the **exit-code mapper**, ``cli.helpers.exit_code_for``, so the description
  cannot claim an exit code the process does not produce.

Lives in ``tools/`` and not in the package: it imports ``config`` and the
capability registry, which is a pairing no layer of ``hydromodpy`` is allowed
to make. ``tools/doc_config/generate.py`` already has this shape.

Refresh with ``python -m tools.processes``. A committed file the generator no
longer reproduces is a gate failure, not a warning: the OpenAPI wrapper next
door is generated without a gate and has drifted.

Two deliberate departures from the specification this was written against:

* the ``$id`` of an embedded input schema carries the **capability** version,
  not the package version. The document is committed and byte-compared, so a
  package version in it would turn the gate red on every release for a
  description that did not change. What governs an input schema is the
  capability that declares it.
* ``progress_file``, ``network`` and ``concurrency`` are **absent** from the
  invocation block. Nothing in this tree writes ``progress.ndjson`` yet, and
  neither of the other two is enforced anywhere. Declaring them would publish
  exactly the kind of statement F1 and F2 spent two phases removing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hydromodpy.cli._workers.process import capability_decls
from hydromodpy.cli.helpers import EXIT_SIGINT, exit_code_for
from hydromodpy.config.schema_export import export_schema, extract_property_schema
from hydromodpy.schema.capability import CapabilityDecl, OutputDecl
from hydromodpy.schema.job.layout import OUTCOME_FILENAME, REQUEST_FILENAME
from hydromodpy.schema.processes import (
    INDEX_FILENAME,
    INDEX_PROFILE,
    PROCESS_PROFILE,
    description_filename,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DESCRIPTIONS_DIR = REPO_ROOT / "hydromodpy" / "schema" / "processes"

JOB_CONTROL_OPTIONS = ("sync-execute",)
"""The process runs to completion in the caller's foreground, and nothing else."""

OUTPUT_TRANSMISSION = ("reference",)
"""Artefacts stay on disk under the job directory; nothing is inlined."""

JOB_DIR_PLACEHOLDER = "{jobdir}"

DISMISSED_STATUS = "dismissed"
"""The status a cancelled job writes. Pinned to ``JobStatus`` by the gate."""


def _write_if_changed(path: Path, content: str) -> bool:
    """Write *content* to *path* only when it differs. Returns whether it wrote."""
    try:
        if path.read_text(encoding="utf-8") == content:
            return False
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def _serialise(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def error_code(exc_cls: type[BaseException]) -> str:
    """Return the stable code of a declared failure.

    ``HMPY.Exxx`` for the typed hierarchy, the Python class name for a builtin
    a capability legitimately raises. One rule, and the two never collide.
    """
    code = getattr(exc_cls, "code", None)
    return code if isinstance(code, str) else exc_cls.__name__


def error_title(exc_cls: type[BaseException]) -> str:
    """Return a one-line human title for a declared failure."""
    title = getattr(exc_cls, "title", None)
    if callable(title):
        return str(title())
    doc = exc_cls.__doc__
    if doc and doc.strip():
        return doc.strip().splitlines()[0].strip()
    return exc_cls.__name__


def build_exceptions(decl: CapabilityDecl) -> list[dict[str, Any]]:
    """Return the failure table, with the exit code the mapper really produces.

    The instance is built with ``__new__``: :func:`exit_code_for` only tests
    ``isinstance``, and a declared exception whose constructor takes arguments
    would otherwise be undescribable.
    """
    table: list[dict[str, Any]] = []
    for exc_cls in decl.exceptions:
        code = error_code(exc_cls)
        table.append(
            {
                "type": f"urn:hmp:error:{code}",
                "code": code,
                "exit_code": exit_code_for(exc_cls.__new__(exc_cls)),
                "title": error_title(exc_cls),
            }
        )
    return table


def _occurrences(field_schema: dict[str, Any], *, required: bool) -> tuple[int, int]:
    """Return ``(minOccurs, maxOccurs)`` of one input.

    A field with a default may be omitted. A sequence occurs as many times as
    its declared upper bound; anything else occurs once. A sequence without an
    upper bound is refused rather than described as unbounded: the description
    has to carry a number, and inventing one would be a promise nothing keeps.
    """
    minimum = 1 if required else 0
    if field_schema.get("type") != "array":
        return minimum, 1
    maximum = field_schema.get("maxItems")
    if not isinstance(maximum, int):
        raise ValueError("an array input must declare max_length so maxOccurs is a number")
    return minimum, maximum


def build_inputs(decl: CapabilityDecl) -> dict[str, Any]:
    """Return one entry per top-level field of the request model."""
    root = export_schema(decl.request_model, scope=f"{decl.id}:{decl.version}")
    required = set(root.get("required", ()))

    inputs: dict[str, Any] = {}
    for name in root.get("properties", {}):
        field_schema = extract_property_schema(root, name)
        minimum, maximum = _occurrences(field_schema, required=name in required)
        field_schema["$id"] = f"urn:hmp:schema:{decl.id}:{decl.version}:{name}"
        field_schema["$schema"] = root["$schema"]
        entry: dict[str, Any] = {
            # Pydantic titles every property but a bare ``$ref``, so the fallback
            # spells the field name the way Pydantic would have.
            "title": field_schema.get("title") or name.replace("_", " ").title(),
            "minOccurs": minimum,
            "maxOccurs": maximum,
            "schema": field_schema,
        }
        description = field_schema.get("description")
        if isinstance(description, str):
            entry["description"] = description
        inputs[name] = entry
    return inputs


def build_output(output: OutputDecl) -> dict[str, Any]:
    """Return one ``outputs`` entry, declared path and roles included."""
    entry: dict[str, Any] = {
        "title": output.title,
        "schema": {"type": "string", "contentMediaType": output.media_type},
        "hmp:path": output.path,
        "hmp:role": list(output.roles),
        "minOccurs": 1 if output.required else 0,
    }
    entry.update({key: value for key, value in sorted(output.extra.items())})
    return entry


def build_invocation(decl: CapabilityDecl) -> dict[str, Any]:
    """Return how this capability is invoked, and what it promises while it runs."""
    return {
        "argv": ["hmp", "process", "run", decl.id, "--job", JOB_DIR_PLACEHOLDER],
        "request_file": REQUEST_FILENAME,
        "outcome_file": OUTCOME_FILENAME,
        "stdout": f"application/json, exactly one document, byte-identical to {OUTCOME_FILENAME}",
        # A list and not a boolean: the answer an orchestrator needs is "what
        # else has to be writable", and for this capability it is not "nothing".
        # Empty means the job directory is the only writable thing it wants.
        "writes_outside_jobdir": list(decl.writes_outside_jobdir),
        "reads_outside_jobdir": f"only the paths declared in {REQUEST_FILENAME}",
        "cancellation": {
            "signal": "SIGTERM",
            "status": DISMISSED_STATUS,
            "exit_code": EXIT_SIGINT,
        },
        "env": list(decl.env),
    }


def build_description(decl: CapabilityDecl) -> dict[str, Any]:
    """Return the full process description of one capability."""
    return {
        "$schema": PROCESS_PROFILE,
        "id": decl.id,
        "version": decl.version,
        "title": decl.title,
        "description": decl.description,
        "keywords": list(decl.keywords),
        "jobControlOptions": list(JOB_CONTROL_OPTIONS),
        "outputTransmission": list(OUTPUT_TRANSMISSION),
        "hmp:invocation": build_invocation(decl),
        "inputs": build_inputs(decl),
        "outputs": {output.id: build_output(output) for output in decl.outputs},
        "hmp:exceptions": build_exceptions(decl),
        "hmp:artifacts": {
            "seal": "manifest.json",
            "seal_rule": (
                "present if and only if the job succeeded and every declared "
                "output exists and hashes"
            ),
        },
        "links": [
            {
                "rel": "self",
                "href": description_filename(decl.id, decl.major),
                "type": "application/json",
            },
            {"rel": "describedby", "href": PROCESS_PROFILE, "type": "application/json"},
        ],
    }


def build_index(decls: tuple[CapabilityDecl, ...]) -> dict[str, Any]:
    """Return the index a shim reads first, one record per description."""
    return {
        "$schema": INDEX_PROFILE,
        "processes": [
            {
                "id": decl.id,
                "version": decl.version,
                "major": decl.major,
                "title": decl.title,
                "file": description_filename(decl.id, decl.major),
            }
            for decl in sorted(decls, key=lambda decl: (decl.id, decl.major))
        ],
    }


def render_all() -> dict[str, str]:
    """Return every file this generator owns, as ``name -> serialised bytes``."""
    decls = tuple(sorted(capability_decls(), key=lambda decl: (decl.id, decl.major)))
    rendered = {
        description_filename(decl.id, decl.major): _serialise(build_description(decl))
        for decl in decls
    }
    rendered[INDEX_FILENAME] = _serialise(build_index(decls))
    return rendered


def generate_all(output_dir: Path | None = None) -> list[Path]:
    """Write every description and the index. Returns the paths it owns."""
    out = (output_dir or DESCRIPTIONS_DIR).resolve()
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, content in sorted(render_all().items()):
        path = out / name
        _write_if_changed(path, content)
        written.append(path)
    return written


__all__ = [
    "DESCRIPTIONS_DIR",
    "DISMISSED_STATUS",
    "build_description",
    "build_exceptions",
    "build_index",
    "build_inputs",
    "build_invocation",
    "build_output",
    "error_code",
    "error_title",
    "generate_all",
    "render_all",
]
