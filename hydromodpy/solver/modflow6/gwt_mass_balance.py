"""Parse the MODFLOW 6 GWT listing-file solute mass budget.

flopy's ``Mf6ListBudget`` only reads the GWF *volume* budget, so the GWT *mass*
budget ("MASS BUDGET FOR ENTIRE MODEL") is parsed here directly. Each per-output
block carries a CUMULATIVE column (mass, kg) and a RATES column (mass flux,
kg/s on the SI seconds clock); we keep the RATES column, which matches the m3/s
convention used for the GWF water budget.
"""

from __future__ import annotations

import re
from pathlib import Path

_MASS_BLOCK_MARKER = "MASS BUDGET FOR ENTIRE MODEL"
_BLOCK_SPLIT_RE = re.compile(r"MASS BUDGET FOR ENTIRE MODEL AT END OF TIME STEP")
_FLOAT_RE = re.compile(r"[-+]?\d+\.?\d*(?:[eE][-+]?\d+)?")


def find_gwt_listing(solver_output_dir: Path) -> Path | None:
    """Return the GWT ``.lst`` (the one with a solute mass budget), or None.

    The workspace also holds the GWF ``.lst`` (volume budget); the two are told
    apart by the mass-budget marker so naming differences (hashed model names) do
    not matter.
    """
    for lst in sorted(Path(solver_output_dir).glob("*.lst")):
        try:
            text = lst.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if _MASS_BLOCK_MARKER in text:
            return lst
    return None


def _rates_value(block: str, label: str) -> float | None:
    """Return the RATES (rightmost) value on the first ``label =`` line."""
    needle = f"{label} ="
    for line in block.splitlines():
        if needle in line:
            floats = _FLOAT_RE.findall(line)
            if floats:
                return float(floats[-1])
    return None


def parse_gwt_mass_balance(lst_path: Path) -> list[dict]:
    """Return one solute mass-balance record per GWT output time.

    Each record carries ``timestep`` (0-based output index, aligned with the
    concentration slices), ``total_in``/``total_out`` (kg/s) and ``percent_error``
    (dimensionless). Returns an empty list when the file is absent or has no
    mass-budget block.
    """
    if not lst_path.is_file():
        return []
    text = lst_path.read_text(encoding="utf-8", errors="ignore")
    blocks = _BLOCK_SPLIT_RE.split(text)[1:]  # drop the preamble before block 0
    records: list[dict] = []
    for idx, block in enumerate(blocks):
        total_in = _rates_value(block, "TOTAL IN")
        total_out = _rates_value(block, "TOTAL OUT")
        percent_error = _rates_value(block, "PERCENT DISCREPANCY")
        if total_in is None and total_out is None and percent_error is None:
            continue
        records.append(
            {
                "timestep": idx,
                "total_in": total_in,
                "total_out": total_out,
                "percent_error": percent_error,
            }
        )
    return records


__all__ = ["find_gwt_listing", "parse_gwt_mass_balance"]
