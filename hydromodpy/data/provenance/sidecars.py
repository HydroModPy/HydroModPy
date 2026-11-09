"""The data cache of a workspace: one JSON sidecar next to each fetched file.

A file fetched from a provider or a URL sits in ``data/<variable>/`` with a
sidecar ``<file>.json`` beside it. The sidecar says where the bytes came from
(source, origin, product, licence), what they cover (variable, station, box,
period) and their digest. It is the only record of the cache: no database
holds a row the disk does not hold.

:func:`scan` reads every sidecar under the data folder in one walk, and
:class:`CacheIndex` keeps the rows in memory for the life of one store and
filters them in Python. A thousand sidecars are read in about 30 ms, ten
thousand in about 300 ms, and a search on the rows takes under a millisecond.

Three name rules decide what is a row. A sidecar must name its variable, and
one written by HydroModPy 2.0.0 without it is reported, never guessed from its
folder. Locks, writes in progress, hidden names, the ``blobs/`` and ``sites/``
folders, the tiles extracted from an archive and any JSON that is not a
sidecar (a manifest) are ignored by name. A sidecar of ``source = "file"``
describes a file of the user: it is counted, never a row, never pruned.

A station that answered nothing is a sidecar without a file, named like the
chronicle it would have described and marked ``empty``. One station has one
live row per variable and source: writing its chronicle removes its empty
sidecar, and the other way round. Two processes that write one station take
the lock of :meth:`CacheIndex.chronicle` in turn.

The database of HydroModPy 2.0.0, ``data/cache.duckdb``, is refused by name
with the sentence of :func:`former_cache_sentence`.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

from filelock import FileLock
from pydantic import BaseModel, ConfigDict, model_validator

from hydromodpy.core.config_kit.stored import read_stored
from hydromodpy.core.exceptions import DataCacheError
from hydromodpy.core.io.file_digest import sha256_of as compute_sha256
from hydromodpy.core.logging import get_logger
from hydromodpy.data.provenance import lockfile as frozen
from hydromodpy.schema.changes import migrations_of

logger = get_logger(__name__)

SIDECAR_SUFFIX = ".json"

#: Extensions of the data files a sidecar can describe. A file named
#: ``<name><one of these>.json`` is a sidecar, never a data file, whether or
#: not its data file exists.
SIDECAR_DATA_SUFFIXES = frozenset(
    {".asc", ".csv", ".geojson", ".gpkg", ".json", ".nc", ".parquet", ".shp", ".tif", ".tiff"}
)

#: Env var that, when set to ``"1"``, forces ``fetched_at`` to ``None`` for every
#: remote source. Use it in CI and fixtures to keep sidecar payloads
#: byte-identical across runs. Local ``file`` sources are already
#: deterministic and ignore the toggle.
DETERMINISTIC_FETCHED_AT_ENV = "HMP_DETERMINISTIC_FETCHED_AT"

#: Fields a downloaded station chronicle adds to its sidecar. These and the two
#: tuples below are written only when set, so the sidecar of any other file
#: keeps the bytes it always had.
CHRONICLE_FIELDS = ("variable", "unit", "source_unit", "frequency", "date_start", "date_end")
DOWNLOAD_FIELDS = ("origin", "etag", "last_modified", "product_version", "state")
CACHE_FIELDS = ("station_id", "product", "asked_window", "bytes", "fetch_metadata")

#: The data cache database of HydroModPy 2.0.0. Written here and nowhere else.
FORMER_CACHE_DATABASE = "cache.duckdb"

#: Folders the scan never enters, with the reason. ``blobs`` and ``sites`` are
#: read at the top of the data folder only, ``extracted_ign`` at any depth.
IGNORED_DIRECTORIES: dict[str, str] = {
    "blobs": "copies derived from a user file, never a fetched file",
    "sites": "the site catalogue of the workspace",
    "extracted_ign": "tiles extracted from an archive, whose own sidecar carries the provenance",
}
_TOP_ONLY_DIRECTORIES = frozenset({"blobs", "sites"})

#: File suffixes the scan never reads, with the reason.
IGNORED_SUFFIXES: dict[str, str] = {
    ".lock": "a lock taken while a file is written",
    ".part": "a write in progress",
}

_STALE_SECONDS = 1.0


def former_cache_sentence(database: Path) -> str:
    """The sentence that refuses the database of HydroModPy 2.0.0 at *database*."""
    return (
        f"{database} is the data cache database of HydroModPy 2.0.0. HydroModPy 2.1 keeps "
        "the cache in the sidecar next to each file and does not read it. Remove it with "
        "hmp workspace clean --data-cache. A file it described is fetched again when a run "
        "needs it."
    )


def refuse_former_cache_database(data_root: Path) -> None:
    """Refuse a data folder that still holds the database of HydroModPy 2.0.0."""
    database = Path(data_root) / FORMER_CACHE_DATABASE
    if database.is_file():
        raise DataCacheError(former_cache_sentence(database))


class Sidecar(BaseModel):
    """Provenance of one fetched file, stored next to it as ``<file>.json``.

    ``fetched_at`` is ``None`` for a local file, which has no network fetch
    event, and under :data:`DETERMINISTIC_FETCHED_AT_ENV`. ``empty`` marks the
    sidecar of a station that answered nothing: it has no file, so no
    ``sha256`` and no ``bytes``. Every other sidecar of a fetched file carries
    the ``sha256``. The sidecar of a user file may say only its source and its
    licence: it is no row of the cache, and its digest is read with the file.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str
    fetched_at: datetime | None = None
    sha256: str | None = None
    origin: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    product_version: str | None = None
    state: str | None = None
    license: str | None = None
    crs: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    notes: str | None = None
    variable: str | None = None
    unit: str | None = None
    source_unit: str | None = None
    frequency: str | None = None
    date_start: str | None = None
    date_end: str | None = None
    station_id: str | None = None
    product: str | None = None
    asked_window: tuple[str, str] | None = None
    empty: bool = False
    bytes: int | None = None
    fetch_metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _bytes_or_empty(self) -> Sidecar:
        if self.empty:
            if self.sha256 is not None or self.bytes is not None:
                raise ValueError(
                    "An empty sidecar describes a station that answered nothing: it has no "
                    "file, so it carries no sha256 and no bytes."
                )
        elif self.sha256 is None and self.source != frozen.USER_FILE_SOURCE:
            raise ValueError("A sidecar carries the sha256 of its file.")
        return self


