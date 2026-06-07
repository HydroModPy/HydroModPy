"""Execution-engine descriptors for the Boussinesq solver."""

from hydromodpy.solver.boussinesq.engines.catalog import (
    BoussinesqEngineSpec,
    resolve_engine_spec,
)

__all__ = ["BoussinesqEngineSpec", "resolve_engine_spec"]
