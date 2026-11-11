"""The optimizer port's contract, one case per id the registry serves.

The port is :class:`~hydromodpy.core.plugin_registry.PluginRegistry` as an
``id -> optimizer class`` surface: a class joins with its ``name`` attribute,
is resolved by ``optimizers.get``, and carries the four members ``ask``,
``tell``, ``best`` and ``converged``. The cases run over
``optimizers.names()`` and not over a list written here, so the same suite
covers an optimizer installed out of tree: that is what
``test_optimizer.py`` runs on.
"""

from __future__ import annotations

import inspect
import os
import subprocess
import sys
from pathlib import Path
from typing import ClassVar

import pytest

from hydromodpy.calibration.optim.optimizer import (
    ENTRY_POINT_GROUP,
    EvaluationResult,
    build_optimizer,
    engine_traits,
    optimizers,
)
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace

from ._installed_probe import REPO_ROOT, collected, run_suite, unpack

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


# ---- the ask and tell loop on a bowl ----
#
# Every id is played on one problem, f(x) = sum (x_i - 0.3)^2 on [0, 1]^d with d = 2,
# or the one parameter an engine that moves one asks for. The loop reads the contract
# only: each proposal is inside the bounds, the best point is the one of lowest value,
# and ``converged`` answers with a boolean. Nothing here names an optimizer: what an
# engine needs to be built comes from its traits and from the fields of its options.

ASKS = 20
CENTER = 0.3
SIGNED = "J_signed"
"""The component a criterion publishes beside its cost for an engine that reads a signed residual."""


def _space_of(name: str) -> ParameterSpace:
    """Return the search space the traits of *name* allow, around the minimum of the bowl."""
    traits = engine_traits(name)
    dim = min(2, traits.max_parameters or 2)
    low, space = (0.01, "log") if traits.required_search_space == "log" else (0.0, "identity")
    return ParameterSpace(
        [CalibParameter(f"p{i}", low, 1.0, search_space=space, sampling=space) for i in range(dim)]
    )


def _constructor_arguments(name: str) -> set[str]:
    return set(inspect.signature(optimizers.get(name)).parameters)


def _options_of(name: str) -> dict[str, object]:
    """Return what the constructor of *name* is given: a seed, a budget, a sample size."""
    declared = _constructor_arguments(name)
    given: dict[str, object] = {}
    if "seed" in declared:
        given["seed"] = 7
    if "n_samples" in declared:
        given["n_samples"] = ASKS
    if engine_traits(name).takes_max_trials:
        given["max_trials"] = ASKS
    return given


def _played(name: str) -> tuple[list[tuple[float, ...]], list[EvaluationResult], object]:
    """Play ``ASKS`` ask and tell rounds, one point each; return points, results, optimizer."""
    space = _space_of(name)
    optimizer = build_optimizer(name, space, **_options_of(name))
    signed = engine_traits(name).needs_signed_residual
    points: list[tuple[float, ...]] = []
    results: list[EvaluationResult] = []
    for _ in range(ASKS):
        if optimizer.converged():
            break
        proposed = optimizer.ask(1)
        if not proposed:
            break
        told = []
        for suggestion in proposed:
            values = tuple(float(suggestion.values[param.name]) for param in space)
            points.append(values)
            for param, value in zip(space, values, strict=True):
                assert param.lower <= value <= param.upper, (name, param.name, value)
            cost = sum((value - CENTER) ** 2 for value in values)
            components = {SIGNED: values[0] - CENTER} if signed else None
            told.append(
                EvaluationResult(
                    trial_id=suggestion.trial_id, sim_id=None, cost=cost, components=components
                )
            )
        optimizer.tell(told)
        results.extend(told)
    return points, results, optimizer


@pytest.mark.parametrize("name", SYS_IDS)
def test_an_optimizer_proposes_inside_the_bounds_and_names_its_best(name: str) -> None:
    points, results, optimizer = _played(name)

    assert points, name
    assert isinstance(optimizer.converged(), bool)
    best = optimizer.best()
    assert best is not None, name
    assert best.cost == min(result.cost for result in results)
    assert len({result.trial_id for result in results}) == len(results)


@pytest.mark.parametrize("name", SYS_IDS)
def test_two_loops_of_one_seed_propose_the_same_points(name: str) -> None:
    if "seed" not in _constructor_arguments(name):
        pytest.skip(f"{name!r} takes no seed")

    assert _played(name)[0] == _played(name)[0]


