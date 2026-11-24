"""What ``check`` reads in a configuration: a document, a file and its chain, a ``[sites]`` project.

The verb :func:`hydromodpy.project.api.check` turns a source into one call of
:func:`check_document` or :func:`check_file`. A file is read the way ``hmp run``
reads it, and each diagnostic of a file carries the line its key is written on.

``check`` is the one check of ``hmp check`` for a run, a calibration or a whole project,
and it gives each case of a ``[sites]`` project the diagnostic ``sites_case``. A
``[site]`` alone is resolved against the site catalog of the workspace by
``data/sites/single_site.py``.
"""

from __future__ import annotations

import copy
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.core.diagnostic import Diagnostic
from hydromodpy.core.state.result_dirs import resolve_project_root
from hydromodpy.core.toml_io.error_locator import locate_loc
from hydromodpy.core.toml_io.loader import (
    ChainFile,
    config_base_dir,
    merge_toml_chain,
    merge_toml_layers,
    read_toml_chain,
)
from hydromodpy.project.launch.plan import (
    PlanDraft,
    SitesProjectError,
    expand_plan,
    find_sites_file,
    group_diagnostics,
)
from hydromodpy.workflow.dispatch import (
    WorkflowError,
    check_workflow_name,
    extract_workflow_field,
)

if TYPE_CHECKING:
    from hydromodpy.core.runtime.bounds import Bounds


_EXPERIMENTAL_KEY = "experimental_key"
MEMORY_TAKES_NO_LAYER = (
    "A document given as a mapping takes no overlay and no set: write the keys in it."
)
SITES_TAKE_NO_OVERLAY = (
    "A [sites] project takes no overlay: write its keys in a recipe of [sites.recipes], "
    "or in <overrides>/<site>.toml for one site."
)
_PROJECT_ROOT_KEYS = ("workspace", "project_root")


def check_document(
    document: Mapping[str, Any],
    *,
    partial: bool,
    inputs: bool,
    base: Path | None,
    bounds: Bounds,
) -> list[Diagnostic]:
    """Return the diagnostics of an assembled document, by the check of ``config``."""
    from hydromodpy.config.check import check

    return check(document, partial=partial, inputs=inputs, base=base, bounds=bounds)


def check_mapping(
    document: Mapping[str, Any],
    partial: bool,
    inputs: bool,
    base: Path | None,
    bounds: Bounds,
    *,
    layered: bool,
) -> list[Diagnostic]:
    """Check a document given as a mapping, which needs a base and takes no overlay or set."""
    from hydromodpy.config.loading import MEMORY_NEEDS_BASE

    if base is None or layered:
        detail = MEMORY_NEEDS_BASE if base is None else MEMORY_TAKES_NO_LAYER
        return [Diagnostic(path="", code="refused_value", severity="error", detail=detail)]
    return check_document(document, partial=partial, inputs=inputs, base=base, bounds=bounds)


