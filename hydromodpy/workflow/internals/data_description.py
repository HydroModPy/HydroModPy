"""What a data load read, and the document that says so.

``load_data`` is the one head step whose product is decided entirely by files
it does not own: a recharge series, a geology layer, a lake bathymetry. It left
nothing of its own on disk, so its journal row carried the digest of the empty
string, and what a run consumed was legible only from the provenance rows
``prepare_solver`` writes five steps later, into SQL.

Declaring those input files as the step's artefacts would be a lie - they are
what it read, not what it produced. What it *produces* is the binding: which
variable came from which source, over which period, from a file with which
digest. That is a document, this module writes it, and the step declares it.

What signing that document buys, precisely: a resume whose description is gone
or truncated replans from the load instead of carrying on over an undescribed
one, and the binding is on disk from the step that made it rather than from
step six.

A forcing rewritten between the crash and the restart is caught in two moves,
not one. The resume that reloads it verifies the document written *before* the
crash, which of course still matches itself, then overwrites it with what it
just read; :func:`changed_sources` compares the two and names the variables
that moved. A later resume then finds the recorded digest and the rewritten
document disagreeing, and replans from the load - which is the right answer,
since the run no longer rests on the bytes it started from.

The same walk over the loaded scopes feeds the provenance rows
:func:`hydromodpy.workflow.steps.prepare_solver.prepare.step_write_provenance`
writes five steps later, so the two views of the same load cannot drift.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

DESCRIPTION_FILENAME = "loaded_data.json"
SCHEMA_VERSION = "hydromodpy.loaded_data.v1"


@dataclass(frozen=True, slots=True)
class LoadedRecord:
    """One loaded series or field, with the scope that holds it."""

    scope: str
    kind: str
    record: Any

    @property
    def variable(self) -> str:
        return str(getattr(self.record, "variable", ""))

    @property
    def loader_name(self) -> str:
        return f"{self.scope}:{type(self.record).__name__}"


def description_path(workspace: Path, run_id: str) -> Path:
    """Return the description path of one run, beside its resume checkpoint."""
    return Path(workspace) / ".hmp" / "checkpoints" / str(run_id) / DESCRIPTION_FILENAME


def record_source_path(record: object) -> Path | None:
    """Return the file a loaded record came from, when it came from one."""
    metadata = getattr(record, "metadata", None)
    if isinstance(metadata, dict):
        for key in ("source_path", "raster_path", "vector_path"):
            value = metadata.get(key)
            if value not in (None, ""):
                return Path(str(value))
    file_path = getattr(record, "file_path", None)
    if file_path is not None:
        return Path(file_path)
    data = getattr(record, "data", None)
    if isinstance(data, (str, Path)):
        return Path(data)
    return None


def sha256_file_or_none(path: Path | None) -> str | None:
    """Return the sha256 of a file, or None when there is no readable file."""
    if path is None or not path.is_file():
        return None
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        logger.debug("data.source_unreadable path=%s err=%s", path, exc)
        return None
    return digest.hexdigest()


def iter_loaded_records(loaded: object) -> Iterator[LoadedRecord]:
    """Yield every point series and every field a data load left in a scope.

    The order follows the declaration order of ``LoadedDataContext``, which is
    stable across processes; callers that need a canonical order sort the
    records they build from it.
    """
    if loaded is None or not dataclasses.is_dataclass(loaded):
        return
    for field in dataclasses.fields(loaded):
        load_result = getattr(loaded, field.name, None)
        if load_result is None:
            continue
        for kind, attribute in (("point", "points"), ("field", "fields")):
            for record in getattr(load_result, attribute, None) or ():
                yield LoadedRecord(scope=field.name, kind=kind, record=record)


_IDENTITY_KEYS = ("scope", "variable", "station_id", "kind", "source")
_SOURCE_KEYS = (
    "station_id",
    "source",
    "source_path",
    "source_sha256",
    "period_start",
    "period_end",
)


def _entry_sort_key(entry: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the total order the document is written in.

    Every field that identifies a record takes part, so two records of one
    scope never depend on the walk order to keep a stable position - a document
    whose order moved would move its digest, and every resume would replan.
    """
    return tuple(str(entry.get(key) or "") for key in (*_IDENTITY_KEYS, "source_path"))


def _text_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _timestamp_or_none(value: object) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            return str(isoformat())
        except (TypeError, ValueError):
            return None
    text = str(value).strip()
    return text or None


