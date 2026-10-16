"""What a published copy records, and what the source remembers of it.

Why
---
``hmp publish`` copies a run or a summary out of the tree. The copy must say
where it came from and what it contains, so a reader can verify it and a
source can be matched to it; the source must remember where it went, so a
delete warns. And nothing that leaves the tree may name the machine it was
computed on: the one function :func:`redact` removes the host, the user and
every absolute path from any document on its way out.

Format
------
``PUBLICATION.json`` in the copy is :class:`Publication`: the source by
project, directory and id, the digest of the manifest and of each copied
file, the label of the day, the version, the instant, the format and what
was taken along. ``published.jsonl`` in the source is one
:class:`PublishedLine` per copy, appended.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Final, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.state.paths import SUMMARY_DIRNAME
from hydromodpy.results.rel_dir import checked_rel_dir
from hydromodpy.results.storage.contract import PUBLICATION_FILENAME, RUN_PUBLISHED_FILENAME
from hydromodpy.results.storage.json_io import check_sealed, read_sealed_json, write_json_atomic
from hydromodpy.results.validity_rules import Label

PUBLICATION_SCHEMA: Final[str] = "hydromodpy.publication.v1"
"""Schema id of ``PUBLICATION.json``."""

PUBLISHED_SCHEMA: Final[str] = "hydromodpy.published.v1"
"""Schema id of one line of ``published.jsonl``."""

REDACTED_PATH: Final[str] = "<absolute path>"
"""What an absolute path outside the project becomes."""

REDACTED_KEYS: Final[frozenset[str]] = frozenset(
    {"host", "hostname", "user", "username", "user_name"}
)
"""Keys removed from any published document, at any depth."""

PublicationFormat = Literal["dir", "tar"]
PublicationExtra = Literal["results", "inputs"]


class PublicationSource(HydroModelBase):
    """The run or summary a copy was made from."""

    project: str = Field(description="Project of the source")
    rel_dir: str = Field(
        description="Directory of the source, relative to the project root; summary for a summary"
    )
    sim_id: str | None = Field(default=None, description="Id of the run; none for a summary")

    @field_validator("rel_dir")
    @classmethod
    def _rel_dir(cls, value: str) -> str:
        if value == SUMMARY_DIRNAME:
            return value
        return checked_rel_dir(value)


class Publication(HydroModelBase):
    """``PUBLICATION.json``: what a published copy is."""

    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(default=PUBLICATION_SCHEMA, alias="schema", description="Schema id")
    source: PublicationSource
    manifest_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$", description="Digest of the sealed manifest"
    )
    files: dict[str, str] = Field(
        default_factory=dict, description="Relative path of each copied file to its sha256"
    )
    label: Label | None = Field(default=None, description="Label of the source on the day")
    label_date: date | None = Field(default=None, description="Day the label was computed")
    hydromodpy_version: str = Field(description="Version that published")
    published_at: datetime = Field(description="Instant of the copy, UTC")
    format: PublicationFormat = Field(description="dir or tar")
    with_: list[PublicationExtra] = Field(
        default_factory=list, alias="with", description="What was taken along"
    )

    @model_validator(mode="after")
    def _schema(self) -> Publication:
        if self.schema_ != PUBLICATION_SCHEMA:
            raise ValueError(
                f"schema is {self.schema_!r}, this module reads {PUBLICATION_SCHEMA!r}"
            )
        return self


class PublishedLine(HydroModelBase):
    """One line of ``published.jsonl``: where a copy went."""

    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(default=PUBLISHED_SCHEMA, alias="schema", description="Schema id")
    to: str = Field(description="Destination of the copy, as given")
    format: PublicationFormat
    published_at: datetime = Field(description="Instant of the copy, UTC")
    publication_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$", description="Digest of the PUBLICATION.json written there"
    )


def publication_path(directory: str | Path) -> Path:
    """Return ``<copy>/PUBLICATION.json``."""
    return Path(directory) / PUBLICATION_FILENAME


def write_publication(directory: str | Path, publication: Publication) -> Path:
    """Write ``PUBLICATION.json`` in a copy and return its path."""
    return write_json_atomic(
        publication_path(directory), publication.model_dump(mode="json", by_alias=True)
    )


def read_publication(directory: str | Path) -> Publication:
    """Read ``PUBLICATION.json`` of a copy."""
    return Publication.model_validate(
        read_sealed_json(publication_path(directory), PUBLICATION_SCHEMA)
    )


def published_path(source_dir: str | Path) -> Path:
    """Return ``<source>/published.jsonl``."""
    return Path(source_dir) / RUN_PUBLISHED_FILENAME


def append_published(source_dir: str | Path, line: PublishedLine) -> Path:
    """Append one line to ``published.jsonl`` of a source and return its path."""
    target = published_path(source_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(line.model_dump(mode="json", by_alias=True), ensure_ascii=False) + "\n"
    fd = os.open(target, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)
    return target


def read_published(source_dir: str | Path) -> list[PublishedLine]:
    """Return every line of ``published.jsonl``, empty when nothing was published."""
    target = published_path(source_dir)
    if not target.is_file():
        return []
    complete = target.read_text(encoding="utf-8").split("\n")[:-1]
    return [
        PublishedLine.model_validate(
            check_sealed(json.loads(text), PUBLISHED_SCHEMA, path=target, line=number)
        )
        for number, text in enumerate(complete, start=1)
        if text.strip()
    ]


_POSIX_ABSOLUTE = re.compile(r"(?<![\w:/])/(?:[^\s\"'<>|/]+)(?:/[^\s\"'<>|/]*)*")
_WINDOWS_ABSOLUTE = re.compile(r"(?<!\w)[A-Za-z]:[\\/][^\s\"'<>|]*")


def redact(payload: Mapping[str, Any], *, project_root: Path | None) -> dict[str, Any]:
    """Return *payload* without host, user or absolute path, at any depth.

    A key of :data:`REDACTED_KEYS` is dropped. A string that is, or holds,
    an absolute path has it replaced: by its path relative to *project_root*
    when it lies under it, by :data:`REDACTED_PATH` otherwise. Lists and
    nested mappings are walked; anything else is kept as it is.
    """
    root = None if project_root is None else Path(project_root).resolve()
    return {
        key: _redact_value(value, root)
        for key, value in payload.items()
        if key not in REDACTED_KEYS
    }


def _redact_value(value: Any, root: Path | None) -> Any:
    if isinstance(value, Mapping):
        return {k: _redact_value(v, root) for k, v in value.items() if k not in REDACTED_KEYS}
    if isinstance(value, list):
        return [_redact_value(item, root) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item, root) for item in value)
    if isinstance(value, str):
        return _redact_text(value, root)
    return value


def _redact_text(text: str, root: Path | None) -> str:
    def posix(match: re.Match[str]) -> str:
        return _relative_or_redacted(PurePosixPath(match.group(0)), root)

    def windows(match: re.Match[str]) -> str:
        return _relative_or_redacted(PureWindowsPath(match.group(0)), root)

    text = _WINDOWS_ABSOLUTE.sub(windows, text)
    return _POSIX_ABSOLUTE.sub(posix, text)


def _relative_or_redacted(path: PurePosixPath | PureWindowsPath, root: Path | None) -> str:
    if root is not None:
        try:
            return Path(path).resolve().relative_to(root).as_posix()
        except ValueError:
            pass
    return REDACTED_PATH


__all__ = [
    "PUBLICATION_SCHEMA",
    "PUBLISHED_SCHEMA",
    "REDACTED_KEYS",
    "REDACTED_PATH",
    "Publication",
    "PublicationExtra",
    "PublicationFormat",
    "PublicationSource",
    "PublishedLine",
    "append_published",
    "publication_path",
    "published_path",
    "read_publication",
    "read_published",
    "redact",
    "write_publication",
]
