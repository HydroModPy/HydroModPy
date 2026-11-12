"""A table {period: rate} reaches every solver with integer keys and every period.

A TOML key is a string, so the table the description of ``values`` promises used
to stop MODFLOW 6 and Boussinesq on a type error. A partial table repeated its last
value under MODFLOW-NWT and read zero under Boussinesq, without a word.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from hydromodpy.model.forcing.validation import complete_period_table, integer_period_keys
from hydromodpy.model.model import ModelTime
from hydromodpy.model.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.solver.boussinesq.forcing.common import ForcingCommonMixin
from hydromodpy.solver.modflow6.builders.recharge import recharge_to_spd
from hydromodpy.solver.modflow_nwt.nwt.payloads.recharge_etp import assemble_rch_data
from tests._helpers.model_factory import make_model

pytestmark = pytest.mark.fast

LABEL = "flow.sinks_sources.recharge.values"


@pytest.mark.parametrize("key", ["january", "1.5", "-1", 1.5, True])
def test_a_key_that_is_no_period_is_refused(key: object) -> None:
    with pytest.raises(ValidationError, match="period index"):
        FlowRechargeConfig(values={key: 1.0})


def test_the_same_period_written_twice_is_refused() -> None:
    with pytest.raises(ValueError, match="names period 1 twice"):
        integer_period_keys({"1": 1.0, 1: 2.0}, label=LABEL)


def test_a_period_outside_the_run_is_named() -> None:
    with pytest.raises(ValueError, match=r"names period\(s\) \[5\]"):
        complete_period_table({0: 1.0, 1: 2.0, 5: 3.0}, nper=2, label=LABEL)


def test_modflow6_reads_a_complete_table_and_refuses_a_partial_one() -> None:
    model = SimpleNamespace(nper=2, ncpl=3, first_clim="mean", steady=[False, False])

    model.recharge = {0: 1.0, 1: 2.0}
    assert recharge_to_spd(model)[1] == pytest.approx([2.0, 2.0, 2.0])

    model.recharge = {0: 1.0}
    with pytest.raises(ValueError, match="gives no rate"):
        recharge_to_spd(model)


def test_modflow_nwt_reads_a_complete_table_and_refuses_a_partial_one() -> None:
    steady = np.array([False, False])
    kwargs = {"first_clim": "mean", "steady": steady, "nper": 2, "durations": [1.0, 1.0]}

    assert assemble_rch_data(payload={0: 1.0, 1: 2.0}, **kwargs) == {0: 1.0, 1: 2.0}
    with pytest.raises(ValueError, match="gives no rate"):
        assemble_rch_data(payload={0: 1.0}, **kwargs)


def test_modflow_nwt_reads_a_list_as_the_other_solvers_do() -> None:
    kwargs = {"first_clim": "mean"}

    steady = np.array([True])
    assert assemble_rch_data(
        payload=[1.0, 2.0, 6.0], steady=steady, nper=1, durations=[1.0], **kwargs
    )[0] == pytest.approx(3.0)
    transient = np.array([False, False])
    kwargs["durations"] = [1.0, 1.0]
    assert assemble_rch_data(payload=[1.5], steady=transient, nper=2, **kwargs) == {0: 1.5, 1: 1.5}
    with pytest.raises(ValueError, match="holds 3 rates and this run has 2 periods"):
        assemble_rch_data(payload=[1.0, 2.0, 6.0], steady=transient, nper=2, **kwargs)


class _Boussinesq(ForcingCommonMixin):
    inputs = make_model(time=ModelTime(grid=None, regime="transient", first_period_steady=False))


def test_boussinesq_reads_a_complete_table_and_refuses_a_partial_one() -> None:
    kwargs = {"nper": 2, "first_clim": "mean", "label": LABEL}

    series = _Boussinesq().recharge_period_series(payload={0: 1.0, 1: 2.0}, **kwargs)
    assert series.tolist() == [1.0, 2.0]
    with pytest.raises(ValueError, match="gives no rate"):
        _Boussinesq().recharge_period_series(payload={0: 1.0}, **kwargs)
