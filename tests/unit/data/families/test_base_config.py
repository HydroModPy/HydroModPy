"""``BaseVariableConfig`` accepts a full window or none, never a half one."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from hydromodpy.data.variables.recharge.config import RechargeConfig, RechargeSourceConfig

SOURCES = [
    RechargeSourceConfig(
        source="synthetic",
        freq="MS",
        start_date="2019-01-01",
        periods=12,
        values=[1.0] * 12,
    )
]


@pytest.mark.parametrize(
    ("declared", "missing"),
    [
        ({"date_start": "2019-01-01"}, "date_end"),
        ({"date_end": "2025-12-31"}, "date_start"),
    ],
)
def test_half_declared_window_is_rejected(declared: dict[str, str], missing: str) -> None:
    with pytest.raises(ValidationError, match=f"{missing} is missing"):
        RechargeConfig(sources=SOURCES, **declared)


def test_reversed_window_is_rejected() -> None:
    with pytest.raises(ValidationError, match="date_start must be before date_end"):
        RechargeConfig(sources=SOURCES, date_start="2025-12-31", date_end="2019-01-01")


def test_a_variable_read_alone_reads_a_workspace_name_in_its_folder(tmp_path: Path) -> None:
    from hydromodpy.data.variables.hydrometry.config import HydrometryConfig

    project = tmp_path / "ws" / "projects" / "aber"
    project.mkdir(parents=True)
    (tmp_path / "ws" / "data" / "hydrometry").mkdir(parents=True)
    (project / "project.toml").write_text(
        '[hydrometry]\n[[hydrometry.sources]]\nsource = "file"\npath = "workspace:."\n',
        encoding="utf-8",
    )

    config = HydrometryConfig.from_toml(project / "project.toml")

    assert config.sources[0].path == tmp_path / "ws" / "data" / "hydrometry"
