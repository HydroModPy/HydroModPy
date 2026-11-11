"""What leaves the tree says where it came from and names no host, user or absolute path."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from hydromodpy.core.exceptions import SchemaVersionMismatchError
from hydromodpy.results.publication import (
    PUBLICATION_SCHEMA,
    PUBLISHED_REMEDY,
    PUBLISHED_SCHEMA,
    REDACTED_PATH,
    Publication,
    PublicationSource,
    PublishedLine,
    append_published,
    deliveries_of,
    latest_by_pair,
    read_publication,
    read_published,
    redact,
    write_publication,
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


def test_a_publication_round_trips_and_spells_with_as_a_key(tmp_path):
    publication = _publication()
    write_publication(tmp_path, publication)

    assert read_publication(tmp_path) == publication
    text = (tmp_path / "PUBLICATION.json").read_text(encoding="utf-8")
    assert '"schema": "hydromodpy.publication.v1"' in text
    assert '"with": [\n    "results"\n  ]' in text
    assert publication.with_ == ["results"]


def test_the_source_remembers_each_copy_in_published_jsonl(tmp_path):
    assert read_published(tmp_path) == []
    first = _copy()
    second = _copy(to="archive.tar", format="tar", publication_sha256="cd" * 32)
    append_published(tmp_path, first)
    append_published(tmp_path, second)

    assert read_published(tmp_path) == [first, second]
    text = (tmp_path / "published.jsonl").read_text(encoding="utf-8")
    assert text.count("\n") == 2
    assert f'"schema": "{PUBLISHED_SCHEMA}"' in text
    assert '"kind": "copy"' in text


def test_a_delivery_line_records_one_file_and_its_state(tmp_path):
    pending = _delivery(state="pending", attempts=0)
    failed = _delivery(state="failed", attempts=3, error="the server refused the file")

    for line in (pending, failed):
        append_published(tmp_path, line)

    assert read_published(tmp_path) == [pending, failed]
    assert (pending.pair, failed.pair) == (
        ("exports/head_last.tif", "/srv/depot/head_last.tif"),
        ("exports/head_last.tif", "/srv/depot/head_last.tif"),
    )
    assert _copy().pair == ("", "~/livrables/nancon")


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


def test_kind_is_required_and_says_copy_or_delivery():
    with pytest.raises(ValidationError, match="kind"):
        PublishedLine.model_validate({**_DELIVERY, "kind": "published"})
    with pytest.raises(ValidationError, match="kind"):
        PublishedLine.model_validate(
            {key: value for key, value in _DELIVERY.items() if key != "kind"}
        )


def test_a_line_written_by_hydroModPy_2_is_refused_with_its_remedy(tmp_path):
    line = {
        "schema": "hydromodpy.published.v1",
        "to": "~/livrables/nancon",
        "format": "dir",
        "published_at": NOW.isoformat(),
        "publication_sha256": "ab" * 32,
    }
    (tmp_path / "published.jsonl").write_text(json.dumps(line) + "\n", encoding="utf-8")

    with pytest.raises(SchemaVersionMismatchError) as refused:
        read_published(tmp_path)
    assert PUBLISHED_REMEDY in str(refused.value)
    assert "hydromodpy.published.v2" in str(refused.value)


def test_latest_by_pair_keeps_the_last_line_of_each_pair_in_first_order():
    copie = _copy(to="~/livrables/one")
    first = _delivery(state="pending", attempts=0)
    second = _delivery(state="failed", attempts=3, error="timeout")
    third = _delivery(state="delivered", attempts=3, sha256="ef" * 32)
    other = _delivery(file="exports/flow.csv", destination="~/livrables/flow.csv")

    latest = latest_by_pair([copie, first, second, other, third])

    assert list(latest) == [
        copie.pair,
        first.pair,
        other.pair,
    ]
    assert latest[first.pair] == third
    assert latest[copie.pair] == copie
    assert latest[other.pair] == other


def test_deliveries_of_returns_the_latest_delivery_of_each_pair(tmp_path):
    first = _delivery(state="pending", attempts=0)
    second = _delivery(state="delivered", attempts=2)
    other = _delivery(file="exports/flow.csv", destination="/srv/depot/flow.csv")
    for line in (first, other, second, _copy()):
        append_published(tmp_path, line)

    assert deliveries_of(tmp_path) == (second, other)


def test_redact_drops_host_and_user_at_any_depth(tmp_path):
    payload = {
        "host": "node12",
        "platform": {"hostname": "node12", "user": "bb", "user_name": "bb", "cpu": "x86"},
        "runs": [{"username": "bb", "pid": 4}],
    }
    assert redact(payload, project_root=tmp_path) == {
        "platform": {"cpu": "x86"},
        "runs": [{"pid": 4}],
    }


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


def test_redact_leaves_urls_dates_relative_paths_and_numbers_alone(tmp_path):
    payload = {
        "url": "https://hubeau.eaufrance.fr/api/v1/hydrometrie",
        "window": "2016-01-01/2020-12-31",
        "rel": "runs/calibration/config.toml",
        "ratio": "1/3 of the basin",
        "n": 12,
        "flag": True,
        "none": None,
    }
    assert redact(payload, project_root=tmp_path) == payload


def test_redact_without_a_project_root_hides_every_absolute_path(tmp_path):
    payload = {"config": str(tmp_path / "config.toml")}
    assert redact(payload, project_root=None) == {"config": REDACTED_PATH}


def test_the_models_refuse_what_they_do_not_know():
    with pytest.raises(ValidationError, match=PUBLICATION_SCHEMA):
        _publication(schema="other")
    with pytest.raises(ValidationError, match="format"):
        _publication(format="zip")
    with pytest.raises(ValidationError, match="publication_sha256"):
        _copy(publication_sha256="short")
    with pytest.raises(ValidationError, match="host"):
        Publication.model_validate({**_publication().model_dump(by_alias=True), "host": "node12"})


def test_a_source_rel_dir_is_a_result_directory_or_the_summary():
    assert PublicationSource(project="p", rel_dir="summary").rel_dir == "summary"
    with pytest.raises(ValidationError, match="not a result directory"):
        PublicationSource(project="p", rel_dir="/home/bb/runs/x")


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
