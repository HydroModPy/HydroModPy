"""JSON sidecars carrying upstream provenance for ``data/<var>/raw/`` inputs.

Every physical input file (DEM, GeoPackage, NetCDF, etc.) sits next to a JSON
sidecar that describes its origin and content fingerprint. The sidecar lives at
``<file_path>.json`` and is meant to be regenerated automatically by ``hmp data
fetch`` and edited by the user when refining provenance.

Specification: ``reports_db/99_master.md §5.3``.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

SIDECAR_SUFFIX = ".json"

#: Extensions of the data files a sidecar can describe. A file named
#: ``<name><one of these>.json`` is a sidecar, never a data file, whether or
#: not its data file exists.
SIDECAR_DATA_SUFFIXES = frozenset(
    {".asc", ".csv", ".geojson", ".gpkg", ".json", ".nc", ".parquet", ".shp", ".tif", ".tiff"}
)

#: Env var that, when set to ``"1"``, forces ``fetched_at`` to ``None`` for every
#: remote source. Use it in CI and fixtures to keep sidecar payloads
#: byte-identical across runs. Local ``custom`` sources are already
#: deterministic and ignore the toggle.
DETERMINISTIC_FETCHED_AT_ENV = "HMP_DETERMINISTIC_FETCHED_AT"

#: Fields a downloaded station chronicle adds to its sidecar. Written only when
#: set, so the sidecar of any other file keeps the bytes it always had.
CHRONICLE_FIELDS = ("variable", "unit", "source_unit", "frequency", "date_start", "date_end")


class Sidecar(BaseModel):
    """Provenance metadata stored next to a ``data/<var>/raw/`` input file.

    ``fetched_at`` is omitted (``None``) for local ``source == "custom"`` inputs
    that have no network fetch event, so the sidecar stays byte-identical across
    test runs and never appears in ``git status``. Real remote fetches keep a
    real ISO timestamp.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str
    fetched_at: datetime | None = None
    sha256: str
    license: str | None = None
    crs: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    notes: str | None = None
    # A downloaded station chronicle also carries what reading it back needs,
    # so the file says it without the cache index.
    variable: str | None = None
    unit: str | None = None
    source_unit: str | None = None
    frequency: str | None = None
    date_start: str | None = None
    date_end: str | None = None


def resolve_fetched_at(source: str, *, now: datetime | None = None) -> datetime | None:
    """Return the ``fetched_at`` value for a sidecar.

    Local ``source == "custom"`` inputs have no network fetch event and always
    return ``None``. Remote sources (``hubeau``, ``ign``, ``brgm``, ``meteo``,
    ...) return a UTC timestamp unless the env var
    :data:`DETERMINISTIC_FETCHED_AT_ENV` is set to ``"1"``, in which case
    ``None`` is returned so the JSON stays byte-identical across runs.
    """
    if str(source).lower() == "custom":
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
    """Write a JSON sidecar next to ``file_path``. Returns the sidecar path."""
    target = sidecar_path_for(file_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = sidecar.model_dump(mode="json")
    for key in CHRONICLE_FIELDS:
        if payload[key] is None:
            del payload[key]
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    target.write_text(text, encoding="utf-8")
    return target


def load_sidecar(file_path: Path) -> Sidecar:
    """Load and validate the sidecar next to ``file_path``."""
    target = sidecar_path_for(file_path)
    raw = target.read_text(encoding="utf-8")
    payload = json.loads(raw)
    return Sidecar.model_validate(payload)


def compute_sha256(path: Path, chunk_size: int = 1 << 20) -> str:
    """Return the streaming SHA-256 hex digest of ``path``."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "CHRONICLE_FIELDS",
    "DETERMINISTIC_FETCHED_AT_ENV",
    "SIDECAR_DATA_SUFFIXES",
    "SIDECAR_SUFFIX",
    "Sidecar",
    "compute_sha256",
    "data_path_for_sidecar",
    "load_sidecar",
    "resolve_fetched_at",
    "sidecar_path_for",
    "unlink_with_sidecar",
    "write_sidecar",
]
