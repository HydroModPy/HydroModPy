"""The resolved configuration a run was launched on, written and read back.

The resume checkpoint has always carried the sha256 of this payload. Until
``validate`` wrote it, that digest pointed at nothing a later process held: the
only frozen copy landed in the run directory at step six, so a run that died
building its model left none, and a refused resume could say that the
configuration had changed but not what had changed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from hydromodpy.core.io.canonical_json import dumps as canonical_dumps
from hydromodpy.workflow.internals.manifest import (
    RESOLVED_CONFIG_SCHEMA,
    config_sections_that_moved,
    read_resolved_config,
    resolved_config_path,
    write_resolved_config,
)

PAYLOAD = {
    "flow": {"flow_regime": "steady", "param_list": ["K"]},
    "simulation": {"name": "naizin"},
    "workspace": {"project_root": "/somewhere"},
}


def test_the_document_round_trips_under_the_run_it_belongs_to(tmp_path: Path) -> None:
    """What is written is what is read, and another run reads nothing."""
    written = write_resolved_config(tmp_path, "run_a", PAYLOAD)

    assert written == resolved_config_path(tmp_path, "run_a")
    assert read_resolved_config(tmp_path, "run_a") == PAYLOAD
    assert read_resolved_config(tmp_path, "run_b") is None


def test_the_document_holds_exactly_what_the_checkpoint_digest_signs(tmp_path: Path) -> None:
    """A digest whose document says something else would be worse than none."""
    write_resolved_config(tmp_path, "run_a", PAYLOAD)

    stored = json.loads(resolved_config_path(tmp_path, "run_a").read_text(encoding="utf-8"))

    assert stored["schema"] == RESOLVED_CONFIG_SCHEMA
    assert (
        hashlib.sha256(canonical_dumps(stored["config"]).encode("utf-8")).hexdigest()
        == hashlib.sha256(canonical_dumps(PAYLOAD).encode("utf-8")).hexdigest()
    )


def test_a_document_of_another_schema_reads_as_absent(tmp_path: Path) -> None:
    """A future schema is a clean miss, never a half-understood document."""
    path = resolved_config_path(tmp_path, "run_a")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"schema": "hydromodpy.resolved_config.v99", "config": {}}', encoding="utf-8")

    assert read_resolved_config(tmp_path, "run_a") is None


def test_an_unreadable_document_reads_as_absent(tmp_path: Path) -> None:
    """Truncated JSON sends the caller to the generic refusal, not to a crash."""
    path = resolved_config_path(tmp_path, "run_a")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"schema": "hydro', encoding="utf-8")

    assert read_resolved_config(tmp_path, "run_a") is None


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

    stored = read_resolved_config(tmp_path, "run_a")

    assert config_sections_that_moved(stored, payload) == ()
