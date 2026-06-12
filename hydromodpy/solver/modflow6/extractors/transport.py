"""Output adapter for MODFLOW 6 GWT transport results.

The concentration binary format (``.ucn``) is identical to what MT3DMS
produces, so this adapter derives from ``Mt3dmsExtractorBase`` for the
concentration fields and adds the GWT solute mass balance on top.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.core.logging import get_logger
from hydromodpy.solver.modflow6.gwt_mass_balance import find_gwt_listing, parse_gwt_mass_balance
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
