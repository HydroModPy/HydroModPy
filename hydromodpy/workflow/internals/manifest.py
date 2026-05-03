"""Resolved run manifest used to validate pipeline resume."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from hydromodpy.core.exceptions import ResumeError
from hydromodpy.core.io.canonical_json import dumps as canonical_dumps
from hydromodpy.workflow.internals.state import PipelineState

SCHEMA_VERSION = "hydromodpy.resolved_run_manifest.v1"


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
            config_path=_string_or_none(_state_get(state, "config_path")),
            workspace=_string_or_none(workspace),
            steps=tuple(_step_name(step) for step in steps),
            step_index=int(state.step_index),
            step_name=str(state.step_name),
            created_at=created_at or now,
            updated_at=now,
        )

    @classmethod
    def read(cls, workspace: Path, run_id: str) -> ResolvedRunManifest | None:
        path = cls.path_for(workspace, run_id)
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
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
    def path_for(workspace: Path, run_id: str) -> Path:
        return Path(workspace) / ".hmp" / "checkpoints" / str(run_id) / "resolved_manifest.json"

    def write_atomic(self, workspace: Path) -> Path:
        path = self.path_for(workspace, self.run_id)
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
        workspace: Path | None,
    ) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ResumeError(f"Unsupported run manifest schema: {self.schema_version!r}")
        if self.run_id != state.run_id:
            raise ResumeError(
                f"Resume run_id mismatch: manifest={self.run_id!r}, state={state.run_id!r}"
            )
        current_steps = tuple(_step_name(step) for step in steps)
        if self.steps != current_steps:
            raise ResumeError("Pipeline steps changed since the checkpoint was written")
        current_workspace = _string_or_none(workspace)
        if self.workspace is not None and current_workspace != self.workspace:
            raise ResumeError(
                f"Workspace mismatch: manifest={self.workspace!r}, current={current_workspace!r}"
            )
        config_payload = _state_config_payload(state)
        if config_payload and self.config_sha256 is not None:
            current_hash = _sha256_payload(config_payload)
            if current_hash != self.config_sha256:
                raise ResumeError("Resolved configuration changed since the checkpoint was written")

    def with_state(self, state: PipelineState, steps: Sequence[object]) -> ResolvedRunManifest:
        current = self.from_state(
            state,
            steps,
            Path(self.workspace) if self.workspace is not None else None,
            created_at=self.created_at,
        )
        return replace(
            current,
            config_sha256=self.config_sha256 or current.config_sha256,
            config_path=self.config_path or current.config_path,
        )


def _step_name(step: object) -> str:
    return str(getattr(step, "name", step.__class__.__name__))


def _state_get(state: PipelineState, key: str) -> Any:
    if isinstance(state.data, Mapping):
        return state.data.get(key)
    return getattr(state.data, key, None)


def _state_config_payload(state: PipelineState) -> Any:
    raw_toml = _state_get(state, "raw_toml")
    if raw_toml:
        return _jsonable(raw_toml)
    config = _state_get(state, "config")
    if config is None:
        config = _state_get(state, "cfg")
    if isinstance(config, BaseModel):
        return _jsonable(config.model_dump(mode="json", by_alias=True, exclude_none=True))
    if isinstance(config, Mapping):
        return _jsonable(config)
    return None


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _jsonable(value.model_dump(mode="json", by_alias=True, exclude_none=True))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(sub) for key, sub in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(sub) for sub in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _sha256_payload(payload: Any) -> str:
    return hashlib.sha256(canonical_dumps(_jsonable(payload)).encode("utf-8")).hexdigest()


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


__all__ = ["ResolvedRunManifest", "SCHEMA_VERSION"]
