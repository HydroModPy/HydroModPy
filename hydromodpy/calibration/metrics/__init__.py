"""RAM metric extraction for lightweight calibration trials.

The package splits the old monolithic ``metrics.py`` (752 LOC, 9 concerns)
into sub-modules:

- :mod:`observable_scoring` : the one scoring route, blocks over named observables.
- :mod:`series` : observation loader, time-index resolution, runoff postprocess.
- :mod:`solver_extract` : flow adapter resolver and point/boundary/cell extractors.
- :mod:`composite` : public ``build_metric_extractor`` factory.
"""
