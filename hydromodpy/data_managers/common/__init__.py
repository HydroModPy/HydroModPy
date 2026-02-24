"""Shared building blocks for data manager implementations.

This package centralizes reusable logic shared by multiple managers
(hydrometry, piezometry, and future managers):
- station-level generic utilities,
- station-set geometric/loading helpers,
- loader-level HTTP/date/reference helpers,
- small cross-cutting utility functions.
"""

from .base_loaders import BaseApiLoader, BaseLocalLoader
from .base_station import BaseStation
from .base_station_set import BaseStationSet
from .utils import safe_file_token

__all__ = [
    "BaseApiLoader",
    "BaseLocalLoader",
    "BaseStation",
    "BaseStationSet",
    "safe_file_token",
]
