"""The request of a run: one form for a TOML file, a dict, JSON, a server and Docker.

A :class:`RunRequest` holds the document a run is given and the options that
steer it, and nothing about where it runs. The base of its relative paths is an
argument of the runner (:func:`base_of`), and so is the
:class:`~hydromodpy.project.environment.Environment`, which is never written. A
server fills a request by ``model_dump`` and ``hmp run x.json`` reads the same
form, so ``request.json`` in a run directory is a request that can be played
again.

:func:`request_of` builds the request from what a caller holds: a ``.toml``
file, whose chain and overlays are read once into ``config``; a ``.json`` file,
which is a serialized request; a mapping or JSON text, which is a document; a
built configuration. The combinations of options a workflow refuses are refused
here, with the sentences of ``hmp run``.

The identity of a request is told by :mod:`hydromodpy.workflow.solution_key`.
:class:`RunOutcome` is the typed reading of the outcome of a run once it is
done.
"""

from __future__ import annotations

import copy
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from hydromodpy.config.config_migration import rewrite_dotted_path
from hydromodpy.config.hydromodpy_config import ROOT_CONFIG, HydroModPyConfig
from hydromodpy.config.loading import (
    MEMORY_NEEDS_BASE,
    REQUEST_SUFFIX,
    TOML_SUFFIX,
    is_json_text,
    json_object,
    read_document,
    refuse_base_config,
    refuse_file_type,
)
from hydromodpy.core.config_kit.written import written_as_a_file
from hydromodpy.core.exceptions import ConfigError, ConfigValidationError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.names import check_name
from hydromodpy.core.state.result_dirs import resolve_project_root
from hydromodpy.core.toml_io.loader import config_base_dir
from hydromodpy.core.toml_io.paths import assign
from hydromodpy.results.outcome import effective_status, read_outcome
from hydromodpy.results.publication import PublishedLine
from hydromodpy.results.storage.contract import RUN_REQUEST_FILENAME
from hydromodpy.results.storage.json_io import write_json_atomic
from hydromodpy.workflow.dispatch import (
    WorkflowName,
    check_workflow_name,
    extract_workflow_field,
    workflow_of_sections,
)

logger = get_logger(__name__)

REQUEST_SCHEMA: Final[str] = "hydromodpy.request.v1"
"""Schema id of a run request."""

RequestForm = Literal["toml", "json", "dict", "object"]
"""What the request was built from: a TOML file, JSON, a mapping or a built configuration."""

WRITTEN_FORMS: Final[frozenset[str]] = frozenset({"json", "dict"})
"""The forms whose request is written as ``request.json`` at the claim.

A TOML file says what it asked in ``config.toml`` already, and so does a built
configuration.
"""


class RunRequest(BaseModel):
    """A run as it is asked for: the document and the options that steer it.

    The base of the relative paths and the environment of the call are not part
    of it, so the request is the same on any machine.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    schema_: Literal["hydromodpy.request.v1"] = Field(
        default=REQUEST_SCHEMA, alias="schema", description="Schema id of the request."
    )
    config: dict[str, Any] = Field(
        description=(
            "The whole configuration document: a TOML file and its base_config chain and "
            "overlays merged, or the document given as JSON or as a dict. It names no "
            "base_config and no [workspace] project_root."
        )
    )
    set: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Values set on top of config by dotted path, the grammar of --set, applied once "
            "at the load and sealed in lineage.overrides."
        ),
    )
    overlays: tuple[str, ...] = Field(
        default=(),
        description="The names of the overlay files merged into config, for lineage.overrides.",
    )
    name: str | None = Field(default=None, description="The name of the run, which wins.")
    resume: str | None = Field(
        default=None,
        description="The run to continue in place; an empty text names the run of the request.",
    )
    from_step: str | None = Field(default=None, description="First step of a partial run.")
    until_step: str | None = Field(default=None, description="Last step of a partial run.")
    force: bool = Field(default=False, description="Compute a run identical to a completed one.")
    fresh: bool = Field(
        default=False, description="File what a previous attempt left and start over."
    )
    frozen: bool = Field(default=False, description="Require frozen input data references.")
    dry_run: bool = Field(default=False, description="Say what would run, and run nothing.")
    no_display: bool = Field(
        default=False, description="Draw no figure. It changes neither the identity nor the seal."
    )
    phase: str | None = Field(
        default=None, description="The one phase of a staged calibration to run."
    )
    source: str | None = Field(
        default=None,
        description="The file the request was read from, relative to the base when it lies under it.",
    )
    form: RequestForm = Field(
        default="json",
        description="What the request was built from; json and dict write request.json.",
    )

    @field_validator("name")
    @classmethod
    def _name_follows_the_rule(cls, value: str | None) -> str | None:
        """Refuse a run name that breaks the rule of a run name."""
        if value is None:
            return None
        try:
            return check_name(value, what="run")
        except ConfigError as exc:
            raise ValueError(exc.message or str(exc)) from exc

    def overrides(self, changes: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Return what the request changes on top of its document, as ``lineage.overrides`` seals it.

        *changes* is the ``set`` of the request told as dotted paths, a name of a
        target replaced by its path. Without it, the ``set`` is taken as written.
        """
        written = self.set if changes is None else changes
        found: dict[str, Any] = {rewrite_dotted_path(key): value for key, value in written.items()}
        if self.overlays:
            found["overlay"] = list(self.overlays)
        return found


