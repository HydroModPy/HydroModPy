"""A pin that is out of range, leaves the channel, lands on a lake or cycles is refused.

The error names a cell, so the caller can find the faulty projection of A.
"""

from __future__ import annotations

import numpy as np
import pytest

from tests.unit.core._descent_meshes import grid_descent

N = 6


def _top() -> np.ndarray:
    rows, cols = np.meshgrid(np.arange(N), np.arange(N), indexing="ij")
    return 10.0 + rows + cols


def _cell(row: int, col: int) -> int:
    return row * N + col


def _channel(*cells: int) -> np.ndarray:
    mask = np.zeros(N * N, dtype=bool)
    mask[list(cells)] = True
    return mask


def _pins(**links: int) -> np.ndarray:
    pins = np.full(N * N, -1, dtype=int)
    for donor, target in links.items():
        pins[int(donor.removeprefix("c"))] = target
    return pins


A, B, C = _cell(2, 2), _cell(2, 3), _cell(3, 3)
LAKE = np.where(np.arange(N * N) == _cell(3, 2), 0, -1)


@pytest.mark.parametrize(
    ("options", "message"),
    [
        (
            {
                "channel": _channel(A, B, C),
                "pinned_receiver": _pins(**{f"c{A}": B, f"c{B}": C, f"c{C}": A}),
            },
            "cycle through cell",
        ),
        (
            {"channel": _channel(A, B), "pinned_receiver": _pins(**{f"c{A}": A})},
            f"cycle through cell {A}",
        ),
        (
            {
                "channel": _channel(A),
                "pinned_receiver": _pins(**{f"c{A}": _cell(3, 2)}),
                "lake_of": LAKE,
            },
            f"cell {A} is pinned onto a lake cell",
        ),
        (
            {"channel": _channel(A, _cell(3, 2)), "lake_of": LAKE},
            f"cell {_cell(3, 2)} is a channel cell inside a lake",
        ),
        (
            {"channel": _channel(A), "pinned_receiver": _pins(**{f"c{A}": N * N})},
            f"cell {A} is pinned to {N * N}",
        ),
        (
            {"channel": _channel(B), "pinned_receiver": _pins(**{f"c{A}": B})},
            f"cell {A} is pinned but is not a channel cell",
        ),
        (
            {"channel": _channel(A), "pinned_receiver": _pins(**{f"c{A}": B})},
            f"cell {A} is pinned onto a cell outside the channel",
        ),
        (
            {"pinned_receiver": _pins(**{f"c{A}": B})},
            "pinned_receiver needs channel",
        ),
    ],
    ids=[
        "cycle",
        "self-pin",
        "onto-lake",
        "channel-in-lake",
        "out-of-range",
        "non-channel-donor",
        "non-channel-target",
        "no-channel",
    ],
)
def test_the_pin_is_refused(options: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        grid_descent(_top(), **options)
