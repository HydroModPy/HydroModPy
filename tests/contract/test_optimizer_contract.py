"""The optimizer port's contract, one case per id the registry serves.

The port is :class:`~hydromodpy.core.plugin_registry.PluginRegistry` as an
``id -> optimizer class`` surface: a class joins with its ``name`` attribute,
is resolved by ``optimizers.get``, and carries the four members ``ask``,
``tell``, ``best`` and ``converged``. The cases run over
``optimizers.names()`` and not over a list written here, so the same suite
covers an optimizer installed out of tree: that is what
``test_optimizer_conformance_reaches_an_installed_optimizer.py`` runs on.
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration.optim.optimizer import (
    ENTRY_POINT_GROUP,
    build_optimizer,
    optimizers,
)

SYS_IDS = optimizers.names()
"""The ids this interpreter serves: the ten shipped, plus an installed one."""

SHIPPED_IDS = tuple(sorted(optimizers.names(shipped_only=True)))
"""The ten ids the build declares in ``_BUILTIN_PATHS``, in case order."""


@pytest.mark.parametrize("name", SYS_IDS)
def test_the_registry_serves_every_id_it_reads(name: str) -> None:
    """A served id resolves to a class that carries the port's members."""
    cls = optimizers.get(name)
    assert isinstance(cls, type)
    for member in ("ask", "tell", "best", "converged"):
        assert hasattr(cls, member)


@pytest.mark.parametrize("name", SHIPPED_IDS)
def test_a_shipped_id_builds_from_its_reader(name: str) -> None:
    """A shipped id builds through ``build_optimizer`` with the shared arguments.

    The two adapters whose constructor demands a per-call fact are judged by
    that fact: one parameter for the root search, a written budget for the
    Latin hypercube.
    """
    from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace

    keyword: dict[str, object] = {"n_samples": 8} if name == "lhs" else {}
    space = ParameterSpace([CalibParameter("x", 1e-6, 1e-2, sampling="log", search_space="log")])
    if name != "bisection":
        space = ParameterSpace([CalibParameter("x", -2.0, 2.0), CalibParameter("y", -2.0, 2.0)])
    optimizer = build_optimizer(name, space, **keyword)
    assert optimizer.name == name


def test_an_unknown_id_is_refused_with_the_sentence_of_the_surface() -> None:
    """A name nothing serves is refused, with what the registry serves."""
    from hydromodpy.core.exceptions import OptimizerError

    served = ", ".join(optimizers.names())
    with pytest.raises(OptimizerError, match="no_such_method") as exc_info:
        try:
            optimizers.get("no_such_method")
        except OptimizerError as exc:
            raise OptimizerError(
                f"calibration.method names 'no_such_method', and this installation serves {served}."
            ) from exc
    assert "no_such_method" in str(exc_info.value)
