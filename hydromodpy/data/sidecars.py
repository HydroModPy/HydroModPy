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
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

SIDECAR_SUFFIX = ".json"


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


def sidecar_path_for(file_path: Path) -> Path:
    """Return the sidecar path for ``file_path`` (``foo.tif`` -> ``foo.tif.json``)."""
    target = Path(file_path)
    return target.with_name(target.name + SIDECAR_SUFFIX)


def write_sidecar(file_path: Path, sidecar: Sidecar) -> Path:
    """Write a JSON sidecar next to ``file_path``. Returns the sidecar path."""
    target = sidecar_path_for(file_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = sidecar.model_dump(mode="json")
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
    "SIDECAR_SUFFIX",
    "Sidecar",
    "compute_sha256",
    "load_sidecar",
    "sidecar_path_for",
    "write_sidecar",
]
