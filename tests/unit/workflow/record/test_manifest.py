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
    SCHEMA_VERSION,
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


def test_from_state_captures_run_fields():
    state = _make_state(raw_toml={"flow": {"k": 1.0}})
    manifest = ResolvedRunManifest.from_state(state, _steps(), workspace=None)

    assert manifest.schema_version == SCHEMA_VERSION
    assert manifest.run_id == "run-42"
    assert manifest.step_index == 2
    assert manifest.step_name == "setup"
    assert manifest.steps == ("validate", "resolve", "setup")
    assert manifest.config_path == "/cfg/project.toml"
    # created_at/updated_at are ISO timestamps for the same build moment.
    assert manifest.created_at == manifest.updated_at
    assert manifest.created_at  # non-empty


def test_from_state_hashes_raw_toml_with_canonical_json():
    payload = {"flow": {"k": 1.0}, "domain": {"name": "naizin"}}
    state = _make_state(raw_toml=payload)
    manifest = ResolvedRunManifest.from_state(state, _steps(), workspace=None)

    import hashlib

    expected = hashlib.sha256(canonical_dumps(payload).encode("utf-8")).hexdigest()
    assert manifest.config_sha256 == expected


def test_from_state_hash_is_order_independent():
    """Canonical JSON sorts keys, so dict ordering must not change the hash."""
    a = _make_state(raw_toml={"a": 1, "b": 2})
    b = _make_state(raw_toml={"b": 2, "a": 1})
    ma = ResolvedRunManifest.from_state(a, _steps(), workspace=None)
    mb = ResolvedRunManifest.from_state(b, _steps(), workspace=None)
    assert ma.config_sha256 == mb.config_sha256


def test_from_state_no_config_payload_yields_none_hash():
    state = _make_state(raw_toml=None, config_path=None)
    manifest = ResolvedRunManifest.from_state(state, _steps(), workspace=None)
    assert manifest.config_sha256 is None
    assert manifest.config_path is None


def test_from_state_step_name_falls_back_to_class_name():
    class Plain:
        pass

    state = _make_state(raw_toml={"x": 1})
    manifest = ResolvedRunManifest.from_state(state, [Plain(), _Step("two")], workspace=None)
    assert manifest.steps == ("Plain", "two")


def test_from_state_created_at_override_preserved():
    state = _make_state(raw_toml={"x": 1})
    manifest = ResolvedRunManifest.from_state(
        state, _steps(), workspace=None, created_at="2020-01-01T00:00:00+00:00"
    )
    assert manifest.created_at == "2020-01-01T00:00:00+00:00"
    # updated_at is the build moment, distinct from the forced created_at.
    assert manifest.updated_at != "2020-01-01T00:00:00+00:00"


# ---------------------------------------------------------------------------
# serialize -> read round-trip identity
# ---------------------------------------------------------------------------


def test_disk_roundtrip_identity(tmp_path):
    state = _make_state(raw_toml={"flow": {"k": 3.5}})
    workspace = tmp_path / "ws"
    original = ResolvedRunManifest.from_state(state, _steps(), workspace=workspace)

    written = original.write_atomic(workspace)
    assert written == ResolvedRunManifest.path_for(workspace)
    assert written.is_file()

    parsed = ResolvedRunManifest.read(workspace)
    # Frozen dataclass equality: every field round-trips byte-for-byte.
    assert parsed == original


def test_write_atomic_path_layout(tmp_path):
    state = _make_state()
    workspace = tmp_path / "ws"
    run_dir = workspace / "runs" / "run-42"
    manifest = ResolvedRunManifest.from_state(state, _steps(), workspace=workspace)
    path = manifest.write_atomic(run_dir)

    rel = path.relative_to(run_dir)
    assert rel.parts == (".hmp", "checkpoints", "resolved_manifest.json")
    # No leftover temp file after the atomic replace.
    assert not path.with_suffix(path.suffix + ".tmp").exists()


