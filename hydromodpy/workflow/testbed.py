"""Testbed runner provider compatibility hooks."""

from __future__ import annotations

from collections.abc import Callable

from hydromodpy.analysis.testbed.contracts import (
    TestbedRunnerProvider,
    register_testbed_runner_provider,
)

_default_provider_factory: Callable[[], TestbedRunnerProvider] | None = None


def set_default_testbed_runner_provider_factory(
    factory: Callable[[], TestbedRunnerProvider],
) -> None:
    """Inject the default provider factory from the root bootstrap layer."""
    global _default_provider_factory
    _default_provider_factory = factory


def register_default_testbed_runner_provider() -> None:
    """Register the injected default testbed provider."""
    if _default_provider_factory is None:
        raise RuntimeError(
            "Default testbed provider factory is not registered. Import "
            "'hydromodpy' or call hydromodpy.bootstrap() before executing "
            "testbed variants."
        )
    register_testbed_runner_provider(_default_provider_factory())


__all__ = [
    "register_default_testbed_runner_provider",
    "set_default_testbed_runner_provider_factory",
]