def describe_loaded_data(loaded: object, *, plan_types: tuple[str, ...] = ()) -> dict[str, Any]:
    """Return the document describing what a data load bound to the runtime.

    A source that is not a file - a synthetic series, a remote query already
    served from a manager cache - keeps its ``source`` name and carries no
    digest. Saying so is the honest record; inventing a digest for it would
    make the document claim more than the load knows.

    ``station_id`` is carried because it is what tells two records of the same
    variable apart: the Hub'Eau managers give every station of a scope the same
    ``variable`` label, so a document without it would describe several
    piezometers as one.
    """
    digests: dict[str, str | None] = {}
    entries: list[dict[str, Any]] = []
    for item in iter_loaded_records(loaded):
        source_path = record_source_path(item.record)
        key = str(source_path) if source_path is not None else None
        if key is not None and key not in digests:
            digests[key] = sha256_file_or_none(source_path)
        entries.append(
            {
                "scope": item.scope,
                "variable": item.variable,
                "station_id": _text_or_none(getattr(item.record, "station_id", None)),
                "kind": item.kind,
                "loader": item.loader_name,
                "source": str(getattr(item.record, "source", "") or ""),
                "source_path": key,
                "source_sha256": digests.get(key) if key is not None else None,
                "period_start": _timestamp_or_none(getattr(item.record, "date_start", None)),
                "period_end": _timestamp_or_none(getattr(item.record, "date_end", None)),
            }
        )
    entries.sort(key=_entry_sort_key)
    return {
        "schema": SCHEMA_VERSION,
        "plan_types": sorted(str(name) for name in plan_types),
        "records": entries,
    }


def source_digests(payload: Mapping[str, Any] | None) -> dict[str, str]:
    """Return the ``path -> sha256`` pairs a load already computed.

    The digest of a file is a function of the file, so a later step that needs
    the same number reads it here instead of hashing the bytes a second time.
    It is also the more faithful number: it describes the file as the load read
    it, not as it stands three steps later.
    """
    if not isinstance(payload, Mapping):
        return {}
    found: dict[str, str] = {}
    for entry in payload.get("records", ()) or ():
        if not isinstance(entry, Mapping):
            continue
        path, digest = entry.get("source_path"), entry.get("source_sha256")
        if isinstance(path, str) and isinstance(digest, str):
            found[path] = digest
    return found


def write_data_description(
    workspace: Path,
    run_id: str,
    payload: Mapping[str, Any],
) -> Path | None:
    """Write the description of one load, atomically, beside its checkpoint.

    Best-effort: a load that cannot describe itself is still a usable load for
    the process holding it in memory. The write is atomic because a truncated
    document read back at resume would be a digest over a half-written file,
    which is worse than no document at all.
    """
    path = description_path(workspace, run_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(dict(payload), indent=2, ensure_ascii=True, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
    except (OSError, TypeError, ValueError) as exc:
        logger.warning("data.description_write_failed run=%s err=%s", run_id, exc)
        return None
    return path


def changed_sources(
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    """Return the ``scope:variable`` names whose source moved between two loads.

    Only what identifies a source is compared - the station, the source name,
    the file, the digest of that file and the period it covers. A record that
    appears or disappears counts as a change: the plan itself moved.

    One name can hold several records - the Hub'Eau managers label every
    station of a scope with the same ``variable`` - so the records under a name
    are compared as a sorted multiset. Keying one record per name would let a
    second station of the same variable drop out of the comparison, which is
    exactly the case a multi-station run is made of.
    """
    if not isinstance(before, Mapping) or not isinstance(after, Mapping):
        return ()

    def _index(payload: Mapping[str, Any]) -> dict[str, list[tuple[Any, ...]]]:
        indexed: dict[str, list[tuple[Any, ...]]] = {}
        for entry in payload.get("records", ()) or ():
            if not isinstance(entry, Mapping):
                continue
            key = f"{entry.get('scope')}:{entry.get('variable')}"
            indexed.setdefault(key, []).append(
                tuple(str(entry.get(field) or "") for field in _SOURCE_KEYS)
            )
        return {key: sorted(values) for key, values in indexed.items()}

    old, new = _index(before), _index(after)
    return tuple(sorted(key for key in old.keys() | new.keys() if old.get(key) != new.get(key)))


def read_data_description(workspace: Path, run_id: str) -> dict[str, Any] | None:
    """Return the description a previous load wrote for this run, or None."""
    path = description_path(workspace, run_id)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("data.description_unreadable path=%s err=%s", path, exc)
        return None
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA_VERSION:
        return None
    return payload


__all__ = (
    "DESCRIPTION_FILENAME",
    "SCHEMA_VERSION",
    "LoadedRecord",
    "changed_sources",
    "describe_loaded_data",
    "description_path",
    "iter_loaded_records",
    "read_data_description",
    "source_digests",
    "record_source_path",
    "sha256_file_or_none",
    "write_data_description",
)
