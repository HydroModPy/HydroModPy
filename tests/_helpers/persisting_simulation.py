"""The part of a base configuration a promotion reads: whether the runs are persisted.

A promotion writes a run only when ``[simulation.results.persistence]``
``save_catalog`` is true, and says so when it is not. A stand-in for the base
configuration of a trial context must therefore carry that section; these
stand in for it, persisting by default.
"""

from __future__ import annotations

from types import SimpleNamespace

from pydantic import BaseModel, Field


class PersistenceStub(BaseModel):
    save_catalog: bool = True


class ResultsStub(BaseModel):
    persistence: PersistenceStub = Field(default_factory=PersistenceStub)


class SimulationStub(BaseModel):
    """The ``simulation`` field of a pydantic stand-in for the base configuration."""

    results: ResultsStub = Field(default_factory=ResultsStub)


def persisting_simulation(*, save_catalog: bool = True) -> SimpleNamespace:
    """Return a ``simulation`` namespace for a ``SimpleNamespace`` base configuration."""
    persistence = SimpleNamespace(save_catalog=save_catalog)
    return SimpleNamespace(results=SimpleNamespace(persistence=persistence))
