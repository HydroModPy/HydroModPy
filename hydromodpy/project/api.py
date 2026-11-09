"""The public verbs that the facade ``hydromodpy`` imports from ``project``.

Today the module holds ``check``, the verb that says what is wrong with a
configuration, and what is not written yet, before anything runs. It takes a
document in memory or a file, reads nothing it was not given, and gives back
every :class:`~hydromodpy.core.diagnostic.Diagnostic` at once.
"""

from __future__ import annotations

import copy
import os
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.core.diagnostic import Diagnostic
from hydromodpy.core.toml_io.error_locator import locate_loc
from hydromodpy.core.toml_io.loader import (
    ChainFile,
    config_base_dir,
    merge_toml_chain,
    read_toml_chain,
)
from hydromodpy.project.environment import Environment
from hydromodpy.project.launch.sites.expansion import (
    PlanDraft,
    SitesProjectError,
    expand_plan,
    find_sites_file,
)
from hydromodpy.project.launch.sites.issues import group_diagnostics
from hydromodpy.workflow.dispatch import (
    WorkflowError,
    check_workflow_name,
    extract_workflow_field,
)

if TYPE_CHECKING:
    from hydromodpy.core.runtime.bounds import Bounds

PathLike = str | os.PathLike[str]
"""A file named by a text or by a path object."""

_EXPERIMENTAL_KEY = "experimental_key"
_PROJECT_ROOT_KEYS = ("workspace", "project_root")


def check(
    source: PathLike | Mapping[str, Any],
    *,
    partial: bool = True,
    inputs: bool = False,
    environment: Environment | None = None,
) -> list[Diagnostic]:
    """Check a configuration, a draft or a file, and return every diagnostic it holds.

    A document that is a mapping is checked as it stands, as a form that is being
    filled would be. A path is read as ``hmp run`` reads it: the ``base_config``
    chain, the project root, the name of the workflow. A ``[sites]`` project is
    expanded case by case, and each issue comes back at the key it reaches. A
    calibration with nothing to fix and nothing to fill is also read by its
    preflight, which looks at the calibration maps on the disk, so a mapping,
    which has no folder to read them from, is not.

    Parameters
    ----------
    source
        A path to a TOML file, or the document as a mapping of sections.
    partial
        True reports a required key that is not written yet as ``to_fill``, a
        severity that stops nothing. False reports it as an ``error``, which is
        what ``hmp run`` refuses.
    inputs
        True also reads the header of each input file the document names, local
        or by its final URL, and downloads nothing.
    environment
        The bounds an input header may be read within. The default is the bounds
        of a bare ``Environment``, every public host and no root.

    Returns
    -------
    list of Diagnostic
        Empty when the document loads and every rule passes. A diagnostic of a
        file carries ``line_number`` where the key is written in that file. The
        file is ``ok`` when no diagnostic has the severity ``error``.

    Raises
    ------
    TypeError
        When *source* is neither a mapping nor a path.
    """
    if not isinstance(source, (str, os.PathLike, Mapping)):
        raise TypeError(
            f"check takes a path or a mapping of sections, not {type(source).__name__}."
        )
    bounds = (environment or Environment()).bounds
    try:
        if isinstance(source, Mapping):
            return _check_document(source, partial=partial, inputs=inputs, base=None, bounds=bounds)
        return _check_file(
            Path(source).expanduser().resolve(), partial=partial, inputs=inputs, bounds=bounds
        )
    except Exception as exc:  # noqa: BLE001 - a check reports, an unexpected error is a finding too
        return [
            Diagnostic(
                path="",
                code="refused_value",
                severity="error",
                detail=f"Config check failed: {exc}",
            )
        ]


def _check_document(
    document: Mapping[str, Any],
    *,
    partial: bool,
    inputs: bool,
    base: Path | None,
    bounds: Bounds,
) -> list[Diagnostic]:
    """Return the diagnostics of an assembled document, by the check of ``config``."""
    from hydromodpy.config.check import check as check_document

    return check_document(document, partial=partial, inputs=inputs, base=base, bounds=bounds)


def _check_file(target: Path, *, partial: bool, inputs: bool, bounds: Bounds) -> list[Diagnostic]:
    """Check the file *target* the way a run reads it."""
    try:
        # As written: the check says the old forms it finds, and does not rewrite them.
        chain = read_toml_chain(target, root=None)
    except tomllib.TOMLDecodeError as exc:
        return [
            Diagnostic(
                path="",
                code="bad_toml",
                severity="error",
                detail=f"Invalid TOML syntax: {exc}",
                line_number=getattr(exc, "lineno", None),
            )
        ]
    except (TypeError, ValueError, OSError) as exc:
        return [
            Diagnostic(
                path="",
                code="bad_chain",
                severity="error",
                detail=f"Invalid base_config chain: {exc}",
            )
        ]
    try:
        sites_file = find_sites_file(chain)
    except SitesProjectError as exc:
        return [Diagnostic(path="", code="sites_case", severity="error", detail=str(exc))]
    if sites_file is not None:
        return _check_sites_project(target, partial=partial, inputs=inputs, bounds=bounds)
    document, told = _read_as_loaded(target, chain)
    try:
        declared = extract_workflow_field(document)
        if declared is not None:
            check_workflow_name(declared)
    except WorkflowError as exc:
        return [Diagnostic(path="workflow", code="unknown_name", severity="error", detail=str(exc))]
    base = config_base_dir(target)
    found = [
        *told,
        *_check_document(document, partial=partial, inputs=inputs, base=base, bounds=bounds),
    ]
    found.extend(_project_root_written(document, base=base))
    if "calibration" in document and not any(item.severity != "warning" for item in found):
        found.extend(_preflight(target))
    return _with_lines(found, target.read_text(encoding="utf-8-sig"))


