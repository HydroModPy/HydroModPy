"""What leaves the tree says where it came from and names no host, user or absolute path."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from hydromodpy.results.publication import (
    PUBLICATION_SCHEMA,
    REDACTED_PATH,
    Publication,
    PublicationSource,
    PublishedLine,
    append_published,
    read_publication,
    read_published,
    redact,
    write_publication,
)

NOW = datetime(2026, 10, 15, 11, 0, tzinfo=UTC)


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
    first = PublishedLine(
        to="~/livrables/nancon", format="dir", published_at=NOW, publication_sha256="ab" * 32
    )
    second = PublishedLine(
        to="archive.tar", format="tar", published_at=NOW, publication_sha256="cd" * 32
    )
    append_published(tmp_path, first)
    append_published(tmp_path, second)

    assert read_published(tmp_path) == [first, second]
    assert (tmp_path / "published.jsonl").read_text(encoding="utf-8").count("\n") == 2


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
        PublishedLine(to="x", format="dir", published_at=NOW, publication_sha256="short")
    with pytest.raises(ValidationError, match="host"):
        Publication.model_validate({**_publication().model_dump(by_alias=True), "host": "node12"})


def test_a_source_rel_dir_is_a_result_directory_or_the_summary():
    assert PublicationSource(project="p", rel_dir="summary").rel_dir == "summary"
    with pytest.raises(ValidationError, match="not a result directory"):
        PublicationSource(project="p", rel_dir="/home/bb/runs/x")
