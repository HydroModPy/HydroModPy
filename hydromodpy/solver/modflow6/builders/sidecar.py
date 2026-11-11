"""The sidecar files a MODFLOW 6 build writes beside the model."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping


def write_sidecar(model, suffix: str, payload: Mapping[str, object]) -> None:
    """Write ``{model_output_name}{suffix}`` next to the solver files, for the extractor.

    The sidecars travel with the model files, so the post-run extraction needs no
    live flopy object. ``.lak.meta.json`` re-keys the LAK obs CSV by ``(lake_id,
    totim)`` and isolates the under-dam leakage, ``.sfr.meta.json`` does the same
    for SFR, and ``.lake_abacus.json`` carries the bed-reconstruction comparison.
    """
    meta_path = os.path.join(str(model.full_path), f"{model.model_output_name}{suffix}")
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(dict(payload), fh, sort_keys=True)