def test_write_atomic_emits_sorted_json_with_trailing_newline(tmp_path):
    state = _make_state(raw_toml={"x": 1})
    workspace = tmp_path / "ws"
    manifest = ResolvedRunManifest.from_state(state, _steps(), workspace=workspace)
    path = manifest.write_atomic(workspace)

    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    payload = json.loads(text)
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["run_id"] == "run-42"
    assert payload["steps"] == ["validate", "resolve", "setup"]


def test_read_missing_returns_none(tmp_path):
    assert ResolvedRunManifest.read(tmp_path / "nope") is None


def test_read_tolerates_missing_optional_keys(tmp_path):
    """A minimal manifest (only required keys) still parses with defaults."""
    path = ResolvedRunManifest.path_for(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": SCHEMA_VERSION, "run_id": "min"}),
        encoding="utf-8",
    )
    parsed = ResolvedRunManifest.read(tmp_path)
    assert parsed is not None
    assert parsed.run_id == "min"
    assert parsed.config_sha256 is None
    assert parsed.steps == ()
    assert parsed.step_index == -1
    assert parsed.step_name == ""


def test_roundtrip_preserves_none_config_fields(tmp_path):
    state = _make_state(raw_toml=None, config_path=None)
    workspace = tmp_path / "ws"
    original = ResolvedRunManifest.from_state(state, _steps(), workspace=workspace)
    original.write_atomic(workspace)
    parsed = ResolvedRunManifest.read(workspace)
    assert parsed == original
    assert parsed.config_sha256 is None
    assert parsed.config_path is None


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


def test_from_state_reads_the_config_path_off_the_payload():
    state = PipelineState(
        run_id="typed",
        step_index=0,
        step_name="validate",
        data={"config_path": "/typed/cfg.toml", "raw_toml": {"k": 1}},
    )
    manifest = ResolvedRunManifest.from_state(state, _steps(), workspace=None)
    assert manifest.config_path == "/typed/cfg.toml"
    assert manifest.config_sha256 is not None


def test_from_state_hashes_pydantic_config_via_model_dump():
    cfg = _TinyConfig(k=2.0, name="basin")
    state = PipelineState(run_id="model", step_index=0, step_name="validate", data={"cfg": cfg})
    manifest = ResolvedRunManifest.from_state(state, _steps(), workspace=None)

    import hashlib

    expected = hashlib.sha256(
        canonical_dumps(cfg.model_dump(mode="json", exclude_none=True)).encode("utf-8")
    ).hexdigest()
    assert manifest.config_sha256 == expected


def test_from_state_hashes_a_mapping_config():
    """A plain dict under ``cfg`` is hashed as it stands, no raw_toml fallback."""
    state = PipelineState(
        run_id="mapcfg", step_index=0, step_name="validate", data={"cfg": {"k": 5}}
    )
    manifest = ResolvedRunManifest.from_state(state, _steps(), workspace=None)

    import hashlib

    expected = hashlib.sha256(canonical_dumps({"k": 5}).encode("utf-8")).hexdigest()
    assert manifest.config_sha256 == expected


def test_a_config_under_the_key_no_step_writes_is_not_a_config():
    """``config`` is not a payload key, and reading one would be inventing it."""
    state = PipelineState(
        run_id="wrongkey", step_index=0, step_name="validate", data={"config": {"k": 5}}
    )
    manifest = ResolvedRunManifest.from_state(state, _steps(), workspace=None)
    assert manifest.config_sha256 is None


def test_pydantic_config_roundtrips_on_disk(tmp_path):
    cfg = _TinyConfig(k=3.0)
    state = PipelineState(
        run_id="model",
        step_index=1,
        step_name="resolve",
        data={"cfg": cfg, "config_path": "/p.toml"},
    )
    workspace = tmp_path / "ws"
    original = ResolvedRunManifest.from_state(state, _steps(), workspace=workspace)
    original.write_atomic(workspace)
    parsed = ResolvedRunManifest.read(workspace)
    assert parsed == original