def resolve_fetched_at(source: str, *, now: datetime | None = None) -> datetime | None:
    """Return the ``fetched_at`` value for a sidecar.

    A user file (``source = "file"``) has no network fetch event and always
    returns ``None``. Remote sources (``hubeau``, ``ign``, ``brgm``, ``meteo``,
    ...) return a UTC timestamp unless the env var
    :data:`DETERMINISTIC_FETCHED_AT_ENV` is set to ``"1"``, in which case
    ``None`` is returned so the JSON stays byte-identical across runs.
    """
    if str(source).lower() == frozen.USER_FILE_SOURCE:
        return None
    if os.environ.get(DETERMINISTIC_FETCHED_AT_ENV) == "1":
        return None
    return now if now is not None else datetime.now(UTC)


def sidecar_path_for(file_path: Path) -> Path:
    """Return the sidecar path for ``file_path`` (``foo.tif`` -> ``foo.tif.json``)."""
    target = Path(file_path)
    return target.with_name(target.name + SIDECAR_SUFFIX)


def data_path_for_sidecar(path: Path) -> Path | None:
    """Return the data file a sidecar describes, or None if ``path`` is no sidecar.

    ``foo.tif.json`` is the sidecar of ``foo.tif``. ``foo.json`` is a data
    file (GeoJSON), because ``foo`` carries no data extension. The answer
    depends on the name alone, so an orphan sidecar is still a sidecar.
    """
    target = Path(path)
    if target.suffix.lower() != SIDECAR_SUFFIX:
        return None
    data_path = target.with_name(target.name[: -len(SIDECAR_SUFFIX)])
    if data_path.suffix.lower() not in SIDECAR_DATA_SUFFIXES:
        return None
    return data_path


def empty_path_for(folder: Path, stem: str) -> Path:
    """Return ``<folder>/<stem>_empty.csv``, the file an empty sidecar stands for.

    ``stem`` is ``<prefix>_<source>_<station>``, the start of every file name of
    one station chronicle. The path has no file: only its sidecar is written.
    """
    return Path(folder) / f"{stem}_empty.csv"


def unlink_with_sidecar(file_path: Path) -> None:
    """Delete ``file_path`` and its sidecar together.

    The sidecar goes first: if the data file then refuses to go, what is left
    is a data file without a sidecar, which the next write describes again,
    never a sidecar without its file. A missing file or sidecar is not an
    error. Any other ``OSError`` propagates to the caller.
    """
    target = Path(file_path)
    sidecar_path_for(target).unlink(missing_ok=True)
    target.unlink(missing_ok=True)


