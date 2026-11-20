"""The ranking of the rows of a campaign summary."""

from __future__ import annotations

import pandas as pd

from hydromodpy.results.run.ranking import rank_rows


def test_rank_rows_follows_the_direction_of_the_metric() -> None:
    frame = pd.DataFrame(
        {
            "case_id": ["a-x", "b-x", "a-y"],
            "site": ["a", "b", "a"],
            "rmse": [0.3, 0.1, 0.2],
            "score_window_start": ["2016-01-01"] * 3,
        }
    )

    assert rank_rows(frame, "rmse")["case_id"].tolist() == ["b-x", "a-y", "a-x"]
    assert rank_rows(frame, "rmse", by="site")["case_id"].tolist() == ["a-y", "b-x"]
