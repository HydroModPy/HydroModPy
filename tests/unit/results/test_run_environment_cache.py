"""The host-environment probes are memoised per process (calibration re-runs them).

``capture_environment`` runs once per simulation, and calibration fires one per
trial, so the subprocess-backed probes (conda hash, pip list, cpuinfo, git,
binary hash) must be cached for the process. They are pure provenance, so caching
never changes a result; this guards that the cache works and cannot be corrupted
by a caller mutating the returned snapshot.
"""

from __future__ import annotations

from hydromodpy.results import run_environment as env


def test_expensive_probes_run_once_across_captures() -> None:
    for probe in (env._conda_env_hash, env._cpu_info, env._env_packages, env._git_head):
        probe.cache_clear()

    first = env.capture_environment()
    second = env.capture_environment()

    # The snapshots carry the same provenance...
    assert first["conda_env_hash"] == second["conda_env_hash"]
    assert first["cpu_info"] == second["cpu_info"]
    # ...but the expensive probes ran once and were served from cache after.
    assert env._conda_env_hash.cache_info().hits >= 1
    assert env._cpu_info.cache_info().hits >= 1
    assert env._env_packages.cache_info().hits >= 1


def test_mutating_a_snapshot_does_not_corrupt_the_cache() -> None:
    for probe in (env._cpu_info, env._env_packages):
        probe.cache_clear()

    snapshot = env.capture_environment()
    snapshot["cpu_info"]["injected"] = True
    snapshot["env_packages"].append("injected-package==9.9.9")

    # The memoised probe values are copied into each snapshot, so a caller
    # mutating one snapshot cannot leak into the shared cache or a later capture.
    assert "injected" not in env._cpu_info()
    assert "injected-package==9.9.9" not in env._env_packages()
    assert "injected" not in env.capture_environment()["cpu_info"]
