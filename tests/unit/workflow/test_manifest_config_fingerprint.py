"""The checkpoint fingerprint follows the resolved config, not the source text.

``hmp run --resume REF`` replays a run from the config frozen in its own run
directory. That file is an expert-profile dump, so its text differs from the
user TOML the run was launched with while resolving to the very same config.
The checkpoint must therefore fingerprint the resolved configuration.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict

from hydromodpy.core.exceptions import ResumeError
from hydromodpy.workflow.internals.manifest import ResolvedRunManifest
from hydromodpy.workflow.internals.state import PipelineState


class _Step:
    def __init__(self, name: str) -> None:
        self.name = name


class _Cfg(BaseModel):
    """Minimal stand-in for the resolved root config."""

    model_config = ConfigDict(extra="forbid")

    k: float = 1.0
    name: str = "demo"


def _steps() -> list[_Step]:
    return [_Step("validate"), _Step("resolve"), _Step("run_solver")]


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

    manifest = ResolvedRunManifest.from_state(launched, _steps(), workspace=None)
    other = ResolvedRunManifest.from_state(frozen, _steps(), workspace=None)

    assert manifest.config_sha256 == other.config_sha256
    manifest.verify_state(frozen, _steps())


def test_changed_resolved_config_still_refuses_the_checkpoint():
    launched = _state(_Cfg(k=2.0), {"flow": {"k": 2.0}})
    edited = _state(_Cfg(k=9.0), {"flow": {"k": 2.0}})

    manifest = ResolvedRunManifest.from_state(launched, _steps(), workspace=None)
    with pytest.raises(ResumeError, match="Resolved configuration changed"):
        manifest.verify_state(edited, _steps())


def test_raw_toml_is_the_fallback_when_no_config_model_is_carried():
    state = PipelineState(
        run_id="run-42",
        step_index=0,
        step_name="validate",
        data={"raw_toml": {"flow": {"k": 1.0}}},
    )
    manifest = ResolvedRunManifest.from_state(state, _steps(), workspace=None)
    assert manifest.config_sha256 is not None
    manifest.verify_state(state, _steps())
