"""The methods the extractors call must exist on the REAL flopy class.

This module exists because of a concrete failure. `extract_discharge_from_cbc`
was rewritten to read by position, copying the pattern of the MODFLOW 6 budget
extractor. That extractor reads through hydromodpy's OWN reader, which exposes
``records`` and ``read_record``; ``flopy.utils.binaryfile.CellBudgetFile``
exposes neither. Every unit test passed, because the stand-ins implemented the
invented API, and the calibration crashed on the first trial after the solve.

A stand-in can only prove that the code does what the stand-in expects. These
tests interrogate the real class instead.
"""

from __future__ import annotations

import inspect

import flopy.utils.binaryfile as bf
import pytest

from hydromodpy.solver.modflow_common import calibration_extractors as cal


@pytest.mark.parametrize("name", ["get_indices", "get_record", "get_times", "close"])
def test_the_method_exists_on_the_real_cellbudgetfile(name: str) -> None:
    assert callable(getattr(bf.CellBudgetFile, name, None)), (
        f"CellBudgetFile has no {name!r}; the extractor calls it on the real class, "
        "and a stand-in that implements it would hide the failure until a run"
    )


def test_get_record_accepts_an_index_and_full3d() -> None:
    # The extractor passes a bare positional index and relies on full3D
    # defaulting to False, so a list package stays a record array.
    params = inspect.signature(bf.CellBudgetFile.get_record).parameters
    assert "idx" in params
    assert params["full3D"].default is False


def test_get_indices_selects_by_record_text() -> None:
    assert "text" in inspect.signature(bf.CellBudgetFile.get_indices).parameters


def test_the_extractor_calls_only_methods_the_real_class_has() -> None:
    """Every ``cbb.<name>`` in the module must be a real CellBudgetFile method.

    The guard that would have caught the crash: it reads the source for the
    calls actually made, instead of trusting a stand-in to describe them.
    """
    import re

    source = inspect.getsource(cal)
    called = set(re.findall(r"\bcbb\.([a-zA-Z_][a-zA-Z0-9_]*)", source))
    unknown = sorted(name for name in called if not hasattr(bf.CellBudgetFile, name))

    assert not unknown, f"the extractor calls {unknown} on a CellBudgetFile that has none"
