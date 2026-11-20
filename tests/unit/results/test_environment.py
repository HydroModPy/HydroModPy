"""The host-environment probes are memoized per process.

``capture_environment`` runs once per simulation and calibration fires one per
trial, so the slow probes (conda hash, pip list, cpuinfo, git) are cached. The
cache must not change a result nor be corrupted by a caller editing a snapshot.
"""

from __future__ import annotations

from hydromodpy.results.run import environment as env


def test_probes_run_once() -> None:
    for probe in (env._conda_env_hash, env._cpu_info, env._env_packages, env._git_head):
        probe.cache_clear()

    first = env.capture_environment()
    second = env.capture_environment()

    assert first["conda_env_hash"] == second["conda_env_hash"]
    assert first["cpu_info"] == second["cpu_info"]
    # The second capture is served from the cache.
    assert env._conda_env_hash.cache_info().hits >= 1
    assert env._cpu_info.cache_info().hits >= 1
    assert env._env_packages.cache_info().hits >= 1


def test_a_snapshot_edit_leaves_the_cache_alone() -> None:
    for probe in (env._cpu_info, env._env_packages):
        probe.cache_clear()

    snapshot = env.capture_environment()
    snapshot["cpu_info"]["injected"] = True
    snapshot["env_packages"].append("injected-package==9.9.9")

    # Each snapshot holds a copy of the memoized values.
    assert "injected" not in env._cpu_info()
    assert "injected-package==9.9.9" not in env._env_packages()
    assert "injected" not in env.capture_environment()["cpu_info"]
