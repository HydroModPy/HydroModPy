"""What a backend may write into the store of a run, and what is refused.

A backend writes only the fields and tables its ``writes`` declares, and a
simulated series carries a name the registry describes. The extract step reads
the names of the store before and after the extractor of a backend runs, and
refuses what the extractor added outside ``writes``. A check after the extract
also sees what an extractor writes through a direct Zarr handle. The series are
refused at write time, in the three series methods of the store, because a
series has no name in ``writes``: a backend declares the table ``timeseries``.

The pipeline writes some names itself for every backend: the groups
``geographic/``, ``mesh/`` and ``forcing/``, the coordinates ``face``, ``layer``
and ``time``, the two arrays the store writes itself (``crs`` and
``quantization_info``), and the tables ``simulation``, ``parameters``,
``provenance``, ``metrics``, ``mesh_face_families``, ``timeseries`` and
``geographic_*``. They are never judged. A ``*`` of a ``writes`` pattern
stands for one path segment.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from pathlib import Path

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.results.field_registry import FIELD_REGISTRY, TIME_SERIES_REGISTRY
from hydromodpy.results.storage.contract import (
    FIELDS_STORE_NAME,
    PARQUET_FILE_SUFFIX,
    TABLES_DIRNAME,
)

PIPELINE_PREFIXES: tuple[str, ...] = ("geographic/", "mesh/", "forcing/")
PIPELINE_ARRAYS: frozenset[str] = frozenset({"face", "layer", "time", "crs", "quantization_info"})
PIPELINE_TABLES: frozenset[str] = frozenset(
    {"simulation", "parameters", "provenance", "metrics", "mesh_face_families", "timeseries"}
)
PIPELINE_TABLE_PREFIXES: tuple[str, ...] = ("geographic_",)

_FIELD_NAMES = frozenset(descriptor.public_name for descriptor in FIELD_REGISTRY.values())


def pattern_regex(pattern: str) -> re.Pattern[str]:
    """Return the regex of a ``writes`` pattern, ``*`` standing for one path segment."""
    pieces = (re.escape(piece) for piece in pattern.split("*"))
    return re.compile("^" + "[^/]+".join(pieces) + "$")


def stored_arrays(fields: Path) -> list[str]:
    """Return the path of each array of a Zarr 3 store, read from its metadata files."""
    if not fields.is_dir():
        return []
    names = []
    for meta in sorted(fields.rglob("zarr.json")):
        if meta.parent == fields:
            continue
        if json.loads(meta.read_text(encoding="utf-8")).get("node_type") == "array":
            names.append(meta.parent.relative_to(fields).as_posix())
    return names


def stored_tables(tables: Path) -> list[str]:
    """Return the name of each table of a run, the stem of its Parquet file."""
    if not tables.is_dir():
        return []
    return sorted(path.stem for path in tables.glob(f"*{PARQUET_FILE_SUFFIX}"))


def stored_names(run_dir: Path) -> frozenset[str]:
    """Return the arrays of ``fields.zarr`` and the tables of ``tables.parquet`` of a run.

    The names the pipeline writes itself are left out. A run that keeps no
    Zarr and no Parquet gives an empty set.
    """
    arrays = (
        name
        for name in stored_arrays(run_dir / FIELDS_STORE_NAME)
        if not name.startswith(PIPELINE_PREFIXES) and name not in PIPELINE_ARRAYS
    )
    tables = (
        name
        for name in stored_tables(run_dir / TABLES_DIRNAME)
        if name not in PIPELINE_TABLES and not name.startswith(PIPELINE_TABLE_PREFIXES)
    )
    return frozenset((*arrays, *tables))


def refuse_undeclared(added: Iterable[str], writes: Sequence[str], *, backend: str) -> None:
    """Refuse a name a backend added to the store that its ``writes`` does not declare.

    ``added`` holds the names the extractor of the backend added, read by
    :func:`stored_names` before and after it ran. Raises
    :class:`~hydromodpy.core.exceptions.DataContractViolation` on the first
    name, in sorted order, that no name or pattern of ``writes`` matches.
    """
    patterns = [pattern_regex(pattern) for pattern in writes]
    for name in sorted(added):
        if name.startswith(PIPELINE_PREFIXES) or name in PIPELINE_ARRAYS:
            continue
        if name in PIPELINE_TABLES or name.startswith(PIPELINE_TABLE_PREFIXES):
            continue
        if not any(regex.match(name) for regex in patterns):
            raise DataContractViolation(
                f"Backend {backend} wrote {name!r}, which its writes does not declare. "
                f"Add {name!r} or its pattern to writes of the {backend} adapter."
            )


def refuse_unknown_series(variables: Iterable[str]) -> None:
    """Refuse a simulated series whose name no descriptor holds.

    A simulated series is named by a key of ``TIME_SERIES_REGISTRY``, or by the
    public name of a field it samples at one point, ``head`` of an observation
    point for example. An observed series carries the name of its data
    variable and is not judged here.
    """
    for variable in sorted(set(variables)):
        if variable in TIME_SERIES_REGISTRY or variable in _FIELD_NAMES:
            continue
        raise DataContractViolation(
            f"A simulated series named {variable!r} has no descriptor. Add it to "
            "TIME_SERIES_REGISTRY in hydromodpy/results/field_registry.py with its unit."
        )
