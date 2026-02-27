"""
Local file loader for water quality data.  Mimics the structure of
piezometry/loaders_local.py but reads user-provided CSVs instead of querying
an API.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence, Tuple

import pandas as pd

try:
    from ..common.base_loaders import BaseLocalLoader
    from .water_quality import WaterQuality
except ImportError:  # pragma: no cover
    import sys

    _manager_root = Path(__file__).resolve().parents[1]
    _manager_dir = Path(__file__).resolve().parent
    for _path in (str(_manager_root), str(_manager_dir)):
        if _path not in sys.path:
            sys.path.insert(0, _path)
    from common.base_loaders import BaseLocalLoader
    from water_quality import WaterQuality


@dataclass
class LocalLoadResult:
    stations_info: pd.DataFrame
    metadata: pd.DataFrame
    data: pd.DataFrame
    missing_data_summary: pd.DataFrame
    samples: Dict[str, WaterQuality]


class LocalWaterQualityLoader(BaseLocalLoader):
    """Load water quality records from local CSV exports."""

    def __init__(
        self,
        *,
        local_data_dir: Path,
        date_start: Optional[datetime] = None,
        date_end: Optional[datetime] = None,
    ):
        self.local_data_dir = Path(local_data_dir)
        self.date_start = date_start
        self.date_end = date_end

    def load(self, *, site_ids: Sequence[str]) -> LocalLoadResult:
        # stubbed; implement logic analogous to the piezometer local loader
        return LocalLoadResult(
            stations_info=pd.DataFrame(),
            metadata=pd.DataFrame(),
            data=pd.DataFrame(),
            missing_data_summary=pd.DataFrame(),
            samples={},
        )

# end of loaders_local.py