@dataclass(frozen=True, slots=True)
class RunOutcome:
    """What a finished run says, read from its directory.

    ``identical_to`` names the completed run a run gave back instead of computing
    it again, and is ``None`` for a run that computed. ``mesh_summary`` is what the
    mesh step of a run that computed one says of its mesh; no file of the run
    directory holds it, so :meth:`read` leaves it ``None``. ``deliveries`` are the
    ``delivery`` lines the call wrote for the run, empty for a run that delivered
    nothing; :meth:`read` leaves them empty.
    """

    name: str
    run_dir: Path
    sim_id: str | None
    request_id: str | None
    status: str
    identical_to: str | None
    project_root: Path
    mesh_summary: Mapping[str, Any] | None = None
    deliveries: tuple[PublishedLine, ...] = ()

    @classmethod
    def read(
        cls, run_dir: Path, *, project_root: Path, identical_to: str | None = None
    ) -> RunOutcome:
        """Return the outcome of the run in *run_dir*.

        Raises ``FileNotFoundError`` when the directory carries no outcome.
        """
        directory = Path(run_dir)
        outcome = read_outcome(directory)
        if outcome is None:
            raise FileNotFoundError(f"{directory} carries no outcome.")
        return cls(
            name=directory.name,
            run_dir=directory,
            sim_id=outcome.sim_id,
            request_id=outcome.request_id,
            status=effective_status(directory),
            identical_to=identical_to,
            project_root=Path(project_root),
        )


def request_of(
    source: str | os.PathLike[str] | Mapping[str, Any] | HydroModPyConfig,
    *,
    base: str | os.PathLike[str] | None = None,
    overlays: Sequence[str | os.PathLike[str]] = (),
    set: Mapping[str, Any] | None = None,  # noqa: A002 - the name of `--set`
    name: str | None = None,
    resume: str | None = None,
    from_step: str | None = None,
    until_step: str | None = None,
    force: bool = False,
    fresh: bool = False,
    frozen: bool = False,
    dry_run: bool = False,
    no_display: bool = False,
    headless: bool = False,
    phase: str | None = None,
) -> RunRequest:
    """Return the request of a run of *source*, with the options a caller gives.

    *source* is the path of a ``.toml`` file, read once with its chain and its
    *overlays*; the path of a ``.json`` file, a serialized request, whose members
    the options given here add to or win over; a mapping or JSON text, the
    document itself; or a built configuration, written as a file writes it.
    *base* only makes ``source`` relative. ``headless`` is ``no_display``.

    Raises
    ------
    ConfigError
        On a file that is neither ``.toml`` nor ``.json``, on a request JSON that
        is not one, on overlays of anything but a TOML file, on ``base_config`` in
        a document, on a run name that breaks the rule, and on a combination of
        options the workflow of the document refuses.
    """
    options: dict[str, Any] = {
        "name": name,
        "resume": resume,
        "from_step": from_step,
        "until_step": until_step,
        "phase": phase,
        "force": force,
        "fresh": fresh,
        "frozen": frozen,
        "dry_run": dry_run,
        "no_display": no_display or headless,
    }
    changes = dict(set or {})
    names = tuple(Path(item).name for item in overlays)
    if isinstance(source, HydroModPyConfig):
        _refuse_overlays(overlays, "a configuration object")
        built = _request(
            config=_document_of(source), form="object", source=None, changes=changes, **options
        )
    elif isinstance(source, Mapping):
        _refuse_overlays(overlays, "a document given as a mapping")
        document = copy.deepcopy(dict(source))
        refuse_base_config(document)
        built = _request(config=document, form="dict", source=None, changes=changes, **options)
    elif isinstance(source, str) and is_json_text(source):
        _refuse_overlays(overlays, "a document given as JSON text")
        document = json_object(source, where="A JSON configuration")
        refuse_base_config(document)
        built = _request(config=document, form="json", source=None, changes=changes, **options)
    elif isinstance(source, (str, os.PathLike)):
        path = Path(source).expanduser().resolve()
        if path.suffix != REQUEST_SUFFIX:
            refuse_file_type(path)
        named = _relative_to(path, base)
        if path.suffix == REQUEST_SUFFIX:
            _refuse_overlays(overlays, "a run request in JSON")
            built = _with_options(read_request(path), changes, options, source=named)
        else:
            document = read_document(path, overlays=overlays, root=ROOT_CONFIG)
            built = _request(
                config=document,
                form="toml",
                source=named,
                changes=changes,
                overlays=names,
                **options,
            )
    else:
        raise TypeError(
            "A run request is built from a TOML or JSON path, a mapping, JSON text or a "
            f"HydroModPyConfig, not {type(source).__name__}."
        )
    if not built.dry_run:
        _refuse_combinations(built)
    return built


