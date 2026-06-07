"""Progress reporting and rate-payload scaling helpers for MODFLOW-NWT.

These helpers are kept out of the solver class to avoid mixing
solver lifecycle code with stdout parsing and unit conversion.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

import numpy as np
from tqdm import tqdm

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

# Map MODFLOW ITMUNI codes to seconds per time unit.
# Used to convert FieldParam SI values (m/s) to solver time units.
ITMUNI_TO_SECONDS: dict[int, float] = {
    0: 1.0,  # undefined treated as seconds
    1: 1.0,  # seconds
    2: 60.0,  # minutes
    3: 3600.0,  # hours
    4: 86400.0,  # days
    5: 31557600.0,  # years (365.25 days)
}

_SOLVING_RE = re.compile(
    r"Solving:\s+Stress period:\s+(\d+)\s+Time step:\s+(\d+)",
    re.IGNORECASE,
)


def scale_rate_payload(payload: object, factor: float) -> object:
    """Scale a recharge / EVT rate payload by ``factor``.

    Handles the three shapes produced by ``flow_to_modflow_adapter``:
    a scalar (steady-state), a 2D ndarray (one map for the whole run),
    or a ``{kper: scalar | ndarray}`` mapping (one entry per stress
    period). Returns ``None`` unchanged so the caller can keep its
    existing skip logic.
    """
    if payload is None:
        return None
    if isinstance(payload, Mapping):
        return {kper: scale_rate_payload(value, factor) for kper, value in payload.items()}
    if isinstance(payload, np.ndarray):
        return payload * factor
    return float(payload) * factor


def run_model_with_progress(
    mf_model,
    nper: int,
) -> tuple[bool, list[str]]:
    """Run a MODFLOW model while showing a tqdm progress bar.

    Intercepts solver stdout, parses ``Solving: Stress period: N`` lines
    to advance the bar, and suppresses the raw output. Non-solving lines
    (header, termination message, etc.) are forwarded to the logger.
    """
    import flopy.mbase as _mbase

    pbar = tqdm(
        total=nper,
        desc="[INFO] MODFLOW solving",
        unit="sp",
        disable=nper <= 1,
    )
    last_sp = 0

    def _progress_print(line: str) -> None:
        nonlocal last_sp
        m = _SOLVING_RE.search(line)
        if m:
            sp = int(m.group(1))
            if sp > last_sp:
                pbar.update(sp - last_sp)
                last_sp = sp
            return
        stripped = line.strip()
        if stripped:
            logger.debug("%s", stripped)

    try:
        success, buff = _mbase.run_model(
            mf_model.exe_name,
            mf_model.namefile,
            model_ws=mf_model.model_ws,
            silent=False,
            report=True,
            custom_print=_progress_print,
        )
    finally:
        pbar.close()

    return success, buff


__all__ = ["ITMUNI_TO_SECONDS", "run_model_with_progress", "scale_rate_payload"]