def write_sidecar(file_path: Path, sidecar: Sidecar) -> Path:
    """Write the sidecar of ``file_path`` in one rename. Returns the sidecar path.

    The text goes to a hidden ``.<name>.<pid>.part`` beside it, then replaces
    the sidecar, so a reader sees the old sidecar or the new one. A sidecar
    without its variable, or one of a file without its size, is refused.
    """
    target = sidecar_path_for(file_path)
    if not sidecar.variable:
        raise DataCacheError(
            f"The sidecar of {file_path} names no variable. A sidecar of the data cache "
            "names the variable of its file."
        )
    if not sidecar.empty and sidecar.bytes is None:
        raise DataCacheError(
            f"The sidecar of {file_path} carries no bytes. A sidecar of the data cache "
            "carries the size of its file."
        )
    payload = sidecar.model_dump(mode="json")
    for key in CHRONICLE_FIELDS + DOWNLOAD_FIELDS + CACHE_FIELDS + ("sha256",):
        if payload[key] is None:
            del payload[key]
    if not payload["empty"]:
        del payload["empty"]
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(f".{target.name}.{os.getpid()}.part")
    try:
        part.write_text(text, encoding="utf-8")
        os.replace(part, target)
    finally:
        part.unlink(missing_ok=True)
    return target


def _as_written_today(payload: dict) -> dict:
    """Read *payload* under today's names, by the rows of ``schema/changes.toml``.

    A sidecar is one flat object, so the path of a row is one key. A row that
    renames a value changes it, a row that moves a key moves it unless the new
    key is written, and a row that retires a key drops it when it says so.
    """
    for row in migrations_of("sidecar"):
        if row.shape == "value":
            if payload.get(row.key) == row.old_value:
                payload[row.key] = row.new_value
        elif row.shape == "move":
            if row.old in payload and row.new not in payload:
                payload[row.new] = payload.pop(row.old)
        elif row.sealed == "drop":
            payload.pop(row.old, None)
    return payload


def load_sidecar(file_path: Path) -> Sidecar:
    """Load and validate the sidecar next to ``file_path``."""
    return _read_sidecar(sidecar_path_for(file_path))


def _read_sidecar(sidecar_path: Path) -> Sidecar:
    raw = sidecar_path.read_text(encoding="utf-8")
    return read_stored(Sidecar, _as_written_today(json.loads(raw)))


# ------------------------------------------------------------------ rows