# ---------------------------------------------------------------------------
# verify_state validation / version checks
# ---------------------------------------------------------------------------


def test_verify_state_accepts_matching_state(tmp_path):
    state = _make_state(raw_toml={"k": 1})
    workspace = tmp_path / "ws"
    manifest = ResolvedRunManifest.from_state(state, _steps(), workspace=workspace)
    # Same state, same steps, same workspace: no exception.
    manifest.verify_state(state, _steps())


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


def test_verify_state_rejects_changed_config_hash():
    state = _make_state(raw_toml={"k": 1})
    manifest = ResolvedRunManifest.from_state(state, _steps(), workspace=None)
    mutated = _make_state(raw_toml={"k": 2})
    with pytest.raises(ResumeError, match="Resolved configuration changed"):
        manifest.verify_state(mutated, _steps())


def test_workflow_profile_does_not_change_config_hash():
    """Toggling [workflow].profile must not invalidate an existing checkpoint."""
    base = _make_state(raw_toml={"workflow": {"mode": "simulation"}, "flow": {"k": 1.0}})
    profiled = _make_state(
        raw_toml={"workflow": {"mode": "simulation", "profile": True}, "flow": {"k": 1.0}}
    )
    m_base = ResolvedRunManifest.from_state(base, _steps(), workspace=None)
    m_profiled = ResolvedRunManifest.from_state(profiled, _steps(), workspace=None)
    assert m_base.config_sha256 == m_profiled.config_sha256
    # Resume works across the toggle, in both directions.
    m_base.verify_state(profiled, _steps())
    m_profiled.verify_state(base, _steps())


def test_workflow_mode_change_still_invalidates_resume():
    a = _make_state(raw_toml={"workflow": {"mode": "simulation", "profile": True}})
    b = _make_state(raw_toml={"workflow": {"mode": "overview", "profile": True}})
    manifest = ResolvedRunManifest.from_state(a, _steps(), workspace=None)
    with pytest.raises(ResumeError, match="Resolved configuration changed"):
        manifest.verify_state(b, _steps())


def test_verify_state_skips_hash_when_manifest_hash_none():
    """No recorded hash means no config-change enforcement."""
    state = _make_state(raw_toml=None, config_path=None)
    manifest = ResolvedRunManifest.from_state(state, _steps(), workspace=None)
    assert manifest.config_sha256 is None
    mutated = _make_state(raw_toml={"k": 99}, config_path=None)
    # Should not raise even though the current state now carries a config.
    manifest.verify_state(mutated, _steps())


# ---------------------------------------------------------------------------
# with_state preservation semantics
# ---------------------------------------------------------------------------


def test_with_state_preserves_created_at_and_advances_step():
    original_state = _make_state(step_index=1, step_name="resolve", raw_toml={"k": 1})
    manifest = ResolvedRunManifest.from_state(
        original_state, _steps(), workspace=None, created_at="2019-05-05T00:00:00+00:00"
    )
    advanced_state = _make_state(step_index=2, step_name="setup", raw_toml={"k": 1})
    updated = manifest.with_state(advanced_state, _steps(), None)

    assert updated.created_at == "2019-05-05T00:00:00+00:00"
    assert updated.step_index == 2
    assert updated.step_name == "setup"
    # config provenance is preserved from the original manifest.
    assert updated.config_sha256 == manifest.config_sha256


def test_with_state_keeps_existing_config_provenance_over_new():
    original_state = _make_state(raw_toml={"k": 1}, config_path="/old/path.toml")
    manifest = ResolvedRunManifest.from_state(original_state, _steps(), workspace=None)
    assert manifest.config_sha256 is not None

    # New state carries a different config; with_state must keep the original.
    new_state = _make_state(raw_toml={"k": 2}, config_path="/new/path.toml")
    updated = manifest.with_state(new_state, _steps(), None)
    assert updated.config_sha256 == manifest.config_sha256
    assert updated.config_path == "/old/path.toml"


