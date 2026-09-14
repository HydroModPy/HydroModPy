"""LAK stage-volume-area table coercion and output-naming helpers.

Private helpers behind ``build_lake_table`` / ``build_lak_package_args``: the
abacus-row coercion and the file-stem / length-bounded lake-tag naming used for
LAK output files and OBS names.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence

import numpy as np


def _abacus_rows(lake_id: str, abacus: object) -> list[tuple[float, float, float]]:
    """Coerce one abacus payload to a list of ``(stage, volume, sarea)`` tuples."""
    if abacus is None:
        raise ValueError(
            f"flow.sinks_sources.lakes.{lake_id}.abacus is required to build the LAK "
            "stage-volume-area table."
        )
    if isinstance(abacus, Mapping):
        stage = np.asarray(abacus["stage"], dtype=float).ravel()
        volume = np.asarray(abacus["volume"], dtype=float).ravel()
        sarea = np.asarray(abacus["sarea"], dtype=float).ravel()
        if not (stage.size == volume.size == sarea.size):
            raise ValueError(
                f"flow.sinks_sources.lakes.{lake_id}.abacus stage, volume and sarea "
                "columns must have the same length."
            )
        return [
            (float(s), float(v), float(a)) for s, v, a in zip(stage, volume, sarea, strict=True)
        ]

    if not isinstance(abacus, Sequence):
        raise ValueError(
            f"flow.sinks_sources.lakes.{lake_id}.abacus must be a mapping of "
            "stage/volume/sarea columns or a sequence of (stage, volume, sarea) rows."
        )
    rows: list[tuple[float, float, float]] = []
    for entry in abacus:
        triple = tuple(float(x) for x in entry)
        if len(triple) != 3:
            raise ValueError(
                f"flow.sinks_sources.lakes.{lake_id}.abacus rows must be (stage, volume, sarea)."
            )
        rows.append((triple[0], triple[1], triple[2]))
    return rows


def _lak_output_stem(model) -> str:
    """Return the output file stem for LAK files (mirrors model.model_output_name)."""
    name = getattr(model, "model_output_name", None)
    if name:
        return str(name)
    return str(getattr(model, "model_name", "") or "model")


_MAX_LAKE_TAG_LEN = 24  # keeps the longest obs name within MF6's 40-char LENOBSNAME


def _safe_lake_tag(lake_id: str) -> str:
    """Return a filename-safe, length-bounded tag for one lake id.

    Bounded so the longest composed obs name (``{tag}_ext_outflow_{n}``) stays
    within MF6's 40-char observation-name limit; a long id is shortened
    deterministically with a hash suffix so the extractor still keys it exactly.
    """
    safe = "".join(ch if ch.isalnum() else "_" for ch in str(lake_id))
    if len(safe) <= _MAX_LAKE_TAG_LEN:
        return safe
    digest = hashlib.blake2b(str(lake_id).encode("utf-8"), digest_size=3).hexdigest()
    return f"{safe[: _MAX_LAKE_TAG_LEN - 7]}_{digest}"