def _naive(value: datetime | date | str | None) -> datetime | None:
    """Return *value* as a naive datetime in UTC, or None when it is not one."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        value = datetime(value.year, value.month, value.day)
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value


@dataclass(frozen=True)
class CacheRow:
    """One row of the data cache: one fetched file, as its sidecar describes it.

    ``path`` is the resolved file. For an ``empty`` row it is the name the
    chronicle would have had, and no file sits there.
    """

    path: Path
    variable: str
    source: str
    station_id: str | None = None
    product: str | None = None
    product_version: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    crs: str | None = None
    date_start: str | None = None
    date_end: str | None = None
    asked_window: tuple[str, str] | None = None
    frequency: str | None = None
    unit: str | None = None
    source_unit: str | None = None
    sha256: str | None = None
    bytes: int | None = None
    license: str | None = None
    fetched_at: datetime | None = None
    origin: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    state: str | None = None
    fetch_metadata: dict[str, Any] | None = None
    empty: bool = False
    notes: str | None = None

    @classmethod
    def of(cls, path: Path, sidecar: Sidecar) -> CacheRow:
        """Return the row of the file at *path* described by *sidecar*."""
        if not sidecar.variable:
            raise DataCacheError(f"The sidecar of {path} names no variable, so it is no row.")
        return cls(
            path=Path(path),
            variable=sidecar.variable,
            source=sidecar.source,
            station_id=sidecar.station_id,
            product=sidecar.product,
            product_version=sidecar.product_version,
            bbox=sidecar.bbox,
            crs=sidecar.crs,
            date_start=sidecar.date_start,
            date_end=sidecar.date_end,
            asked_window=sidecar.asked_window,
            frequency=sidecar.frequency,
            unit=sidecar.unit,
            source_unit=sidecar.source_unit,
            sha256=sidecar.sha256,
            bytes=sidecar.bytes,
            license=sidecar.license,
            fetched_at=sidecar.fetched_at,
            origin=sidecar.origin,
            etag=sidecar.etag,
            last_modified=sidecar.last_modified,
            state=sidecar.state,
            fetch_metadata=sidecar.fetch_metadata,
            empty=sidecar.empty,
            notes=sidecar.notes,
        )

    @property
    def sidecar_path(self) -> Path:
        """The sidecar of this row."""
        return sidecar_path_for(self.path)

    def window(self) -> tuple[datetime, datetime] | None:
        """The period the provider was asked for, or None when it is not recorded."""
        if self.asked_window is None:
            return None
        start, end = (_naive(value) for value in self.asked_window)
        if start is None or end is None:
            return None
        return start, end

    def to_dict(self) -> dict[str, Any]:
        """The row as plain values, the shape of ``hmp data ls --json``."""
        return {
            "variable": self.variable,
            "source": self.source,
            "station_id": self.station_id,
            "product": self.product,
            "product_version": self.product_version,
            "path": str(self.path),
            "sha256": self.sha256,
            "bytes": self.bytes,
            "license": self.license,
            "fetched_at": None if self.fetched_at is None else self.fetched_at.isoformat(),
            "date_start": self.date_start,
            "date_end": self.date_end,
            "bbox": None if self.bbox is None else list(self.bbox),
            "crs": self.crs,
            "frequency": self.frequency,
            "unit": self.unit,
            "source_unit": self.source_unit,
            "empty": self.empty,
        }


@dataclass(frozen=True)
class ScanReport:
    """What one walk of a data folder found."""

    data_root: Path
    rows: tuple[CacheRow, ...] = ()
    user_files: tuple[Path, ...] = ()
    without_variable: tuple[Path, ...] = ()
    orphans: tuple[Path, ...] = ()
    unreadable: tuple[tuple[Path, str], ...] = ()

    def lines(self) -> list[str]:
        """One sentence per sidecar that is no row and is not a user file."""
        out = [
            f"{path}: written by HydroModPy 2.0.0 without its variable, so it is no row of "
            "the cache. Its file is fetched again when a run needs it."
            for path in self.without_variable
        ]
        out.extend(f"{path}: its file is gone, so it is no row." for path in self.orphans)
        out.extend(f"{path}: unreadable ({why})." for path, why in self.unreadable)
        return out


def _walk_sidecars(data_root: Path) -> Iterator[Path]:
    """Yield every sidecar under *data_root*, by the name rules of this module."""
    root = str(data_root)
    for folder, dirs, names in os.walk(root):
        at_top = folder == root
        dirs[:] = sorted(
            d
            for d in dirs
            if not d.startswith(".")
            and not (d in _TOP_ONLY_DIRECTORIES and at_top)
            and not (d in IGNORED_DIRECTORIES and d not in _TOP_ONLY_DIRECTORIES)
        )
        for name in sorted(names):
            if name.startswith(".") or not name.endswith(SIDECAR_SUFFIX):
                continue
            if any(name.endswith(suffix) for suffix in IGNORED_SUFFIXES):
                continue
            path = Path(folder) / name
            if data_path_for_sidecar(path) is not None:
                yield path


def scan(data_root: Path) -> ScanReport:
    """Read every sidecar under *data_root* and sort them into rows and the rest.

    The folder is refused when it still holds the database of HydroModPy 2.0.0.
    A missing folder has no rows.
    """
    root = Path(data_root).expanduser().resolve()
    refuse_former_cache_database(root)
    rows: list[CacheRow] = []
    user_files: list[Path] = []
    without_variable: list[Path] = []
    orphans: list[Path] = []
    unreadable: list[tuple[Path, str]] = []
    if not root.is_dir():
        return ScanReport(data_root=root)
    for sidecar_path in _walk_sidecars(root):
        data_path = data_path_for_sidecar(sidecar_path)
        assert data_path is not None  # _walk_sidecars yields sidecars only
        try:
            sidecar = _read_sidecar(sidecar_path)
        except Exception as exc:  # noqa: BLE001 - any unreadable sidecar is reported
            unreadable.append((sidecar_path, str(exc).splitlines()[0]))
            continue
        if sidecar.source == frozen.USER_FILE_SOURCE:
            user_files.append(data_path)
            continue
        if not sidecar.empty and not data_path.is_file():
            orphans.append(sidecar_path)
            continue
        if not sidecar.variable:
            without_variable.append(sidecar_path)
            continue
        rows.append(CacheRow.of(data_path, sidecar))
    return ScanReport(
        data_root=root,
        rows=tuple(rows),
        user_files=tuple(user_files),
        without_variable=tuple(without_variable),
        orphans=tuple(orphans),
        unreadable=tuple(unreadable),
    )


# ------------------------------------------------------------------ the index


def _contains(outer: tuple | None, inner: tuple) -> bool:
    if outer is None:
        return False
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and outer[2] >= inner[2]
        and (outer[3] >= inner[3])
    )


def _covers(row: CacheRow, start: datetime | None, end: datetime | None) -> bool:
    """Whether the period of *row* covers ``start`` to ``end``, each side only when given."""
    if row.empty:
        window = row.window()
        if window is None:
            return start is None and end is None
        first, last = window
    else:
        first, last = _naive(row.date_start), _naive(row.date_end)
    if start is not None and (first is None or first > start):
        return False
    return not (end is not None and (last is None or last < end))


def _newest_first(row: CacheRow) -> tuple[float, float]:
    fetched = -math.inf if row.fetched_at is None else row.fetched_at.timestamp()
    try:
        mtime = (row.sidecar_path if row.empty else row.path).stat().st_mtime
    except OSError:
        mtime = -math.inf
    return fetched, mtime


def _same_bytes_sidecar(path: Path, digest: str) -> Sidecar | None:
    """The sidecar already next to *path* when it describes the same bytes."""
    if not sidecar_path_for(path).is_file():
        return None
    try:
        existing = load_sidecar(path)
    except Exception:  # noqa: BLE001 - an unreadable sidecar is rewritten
        return None
    return existing if existing.sha256 == digest else None


def _licence(source: str, given: str | None, existing: Sidecar | None) -> str:
    """The licence a new sidecar carries: given, kept when determined, else the registry's."""
    from hydromodpy.schema.sources import is_determined, licence_for_source

    if given:
        return str(given)
    if existing is not None and is_determined(existing.license):
        return str(existing.license)
    return licence_for_source(source).spdx