def read_request(path: str | os.PathLike[str]) -> RunRequest:
    """Return the run request the JSON file *path* holds, or refuse it with what to write."""
    target = Path(path).expanduser().resolve()
    payload = json_object(target.read_bytes(), where=str(target))
    if "schema" not in payload:
        raise ConfigError(
            f"{target} names no schema. A run request is a JSON object "
            f'{{"schema": "{REQUEST_SCHEMA}", "config": {{...}}}}: put the configuration '
            "document under config."
        )
    if payload["schema"] != REQUEST_SCHEMA:
        raise ConfigError(
            f"{target}: schema {payload['schema']!r} is not a run request this version "
            f"reads. It reads {REQUEST_SCHEMA!r}."
        )
    config = payload.get("config")
    if isinstance(config, Mapping):
        refuse_base_config(config)
    try:
        return RunRequest.model_validate(payload)
    except ValidationError as exc:
        raise _refusal_of(exc, target) from exc


def write_request_file(run_dir: Path, request: RunRequest) -> Path | None:
    """Write *request* as ``request.json`` of *run_dir* when its form asks for it.

    A request given as JSON or as a mapping is written whole, by one rename, and
    never redacted. A TOML file or a built configuration writes nothing here.
    """
    if request.form not in WRITTEN_FORMS:
        return None
    return write_json_atomic(
        Path(run_dir) / RUN_REQUEST_FILENAME, request.model_dump(mode="json", by_alias=True)
    )


def base_of(
    source: str | os.PathLike[str] | Mapping[str, Any] | HydroModPyConfig,
    base: str | os.PathLike[str] | None = None,
) -> Path:
    """Return the folder the relative paths of *source* are read from.

    A *base* given wins. A configuration object reads from its project root. A
    TOML file reads from the project root above it, else from the folder of the
    root file of its chain, which this reads only outside a project. A request
    in JSON reads from the project root above it, else from its own folder. A
    mapping or JSON text has no folder: it is refused without *base*.
    """
    if base is not None:
        return Path(base).expanduser().resolve()
    if isinstance(source, HydroModPyConfig):
        return Path(source.workspace.project_root)
    if isinstance(source, Mapping) or (isinstance(source, str) and is_json_text(source)):
        raise ConfigError(MEMORY_NEEDS_BASE)
    path = Path(source).expanduser().resolve()
    if path.suffix == TOML_SUFFIX:
        return config_base_dir(path)
    return resolve_project_root(path.parent)


def workflow_of(request: RunRequest) -> WorkflowName:
    """Return the workflow the document of *request* asks for, its changes applied.

    The declared ``workflow.mode`` wins, else the sections say it.
    """
    document = _with_changes(request.config, request.set)
    declared = extract_workflow_field(document)
    if declared is not None:
        return check_workflow_name(declared)
    return workflow_of_sections(document)


def _request(
    *,
    config: dict[str, Any],
    form: RequestForm,
    source: str | None,
    changes: dict[str, Any],
    overlays: tuple[str, ...] = (),
    **options: Any,
) -> RunRequest:
    try:
        return RunRequest(
            config=config,
            set=changes,
            overlays=overlays,
            form=form,
            source=source,
            **{key: value for key, value in options.items() if value is not None},
        )
    except ValidationError as exc:
        raise _refusal_of(exc, None) from exc


