"""The last state of a run, in double precision, for the run that starts from it.

Every flow extractor writes ``<run>/final_state/`` once the solve is done: the
head of the last time step, the stage of each lake and, when SFR routes with
storage, the stage of each reach. It is a Zarr 3 group in float64 compressed
without loss, because a restart must not change the state it starts from:
``fields.zarr`` may round the head to 2^-17 under the compact precision, which
is 0.8 mm on 100 m. The next window of a chain and ``[flow] restart_from`` read
it through ``read_prior_state``.

The group holds ``head`` shaped ``(nlay, ncpl)`` with NaN on inactive cells,
``lake_stage`` with the attribute ``lake_ids``, ``sfr_stage`` with the
attribute ``reaches``, and the attributes ``schema`` and ``at``. It is written
in a scratch folder under ``.hmp/`` and moved into place, so a reader never
sees half of it.
"""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

import numpy as np
import pandas as pd

from hydromodpy.core.state.layout import INTERNAL_DIRNAME
from hydromodpy.results.storage.contract import FINAL_STATE_DIRNAME
from hydromodpy.results.zarr_store.constants import BLOSC_ZSTD

FINAL_STATE_SCHEMA = "hydromodpy.final_state.v1"
"""The schema attribute of a ``final_state/`` group."""


@dataclass(frozen=True, slots=True, eq=False)
class FinalState:
    """The last state of a run, in metres and float64.

    ``head`` is shaped ``(nlay, ncpl)``, NaN on inactive cells. ``lake_stages``
    maps a lake id to its stage and ``sfr_stages`` an SFR reach number, from 0,
    to its stage. ``at`` is the end of the last period, or ``None`` for a
    steady run without ``[simulation.time]``.
    """

    head: np.ndarray
    lake_stages: Mapping[str, float] = MappingProxyType({})
    sfr_stages: Mapping[int, float] = MappingProxyType({})
    at: pd.Timestamp | None = None

    def __post_init__(self) -> None:
        head = np.array(self.head, dtype=np.float64, copy=True)
        if head.ndim != 2:
            raise ValueError(
                f"A final state head is shaped (nlay, ncpl); got {head.ndim} dimension(s)."
            )
        head = np.where(np.isnan(head), np.nan, head) + 0.0
        head.setflags(write=False)
        object.__setattr__(self, "head", head)
        object.__setattr__(
            self,
            "lake_stages",
            MappingProxyType({str(k): float(v) for k, v in dict(self.lake_stages).items()}),
        )
        object.__setattr__(
            self,
            "sfr_stages",
            MappingProxyType({int(k): float(v) for k, v in dict(self.sfr_stages).items()}),
        )
        if self.at is not None:
            object.__setattr__(self, "at", pd.Timestamp(self.at))


def final_state_dir(run_dir: Path) -> Path:
    """Return ``<run>/final_state``."""
    return Path(run_dir) / FINAL_STATE_DIRNAME


def write_final_state(run_dir: Path, state: FinalState) -> Path:
    """Write ``state`` to ``<run>/final_state/`` and return that folder.

    A group already there is replaced, as a rerun of the solve replaces it.
    """
    import zarr

    target = final_state_dir(run_dir)
    scratch = Path(run_dir) / INTERNAL_DIRNAME / f"{FINAL_STATE_DIRNAME}.partial"
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.parent.mkdir(parents=True, exist_ok=True)
    root = zarr.open_group(str(scratch), mode="w", zarr_format=3)
    root.attrs.update(
        {
            "schema": FINAL_STATE_SCHEMA,
            "at": None if state.at is None else state.at.isoformat(),
        }
    )
    root.create_array("head", data=state.head, compressors=BLOSC_ZSTD)
    lake_ids = list(state.lake_stages)
    lakes = root.create_array(
        "lake_stage",
        data=np.array([state.lake_stages[lake] for lake in lake_ids], dtype=np.float64),
        compressors=BLOSC_ZSTD,
    )
    lakes.attrs["lake_ids"] = lake_ids
    if state.sfr_stages:
        reaches = sorted(state.sfr_stages)
        sfr = root.create_array(
            "sfr_stage",
            data=np.array([state.sfr_stages[reach] for reach in reaches], dtype=np.float64),
            compressors=BLOSC_ZSTD,
        )
        sfr.attrs["reaches"] = reaches
    if target.exists():
        shutil.rmtree(target)
    scratch.replace(target)
    return target


def read_final_state(run_dir: Path) -> FinalState | None:
    """Return the final state of the run at ``run_dir``, or ``None`` when it has none.

    A run of HydroModPy 2.0 has no ``final_state/``; its last head is read from
    ``fields.zarr`` by ``read_prior_state``.
    """
    import zarr

    folder = final_state_dir(run_dir)
    if not folder.is_dir():
        return None
    root = zarr.open_group(str(folder), mode="r")
    schema = root.attrs.get("schema")
    if schema != FINAL_STATE_SCHEMA:
        raise ValueError(
            f"{folder} has schema {schema!r}; this version reads {FINAL_STATE_SCHEMA!r}."
        )
    head = np.asarray(root["head"][:], dtype=np.float64)
    lake_ids = [str(lake) for lake in root["lake_stage"].attrs.get("lake_ids", [])]
    lake_values = np.asarray(root["lake_stage"][:], dtype=np.float64).reshape(-1)
    sfr: dict[int, float] = {}
    if "sfr_stage" in root:
        reaches = [int(reach) for reach in root["sfr_stage"].attrs.get("reaches", [])]
        sfr_values = np.asarray(root["sfr_stage"][:], dtype=np.float64).reshape(-1)
        sfr = dict(zip(reaches, (float(v) for v in sfr_values), strict=True))
    at = root.attrs.get("at")
    return FinalState(
        head=head,
        lake_stages=dict(zip(lake_ids, (float(v) for v in lake_values), strict=True)),
        sfr_stages=sfr,
        at=None if at is None else pd.Timestamp(at),
    )


__all__ = [
    "FINAL_STATE_SCHEMA",
    "FinalState",
    "final_state_dir",
    "read_final_state",
    "write_final_state",
]