#: Root of the installed ``hydromodpy`` package. A file bundled inside it is
#: read-only and its committed sidecar is never rewritten at runtime.
_PACKAGE_ROOT = Path(__file__).resolve().parents[__name__.count(".") - 1]


def _is_inside_package(path: Path) -> bool:
    return Path(path).resolve().is_relative_to(_PACKAGE_ROOT)


class CacheIndex:
    """The rows of one data folder, read once and kept in memory.

    The folder is walked on the first call and the rows stay on this object,
    so the index lives as long as the store that holds it and no module keeps
    state. :meth:`record` and :meth:`forget` change the disk and the rows in
    the same call. Without a data folder the index finds nothing and refuses
    to write.

    The index notes the instant it opened and the rows it recorded itself.
    :meth:`subsume` uses both to leave alone a file another process wrote
    after that instant, which that process may still be reading.
    """

    def __init__(self, data_root: Path | str | None) -> None:
        self.data_root = None if data_root is None else Path(data_root).expanduser().resolve()
        self._rows: dict[Path, CacheRow] | None = None
        self._report: ScanReport | None = None
        self._guard = threading.RLock()
        self._opened_ns = time.time_ns()
        self._own: set[Path] = set()

    # -- reading -------------------------------------------------------

    def _loaded(self) -> dict[Path, CacheRow]:
        with self._guard:
            if self._rows is None:
                if self.data_root is None:
                    self._report = ScanReport(data_root=Path())
                    self._rows = {}
                else:
                    self._report = scan(self.data_root)
                    self._rows = {row.path: row for row in self._report.rows}
            return self._rows

    @property
    def report(self) -> ScanReport:
        """The walk this index was built from."""
        self._loaded()
        assert self._report is not None
        return self._report

    def rows(
        self,
        variable: str | None = None,
        source: str | None = None,
        station_id: str | None = None,
    ) -> list[CacheRow]:
        """The rows, filtered on each argument given, sorted by path."""
        with self._guard:
            found = [
                row
                for row in self._loaded().values()
                if (variable is None or row.variable == variable)
                and (source is None or row.source == source)
                and (station_id is None or row.station_id == station_id)
            ]
        return sorted(found, key=lambda row: str(row.path))

    def row_for(self, path: Path | str) -> CacheRow | None:
        """The row of the file at *path*, or None."""
        with self._guard:
            return self._loaded().get(self.resolve(path))

    def resolve(self, path: Path | str) -> Path:
        """Return *path* resolved; a relative path is read under the data folder."""
        target = Path(path).expanduser()
        if not target.is_absolute() and self.data_root is not None:
            target = self.data_root / target
        return target.resolve()

    def relative(self, path: Path) -> str:
        """Return *path* relative to the data folder, in POSIX form."""
        if self.data_root is None:
            return Path(path).as_posix()
        return PurePosixPath(Path(path).relative_to(self.data_root).as_posix()).as_posix()

    def find(
        self,
        variable: str,
        source: str,
        *,
        station_id: str | None = None,
        product: str | None = None,
        product_version: str | None = None,
        bbox: tuple | None = None,
        date_start: datetime | date | str | None = None,
        date_end: datetime | date | str | None = None,
    ) -> CacheRow | None:
        """Return the row that holds what is asked, or None.

        The row holds a superset: its box contains *bbox* and its period runs
        from *date_start* or before to *date_end* or after. *product* and
        *product_version* must be equal when given. An empty row answers a
        search by station only, and only for the window it was asked for. Among
        several rows, the most recently fetched wins. In frozen mode a miss, a
        row the lockfile does not pin and a row of other bytes are refused.
        """
        if bbox is not None and not (bbox[0] <= bbox[2] and bbox[1] <= bbox[3]):
            logger.warning("find() called with an inverted bbox: %s", bbox)
            return None
        start, end = _naive(date_start), _naive(date_end)
        with self._guard:
            candidates = [
                row
                for row in self._loaded().values()
                if row.variable == variable
                and row.source == source
                and (station_id is None or row.station_id == station_id)
                and (product is None or row.product == product)
                and (product_version is None or row.product_version == product_version)
                and (not row.empty or station_id is not None)
                and (bbox is None or row.empty or _contains(row.bbox, tuple(bbox)))
                and ((start is None and end is None) or _covers(row, start, end))
            ]
        if not candidates:
            frozen.reject_frozen_cache_miss(
                data_root=self.data_root,
                variable=variable,
                source=source,
                station_id=station_id,
            )
            return None
        row = max(candidates, key=_newest_first)
        if row.empty:
            frozen.reject_frozen_empty(
                variable=row.variable, source=row.source, station_id=row.station_id
            )
        else:
            frozen.reject_frozen_row(
                variable=row.variable,
                source=row.source,
                station_id=row.station_id,
                path=self.relative(row.path),
                sha256=row.sha256,
            )
        return row

    def is_stale(self, row: CacheRow) -> bool:
        """Whether the file of *row* no longer holds the bytes its sidecar names.

        A file whose size differs from the sidecar, or that is newer than its
        sidecar by more than a second, is hashed again, and is stale only when
        the digest differs. A copy by ``cp`` keeps its rows. A missing file is
        stale. An empty row is never stale.
        """
        if row.empty:
            return False
        try:
            stat = row.path.stat()
        except OSError:
            return True
        try:
            sidecar_mtime = row.sidecar_path.stat().st_mtime
        except OSError:
            sidecar_mtime = -math.inf
        if row.bytes is not None and stat.st_size != row.bytes:
            return compute_sha256(row.path) != row.sha256
        if stat.st_mtime > sidecar_mtime + _STALE_SECONDS:
            return compute_sha256(row.path) != row.sha256
        return False

    # -- writing -------------------------------------------------------

    def _require_root(self, path: Path) -> Path:
        if self.data_root is None:
            raise DataCacheError(
                f"{path} cannot enter the data cache: this store has no data folder."
            )
        resolved = Path(path).resolve()
        if not resolved.is_relative_to(self.data_root):
            raise DataCacheError(
                f"{resolved} lies outside the data folder {self.data_root}, so it cannot "
                "be a row of its cache."
            )
        return resolved

    @contextmanager
    def chronicle(self, folder: Path, stem: str) -> Iterator[list[CacheRow]]:
        """Hold the lock of one station chronicle and yield its rows, read again.

        Every file of the chronicle is named ``<stem>_<anything>`` in *folder*,
        and the lock is ``<folder>/.<stem>.lock``. Inside the block the caller
        deletes the old file, writes the new one and records it, so two
        processes that fetch one station leave one file and one sidecar. The
        lock is taken again by the same thread without blocking.
        """
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        lock = FileLock(str(folder / f".{stem}.lock"), is_singleton=True)
        with lock:
            yield self._reread(folder, stem)

    def _reread(self, folder: Path, stem: str) -> list[CacheRow]:
        """Read the sidecars of one chronicle again and put them in the index."""
        resolved = folder.resolve()
        prefix = f"{stem}_"
        found: dict[Path, CacheRow] = {}
        for sidecar_path in sorted(resolved.glob(f"{stem}_*{SIDECAR_SUFFIX}")):
            data_path = data_path_for_sidecar(sidecar_path)
            if data_path is None:
                continue
            try:
                sidecar = _read_sidecar(sidecar_path)
            except Exception:  # noqa: BLE001 - an unreadable sidecar is no row
                continue
            if sidecar.source == frozen.USER_FILE_SOURCE or not sidecar.variable:
                continue
            if not sidecar.empty and not data_path.is_file():
                continue
            found[data_path] = CacheRow.of(data_path, sidecar)
        with self._guard:
            rows = self._loaded()
            for path in [p for p in rows if p.parent == resolved and p.name.startswith(prefix)]:
                if path not in found:
                    del rows[path]
            rows.update(found)
        return sorted(found.values(), key=lambda row: str(row.path))

    def record(
        self,
        path: Path | str,
        *,
        variable: str,
        source: str,
        station_id: str | None = None,
        product: str | None = None,
        product_version: str | None = None,
        bbox: tuple | None = None,
        crs: str | None = None,
        date_start: datetime | date | str | None = None,
        date_end: datetime | date | str | None = None,
        asked_window: tuple[datetime | date | str, datetime | date | str] | None = None,
        frequency: str | None = None,
        unit: str | None = None,
        source_unit: str | None = None,
        origin: str | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
        state: str | None = None,
        license: str | None = None,
        fetch_metadata: dict[str, Any] | None = None,
        notes: str | None = None,
    ) -> CacheRow:
        """Write the sidecar of a fetched file already on disk, and return its row.

        The digest and the size are read from the file. A field left unset
        takes the value of the sidecar already there when it describes the same
        bytes, so a unit or a declared licence is never erased by a rewrite.
        With *station_id*, the other rows of that station, its empty sidecar
        included, leave with their files: write a station inside
        :meth:`chronicle`. A file of the user is no row, and is refused.
        """
        if source == frozen.USER_FILE_SOURCE:
            raise DataCacheError(
                f"{path} is a user file (source 'file'). A user file is read where it "
                "lies and is no row of the data cache."
            )
        target = self._require_root(Path(path))
        if not target.is_file():
            raise DataCacheError(f"{target} is not a file, so it cannot be recorded.")
        digest = compute_sha256(target)
        frozen.reject_frozen_record(
            variable=variable,
            source=source,
            station_id=station_id,
            path=self.relative(target),
            sha256=digest,
        )
        existing = _same_bytes_sidecar(target, digest)
        given = {
            "station_id": station_id,
            "product": product,
            "product_version": product_version,
            "bbox": None if bbox is None else tuple(float(v) for v in bbox),
            "crs": None if crs is None else str(crs),
            "date_start": _iso(date_start),
            "date_end": _iso(date_end),
            "asked_window": _window(asked_window),
            "frequency": frequency,
            "unit": unit,
            "source_unit": source_unit,
            "origin": origin,
            "etag": etag,
            "last_modified": last_modified,
            "state": state,
            "fetch_metadata": fetch_metadata or None,
            "notes": notes,
        }
        if existing is not None:
            for key, value in given.items():
                if value is None:
                    given[key] = getattr(existing, key)
        fetched_at = (
            existing.fetched_at
            if existing is not None and existing.fetched_at is not None
            else resolve_fetched_at(source)
        )
        sidecar = Sidecar(
            source=str(source),
            variable=variable,
            fetched_at=fetched_at,
            sha256=digest,
            bytes=target.stat().st_size,
            license=_licence(source, license, existing),
            **given,
        )
        row = CacheRow.of(target, sidecar)
        if not _is_inside_package(target):
            write_sidecar(target, sidecar)
        self._take(row)
        return row

    def record_empty(
        self,
        path: Path | str,
        *,
        variable: str,
        source: str,
        station_id: str,
        product: str | None = None,
        asked_window: tuple[datetime | date | str, datetime | date | str] | None = None,
    ) -> CacheRow:
        """Write the sidecar of a station that answered nothing, and return its row.

        *path* comes from :func:`empty_path_for` and holds no file. The
        chronicle of the station, if any, leaves with its file.
        """
        target = self._require_root(Path(path).parent) / Path(path).name
        frozen.reject_frozen_record(
            variable=variable,
            source=source,
            station_id=station_id,
            path=self.relative(target),
            sha256=None,
        )
        sidecar = Sidecar(
            source=str(source),
            variable=variable,
            fetched_at=resolve_fetched_at(source),
            station_id=station_id,
            product=product,
            asked_window=_window(asked_window),
            empty=True,
            license=_licence(source, None, None),
        )
        row = CacheRow.of(target, sidecar)
        write_sidecar(target, sidecar)
        self._take(row)
        return row

    def _take(self, row: CacheRow) -> None:
        """Put *row* in the index; a station keeps one row, so the others leave."""
        with self._guard:
            rows = self._loaded()
            if row.station_id is not None:
                for other in list(rows.values()):
                    if (
                        other.path != row.path
                        and other.variable == row.variable
                        and other.source == row.source
                        and other.station_id == row.station_id
                    ):
                        self._drop(other, delete_file=True)
            rows[row.path] = row
            self._own.add(row.path)

    def forget(self, row: CacheRow, *, delete_file: bool = False) -> None:
        """Remove *row*: its sidecar, and its file when *delete_file* is set."""
        with self._guard:
            self._loaded()
            self._drop(row, delete_file=delete_file)

    def _drop(self, row: CacheRow, *, delete_file: bool) -> None:
        if delete_file and not row.empty:
            unlink_with_sidecar(row.path)
        else:
            row.sidecar_path.unlink(missing_ok=True)
        assert self._rows is not None
        self._rows.pop(row.path, None)

    def forget_orphans(self) -> list[Path]:
        """Remove the sidecars whose file is gone. Returns them."""
        removed: list[Path] = []
        for sidecar_path in self.report.orphans:
            sidecar_path.unlink(missing_ok=True)
            removed.append(sidecar_path)
        with self._guard:
            for path in [p for p, row in self._loaded().items() if not row.empty]:
                if not path.is_file():
                    removed.append(sidecar_path_for(path))
                    sidecar_path_for(path).unlink(missing_ok=True)
                    del self._rows[path]  # type: ignore[index]
        return removed

    def subsume(self, keep: CacheRow) -> int:
        """Remove the grids that *keep* contains, files included. Returns the count.

        A row leaves when it has no station, is not empty, has the variable and
        source of *keep*, and its box and period lie inside those of *keep*.
        *keep* without a box removes nothing. A row stays when another process
        wrote its sidecar after this index opened: the prepare children of
        nested sites share one data folder, and the child that wrote that file
        may still read it. ``hmp data prune`` removes such a row later.
        """
        if keep.bbox is None:
            return 0
        first, last = _naive(keep.date_start), _naive(keep.date_end)
        count = 0
        with self._guard:
            for row in list(self._loaded().values()):
                if (
                    row.path == keep.path
                    or row.station_id is not None
                    or row.empty
                    or row.variable != keep.variable
                    or row.source != keep.source
                    or not _contains(keep.bbox, row.bbox or (math.nan,) * 4)
                    or not self._settled(row)
                ):
                    continue
                if first is not None and not (
                    (start := _naive(row.date_start)) is not None and start >= first
                ):
                    continue
                if last is not None and not (
                    (end := _naive(row.date_end)) is not None and end <= last
                ):
                    continue
                self._drop(row, delete_file=True)
                count += 1
        return count

    def _settled(self, row: CacheRow) -> bool:
        """Say whether *row* is this index's own, or was written before it opened."""
        if row.path in self._own:
            return True
        try:
            written_ns = row.sidecar_path.stat().st_mtime_ns
        except OSError:
            return False
        return written_ns < self._opened_ns


