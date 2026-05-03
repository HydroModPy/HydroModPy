"""Shared base for MT3DMS / MF6-GWT concentration output adapters.

The unformatted concentration file (``.ucn``) format is identical between
MT3DMS (shipped with the NWT toolchain) and MODFLOW 6's GWT model. Both
backends derive thin subclasses from ``Mt3dmsExtractorBase`` that only set
their ``solver_name`` class attribute.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)


class Mt3dmsExtractorBase:
    """Read MT3DMS / MF6-GWT binary outputs and inject them into a SimulationCatalog.

    Expects a solver output directory containing ``{model_name}.ucn``
    (unformatted concentration file). Subclasses must override
    ``solver_name``.
    """

    solver_name: str
    category = "distributed"

    def extract(
        self,
        sim_id: str,
        solver_output_dir: Path,
        store: Any,
        *,
        model_name: str | None = None,
    ) -> None:
        """Read .ucn file and write concentration fields into the store."""
        import flopy.utils.binaryfile as bf

        solver_output_dir = Path(solver_output_dir)
        if model_name is None:
            ucn_files = list(solver_output_dir.glob("*.ucn")) + list(
                solver_output_dir.glob("*.UCN")
            )
            if not ucn_files:
                raise FileNotFoundError(f"No .ucn file in {solver_output_dir}")
            model_name = ucn_files[0].stem

        ucn_path = solver_output_dir / f"{model_name}.ucn"
        if not ucn_path.exists():
            ucn_path = solver_output_dir / f"{model_name}.UCN"

        # MT3DMS uses UcnFile; MF6-GWT uses the same binary format as HeadFile.
        try:
            ucn = bf.UcnFile(str(ucn_path))
        except (EOFError, Exception):
            ucn = bf.HeadFile(str(ucn_path), text="concentration")
        times = ucn.get_times()
        n_timesteps = len(times)

        conc0 = ucn.get_data(totim=times[0])
        if conc0.ndim == 3:
            nlay, nrow, ncol = conc0.shape
            n_cells = nrow * ncol
        elif conc0.ndim == 2:
            nlay = 1
            n_cells = conc0.shape[-1]
        else:
            nlay = 1
            n_cells = conc0.size

        logger.info(
            "Extracting MT3DMS concentration: %d timesteps, %d layers, %d cells",
            n_timesteps,
            nlay,
            n_cells,
        )

        for t, time in enumerate(times):
            conc = ucn.get_data(totim=time)
            values = conc.reshape(nlay, n_cells)
            store.write_field(
                sim_id,
                "concentration",
                t,
                values,
                n_timesteps=n_timesteps if t == 0 else None,
            )

        ucn.close()

    def derive(
        self,
        sim_id: str,
        store: Any,
        config: dict | None = None,
    ) -> None:
        """Compute derived variables from stored concentration fields."""
        from hydromodpy.simulation.extraction.extractors.derived import compute_derived

        cfg = config or {}
        compute_derived(sim_id, store, cfg)