def check_file(
    target: Path,
    *,
    partial: bool,
    inputs: bool,
    bounds: Bounds,
    base: Path | None,
    overlays: Sequence[Path] = (),
    changes: Mapping[str, Any] | None = None,
) -> list[Diagnostic]:
    """Check the file *target* the way a run reads it, against *base* when it is given.

    *overlays* and *changes* are merged over the chain as ``hmp run --overlay`` and
    ``--set`` merge them, so a file and the overlay it runs with are checked together.
    """
    try:
        # As written: the check says the old forms it finds, and does not rewrite them.
        chain = read_toml_chain(target, root=None)
        layers = [
            read_toml_chain(Path(item).expanduser().resolve(), root=None) for item in overlays
        ]
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
        if overlays:
            return [
                Diagnostic(
                    path="", code="sites_case", severity="error", detail=SITES_TAKE_NO_OVERLAY
                )
            ]
        return _check_sites_project(
            target, partial=partial, inputs=inputs, bounds=bounds, changes=changes
        )
    try:
        document, told = _read_as_loaded(chain, layers, changes)
    except ValueError as exc:
        # Two bases that disagree, or a directive the merge cannot apply.
        return [
            Diagnostic(
                path="",
                code="bad_chain",
                severity="error",
                detail=f"Invalid base_config chain: {exc}",
            )  # fmt: skip
        ]
    try:
        declared = extract_workflow_field(document)
        if declared is not None:
            check_workflow_name(declared)
    except WorkflowError as exc:
        return [Diagnostic(path="workflow", code="unknown_name", severity="error", detail=str(exc))]
    folder = base if base is not None else config_base_dir(target, chain=chain)
    found = [
        *told,
        *check_document(document, partial=partial, inputs=inputs, base=folder, bounds=bounds),
    ]
    found.extend(_project_root_written(document, base=folder))
    if "calibration" in document and not any(item.severity != "warning" for item in found):
        found.extend(_preflight(target, folder))
    return _with_lines(found, target.read_text(encoding="utf-8-sig"))


def _read_as_loaded(
    written: Sequence[ChainFile],
    overlays: Sequence[Sequence[ChainFile]] = (),
    changes: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], list[Diagnostic]]:
    """Return the merged document as a load reads it, and one ``old_key`` per old form.

    The chain of each overlay is read like the chain of the file, then merged over
    it, and *changes* last, the order of ``hmp run``.
    """
    from hydromodpy.config.loading import changes_payload

    chains: list[list[ChainFile]] = []
    told: list[Diagnostic] = []
    for chain in (written, *overlays):
        files, said = _migrated_chain(chain)
        chains.append(files)
        told.extend(said)
    if len(chains) == 1 and not changes:
        return merge_toml_chain(chains[0], root=None), told
    payload = changes_payload(changes) or None
    return merge_toml_layers(chains, root=None, cli_overrides=payload), told


def _migrated_chain(written: Sequence[ChainFile]) -> tuple[list[ChainFile], list[Diagnostic]]:
    """Return the files of one chain each migrated on its own, and one ``old_key`` per old form.

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
            return list(written), []
        # The migration marks a change a load refuses by a subclass of str.
        if any(type(change) is not str for change in changes):
            return list(written), []
        if not is_sealed_run_config(item.path):
            told.extend(
                _old_form(item.path, change) for change in changes if CANNOT_REWRITE not in change
            )
        files.append(ChainFile(path=item.path, own=own, bases=item.bases))
    return files, told


def _old_form(path: Path, change: str) -> Diagnostic:
    """Return the ``old_key`` of *change* in the file *path*, at the key it names first."""
    key = change.split(None, 1)[0] if change else ""
    return Diagnostic(path=key, code="old_key", severity="warning", detail=f"{path}: {change}.")


def _check_sites_project(
    target: Path,
    *,
    partial: bool,
    inputs: bool,
    bounds: Bounds,
    changes: Mapping[str, Any] | None = None,
) -> list[Diagnostic]:
    """Expand the ``[sites]`` project *target* and return the issues of its cases, grouped.

    With *inputs*, the header of each input file a case names is read once, and
    a fault shared by several cases is told once.
    """
    from hydromodpy.config.loading import changes_payload
    from hydromodpy.core.exceptions import ConfigError

    try:
        draft: PlanDraft = expand_plan(
            resolve_project_root(target.parent),
            target,
            set_overrides=changes_payload(changes) or None,
        )
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
        for item in check_document(
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


def _preflight(target: Path, base: Path) -> list[Diagnostic]:
    """Return the preflight of the calibration in *target*, which loads without a fault."""
    from hydromodpy.calibration.preflight import preflight_calibration
    from hydromodpy.config.loading import load
    from hydromodpy.core.exceptions import ConfigError
    from hydromodpy.project.trial_pipeline import fill_trial_pipeline

    fill_trial_pipeline()
    try:
        config = load(target, base)
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
