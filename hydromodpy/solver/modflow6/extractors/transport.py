"""Output adapter for MODFLOW 6 GWT transport results.

The concentration fields are stored as ``Mt3dmsExtractorBase`` stores them.
The file itself is the MODFLOW 6 head layout in double precision, not the
MT3DMS one: read as MT3DMS, its header gives a grid of 538 976 334 columns
(the text ``N   `` taken as an integer). The adapter adds the GWT solute
mass balance on top.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.core.logging import get_logger
from hydromodpy.solver.modflow6.extractors._gwt_mass_balance import (
    find_gwt_listing,
    parse_gwt_mass_balance,
)
from hydromodpy.solver.modflow_common.mt3dms_extractor_base import Mt3dmsExtractorBase

logger = get_logger(__name__)


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
        rows = [{**record, "quantity": "solute", "unit": "kg/s"} for record in records]
        try:
            writer(sim_id, rows)
        except Exception:
            logger.debug("Could not persist GWT solute mass balance", exc_info=True)