def _with_options(
    request: RunRequest, changes: dict[str, Any], options: Mapping[str, Any], *, source: str | None
) -> RunRequest:
    """Add what a caller gives to a request read from JSON; the caller wins."""
    update: dict[str, Any] = {
        key: value for key, value in options.items() if value not in (None, False)
    }
    if changes:
        update["set"] = {**request.set, **changes}
    if source is not None and request.source is None:
        update["source"] = source
    try:
        return RunRequest.model_validate({**request.model_dump(by_alias=True), **update})
    except ValidationError as exc:
        raise _refusal_of(exc, None) from exc


def _refusal_of(exc: ValidationError, where: Path | None) -> ConfigValidationError:
    """Return a validation error of a request as the refusal a user reads."""
    lines = []
    for error in exc.errors():
        key = ".".join(str(part) for part in error.get("loc", ())) or "<root>"
        if error.get("type") == "extra_forbidden":
            lines.append(
                f"{key} is not a member of a run request. The members are "
                f"{', '.join(sorted(_member_names()))}."
            )
        else:
            lines.append(f"{key}: {error.get('msg')}")
    prefix = f"{where}: " if where is not None else ""
    return ConfigValidationError(f"{prefix}{' '.join(lines)}")


def _member_names() -> list[str]:
    return [field.alias or name for name, field in RunRequest.model_fields.items()]


def _refuse_overlays(overlays: Sequence[Any], what: str) -> None:
    if overlays:
        raise ConfigError(
            f"--overlay merges a TOML file into a TOML file, and {what} carries its whole "
            "document. Merge the overlay into the document first."
        )


def _refuse_combinations(request: RunRequest) -> None:
    """Refuse the options the workflow of *request* cannot take, with the words of ``hmp run``."""
    workflow = workflow_of(request)
    file = Path(request.source).name if request.source else "<file>"
    steps_given = request.from_step is not None or request.until_step is not None
    refusals = (
        (
            request.resume is not None and workflow not in ("simulation", "calibration"),
            "--resume is only supported for the 'simulation' and 'calibration' workflows "
            f"(detected '{workflow}').",
        ),
        (
            bool(request.resume) and workflow == "calibration",
            "A calibration reopens the latest session of the case its file names: "
            f"pass a bare --resume, not --resume {request.resume}.",
        ),
        (
            steps_given and workflow == "calibration",
            "--from / --until are only supported for the 'simulation' workflow "
            "(detected 'calibration'). To run the first steps of this file, for "
            "example to check the soil reservoir alone, add "
            "--set workflow.mode=simulation: "
            f"hmp run {file} --until load_data --set workflow.mode=simulation",
        ),
        (
            steps_given and workflow != "simulation",
            "--from / --until are only supported for the "
            f"'simulation' workflow (detected '{workflow}').",
        ),
        (
            request.force and workflow not in ("simulation", "calibration"),
            "--force is only supported for the 'simulation' and 'calibration' workflows "
            f"(detected '{workflow}'), the two that give back identical completed work "
            "instead of computing it again.",
        ),
    )
    for refused, message in refusals:
        if refused:
            raise ConfigError(message)


def _with_changes(document: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]:
    changed = copy.deepcopy(dict(document))
    for dotted, value in changes.items():
        assign(changed, dotted, value)
    return changed


def _document_of(cfg: HydroModPyConfig) -> dict[str, Any]:
    """Return what a file of *cfg* writes, without the project root, which the base gives."""
    document = written_as_a_file(cfg)
    workspace = document.get("workspace")
    if isinstance(workspace, dict):
        workspace.pop("project_root", None)
        if not workspace:
            del document["workspace"]
    return json.loads(json.dumps(document, default=str))


def _relative_to(path: Path, base: str | os.PathLike[str] | None) -> str:
    if base is not None:
        folder = Path(base).expanduser().resolve()
        if path.is_relative_to(folder):
            return path.relative_to(folder).as_posix()
    return path.as_posix()


__all__ = [
    "REQUEST_SCHEMA",
    "WRITTEN_FORMS",
    "RequestForm",
    "RunOutcome",
    "RunRequest",
    "base_of",
    "read_request",
    "request_of",
    "workflow_of",
    "write_request_file",
]
