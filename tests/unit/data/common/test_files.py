"""Readers of the user's station files: a locations table and one chronicle per station."""

import pandas as pd
import pytest

from hydromodpy.data.common.files import read_locations_csv, read_timeseries_csv


def test_custom_timeseries_columns(tmp_path):
    csv_path = tmp_path / "ts.csv"
    pd.DataFrame({"date": ["2020-01-01"], "debit": [3.14]}).to_csv(csv_path, index=False)

    df = read_timeseries_csv(csv_path, col_datetime="date", col_value="debit")

    assert df["value"].iloc[0] == pytest.approx(3.14)


REFUSALS = [
    pytest.param(read_locations_csv, {"x": [1], "y": [2]}, "missing id column", id="no id column"),
    pytest.param(read_timeseries_csv, {"value": [1]}, "missing datetime column", id="no datetime"),
]


@pytest.mark.parametrize(("reader", "columns", "message"), REFUSALS)
def test_refusals(reader, columns, message, tmp_path):
    csv_path = tmp_path / "table.csv"
    pd.DataFrame(columns).to_csv(csv_path, index=False)

    with pytest.raises(ValueError, match=message):
        reader(csv_path)
