"""End-to-end test scenarios.

Tests in this directory exercise HydroModPy as a black box — at the
public API or CLI level — and may spin up subprocesses, run real
solvers, or persist to DuckDB/Zarr. Each scenario is self-contained
and isolates its workspace in ``tmp_path``.
"""