def _iso(value: datetime | date | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


def _window(
    window: tuple[datetime | date | str, datetime | date | str] | None,
) -> tuple[str, str] | None:
    if window is None:
        return None
    start, end = window
    return str(_iso(start)), str(_iso(end))


# ------------------------------------------------------------------ prune


@dataclass(frozen=True)
class PruneReport:
    """What one prune removed, and what it kept because a run or a lockfile cites it."""

    removed: tuple[Path, ...] = ()
    kept_cited: tuple[Path, ...] = ()
    orphans: tuple[Path, ...] = ()
    user_files: int = 0
    dry_run: bool = False


def _age_reference(row: CacheRow) -> datetime:
    """The instant a row was fetched: its ``fetched_at``, else the date of its file."""
    if row.fetched_at is not None:
        return _naive(row.fetched_at) or datetime.min
    try:
        mtime = (row.sidecar_path if row.empty else row.path).stat().st_mtime
    except OSError:
        return datetime.min
    return datetime.fromtimestamp(mtime, UTC).replace(tzinfo=None)


def prune(
    data_root: Path,
    *,
    keep: frozenset[str] | Iterable[str],
    keep_empty: frozenset[str] | Iterable[str] = (),
    older_than_days: float | None = None,
    delete_files: bool = False,
    dry_run: bool = False,
    now: datetime | None = None,
) -> PruneReport:
    """Remove the rows of *data_root* fetched more than *older_than_days* ago.

    *keep* is every digest a run or a lockfile cites, computed by ``project``:
    such a row stays, and is named in the report. An empty answer has no
    digest: it stays when its path, relative to *data_root*, is in
    *keep_empty*, the empty answers a lockfile pins. A sidecar whose file is gone
    always leaves. Without *delete_files* only the sidecars leave, and their
    files are then no rows. A user file is never a row, so it never leaves.
    """
    cited = frozenset(keep)
    cited_empty = frozenset(keep_empty)
    index = CacheIndex(data_root)
    report = index.report
    limit = None
    if older_than_days is not None:
        instant = _naive(now) if now is not None else datetime.now(UTC).replace(tzinfo=None)
        assert instant is not None
        limit = instant - timedelta(days=float(older_than_days))
    removed: list[Path] = []
    kept: list[Path] = []
    for row in index.rows():
        if limit is not None and _age_reference(row) >= limit:
            continue
        if (row.sha256 is not None and row.sha256 in cited) or (
            row.empty and index.relative(row.path) in cited_empty
        ):
            kept.append(row.path)
            continue
        removed.append(row.path)
        if not dry_run:
            index.forget(row, delete_file=delete_files)
    if not dry_run:
        for sidecar_path in report.orphans:
            sidecar_path.unlink(missing_ok=True)
    return PruneReport(
        removed=tuple(removed),
        kept_cited=tuple(kept),
        orphans=report.orphans,
        user_files=len(report.user_files),
        dry_run=dry_run,
    )


__all__ = [
    "CACHE_FIELDS",
    "CHRONICLE_FIELDS",
    "DETERMINISTIC_FETCHED_AT_ENV",
    "DOWNLOAD_FIELDS",
    "FORMER_CACHE_DATABASE",
    "IGNORED_DIRECTORIES",
    "IGNORED_SUFFIXES",
    "SIDECAR_DATA_SUFFIXES",
    "SIDECAR_SUFFIX",
    "CacheIndex",
    "CacheRow",
    "PruneReport",
    "ScanReport",
    "Sidecar",
    "compute_sha256",
    "data_path_for_sidecar",
    "empty_path_for",
    "former_cache_sentence",
    "load_sidecar",
    "prune",
    "refuse_former_cache_database",
    "resolve_fetched_at",
    "scan",
    "sidecar_path_for",
    "unlink_with_sidecar",
    "write_sidecar",
]