# ---- installed-probe section ----
#
# The conformance suite of the optimizer port reaches an optimizer it does not name.
#
# ``add-a-calibration-method.rst`` tells a plugin author to run the suite from a
# clone, with the plugin installed. This file installs an optimizer the suite has
# never heard of and runs the suite on it, in a subprocess because
# ``importlib.metadata`` reads the entry points once (the reason the other
# port files of this directory share a probe in ``_installed_probe.py``).
#
# The entry point carries the id the registry keys it on, the adapter's ``name``
# attribute: a third-party method is published under the id its class declares,
# exactly the rule the evaluators follow.

SUITE: ClassVar[str] = "tests/ports/test_optimizer.py"
PROBE_ID: ClassVar[str] = "probe-shim"
CASES_PER_ID: ClassVar[int] = 3
"""One case per parametrized test that runs over the ids served, and the suite has three."""

PROBE_MODULE = """\\
from typing import ClassVar
from pydantic import BaseModel
from hydromodpy.calibration.optim.optimizer import ParamSuggestion, best_completed


class ProbeOptions(BaseModel):
    max_steps: int = 10


class ProbeShim:
    name: ClassVar[str] = "probe-shim"
    options: ClassVar[type[BaseModel] | None] = ProbeOptions

    def __init__(self, space, **options):
        self.space = space
        self.settings = options
        self.history = []
        self.next_id = 0

    def ask(self, n: int = 1) -> list[ParamSuggestion]:
        asked = []
        for _ in range(n):
            share = (self.next_id % 7 + 1) / 8
            values = {p.name: p.lower + share * (p.upper - p.lower) for p in self.space}
            asked.append(ParamSuggestion(trial_id=self.next_id, values=values))
            self.next_id += 1
        return asked

    def tell(self, results: list) -> None:
        self.history.extend(results)

    def best(self):
        return best_completed(self.history)

    def converged(self) -> bool:
        return False
"""


@pytest.fixture(scope="module")
def installed_probe(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A module and its ``.dist-info``, what a wheel unpacks to. No build, no network."""
    return unpack(
        tmp_path_factory.mktemp("probe_site_packages"),
        "hmp_optimizer_probe",
        PROBE_MODULE,
        ENTRY_POINT_GROUP,
        PROBE_ID,
        "ProbeShim",
    )  # fmt: skip


def _run_python_in_subprocess(code: str, site_packages: Path) -> subprocess.CompletedProcess:
    environment = dict(os.environ)
    environment.pop("PYTEST_XDIST_WORKER", None)
    entries = [site_packages, REPO_ROOT, environment.get("PYTHONPATH")]
    environment["PYTHONPATH"] = os.pathsep.join(str(entry) for entry in entries if entry)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_the_suite_holds_an_installed_optimizer_to_the_port(
    installed_probe: Path, tmp_path: Path
) -> None:
    """The conformance suite reaches an installed optimizer, one group scan."""
    listing = run_suite(SUITE, tmp_path / "collect", "--collect-only", "-q", site_packages=installed_probe)  # fmt: skip
    assert listing.returncode == 0, listing.stdout[-4000:]
    nodes = collected(listing.stdout, SUITE, PROBE_ID)
    assert len(nodes) == CASES_PER_ID, listing.stdout[-4000:]

    result = run_suite(SUITE, tmp_path / "run", "-q", "-k", PROBE_ID, site_packages=installed_probe)  # fmt: skip
    assert result.returncode == 0, result.stdout[-8000:]


def test_installed_optimizer_accepted_by_calibration_method(
    installed_probe: Path,
) -> None:
    code = """
from pydantic import TypeAdapter
from hydromodpy.calibration.config import CalibrationMethod
from hydromodpy.calibration.optim.optimizer import optimizers

assert "probe-shim" in optimizers.names()
adapter = TypeAdapter(CalibrationMethod)
val = adapter.validate_python("probe-shim")
assert val == "probe-shim"
"""
    result = _run_python_in_subprocess(code, installed_probe)
    assert result.returncode == 0, result.stderr or result.stdout


def test_installed_optimizer_options_validated(
    installed_probe: Path,
) -> None:
    code = """
from hydromodpy.calibration.optim.method_config import validate_method_kwargs

# Valid options
validated = validate_method_kwargs("probe-shim", {"max_steps": 20})
assert validated.max_steps == 20

# Invalid options
try:
    validate_method_kwargs("probe-shim", {"max_steps": "not_an_int"})
except Exception as exc:
    assert "max_steps" in str(exc)
else:
    raise AssertionError("Should have raised exception on invalid options")
"""
    result = _run_python_in_subprocess(code, installed_probe)
    assert result.returncode == 0, result.stderr or result.stdout