def test_with_state_fills_missing_config_provenance():
    """When the original has no hash, with_state adopts the new state's hash."""
    bare_state = _make_state(raw_toml=None, config_path=None)
    manifest = ResolvedRunManifest.from_state(bare_state, _steps(), workspace=None)
    assert manifest.config_sha256 is None

    populated = _make_state(raw_toml={"k": 7}, config_path="/cfg.toml")
    updated = manifest.with_state(populated, _steps(), None)
    assert updated.config_sha256 is not None
    assert updated.config_path == "/cfg.toml"


def test_with_state_roundtrips_after_write(tmp_path):
    """with_state output survives a disk round-trip unchanged."""
    workspace = tmp_path / "ws"
    state1 = _make_state(step_index=1, step_name="resolve", raw_toml={"k": 1})
    manifest = ResolvedRunManifest.from_state(state1, _steps(), workspace=workspace)
    state2 = _make_state(step_index=2, step_name="setup", raw_toml={"k": 1})
    updated = manifest.with_state(state2, _steps(), workspace)
    # workspace was preserved through with_state.
    assert updated.workspace == str(workspace)

    updated.write_atomic(workspace)
    parsed = ResolvedRunManifest.read(workspace)
    assert parsed == updated


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


def test_same_resolved_config_from_a_different_source_text_resumes():
    launched = _state(_Cfg(k=2.0), {"flow": {"k": 2.0}})
    frozen = _state(_Cfg(k=2.0), {"flow": {"k": 2.0}, "workspace": {"root": "/ws"}})

    manifest = ResolvedRunManifest.from_state(launched, _named_steps(), workspace=None)
    other = ResolvedRunManifest.from_state(frozen, _named_steps(), workspace=None)

    assert manifest.config_sha256 == other.config_sha256
    manifest.verify_state(frozen, _named_steps())


def test_changed_resolved_config_still_refuses_the_checkpoint():
    launched = _state(_Cfg(k=2.0), {"flow": {"k": 2.0}})
    edited = _state(_Cfg(k=9.0), {"flow": {"k": 2.0}})

    manifest = ResolvedRunManifest.from_state(launched, _named_steps(), workspace=None)
    with pytest.raises(ResumeError, match="Resolved configuration changed"):
        manifest.verify_state(edited, _named_steps())


def test_raw_toml_is_the_fallback_when_no_config_model_is_carried():
    state = PipelineState(
        run_id="run-42",
        step_index=0,
        step_name="validate",
        data={"raw_toml": {"flow": {"k": 1.0}}},
    )
    manifest = ResolvedRunManifest.from_state(state, _named_steps(), workspace=None)
    assert manifest.config_sha256 is not None
    manifest.verify_state(state, _named_steps())


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


def test_a_document_of_another_schema_is_refused_by_name(tmp_path: Path) -> None:
    """A future schema is refused with the version read, never half understood."""
    import pytest

    from hydromodpy.core.exceptions import SchemaVersionMismatchError

    path = resolved_config_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"schema": "hydromodpy.resolved_config.v99", "config": {}}', encoding="utf-8")

    with pytest.raises(
        SchemaVersionMismatchError, match="resolved_config.v99.*delete it and run again"
    ):
        read_resolved_config(tmp_path)


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


def test_comparing_against_nothing_names_nothing() -> None:
    """Without a document to compare with, the refusal stays generic."""
    assert config_sections_that_moved(None, PAYLOAD) == ()
    assert config_sections_that_moved(PAYLOAD, None) == ()


def test_a_nan_does_not_make_a_section_look_moved(tmp_path: Path) -> None:
    """``nan != nan`` would have the refusal name a section nobody touched."""
    payload = {"flow": {"threshold": float("nan")}, "simulation": {"name": "n"}}
    write_resolved_config(tmp_path, "run_a", payload)

    stored = read_resolved_config(tmp_path)

    assert config_sections_that_moved(stored, payload) == ()
