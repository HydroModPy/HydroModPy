"""The manifest a run writes at each step, and the resolved config document beside it.

The manifest fingerprints the config (sha256), the run id and the step names. A resume
checks it and refuses when any of them moved. The document stores the resolved config.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import ResumeError, SchemaVersionMismatchError
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


class Step:
    def __init__(self, name: str) -> None:
        self.name = name


def steps(*names: str) -> list[Step]:
    return [Step(name) for name in names or ("validate", "resolve", "setup")]


def state_of(
    run_id: str = "run-42", *, raw_toml: dict | None = None, cfg: dict | None = None
) -> PipelineState:
    data: dict = {"config_path": "/cfg/project.toml"}
    if raw_toml is not None:
        data["raw_toml"] = raw_toml
    if cfg is not None:
        data["cfg"] = cfg
    return PipelineState(run_id=run_id, step_index=2, step_name="setup", data=data)


def sha(document: dict) -> str:
    return hashlib.sha256(canonical_dumps(document).encode("utf-8")).hexdigest()


def test_mapping_config_is_hashed_as_it_stands() -> None:
    # A plain dict under cfg is hashed whole, with no raw_toml fallback.
    manifest = ResolvedRunManifest.from_state(state_of(cfg={"k": 5}), steps(), workspace=None)
    assert manifest.config_sha256 == sha({"k": 5})


def test_unknown_schema_is_refused() -> None:
    state = state_of(raw_toml={"k": 1})
    manifest = ResolvedRunManifest.from_state(state, steps(), workspace=None)
    bad = replace(manifest, schema_version="hydromodpy.resolved_run_manifest.v999")
    with pytest.raises(SchemaVersionMismatchError, match="resolved_run_manifest.v999"):
        bad.verify_state(state, steps())


CHECKPOINTS_THAT_RESUME = [
    # A checkpoint written by --until records a prefix of the steps, not a divergence.
    pytest.param(steps("validate", "resolve"), None, id="truncated steps"),
    # The recorded workspace is provenance: a copied project still resumes.
    pytest.param(steps(), Path("/old/project"), id="moved project"),
]


@pytest.mark.parametrize(("stored_steps", "workspace"), CHECKPOINTS_THAT_RESUME)
def test_checkpoints_that_resume(stored_steps, workspace) -> None:
    state = state_of(raw_toml={"k": 1})
    manifest = ResolvedRunManifest.from_state(state, stored_steps, workspace=workspace)
    manifest.verify_state(state, steps())


MODE_A = {"workflow": {"mode": "simulation", "profile": True}}
MODE_B = {"workflow": {"mode": "overview", "profile": True}}

REFUSED_RESUMES = [
    pytest.param(
        state_of("A", raw_toml={"k": 1}),
        state_of("B", raw_toml={"k": 1}),
        steps(),
        "run_id mismatch",
        id="other run id",
    ),
    pytest.param(
        state_of(raw_toml={"k": 1}),
        state_of(raw_toml={"k": 1}),
        steps("validate", "transform", "setup"),
        "Pipeline steps changed",
        id="reordered steps",
    ),
    pytest.param(
        state_of(raw_toml=MODE_A),
        state_of(raw_toml=MODE_B),
        steps(),
        "Resolved configuration changed",
        id="workflow mode changed",
    ),
]


@pytest.mark.parametrize(("stored", "checked", "checked_steps", "match"), REFUSED_RESUMES)
def test_refused_resumes(stored, checked, checked_steps, match) -> None:
    manifest = ResolvedRunManifest.from_state(stored, steps(), workspace=None)
    with pytest.raises(ResumeError, match=match):
        manifest.verify_state(checked, checked_steps)


# The resume checkpoint carries the sha256 of this payload, so a refused resume can name
# the section that changed.
PAYLOAD = {
    "flow": {"flow_regime": "steady", "param_list": ["K"]},
    "simulation": {"name": "naizin"},
    "workspace": {"project_root": "/somewhere"},
}


def test_document_round_trip(tmp_path: Path) -> None:
    # What is written is what is read, and another run reads nothing.
    written = write_resolved_config(tmp_path, "run_a", PAYLOAD)

    assert written == resolved_config_path(tmp_path)
    assert read_resolved_config(tmp_path) == PAYLOAD
    assert read_resolved_config(tmp_path / "other_run") is None


def test_document_holds_what_the_digest_signs(tmp_path: Path) -> None:
    write_resolved_config(tmp_path, "run_a", PAYLOAD)

    stored = json.loads(resolved_config_path(tmp_path).read_text(encoding="utf-8"))

    assert stored["schema"] == RESOLVED_CONFIG_SCHEMA
    assert sha(stored["config"]) == sha(PAYLOAD)


def test_unreadable_document_reads_as_absent(tmp_path: Path) -> None:
    # Truncated JSON sends the caller to the generic refusal, not to a crash.
    path = resolved_config_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"schema": "hydro', encoding="utf-8")

    assert read_resolved_config(tmp_path) is None


def test_moved_sections_are_named_at_the_top_level() -> None:
    # A resume refusal names the section, not the leaf.
    after = {**PAYLOAD, "flow": {"flow_regime": "transient", "param_list": ["K"]}}

    assert config_sections_that_moved(PAYLOAD, after) == ("flow",)
    assert config_sections_that_moved(PAYLOAD, PAYLOAD) == ()


def test_added_or_removed_section_has_moved() -> None:
    after = {**PAYLOAD, "transport": {"enabled": True}}

    assert config_sections_that_moved(PAYLOAD, after) == ("transport",)
    assert config_sections_that_moved(after, PAYLOAD) == ("transport",)
