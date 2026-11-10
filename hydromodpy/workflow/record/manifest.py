"""Resolved run manifest used to validate pipeline resume, and the config it signs.

The manifest carries the sha256 of the resolved configuration, and until now
that number pointed at nothing: the only frozen copy of the configuration is
written into the run directory by ``prepare_solver``, step six, so a run that
died while building its model left no resolved configuration anywhere, and a
resume refused with "the configuration changed" without being able to say what.

``validate`` writes the payload that digest is taken over, beside the
manifest under ``<run>/.hmp/checkpoints/``, and declares it. The refusal names
the sections that moved.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from hydromodpy.core.exceptions import ResumeError
from hydromodpy.core.io.canonical_json import dumps as canonical_dumps
from hydromodpy.core.io.document_version import TRANSIENT_REMEDY, check_document, check_exact
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.layout import (
    INTERNAL_DIRNAME,
    PER_RUN_CONFIG_KEYS,
    RUN_INTERNAL_CHECKPOINTS_DIRNAME,
)
from hydromodpy.workflow.state import PipelineState
from hydromodpy.workflow.step import step_name

logger = get_logger(__name__)

SCHEMA_VERSION = "hydromodpy.resolved_run_manifest.v1"
RESOLVED_MANIFEST_FILENAME = "resolved_manifest.json"
RESOLVED_CONFIG_FILENAME = "resolved_config.json"
RESOLVED_CONFIG_SCHEMA = "hydromodpy.resolved_config.v1"


def _checkpoints_dir(run_dir: Path) -> Path:
    """Return ``<run>/.hmp/checkpoints``, the attempt state the documents live in."""
    return Path(run_dir) / INTERNAL_DIRNAME / RUN_INTERNAL_CHECKPOINTS_DIRNAME


@dataclass(frozen=True, slots=True)
class ResolvedRunManifest:
    """Small JSON contract for one resolved pipeline run."""

    schema_version: str
    run_id: str
    config_sha256: str | None
    config_path: str | None
    workspace: str | None
    steps: tuple[str, ...]
    step_index: int
    step_name: str
    created_at: str
    updated_at: str

    @classmethod
    def from_state(
        cls,
        state: PipelineState,
        steps: Sequence[object],
        workspace: Path | None,
        *,
        created_at: str | None = None,
    ) -> ResolvedRunManifest:
        now = datetime.now(UTC).isoformat()
        config_payload = _state_config_payload(state)
        return cls(
            schema_version=SCHEMA_VERSION,
            run_id=state.run_id,
            config_sha256=_sha256_payload(config_payload) if config_payload else None,
            config_path=_string_or_none(state.get("config_path")),
            workspace=_string_or_none(workspace),
            steps=tuple(step_name(step) for step in steps),
            step_index=int(state.step_index),
            step_name=str(state.step_name),
            created_at=created_at or now,
            updated_at=now,
        )

    @classmethod
    def read(cls, run_dir: Path) -> ResolvedRunManifest | None:
        path = cls.path_for(run_dir)
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        check_document(
            payload, SCHEMA_VERSION, document=path, remedy=TRANSIENT_REMEDY, key="schema_version"
        )
        return cls(
            schema_version=str(payload["schema_version"]),
            run_id=str(payload["run_id"]),
            config_sha256=_string_or_none(payload.get("config_sha256")),
            config_path=_string_or_none(payload.get("config_path")),
            workspace=_string_or_none(payload.get("workspace")),
            steps=tuple(str(item) for item in payload.get("steps", ())),
            step_index=int(payload.get("step_index", -1)),
            step_name=str(payload.get("step_name", "")),
            created_at=str(payload.get("created_at", "")),
            updated_at=str(payload.get("updated_at", "")),
        )

    @staticmethod
    def path_for(run_dir: Path) -> Path:
        return _checkpoints_dir(run_dir) / RESOLVED_MANIFEST_FILENAME

    def write_atomic(self, run_dir: Path) -> Path:
        path = self.path_for(run_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(asdict(self), indent=2, sort_keys=True, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
        return path

    def verify_state(
        self,
        state: PipelineState,
        steps: Sequence[object],
        *,
        run_dir: Path | None = None,
    ) -> None:
        """Raise :class:`ResumeError` when the checkpoint cannot drive this run.

        The step sequences must agree on their common prefix; a shorter one is
        a partial execution (``--until``), not a divergence. The recorded
        ``workspace`` is provenance only: the manifest is read from inside the
        run it belongs to, so a project that was moved or copied still
        resumes. ``run_dir`` names where to look for the resolved
        configuration this manifest signs, so the refusal can say which
        sections moved instead of only that something did.
        """
        check_exact(
            self.schema_version,
            SCHEMA_VERSION,
            document=self.path_for(run_dir) if run_dir is not None else "resolved run manifest",
            key="schema_version",
            remedy=TRANSIENT_REMEDY,
        )
        if self.run_id != state.run_id:
            raise ResumeError(
                f"Resume run_id mismatch: manifest={self.run_id!r}, state={state.run_id!r}"
            )
        current_steps = tuple(step_name(step) for step in steps)
        divergence = _step_divergence(self.steps, current_steps)
        if divergence is not None:
            raise ResumeError(
                f"Pipeline steps changed since the checkpoint was written ({divergence})"
            )
        config_payload = _state_config_payload(state)
        if config_payload and self.config_sha256 is not None:
            current_hash = _sha256_payload(config_payload)
            stored = read_resolved_config(run_dir) if run_dir is not None else None
            if current_hash != self.config_sha256 and not self._signs_the_same_config(
                stored, config_payload
            ):
                moved = config_sections_that_moved(stored, config_payload)
                detail = f" ({', '.join(moved)})" if moved else ""
                raise ResumeError(
                    f"Resolved configuration changed since the checkpoint was written{detail}"
                )

    def _signs_the_same_config(self, stored: Any, current: Any) -> bool:
        """Return whether a checkpoint of an earlier version signs *current*.

        The digest covers the dump of the model of the version that wrote the
        checkpoint. A key removed from the schema since, or a field added with
        its default, changes the digest of the same configuration. The stored
        payload is checked against the digest first, then both payloads are
        migrated and dumped by this version's model and compared.
        """
        if stored is None or _sha256_payload(stored) != self.config_sha256:
            return False
        before, after = _current_dump(stored), _current_dump(current)
        if before is None or after is None or _sha256_payload(before) != _sha256_payload(after):
            return False
        logger.info(
            "resume.checkpoint_config_migrated run=%s: the checkpoint was written by an "
            "earlier schema and signs the same configuration",
            self.run_id,
        )
        return True

    def with_state(
        self,
        state: PipelineState,
        steps: Sequence[object],
        workspace: Path | None,
    ) -> ResolvedRunManifest:
        """Return this manifest advanced to ``state``, keeping its provenance."""
        current = self.from_state(state, steps, workspace, created_at=self.created_at)
        return replace(
            current,
            config_sha256=self.config_sha256 or current.config_sha256,
            config_path=self.config_path or current.config_path,
        )


def resolved_config_path(run_dir: Path) -> Path:
    """Return where a run keeps the resolved configuration it was launched on."""
    return _checkpoints_dir(run_dir) / RESOLVED_CONFIG_FILENAME


def state_config_payload(state: PipelineState) -> Any:
    """Return the resolved-configuration payload the checkpoint is signed over."""
    return _state_config_payload(state)


def write_resolved_config(run_dir: Path, run_id: str, payload: Any) -> Path | None:
    """Write the resolved configuration of a run, atomically, best-effort.

    A configuration that cannot be written is still a usable configuration for
    the process holding it; what is lost is the ability of a later process to
    read it back, which is exactly what the declaration says when it comes back
    empty.
    """
    path = resolved_config_path(run_dir)
    document = {"schema": RESOLVED_CONFIG_SCHEMA, "config": _json_ready(payload)}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(canonical_dumps(document) + "\n", encoding="utf-8")
        tmp.replace(path)
    except (OSError, TypeError, ValueError) as exc:
        logger.warning("validate.resolved_config_write_failed run=%s err=%s", run_id, exc)
        return None
    return path


def read_resolved_config(run_dir: Path) -> Any | None:
    """Return the resolved configuration a run was launched on, or None."""
    path = resolved_config_path(run_dir)
    if not path.is_file():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("validate.resolved_config_unreadable path=%s err=%s", path, exc)
        return None
    check_document(document, RESOLVED_CONFIG_SCHEMA, document=path, remedy=TRANSIENT_REMEDY)
    return document.get("config")


def config_sections_that_moved(before: Any, after: Any) -> tuple[str, ...]:
    """Return the top-level configuration sections that differ between two payloads.

    Top level only: a resume refusal has to be readable, and ``[flow]`` is
    enough to send a reader to the right place. Naming the leaf would mean
    walking a structure whose shape is the config schema's business.

    Sections are compared on their canonical rendering, not as Python objects:
    a configuration holding a NaN is equal to itself on disk and unequal to
    itself in memory, and a refusal that named a section nobody touched would
    send its reader to the wrong file.
    """
    if not isinstance(before, Mapping) or not isinstance(after, Mapping):
        return ()
    old, new = _json_ready(before), _json_ready(after)
    return tuple(
        sorted(
            key
            for key in old.keys() | new.keys()
            if canonical_dumps(old.get(key)) != canonical_dumps(new.get(key))
        )
    )


def config_sections_moved_since(run_dir: Path, config: BaseModel) -> tuple[str, ...]:
    """Return the sections of *config* that differ from the one *run_dir* was launched on.

    Both sides are dumped by this version's model, without the keys that only
    observe the run, so a key added with its default since names nothing. A run
    that kept no resolved configuration gives an empty tuple.
    """
    stored = read_resolved_config(run_dir)
    if stored is None:
        return ()
    current = _strip_observability_keys(config.model_dump(mode="json", exclude_none=True))
    before = _current_dump(stored)
    return config_sections_that_moved(stored if before is None else before, current)


def _step_divergence(recorded: Sequence[str], current: Sequence[str]) -> str | None:
    """Return why two step sequences diverge, or None when one is the other's prefix.

    A run stopped early by ``--until`` records fewer steps than the canonical
    pipeline. That is a partial execution, not a pipeline change, so only the
    common prefix has to match.
    """
    for index in range(min(len(recorded), len(current))):
        if recorded[index] != current[index]:
            return f"step {index}: checkpoint={recorded[index]!r}, current={current[index]!r}"
    return None


def _strip_observability_keys(payload: Any) -> Any:
    """Drop config keys that never change what the run computes.

    ``workflow.profile`` only observes the run. ``PER_RUN_CONFIG_KEYS`` names
    the project root, filled from where the project sits on disk: a project
    moved or copied elsewhere resumes the same run. ``simulation.name`` is the
    directory of the run, which its frozen file writes and ``--case`` may have
    replaced in the first launch. None may invalidate an existing checkpoint.
    """
    if not isinstance(payload, Mapping):
        return payload
    dropped = {("workflow", "profile"), ("simulation", "name"), *PER_RUN_CONFIG_KEYS}
    out = dict(payload)
    for section, key in dropped:
        block = out.get(section)
        if isinstance(block, Mapping) and key in block:
            out[section] = {k: v for k, v in block.items() if k != key}
    return out


def _state_config_payload(state: PipelineState) -> Any:
    """Return the payload the checkpoint fingerprint is computed on.

    The resolved configuration comes first: it is the only representation two
    launches of the same run share, whatever their source text. A run resumed
    from the config frozen in its own run directory therefore fingerprints
    exactly like its original launch from the user TOML. ``raw_toml`` is the
    fallback for states carrying no config model.

    The key is ``cfg``, and it used to be looked up under ``config`` first. No
    step ever wrote that name - it came from ``ValidatedState.config``, a field
    of the payload class chain that nothing built - so the first lookup always
    missed and the fallback always fired.
    """
    config = state.get("cfg")
    if isinstance(config, BaseModel):
        return _strip_observability_keys(config.model_dump(mode="json", exclude_none=True))
    if isinstance(config, Mapping):
        return _strip_observability_keys(config)
    raw_toml = state.get("raw_toml")
    if raw_toml:
        return _strip_observability_keys(raw_toml)
    return None


def _current_dump(payload: Any) -> Any | None:
    """Return *payload* as this version's model dumps it, or None when it does not load."""
    from hydromodpy.config import HydroModPyConfig

    if not isinstance(payload, Mapping):
        return None
    try:
        cfg = HydroModPyConfig.model_validate(payload)
    except ValueError:
        # A payload this version refuses signs nothing it can compare: the
        # caller keeps the refusal, which names the sections that moved.
        return None
    return _strip_observability_keys(cfg.model_dump(mode="json", exclude_none=True))


def _json_ready(value: Any) -> Any:
    """Render TOML date/time scalars as ISO strings so the payload hashes.

    ``tomllib`` returns real ``date`` / ``datetime`` / ``time`` objects for
    unquoted TOML literals, which JSON cannot serialize.
    """
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return value


def _sha256_payload(payload: Any) -> str:
    return hashlib.sha256(canonical_dumps(_json_ready(payload)).encode("utf-8")).hexdigest()


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


__all__ = [
    "RESOLVED_CONFIG_FILENAME",
    "RESOLVED_CONFIG_SCHEMA",
    "RESOLVED_MANIFEST_FILENAME",
    "SCHEMA_VERSION",
    "ResolvedRunManifest",
    "config_sections_moved_since",
    "config_sections_that_moved",
    "read_resolved_config",
    "resolved_config_path",
    "state_config_payload",
    "write_resolved_config",
]
