"""Pydantic configuration models for ``[simulation.results]``."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.persistence import PersistenceConfig
from hydromodpy.core.config_kit.profile import Profile


class ResultsConfig(HydroModelBase):
    """Configuration for ``[simulation.results]``.

    Controls whether simulation outputs are stored in the Catalog, which raw
    solver files are kept and how much of the per-cell budget a run keeps.
    Every derived field is rebuilt on read. Automated export formats live in
    the top-level ``[export]`` section (:class:`ExportConfig`), not here.
    """

    persistence: Annotated[PersistenceConfig, Profile.USER] = Field(
        default_factory=PersistenceConfig,
        description=(
            "Simulation-run persistence switch passed to the result catalog "
            "(DuckDB rows, Zarr fields, Parquet tables)."
        ),
    )
    keep_solver_files: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Keep the raw solver files (.hds, .cbc, .lst) once their results are stored. "
            "Off, they are deleted; turn it on to read the listing file of a run that "
            "did not converge."
        ),
    )
    keep_per_cell_budget: Annotated[bool, Profile.DEV] = Field(
        default=True,
        description=(
            "Keep every per-cell budget term the solver produces, storage terms included, "
            "so every flux can be mapped, exported and read after the run is sealed "
            "(hmp export, hmp viz show, the Python API), and every derived field is rebuilt "
            "on read. False keeps only the terms the run's own consumers read: the figures "
            "of [display].figures, the [[export]] blocks, the calibration criterion and the "
            "seepage mask of a surface-excess solver. A later read of anything else then "
            "needs a new run. On a daily run, true is the heaviest group of the store: about "
            "300 MB for six daily years on about 21 000 cells, 3.7 times the head."
        ),
    )


__all__ = ["ResultsConfig"]
