"""The recharge stack must not survive the package that consumed it.

On a long chronicle the stack is the largest array a MODFLOW 6 model builds:
measured on the Nancon at 25 m, 1826 periods x 243 552 cells x 8 bytes = 3.31 GB.
On the shared calibration path FloPy is handed FILENAMES without the arrays, so
anything still holding the stack holds it for the whole solve, once per
concurrent trial. It used to be ``model.rch_spd``, an attribute nothing in the
package ever read.
"""

from __future__ import annotations

import gc
import weakref

import numpy as np
import pytest

from hydromodpy.solver.modflow6.builders.recharge import (
    RECHARGE_BINARY_MIN_PERIODS,
    externalize_recharge_spd,
)

N_CELLS = 32
N_PERIODS = RECHARGE_BINARY_MIN_PERIODS + 4


def _stack() -> dict[int, np.ndarray]:
    return {kper: np.full(N_CELLS, 1e-8 * (kper + 1), dtype="float64") for kper in range(N_PERIODS)}


def test_the_shared_payload_hands_filenames_and_not_the_arrays(tmp_path) -> None:
    payload = externalize_recharge_spd(_stack(), basename="m", shared_dir=tmp_path)

    assert set(payload) == set(range(N_PERIODS))
    for record in payload.values():
        assert "filename" in record
        assert "data" not in record, "the array travels to FloPy and stays alive with it"


def test_nothing_in_the_payload_keeps_the_stack_alive(tmp_path) -> None:
    spd = _stack()
    watchers = {kper: weakref.ref(arr) for kper, arr in spd.items()}

    payload = externalize_recharge_spd(spd, basename="m", shared_dir=tmp_path)
    del spd
    gc.collect()

    alive = [kper for kper, ref in watchers.items() if ref() is not None]
    assert not alive, f"{len(alive)} period(s) of the stack outlived their externalisation"
    assert len(payload) == N_PERIODS


def test_a_short_chronicle_is_left_internal_and_keeps_its_arrays(tmp_path) -> None:
    # Below the threshold the arrays ARE the payload, so they must stay alive:
    # the guard above must not be read as "always drop the data".
    short = {kper: np.zeros(N_CELLS) for kper in range(RECHARGE_BINARY_MIN_PERIODS - 1)}
    payload = externalize_recharge_spd(short, basename="m", shared_dir=tmp_path)

    assert payload is short


def test_the_model_never_carries_the_stack_as_an_attribute() -> None:
    # The retention this module exists for. `rch_spd` had no reader anywhere in
    # the package, so re-introducing the attribute is the regression to catch.
    import inspect

    from hydromodpy.solver.modflow6 import build

    # Comments are stripped: the line explaining WHY the attribute is gone names
    # it, and a test that matched its own explanation would never fail.
    code = [
        line for line in inspect.getsource(build).splitlines() if not line.lstrip().startswith("#")
    ]
    offenders = [line.strip() for line in code if "model.rch_spd" in line]
    assert not offenders, (
        f"the recharge stack is back on the model ({offenders}); it holds 3.31 GB per "
        "trial on a daily five-year chronicle and nothing reads it"
    )
