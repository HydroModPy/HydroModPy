"""The resolved run manifest and the resolved config document."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from hydromodpy.core.exceptions import ResumeError
from hydromodpy.core.io.canonical_json import dumps as canonical_dumps
from hydromodpy.workflow.record.manifest import (
    RESOLVED_CONFIG_SCHEMA,
    ResolvedRunManifest,
    config_sections_that_moved,
    read_resolved_config,
    resolved_config_path,
    write_resolved_config,
)
from hydromodpy.workflow.state import PipelineState

# --- test_manifest_roundtrip ---
# Round-trip and validation tests for the resolved run manifest.
#
# These tests drive the real ``ResolvedRunManifest`` API against synthetic
# ``PipelineState`` payloads. They assert the disk round-trip identity that
# underpins resume (build -> write_atomic -> read -> equal) plus the schema,
# run_id, steps, workspace, and config-hash invariants enforced by
# ``verify_state``.


class _Step:
    """Minimal stand-in for a pipeline step exposing a ``name``."""

    def __init__(self, name: str) -> None:
        self.name = name


def _make_state(
    run_id: str = "run-42",
    *,
    step_index: int = 2,
    step_name: str = "setup",
    raw_toml: dict | None = None,
    config_path: str | None = "/cfg/project.toml",
) -> PipelineState:
    data: dict = {}
    if raw_toml is not None:
        data["raw_toml"] = raw_toml
    if config_path is not None:
        data["config_path"] = config_path
    return PipelineState(
        run_id=run_id,
        step_index=step_index,
        step_name=step_name,
        data=data,
    )


def _steps() -> list[_Step]:
    return [_Step("validate"), _Step("resolve"), _Step("setup")]


# ---------------------------------------------------------------------------
# build (from_state)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# serialize -> read round-trip identity
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# What the manifest fingerprints, off the payload the pipeline really carries
# ---------------------------------------------------------------------------
#
# These four used to build a frozen dataclass payload and put the config under a
# ``config`` key, because ``_state_config_payload`` had a branch for each. It had
# them for the eleven typed payload classes, whose field was named ``config`` -
# and no step ever built one, nor ever wrote that key. Both branches are gone,
# and these tests now use ``cfg``, which is what ``ValidateStep`` writes.


class _TinyConfig(BaseModel):
    """Minimal Pydantic config to exercise the model_dump hash path."""

    model_config = ConfigDict(extra="forbid")

    k: float = 1.0
    name: str = "demo"


def test_from_state_hashes_a_mapping_config():
    """A plain dict under ``cfg`` is hashed as it stands, no raw_toml fallback."""
    state = PipelineState(
        run_id="mapcfg", step_index=0, step_name="validate", data={"cfg": {"k": 5}}
    )
    manifest = ResolvedRunManifest.from_state(state, _steps(), workspace=None)

    import hashlib

    expected = hashlib.sha256(canonical_dumps({"k": 5}).encode("utf-8")).hexdigest()
    assert manifest.config_sha256 == expected


# ---------------------------------------------------------------------------
# verify_state validation / version checks
# ---------------------------------------------------------------------------


def test_verify_state_rejects_unknown_schema():
    state = _make_state(raw_toml={"k": 1})
    manifest = ResolvedRunManifest.from_state(state, _steps(), workspace=None)
    bad = replace(manifest, schema_version="hydromodpy.resolved_run_manifest.v999")
    from hydromodpy.core.exceptions import SchemaVersionMismatchError

    with pytest.raises(SchemaVersionMismatchError, match="resolved_run_manifest.v999"):
        bad.verify_state(state, _steps())


def test_verify_state_rejects_run_id_mismatch():
    state = _make_state(run_id="A", raw_toml={"k": 1})
    manifest = ResolvedRunManifest.from_state(state, _steps(), workspace=None)
    other = _make_state(run_id="B", raw_toml={"k": 1})
    with pytest.raises(ResumeError, match="run_id mismatch"):
        manifest.verify_state(other, _steps())


def test_verify_state_rejects_reordered_steps():
    state = _make_state(raw_toml={"k": 1})
    manifest = ResolvedRunManifest.from_state(state, _steps(), workspace=None)
    changed = [_Step("validate"), _Step("transform"), _Step("setup")]
    with pytest.raises(ResumeError, match="Pipeline steps changed"):
        manifest.verify_state(state, changed)


def test_verify_state_accepts_truncated_steps():
    """A checkpoint written by ``--until`` records a prefix, not a divergence."""
    state = _make_state(raw_toml={"k": 1})
    partial = ResolvedRunManifest.from_state(state, _steps()[:2], workspace=None)
    partial.verify_state(state, _steps())


def test_verify_state_accepts_a_moved_project(tmp_path):
    """The recorded workspace is provenance: a copied project still resumes."""
    state = _make_state(raw_toml={"k": 1})
    manifest = ResolvedRunManifest.from_state(state, _steps(), workspace=tmp_path / "a")
    manifest.verify_state(state, _steps())


def test_workflow_mode_change_still_invalidates_resume():
    a = _make_state(raw_toml={"workflow": {"mode": "simulation", "profile": True}})
    b = _make_state(raw_toml={"workflow": {"mode": "overview", "profile": True}})
    manifest = ResolvedRunManifest.from_state(a, _steps(), workspace=None)
    with pytest.raises(ResumeError, match="Resolved configuration changed"):
        manifest.verify_state(b, _steps())


# ---------------------------------------------------------------------------
# with_state preservation semantics
# ---------------------------------------------------------------------------


# --- test_manifest_config_fingerprint ---
# The checkpoint fingerprint follows the resolved config, not the source text.
#
# ``hmp run --resume REF`` replays a run from the config frozen in its own run
# directory. That file is an expert-profile dump, so its text differs from the
# user TOML the run was launched with while resolving to the very same config.
# The checkpoint must therefore fingerprint the resolved configuration.


class _NamedStep:
    def __init__(self, name: str) -> None:
        self.name = name


class _Cfg(BaseModel):
    """Minimal stand-in for the resolved root config."""

    model_config = ConfigDict(extra="forbid")

    k: float = 1.0
    name: str = "demo"


def _named_steps() -> list[_NamedStep]:
    return [_NamedStep("validate"), _NamedStep("resolve"), _NamedStep("run_solver")]


def _state(cfg: _Cfg, raw_toml: dict) -> PipelineState:
    return PipelineState(
        run_id="run-42",
        step_index=0,
        step_name="validate",
        data={"cfg": cfg, "raw_toml": raw_toml},
    )


# --- test_resolved_config_document ---
# The resolved configuration a run was launched on, written and read back.
#
# The resume checkpoint has always carried the sha256 of this payload. Until
# ``validate`` wrote it, that digest pointed at nothing a later process held: the
# only frozen copy landed in the run directory at step six, so a run that died
# building its model left none, and a refused resume could say that the
# configuration had changed but not what had changed.

PAYLOAD = {
    "flow": {"flow_regime": "steady", "param_list": ["K"]},
    "simulation": {"name": "naizin"},
    "workspace": {"project_root": "/somewhere"},
}


def test_the_document_round_trips_under_the_run_it_belongs_to(tmp_path: Path) -> None:
    """What is written is what is read, and another run reads nothing."""
    written = write_resolved_config(tmp_path, "run_a", PAYLOAD)

    assert written == resolved_config_path(tmp_path)
    assert read_resolved_config(tmp_path) == PAYLOAD
    assert read_resolved_config(tmp_path / "other_run") is None


def test_the_document_holds_exactly_what_the_checkpoint_digest_signs(tmp_path: Path) -> None:
    """A digest whose document says something else would be worse than none."""
    write_resolved_config(tmp_path, "run_a", PAYLOAD)

    stored = json.loads(resolved_config_path(tmp_path).read_text(encoding="utf-8"))

    assert stored["schema"] == RESOLVED_CONFIG_SCHEMA
    assert (
        hashlib.sha256(canonical_dumps(stored["config"]).encode("utf-8")).hexdigest()
        == hashlib.sha256(canonical_dumps(PAYLOAD).encode("utf-8")).hexdigest()
    )


def test_an_unreadable_document_reads_as_absent(tmp_path: Path) -> None:
    """Truncated JSON sends the caller to the generic refusal, not to a crash."""
    path = resolved_config_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"schema": "hydro', encoding="utf-8")

    assert read_resolved_config(tmp_path) is None


def test_the_sections_that_moved_are_named_at_the_top_level() -> None:
    """A resume refusal has to be readable: the section, not the leaf."""
    after = {**PAYLOAD, "flow": {"flow_regime": "transient", "param_list": ["K"]}}

    assert config_sections_that_moved(PAYLOAD, after) == ("flow",)
    assert config_sections_that_moved(PAYLOAD, PAYLOAD) == ()


def test_a_section_added_or_removed_is_a_section_that_moved() -> None:
    """A configuration that gained a section is not the one the run started on."""
    after = {**PAYLOAD, "transport": {"enabled": True}}

    assert config_sections_that_moved(PAYLOAD, after) == ("transport",)
    assert config_sections_that_moved(after, PAYLOAD) == ("transport",)
