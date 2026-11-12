"""What leaves the tree says where it came from and names no host, user or absolute path."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from hydromodpy.results.publication import (
    PUBLICATION_SCHEMA,
    REDACTED_PATH,
    Publication,
    PublicationSource,
    PublishedLine,
    redact,
)

NOW = datetime(2026, 10, 15, 11, 0, tzinfo=UTC)

_COPY = {
    "kind": "copy",
    "to": "~/livrables/nancon",
    "format": "dir",
    "published_at": NOW,
    "publication_sha256": "ab" * 32,
}
_DELIVERY = {
    "kind": "delivery",
    "published_at": NOW,
    "file": "exports/head_last.tif",
    "destination": "/srv/depot/head_last.tif",
    "state": "delivered",
    "sha256": "cd" * 32,
    "bytes": 2048,
    "attempts": 1,
}


def _copy(**overrides) -> PublishedLine:
    return PublishedLine.model_validate({**_COPY, **overrides})


def _delivery(**overrides) -> PublishedLine:
    return PublishedLine.model_validate({**_DELIVERY, **overrides})


def _publication(**overrides) -> Publication:
    payload = {
        "source": PublicationSource(
            project="nancon", rel_dir="runs/calibration", sim_id="9a4f" * 8
        ),
        "manifest_sha256": "ab" * 32,
        "files": {"README.md": "cd" * 32, "manifest.json": "ab" * 32},
        "label": "calibrated",
        "label_date": date(2026, 10, 15),
        "hydromodpy_version": "2.0.0a5",
        "published_at": NOW,
        "format": "dir",
        "with": ["results"],
    }
    payload.update(overrides)
    return Publication.model_validate(payload)


REFUSED = [
    pytest.param(
        {**_COPY, "to": None, "format": None, "publication_sha256": None},
        "a copy line requires to, format, publication_sha256",
        id="copy without its fields",
    ),
    pytest.param(
        {**_COPY, "state": "delivered"},
        "a copy line carries no state",
        id="copy with a delivery field",
    ),
    pytest.param(
        {**_COPY, "error": "gone"},
        "only a failed delivery line carries error",
        id="copy with an error",
    ),
    pytest.param(
        {
            **_DELIVERY,
            "destination": None,
            "state": None,
            "sha256": None,
            "bytes": None,
            "attempts": None,
        },
        "a delivery line requires destination, state, sha256, bytes, attempts",
        id="delivery without its fields",
    ),
    pytest.param(
        {**_DELIVERY, "to": "/srv/depot/"},
        "a delivery line carries no to",
        id="delivery with a copy field",
    ),
    pytest.param(
        {**_DELIVERY, "published_at": None},
        "published_at",
        id="delivery without an instant",
    ),
    pytest.param(
        {**_DELIVERY, "attempts": 0},
        "a delivered or failed delivery line has attempts = 1 to 3",
        id="delivered without an attempt",
    ),
    pytest.param(
        {**_DELIVERY, "state": "pending", "attempts": 1},
        "a pending delivery line has attempts = 0",
        id="pending with an attempt",
    ),
    pytest.param(
        {**_DELIVERY, "state": "failed"},
        "a failed delivery line carries error",
        id="failed without its reason",
    ),
    pytest.param(
        {**_DELIVERY, "error": "the server refused the file"},
        "only a failed delivery line carries error",
        id="delivered with an error",
    ),
]


@pytest.mark.parametrize(("payload", "phrase"), REFUSED)
def test_a_line_refuses_a_form_that_mixes_the_two_kinds(payload, phrase):
    with pytest.raises(ValidationError, match=re.escape(phrase)):
        PublishedLine.model_validate(payload)


def test_redact_makes_a_path_under_the_project_relative_and_hides_the_others(tmp_path):
    inside = tmp_path / "runs" / "calibration" / "config.toml"
    payload = {
        "config": str(inside),
        "binary": "/home/bb/.cache/hydromodpy/bin/mf6",
        "note": f"solved with {inside} on /opt/mf6/bin/mf6",
        "paths": [str(tmp_path / "data"), "/var/tmp/x"],
        "windows": "C:\\Users\\bb\\hydromodpy\\mf6.exe",
    }
    redacted = redact(payload, project_root=tmp_path)

    assert redacted["config"] == "runs/calibration/config.toml"
    assert redacted["binary"] == REDACTED_PATH
    assert redacted["note"] == f"solved with runs/calibration/config.toml on {REDACTED_PATH}"
    assert redacted["paths"] == ["data", REDACTED_PATH]
    assert redacted["windows"] == REDACTED_PATH


def test_redact_still_hides_an_absolute_path_after_a_space_or_a_quote(tmp_path):
    redacted = redact(
        {"text": "see /etc/hosts and '/var/log/x' or C:/Users/me/x"}, project_root=tmp_path
    )
    assert redacted["text"] == f"see {REDACTED_PATH} and '{REDACTED_PATH}' or {REDACTED_PATH}"


def test_the_models_refuse_what_they_do_not_know():
    with pytest.raises(ValidationError, match=PUBLICATION_SCHEMA):
        _publication(schema="other")
    with pytest.raises(ValidationError, match="format"):
        _publication(format="zip")
    with pytest.raises(ValidationError, match="publication_sha256"):
        _copy(publication_sha256="short")
    with pytest.raises(ValidationError, match="host"):
        Publication.model_validate({**_publication().model_dump(by_alias=True), "host": "node12"})


def test_a_project_copy_lists_members_and_only_it_does():
    member = {
        "name": "calibration",
        "rel_dir": "runs/calibration",
        "manifest_sha256": "ab" * 32,
        "publication_sha256": "cd" * 32,
    }
    source = PublicationSource(project="nancon", rel_dir=".")
    project = _publication(
        kind="project", source=source, manifest_sha256=None, files={}, members=[member]
    )
    assert project.members[0].name == "calibration"
    assert _publication().kind == "run"
    with pytest.raises(ValidationError, match="only a project copy lists members"):
        _publication(members=[member])
    with pytest.raises(ValidationError, match="a project copy has source.rel_dir '.'"):
        _publication(kind="project", members=[member])
    with pytest.raises(ValidationError, match="each member once"):
        _publication(kind="project", source=source, members=[member, member])
    with pytest.raises(ValidationError, match="not an entry name"):
        _publication(kind="project", source=source, members=[{**member, "name": "a/b"}])
