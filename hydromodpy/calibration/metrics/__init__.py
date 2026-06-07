"""RAM metric extraction for lightweight calibration trials.

The package splits the old monolithic ``metrics.py`` (752 LOC, 9 concerns)
into five sub-modules:

- :mod:`scalar` : KGE/NSE/RMSE/MAE scoring primitives.
- :mod:`series` : observation loader, time-index resolution, runoff postprocess.
- :mod:`solver_extract` : flow adapter resolver and point/boundary/cell extractors.
- :mod:`composite` : public ``build_metric_extractor`` factory.
- :mod:`network` : drainage-network metrics for B0 prototypes.
"""

from hydromodpy.calibration.metrics.composite import build_metric_extractor
from hydromodpy.calibration.metrics.series import ObservedSeries

__all__ = ("build_metric_extractor", "ObservedSeries")