def _read_as_loaded(
    target: Path, written: Sequence[ChainFile]
) -> tuple[dict[str, Any], list[Diagnostic]]:
    """Return the merged document as a load reads it, and one ``old_key`` per old form.

    Each file of the chain is migrated on its own, so an old form is told under
    the file that holds it. The migration returns its changes as values, so the
    check catches no warning and writes no state of the process. A form the
    loader refuses cannot be told that way: the document is then merged as
    written and the check names the refusal. A form only the merged document
    shows is told by the check of that document. A sealed file is read in
    silence, as a load reads it.
    """
    from hydromodpy.config.config_migration import migrate_config_doc
    from hydromodpy.core.config_kit.base import CANNOT_REWRITE
    from hydromodpy.core.exceptions import HydroModPyError
    from hydromodpy.core.state.result_dirs import is_sealed_run_config

    files: list[ChainFile] = []
    told: list[Diagnostic] = []
    for item in written:
        own = copy.deepcopy(item.own)
        try:
            changes = migrate_config_doc(own)
        except (HydroModPyError, ValueError):
            return merge_toml_chain(written, root=None), []
        # The migration marks a change a load refuses by a subclass of str.
        if any(type(change) is not str for change in changes):
            return merge_toml_chain(written, root=None), []
        if not is_sealed_run_config(item.path):
            told.extend(
                _old_form(item.path, change) for change in changes if CANNOT_REWRITE not in change
            )
        files.append(ChainFile(path=item.path, own=own))
    return merge_toml_chain(files, root=None), told


def _old_form(path: Path, change: str) -> Diagnostic:
    """Return the ``old_key`` of *change* in the file *path*, at the key it names first."""
    key = change.split(None, 1)[0] if change else ""
    return Diagnostic(path=key, code="old_key", severity="warning", detail=f"{path}: {change}.")


def _check_sites_project(
    target: Path, *, partial: bool, inputs: bool, bounds: Bounds
) -> list[Diagnostic]:
    """Expand the ``[sites]`` project *target* and return the issues of its cases, grouped.

    With *inputs*, the header of each input file a case names is read once, and
    a fault shared by several cases is told once.
    """
    from hydromodpy.core.exceptions import ConfigError
    from hydromodpy.core.state.result_dirs import resolve_project_root

    try:
        draft: PlanDraft = expand_plan(resolve_project_root(target.parent), target)
    except ConfigError as exc:
        return [Diagnostic(path="", code="sites_case", severity="error", detail=str(exc))]
    keys = dict.fromkeys(key for case in draft.cases for key in case.experimental_keys)
    found = [
        *group_diagnostics(draft.errors, "error"),
        *group_diagnostics(draft.warnings, "warning"),
        *(Diagnostic(path=key, code=_EXPERIMENTAL_KEY, severity="warning") for key in keys),
    ]
    if inputs:
        found.extend(_inputs_of_the_cases(draft, base=config_base_dir(target), bounds=bounds))
    if not partial:
        found = [
            diagnostic.with_severity("error") if diagnostic.severity == "to_fill" else diagnostic
            for diagnostic in found
        ]
    return found


def _inputs_of_the_cases(draft: PlanDraft, *, base: Path, bounds: Bounds) -> list[Diagnostic]:
    """Return the input header faults of every case of *draft*, each distinct fault once."""
    from hydromodpy.config.input_headers import INPUT_CODES

    found: dict[tuple[str, str, str], Diagnostic] = {}
    for case in draft.cases:
        for item in _check_document(
            case.document, partial=True, inputs=True, base=base, bounds=bounds
        ):
            if item.code in INPUT_CODES:
                found.setdefault((item.path, item.code, item.detail), item)
    return list(found.values())


def _project_root_written(document: Mapping[str, Any], *, base: Path) -> list[Diagnostic]:
    """Return the refusal of a project root written in a file, as the loader of a file gives it.

    ``config.check`` reads a document, which may name its root. A file may not:
    its root is the folder of ``project.toml`` or of the file itself.
    """
    workspace = document.get("workspace")
    if not isinstance(workspace, Mapping) or "project_root" not in workspace:
        return []
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig
    from hydromodpy.config.section_loader import resolve_document

    resolved = resolve_document(
        HydroModPyConfig,
        copy.deepcopy(dict(document)),
        base=base,
        forced_root=None,
        in_a_file=True,
    )
    return [
        diagnostic
        for fault in resolved.faults
        for diagnostic in fault.diagnostics
        if diagnostic.parts == _PROJECT_ROOT_KEYS
    ]


def _preflight(target: Path) -> list[Diagnostic]:
    """Return the preflight of the calibration in *target*, which loads without a fault."""
    from hydromodpy.calibration.preflight import preflight_calibration
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig
    from hydromodpy.core.exceptions import ConfigError
    from hydromodpy.project.trial_pipeline import fill_trial_pipeline

    fill_trial_pipeline()
    try:
        config = HydroModPyConfig.from_toml(target)
    except (ConfigError, ValueError) as exc:
        held = getattr(exc, "diagnostics", ())
        if held:
            return list(held)
        return [Diagnostic(path="", code="refused_value", severity="error", detail=str(exc))]
    return list(preflight_calibration(config, source=target))


def _with_lines(found: Sequence[Diagnostic], text: str) -> list[Diagnostic]:
    """Return *found* with the line of each key in *text*, where the file writes it."""
    placed: list[Diagnostic] = []
    for item in found:
        line = item.line_number
        if line is None and item.parts:
            line = locate_loc(text, item.parts)
        placed.append(item if line is None else replace(item, line_number=line))
    return placed


__all__ = ["PathLike", "check"]
