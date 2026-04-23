"""GR4J lumped catchment model package.

This package currently ships only the output extractor used by the
simulation runner to persist GR4J time series into the catalog. The
numerical GR4J implementation lives in its consumer (project façade
and tests) since the model is in-memory and has no solver binary.
"""
