"""Public data-overview launcher facade under the canonical namespace."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from launchers.data_overview.config import DataOverviewConfig, OverviewSection
    from launchers.data_overview.launcher import DataOverviewLauncher
    from launchers.data_overview.state import DataOverviewState

__all__ = [
    "DataOverviewConfig",
    "DataOverviewLauncher",
    "DataOverviewState",
    "OverviewSection",
]


def __getattr__(name: str):
    if name == "DataOverviewConfig":
        from launchers.data_overview.config import DataOverviewConfig

        return DataOverviewConfig
    if name == "OverviewSection":
        from launchers.data_overview.config import OverviewSection

        return OverviewSection
    if name == "DataOverviewLauncher":
        from launchers.data_overview.launcher import DataOverviewLauncher

        return DataOverviewLauncher
    if name == "DataOverviewState":
        from launchers.data_overview.state import DataOverviewState

        return DataOverviewState
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
