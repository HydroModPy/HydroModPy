"""The check of a configuration document, section by section, with every diagnostic at once.

``check(document, partial=True)`` validates a document already assembled, a whole
project or a draft a form is filling. It reads no file and asks no network unless
``inputs`` is true. It walks the validator the loader walks
(``config/section_loader.py``), so a document ``check(partial=False)`` passes is
one ``HydroModPyConfig.from_toml`` loads, and a document it refuses is refused by
the loader at the pointer of the first error.

Partial means this. The resolutions run first, on a copy: the old forms of a
key, the protocol of a calibration, the gauge of ``[site]`` and the window of
``[metrics]`` written into ``[calibration]``. A required key the document does
not write yet is ``to_fill``, found by walking the required fields of each
section and never read from the type of a Pydantic error. A section is complete
when it has no ``error`` and no ``to_fill``, and an optional section left out
counts as complete at its default. A rule of ``CROSS_RULES`` runs once every
section it reads is complete, and waits without a word before. ``partial=False``
turns each ``to_fill`` into an ``error`` at the same code and changes nothing else.

The phrase of a code, in English and in French, is read from
``hydromodpy/schema/phrases.toml`` by :func:`phrase` when a diagnostic is written
for a reader.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from hydromodpy.config.config_migration import _change_label, migrate_merged_doc
from hydromodpy.config.cross_checks import deduce_the_mesh_engine, run_cross_rules
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.config.section_loader import (
    SECTIONS,
    align_solver_keys,
    build_document,
    faults_of_rules,
    resolve_document,
    severity_of,
    validate_sections,
)
from hydromodpy.core.config_kit.base import CANNOT_REWRITE, ConfigKeyRenamedWarning
from hydromodpy.core.config_kit.said import Said, collecting
from hydromodpy.core.config_kit.written import written_experimental_keys
from hydromodpy.core.diagnostic import Diagnostic
from hydromodpy.core.exceptions import HydroModPyError
from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.core.toml_io.error_locator import format_loc
from hydromodpy.data.sites.gauge import apply_site_gauge
from hydromodpy.schema.phrases import keys
from hydromodpy.schema.phrases import phrase as read_phrase

CHECK_CODES: frozenset[str] = keys("check")
"""The closed set of the codes a check gives, the keys of ``[check]`` in ``schema/phrases.toml``."""


def phrase(code: str, lang: str = "en") -> str:
    """Return the phrase of a check code in *lang*, ``en`` or ``fr``.

    Raises
    ------
    KeyError
        When *code* is not a check code.
    ValueError
        When *lang* is not one of ``LANGS``.
    """
    return read_phrase("check", code, lang)


def check(
    document: Mapping[str, Any],
    *,
    base: Path,
    partial: bool = True,
    inputs: bool = False,
    bounds: Bounds | None = None,
) -> list[Diagnostic]:
    """Check a configuration document and return every diagnostic it holds.

    The warnings of the sections are collected in a sink the call opens
    (``core/config_kit/said.py``). The sink belongs to the calling thread, so a
    check beside another check, or beside a run, in another thread keeps its own
    warnings and never touches the filters of the process.

    Parameters
    ----------
    document
        The document as written: one table per section, a draft or a whole file.
    base
        The folder relative paths are read from, the project root. A document has
        no folder of its own, so the caller names it; the current folder is never
        used.
    partial
        True reports a required key not written yet as ``to_fill``. False reports
        it as an ``error``, which is what ``hmp run`` refuses.
    inputs
        True also reads the header of each input file the document names, local or
        by its final URL, and downloads nothing.
    bounds
        The hosts and roots an input header may be read from. Without it, an input
        given by URL is ``input_unreachable``.

    Returns
    -------
    list of Diagnostic
        Empty when the document loads and every rule passes.
    """
    if not isinstance(document, Mapping):
        return [
            Diagnostic(
                path="",
                code="wrong_type",
                severity="error",
                detail="A configuration document is a table of sections.",
                keys=(),
                error_type="dict_type",
            )
        ]
    root = HydroModPyConfig
    base = Path(base).expanduser().resolve()
    raw = copy.deepcopy(dict(document))
    found = _old_forms(raw)
    with collecting() as said_by_sections:
        resolved = resolve_document(root, raw, base=base, forced_root=None, in_a_file=False)
        sections, faults = validate_sections(root, resolved, base=base)
        faults = [*resolved.faults, *faults]
        built: HydroModPyConfig | None = None
        said: list[str] = []
        if not faults:
            cfg, faults, said = build_document(root, sections, resolved, context="api")
            built = cfg if isinstance(cfg, HydroModPyConfig) else None
        held = [diagnostic for fault in faults for diagnostic in fault.diagnostics]
        if built is None:
            waited, said = _rules_on_what_is_complete(sections, held)
            held.extend(waited)
    found.extend(held)
    found.extend(
        Diagnostic(path="", code="cross_warning", severity="warning", detail=text, keys=())
        for text in said
    )
    found.extend(_said_by_the_sections(said_by_sections))
    if built is not None:
        found.extend(
            Diagnostic(path=key, code="experimental_key", severity="warning")
            for key in written_experimental_keys(built)
        )
    if inputs:
        # Imported here: rasterio costs at import, and neither ``import hydromodpy``
        # nor a check without inputs should pay it.
        from hydromodpy.config.input_headers import read_input_headers

        target = built if built is not None else SimpleNamespace(**sections)
        found.extend(read_input_headers(target, base=base, bounds=bounds))
    if not partial:
        found = [
            diagnostic.with_severity("error") if diagnostic.severity == "to_fill" else diagnostic
            for diagnostic in found
        ]
    return found


def _old_forms(raw: dict[str, Any]) -> list[Diagnostic]:
    """Rewrite the old forms of *raw* in place and return one diagnostic per form.

    A form the migration rewrites still loads, with ``old_key``. A form it cannot
    rewrite, or one a load refuses, is ``retired_key``, at each key the refusal
    names when it names them.
    """
    try:
        changes = migrate_merged_doc(raw)
    except (ValueError, HydroModPyError) as exc:
        detail = getattr(exc, "message", "") or str(exc)
        named = [entry for entry in getattr(exc, "details", ()) if entry.get("loc")]
        if not named:
            return [
                Diagnostic(path="", code="retired_key", severity="error", detail=detail, keys=())
            ]
        return [
            Diagnostic(
                path=format_loc(entry["loc"]),
                code="retired_key",
                severity="error",
                detail=str(entry.get("msg") or detail),
                keys=tuple(str(part) for part in entry["loc"]),
            )
            for entry in named
        ]
    found: list[Diagnostic] = []
    for change in changes:
        # A change a load refuses is marked by a subclass of str in the migration.
        refused = CANNOT_REWRITE in change or type(change) is not str
        code = "retired_key" if refused else "old_key"
        found.append(
            Diagnostic(
                path=_change_label(str(change)),
                code=code,
                severity=severity_of(code),
                detail=str(change),
            )
        )
    return found


def _rules_on_what_is_complete(
    sections: Mapping[str, Any], held: Sequence[Diagnostic]
) -> tuple[list[Diagnostic], list[str]]:
    """Run the rules whose sections are all complete, on a document that does not build.

    The resolutions a built root applies run first on what is complete: the
    backend that follows the flow process, the gauge of ``[site]`` in the station
    sources, the mesh engine a global model reads. A rule that reads a section
    with an ``error`` or a ``to_fill`` waits.
    """
    root = HydroModPyConfig
    blocked = {
        diagnostic.parts[0]
        for diagnostic in held
        if diagnostic.severity != "warning" and diagnostic.parts
    }
    complete = {name for name in SECTIONS if name in sections and name not in blocked}
    namespace = SimpleNamespace(**{name: sections.get(name) for name in SECTIONS})
    if "workflow" not in sections and "workflow" not in blocked:
        namespace.workflow = root.model_fields["workflow"].get_default(call_default_factory=True)
        complete.add("workflow")
    found: list[Diagnostic] = []
    if {"simulation", "solver"} <= complete:
        try:
            aligned = align_solver_keys(
                {"simulation": namespace.simulation, "solver": namespace.solver}
            )
        except ValueError as exc:
            found.append(_whole_document(str(exc), "value_error"))
            complete.discard("solver")
        else:
            namespace.solver = aligned["solver"]
    if {"data", "site"} <= complete:
        try:
            apply_site_gauge(namespace.data, namespace.site)
        except HydroModPyError as exc:
            found.append(_whole_document(exc.message or str(exc), "value_error"))
            complete.discard("data")
    if {"solver", "mesh"} <= complete:
        deduce_the_mesh_engine(namespace)
    outcomes = run_cross_rules(namespace, sealed=False, ready=lambda rule: rule.reads <= complete)
    for fault in faults_of_rules(outcomes, root=root, document=dict(sections)):
        found.extend(fault.diagnostics)
    return found, [text for outcome in outcomes for text in outcome.warnings]


def _whole_document(detail: str, error_type: str) -> Diagnostic:
    """Return the refusal of a resolution that reads several sections, at the whole document."""
    return Diagnostic(
        path="",
        code="refused_value",
        severity="error",
        detail=detail,
        keys=(),
        error_type=error_type,
    )


def _said_by_the_sections(caught: Sequence[Said]) -> list[Diagnostic]:
    """Return the warnings the validators of the sections gave, once each.

    An old spelling a model renames is ``old_key``, any other warning of a
    validator ``section_warning``. A deprecation is for a developer of the
    package and a resource warning comes from an object opened elsewhere, so
    neither is a fault of the document.
    """
    found: dict[tuple[str, str], Diagnostic] = {}
    for item in caught:
        if issubclass(item.category, (DeprecationWarning, ResourceWarning)):
            continue
        code = (
            "old_key" if issubclass(item.category, ConfigKeyRenamedWarning) else "section_warning"
        )
        text = item.text
        found.setdefault(
            (code, text),
            Diagnostic(path="", code=code, severity="warning", detail=text, keys=()),
        )
    return list(found.values())


__all__ = ["CHECK_CODES", "check", "phrase"]
