"""A share of the cost prints so that a small one does not read as off.

``{hydrograph = 1000, network = 1}`` printed ``share 0%`` for the network, which
reads as a block that does not count. Below 1 % a share keeps one significant
digit, and above 99 % its complement's, so the pair still adds up to 100 %.
"""

from __future__ import annotations

import pytest

from hydromodpy.cli.commands.calibrate import _percent, _shares_text


@pytest.mark.parametrize(
    ("share", "printed"),
    [
        (1.0, "100%"),
        (0.5, "50%"),
        (0.25, "25%"),
        (0.0, "0%"),
        (1 / 101, "1%"),
        (100 / 101, "99%"),
        (1 / 1001, "0.1%"),
        (1000 / 1001, "99.9%"),
        (0.00004, "0.004%"),
        (0.00096, "0.1%"),
    ],
)
def test_a_share_prints_as_a_reader_reads_it(share: float, printed: str) -> None:
    assert _percent(share) == printed


def test_a_small_block_of_a_result_is_not_printed_as_zero() -> None:
    assert _shares_text({"hydrograph": 1000 / 1001, "network": 1 / 1001}) == (
        "hydrograph 99.9%, network 0.1%"
    )
