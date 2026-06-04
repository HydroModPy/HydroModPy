"""Round-trip and validation tests for the resolved run manifest.

These tests drive the real ``ResolvedRunManifest`` API against synthetic
``PipelineState`` payloads. They assert the disk round-trip identity that
underpins resume (build -> write_atomic -> read -> equal) plus the schema,
run_id, steps, workspace, and config-hash invariants enforced by
``verify_state``.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from pydantic import BaseModel, ConfigDict

from hydromodpy.core.exceptions import ResumeError
from hydromodpy.core.io.canonical_json import dumps as canonical_dumps
from hydromodpy.workflow.internals.manifest import (
    SCHEMA_VERSION,
    ResolvedRunManifest,
)
from hydromodpy.workflow.internals.state import PipelineState


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
    assert written == ResolvedRunManifest.path_for(workspace, "run-42")
    assert written.is_file()

    parsed = ResolvedRunManifest.read(workspace, "run-42")
    # Frozen dataclass equality: every field round-trips byte-for-byte.
    assert parsed == original


def test_write_atomic_path_layout(tmp_path):
    state = _make_state()
    workspace = tmp_path / "ws"
    manifest = ResolvedRunManifest.from_state(state, _steps(), workspace=workspace)
    path = manifest.write_atomic(workspace)

    rel = path.relative_to(workspace)
    assert rel.parts == (".hmp", "checkpoints", "run-42", "resolved_manifest.json")
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
    assert ResolvedRunManifest.read(tmp_path, "nope") is None


def test_read_tolerates_missing_optional_keys(tmp_path):
    """A minimal manifest (only required keys) still parses with defaults."""
    path = ResolvedRunManifest.path_for(tmp_path, "min")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": SCHEMA_VERSION, "run_id": "min"}),
        encoding="utf-8",
    )
    parsed = ResolvedRunManifest.read(tmp_path, "min")
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
    parsed = ResolvedRunManifest.read(workspace, "run-42")
    assert parsed == original
    assert parsed.config_sha256 is None
    assert parsed.config_path is None


# ---------------------------------------------------------------------------
# config payload extraction from non-mapping / model / mapping configs
# ---------------------------------------------------------------------------


from dataclasses import dataclass  # noqa: E402


@dataclass(frozen=True, slots=True)
class _TypedPayload:
    """Stand-in for a typed (non-Mapping) PipelineState payload."""

    config_path: str | None = None
    config: object | None = None
    raw_toml: dict | None = None


class _TinyConfig(BaseModel):
    """Minimal Pydantic config to exercise the model_dump hash path."""

    model_config = ConfigDict(extra="forbid")

    k: float = 1.0
    name: str = "demo"


def test_from_state_typed_payload_reads_attributes():
    """Non-Mapping payload: config_path is read via getattr (line 142)."""
    payload = _TypedPayload(config_path="/typed/cfg.toml", raw_toml={"k": 1})
    state = PipelineState(run_id="typed", step_index=0, step_name="validate", data=payload)
    manifest = ResolvedRunManifest.from_state(state, _steps(), workspace=None)
    assert manifest.config_path == "/typed/cfg.toml"
    assert manifest.config_sha256 is not None


def test_from_state_hashes_pydantic_config_via_model_dump():
    """A BaseModel config is hashed through model_dump (line 153)."""
    cfg = _TinyConfig(k=2.0, name="basin")
    payload = _TypedPayload(config=cfg)
    state = PipelineState(run_id="model", step_index=0, step_name="validate", data=payload)
    manifest = ResolvedRunManifest.from_state(state, _steps(), workspace=None)

    import hashlib

    expected = hashlib.sha256(
        canonical_dumps(cfg.model_dump(mode="json", exclude_none=True)).encode("utf-8")
    ).hexdigest()
    assert manifest.config_sha256 == expected


def test_from_state_hashes_mapping_config_key():
    """A dict under the 'config' key (no raw_toml) is hashed directly (line 155)."""
    payload = {"config": {"k": 5}}
    state = PipelineState(run_id="mapcfg", step_index=0, step_name="validate", data=payload)
    manifest = ResolvedRunManifest.from_state(state, _steps(), workspace=None)

    import hashlib

    expected = hashlib.sha256(canonical_dumps({"k": 5}).encode("utf-8")).hexdigest()
    assert manifest.config_sha256 == expected


def test_pydantic_config_roundtrips_on_disk(tmp_path):
    cfg = _TinyConfig(k=3.0)
    payload = _TypedPayload(config=cfg, config_path="/p.toml")
    state = PipelineState(run_id="model", step_index=1, step_name="resolve", data=payload)
    workspace = tmp_path / "ws"
    original = ResolvedRunManifest.from_state(state, _steps(), workspace=workspace)
    original.write_atomic(workspace)
    parsed = ResolvedRunManifest.read(workspace, "model")
    assert parsed == original


# ---------------------------------------------------------------------------
# verify_state validation / version checks
# ---------------------------------------------------------------------------


def test_verify_state_accepts_matching_state(tmp_path):
    state = _make_state(raw_toml={"k": 1})
    workspace = tmp_path / "ws"
    manifest = ResolvedRunManifest.from_state(state, _steps(), workspace=workspace)
    # Same state, same steps, same workspace: no exception.
    manifest.verify_state(state, _steps(), workspace)


def test_verify_state_rejects_unknown_schema():
    state = _make_state(raw_toml={"k": 1})
    manifest = ResolvedRunManifest.from_state(state, _steps(), workspace=None)
    bad = replace(manifest, schema_version="hydromodpy.resolved_run_manifest.v999")
    with pytest.raises(ResumeError, match="Unsupported run manifest schema"):
        bad.verify_state(state, _steps(), None)


def test_verify_state_rejects_run_id_mismatch():
    state = _make_state(run_id="A", raw_toml={"k": 1})
    manifest = ResolvedRunManifest.from_state(state, _steps(), workspace=None)
    other = _make_state(run_id="B", raw_toml={"k": 1})
    with pytest.raises(ResumeError, match="run_id mismatch"):
        manifest.verify_state(other, _steps(), None)


def test_verify_state_rejects_changed_steps():
    state = _make_state(raw_toml={"k": 1})
    manifest = ResolvedRunManifest.from_state(state, _steps(), workspace=None)
    changed = [_Step("validate"), _Step("resolve")]  # one step dropped
    with pytest.raises(ResumeError, match="Pipeline steps changed"):
        manifest.verify_state(state, changed, None)


def test_verify_state_rejects_workspace_mismatch(tmp_path):
    state = _make_state(raw_toml={"k": 1})
    ws_a = tmp_path / "a"
    manifest = ResolvedRunManifest.from_state(state, _steps(), workspace=ws_a)
    with pytest.raises(ResumeError, match="Workspace mismatch"):
        manifest.verify_state(state, _steps(), tmp_path / "b")


def test_verify_state_ignores_workspace_when_manifest_has_none():
    state = _make_state(raw_toml={"k": 1})
    manifest = ResolvedRunManifest.from_state(state, _steps(), workspace=None)
    assert manifest.workspace is None
    # A current workspace is allowed when the manifest never recorded one.
    manifest.verify_state(state, _steps(), None)


def test_verify_state_rejects_changed_config_hash():
    state = _make_state(raw_toml={"k": 1})
    manifest = ResolvedRunManifest.from_state(state, _steps(), workspace=None)
    mutated = _make_state(raw_toml={"k": 2})
    with pytest.raises(ResumeError, match="Resolved configuration changed"):
        manifest.verify_state(mutated, _steps(), None)


def test_verify_state_skips_hash_when_manifest_hash_none():
    """No recorded hash means no config-change enforcement."""
    state = _make_state(raw_toml=None, config_path=None)
    manifest = ResolvedRunManifest.from_state(state, _steps(), workspace=None)
    assert manifest.config_sha256 is None
    mutated = _make_state(raw_toml={"k": 99}, config_path=None)
    # Should not raise even though the current state now carries a config.
    manifest.verify_state(mutated, _steps(), None)


# ---------------------------------------------------------------------------
# with_state preservation semantics
# ---------------------------------------------------------------------------


def test_with_state_preserves_created_at_and_advances_step():
    original_state = _make_state(step_index=1, step_name="resolve", raw_toml={"k": 1})
    manifest = ResolvedRunManifest.from_state(
        original_state, _steps(), workspace=None, created_at="2019-05-05T00:00:00+00:00"
    )
    advanced_state = _make_state(step_index=2, step_name="setup", raw_toml={"k": 1})
    updated = manifest.with_state(advanced_state, _steps())

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
    updated = manifest.with_state(new_state, _steps())
    assert updated.config_sha256 == manifest.config_sha256
    assert updated.config_path == "/old/path.toml"


def test_with_state_fills_missing_config_provenance():
    """When the original has no hash, with_state adopts the new state's hash."""
    bare_state = _make_state(raw_toml=None, config_path=None)
    manifest = ResolvedRunManifest.from_state(bare_state, _steps(), workspace=None)
    assert manifest.config_sha256 is None

    populated = _make_state(raw_toml={"k": 7}, config_path="/cfg.toml")
    updated = manifest.with_state(populated, _steps())
    assert updated.config_sha256 is not None
    assert updated.config_path == "/cfg.toml"


def test_with_state_roundtrips_after_write(tmp_path):
    """with_state output survives a disk round-trip unchanged."""
    workspace = tmp_path / "ws"
    state1 = _make_state(step_index=1, step_name="resolve", raw_toml={"k": 1})
    manifest = ResolvedRunManifest.from_state(state1, _steps(), workspace=workspace)
    state2 = _make_state(step_index=2, step_name="setup", raw_toml={"k": 1})
    updated = manifest.with_state(state2, _steps())
    # workspace was preserved through with_state.
    assert updated.workspace == str(workspace)

    updated.write_atomic(workspace)
    parsed = ResolvedRunManifest.read(workspace, "run-42")
    assert parsed == updated
