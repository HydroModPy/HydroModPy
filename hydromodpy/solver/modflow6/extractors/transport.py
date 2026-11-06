"""Output adapter for MODFLOW 6 GWT transport results.

The concentration fields are stored as ``Mt3dmsExtractorBase`` stores them.
The file itself is the MODFLOW 6 head layout in double precision, not the
MT3DMS one: read as MT3DMS, its header gives a grid of 538 976 334 columns
(the text ``N   `` taken as an integer). The adapter adds the GWT solute
mass balance on top.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from hydromodpy.core.logging import get_logger
from hydromodpy.solver.modflow_common.mt3dms_extractor_base import Mt3dmsExtractorBase

logger = get_logger(__name__)


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


class Modflow6GwtOutputAdapter(Mt3dmsExtractorBase):
    """Ingest MODFLOW 6 GWT concentration outputs into a Catalog."""

    solver_name = "modflow6"

    def extract(
        self,
        sim_id: str,
        solver_output_dir: Path,
        store: Any,
        *,
        model_name: str | None = None,
    ) -> None:
        """Read concentration fields, then persist the GWT solute mass balance."""
        super().extract(sim_id, solver_output_dir, store, model_name=model_name)
        self._extract_solute_mass_balance(sim_id, solver_output_dir, store)

    def _open_concentration_file(self, ucn_path: Path) -> Any:
        """Open the GWT concentration file in the MODFLOW 6 double layout."""
        import flopy.utils.binaryfile as bf

        return bf.HeadFile(str(ucn_path), text="CONCENTRATION", precision="double")

    @staticmethod
    def _extract_solute_mass_balance(sim_id: str, solver_output_dir: Path, store: Any) -> None:
        """Parse the GWT .lst and store the solute mass budget (quantity='solute').

        The GWF water budget is written by the flow adapter under
        quantity='water', so the two coexist on the shared simulation id.
        """
        lst_path = find_gwt_listing(Path(solver_output_dir))
        if lst_path is None:
            return
        records = parse_gwt_mass_balance(lst_path)
        if not records:
            return
        writer = getattr(store, "write_mass_balances", None)
        if writer is None:
            return
        rows = [{**record, "quantity": "solute", "unit": "kg s-1"} for record in records]
        try:
            writer(sim_id, rows)
        except Exception:
            logger.debug("Could not persist GWT solute mass balance", exc_info=True)
