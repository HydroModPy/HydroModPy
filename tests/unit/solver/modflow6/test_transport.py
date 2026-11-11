"""The decay guard of MODFLOW 6 GWT reads ``rate_decay`` in 1/s.

The GWT clock is seconds, so a rate written per day is about 86 400 times too
large and wipes the solute out within one output step. The guard warns when
the run spans more than 30 half-lives of the fastest rate. Each row gives the
stress period lengths in seconds, the rate and whether a warning is expected.
"""

from __future__ import annotations

import warnings
from types import SimpleNamespace

import pytest

from hydromodpy.solver.modflow6.transport import Modflow6Transport

_TEN_YEARS_SECONDS = 10 * 365.25 * 86400.0


def _transport(perlen) -> Modflow6Transport:
    transport = object.__new__(Modflow6Transport)
    transport.model_modflow = SimpleNamespace(perlen=perlen)
    return transport


_ROWS = [
    # 1e-9 1/s over ten years is 0.46 half-lives.
    pytest.param([_TEN_YEARS_SECONDS], 1e-9, False, id="per_second_rate_does_not_warn"),
    # 0.01 per day read as 1/s is 4.6 million half-lives over ten years.
    pytest.param([_TEN_YEARS_SECONDS], 0.01, True, id="per_day_value_warns"),
    # Two periods add up: 30 half-lives sit at 30 * ln 2 / rate seconds.
    pytest.param([5.0e6, 5.0e6], 30 * 0.6931471805599453 / 1.0e7 * 1.01, True, id="periods_add_up"),
    pytest.param(None, 0.01, False, id="no_perlen_does_not_warn"),
    pytest.param([0.0], 0.01, False, id="zero_duration_does_not_warn"),
]


@pytest.mark.parametrize(("perlen", "rate", "warns"), _ROWS)
def test_the_decay_guard_reads_the_rate_in_one_over_seconds(perlen, rate, warns) -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _transport(perlen)._warn_if_decay_annihilates_solute(rate)

    decay = [w for w in caught if "half-lives" in str(w.message)]
    assert bool(decay) is warns
    if warns:
        assert "1/s" in str(decay[0].message)
