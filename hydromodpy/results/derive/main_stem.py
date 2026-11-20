"""The main stem of an SFR network: the longest path of reaches that ends at an outlet.

A reach that splits in two sends its flow down the branch with the larger share of it
(``ustrf``), and the longest path is taken over that tree. Without the column of shares,
the first downstream reach is followed. Reach numbers grow downstream, so one pass from
the first reach to the last gives the longest path to each reach.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def main_stem(reaches: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Return the rows of the main stem, head first, and their distance to the outlet in m.

    ``reaches`` is the table ``sfr_reaches`` sorted by ``network_id`` and ``reach``, with
    a default index. The distance is taken at the middle of each reach.
    """
    key = {
        (n, r): i
        for i, (n, r) in enumerate(zip(reaches["network_id"], reaches["reach"], strict=True))
    }
    length = reaches["rlen"].to_numpy(float)
    share = reaches["ustrf"].to_numpy(float) if "ustrf" in reaches else np.ones_like(length)
    down = []
    for n, ds in zip(reaches["network_id"], reaches["downstream"], strict=True):
        found = [key[(n, d)] for d in ds if (n, d) in key]
        down.append(max(found, key=lambda i: (share[i], -i)) if found else -1)
    upstream: list[list[int]] = [[] for _ in length]
    for i, d in enumerate(down):
        if d >= 0:
            upstream[d].append(i)
    span = length.copy()
    for i in range(len(length)):
        if upstream[i]:
            span[i] += max(span[j] for j in upstream[i])
    outlets = [i for i, d in enumerate(down) if d < 0]
    stem = [max(outlets, key=lambda i: span[i])]
    while upstream[stem[-1]]:
        stem.append(max(upstream[stem[-1]], key=lambda j: span[j]))
    stem = np.array(stem[::-1])
    to_outlet = np.cumsum(length[stem][::-1])[::-1]
    return stem, to_outlet - 0.5 * length[stem]
