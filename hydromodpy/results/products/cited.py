"""``products.json`` of a run, and the keys a running attempt protects.

A run writes the products it read from the store, one entry per kind, in the
order the steps first asked for them. The document is read on a resume, to ask
the store for the same keys instead of recomputing them, and by eviction, to
keep the products of a run that still runs.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from hydromodpy.core.io.atomic_replace import staged_path
from hydromodpy.results.outcome import effective_status
from hydromodpy.results.storage.contract import RUN_PRODUCTS_FILENAME

PRODUCTS_SCHEMA = "hydromodpy.products.v1"
"""Schema id of the document."""


@dataclass(frozen=True, slots=True)
class CitedProduct:
    """One product a run read, by kind and key."""

    kind: str
    key: str


def write_cited(run_dir: str | Path, products: Iterable[CitedProduct]) -> Path:
    """Write ``products.json`` of ``run_dir`` and return its path."""
    payload = {
        "schema": PRODUCTS_SCHEMA,
        "products": [asdict(product) for product in products],
    }
    path = Path(run_dir) / RUN_PRODUCTS_FILENAME
    with staged_path(path) as staged:
        staged.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    return path


def read_cited(run_dir: str | Path) -> tuple[CitedProduct, ...]:
    """Return the products a run cited, empty when the file is absent."""
    path = Path(run_dir) / RUN_PRODUCTS_FILENAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ()
    if payload.get("schema") != PRODUCTS_SCHEMA:
        raise ValueError(
            f"products.json schema is {payload.get('schema')!r}, this module reads {PRODUCTS_SCHEMA!r}"
        )
    return tuple(
        CitedProduct(kind=item["kind"], key=item["key"]) for item in payload.get("products", [])
    )


def alive_keys(project_root: str | Path) -> frozenset[str]:
    """Return the keys cited by the runs that still run, the set an eviction keeps."""
    runs_dir = Path(project_root) / "runs"
    if not runs_dir.is_dir():
        return frozenset()
    keys: set[str] = set()
    for run_dir in runs_dir.iterdir():
        if run_dir.is_dir() and effective_status(run_dir) == "running":
            keys.update(product.key for product in read_cited(run_dir))
    return frozenset(keys)


__all__ = ["PRODUCTS_SCHEMA", "CitedProduct", "alive_keys", "read_cited", "write_cited"]
