"""Catalog of the calibration methods and metrics, read from the code.

Nothing here is typed for a page. Each fact comes from a registry:

- methods: the optimizer registry (``calibration.optim.optimizer``), the traits
  each engine declares (``EngineTraits``), the options model of each engine
  (``calibration.optim.method_config``, its docstring and its fields), and the
  engines a search that names none is given (``CHOSEN_FROM``);
- metrics: ``calibration.criteria.series.METRICS``, the requirements each
  criterion declares (``criterion_for(name).requirements()``), the direction
  (``series.HIGHER_IS_BETTER``) and the formulas
  (``calibration.criteria.formulas.METRIC_FORMULAS``).

A wrong row is fixed in the code. ``hmp_calibration`` renders the payload on the
reference page of the methods and on the theory page of the inverse problem.

Usage: python -m tools.docs.calibration_catalog [OUT.json]
"""

from __future__ import annotations

import argparse
import inspect
import json
import re
import types
import typing
from pathlib import Path
from typing import Any

from pydantic_core import PydanticUndefined


def _paragraphs(doc: str | None) -> list[str]:
    text = inspect.cleandoc(doc or "")
    return [" ".join(chunk.split()) for chunk in re.split(r"\n\s*\n", text) if chunk.strip()]


def _type_name(annotation: Any) -> str:
    """A short, readable name of a field annotation."""
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        return " or ".join(_type_name(arg) for arg in typing.get_args(annotation))
    if origin is typing.Literal:
        return " | ".join(repr(arg) for arg in typing.get_args(annotation))
    if origin in (list, tuple):
        args = typing.get_args(annotation)
        inner = _type_name(args[0]) if args else "value"
        return f"list of {inner}"
    if annotation is type(None):
        return "None"
    return getattr(annotation, "__name__", str(annotation))


def _default(field: Any) -> dict[str, Any]:
    if field.is_required():
        return {"required": True, "default": None}
    value = field.default
    if value is PydanticUndefined:
        value = None
    return {"required": False, "default": value}


def _options(model: type) -> list[dict[str, Any]]:
    rows = []
    for name, field in model.model_fields.items():
        if name == "method":
            continue
        rows.append(
            {
                "name": name,
                "type": _type_name(field.annotation),
                **_default(field),
                "description": " ".join((field.description or "").split()),
            }
        )
    return rows


def _engine_class(name: str) -> type | None:
    from hydromodpy.calibration.optim import optimizer

    optimizer._ensure_builtins_loaded()
    engine = optimizer._BUILTIN.get(name)
    return engine if isinstance(engine, type) else None


def methods() -> list[dict[str, Any]]:
    """One record per registered method, with its options and declared traits."""
    from hydromodpy.calibration.optim import method_config
    from hydromodpy.calibration.optim.optimizer import (
        CHOSEN_FROM,
        available_optimizers,
        engine_traits,
    )
    from hydromodpy.calibration.optim.stopping import UNCOUNTED_BUDGET

    names = sorted(set(available_optimizers()) | set(method_config.typed_methods()))
    rows = []
    for name in names:
        model = method_config._MODELS_BY_METHOD.get(name)
        paragraphs = _paragraphs(model.__doc__ if model is not None else None)
        traits = engine_traits(name)
        engine = _engine_class(name)
        rows.append(
            {
                "name": name,
                "registered": name in available_optimizers(),
                "summary": paragraphs[0] if paragraphs else "",
                "details": paragraphs[1:],
                "options": _options(model) if model is not None else None,
                "max_parameters": traits.max_parameters,
                "required_transform": traits.required_transform,
                "needs_signed_residual": traits.needs_signed_residual,
                "supports_parallel": traits.supports_parallel,
                "tolerance_option": traits.tolerance_option,
                "tolerance_reads": traits.tolerance_reads,
                "accepts_a_start_point": traits.accepts_a_start_point,
                "reads_cost_as": traits.reads_cost_as,
                "restarts_explore_differently": traits.restarts_explore_differently,
                "counts_its_budget": engine is not None and hasattr(engine, "counted_budget"),
                "chosen_rank": CHOSEN_FROM.index(name) if name in CHOSEN_FROM else None,
                "uncounted_budget": UNCOUNTED_BUDGET,
            }
        )
    return rows


def metrics() -> list[dict[str, Any]]:
    """One record per metric a TOML may name, with its formula and requirements."""
    from hydromodpy.calibration.criteria.formulas import METRIC_FORMULAS
    from hydromodpy.calibration.criteria.registry import (
        NETWORK_ESTIMATORS,
        available_criteria,
        criterion_for,
    )
    from hydromodpy.calibration.criteria.series import HIGHER_IS_BETTER, LOG_METRICS

    rows = []
    for name in available_criteria():
        needs = criterion_for(name).requirements()
        formula = METRIC_FORMULAS.get(name)
        if needs.cost_is_dimensionless:
            unit = "none"
        elif needs.cost_unit == "m":
            unit = "m"
        else:
            unit = "unit of the observation"
        if name in NETWORK_ESTIMATORS:
            family = "network distance"
        elif name in HIGHER_IS_BETTER:
            family = "efficiency"
        else:
            family = "error"
        rows.append(
            {
                "name": name,
                "family": family,
                "higher_is_better": name in HIGHER_IS_BETTER,
                "cost": "1 - score" if name in HIGHER_IS_BETTER else "score",
                "unit": unit,
                "signed": needs.signed,
                "needs_observations": needs.needs_observations,
                "has_time_axis": needs.has_time_axis,
                "reads_supports": list(needs.reads_supports),
                "takes_log": name in LOG_METRICS,
                "normalize_cost": _normalisation(name),
                "score": formula.score if formula else "",
                "reads": formula.reads if formula else "",
                "where": formula.where if formula else "",
                "note": formula.note if formula else "",
            }
        )
    return rows


def _normalisation(metric: str) -> str:
    """What ``normalize_cost = true`` divides this metric by, or why it is refused."""
    from hydromodpy.calibration.criteria import criterion_for
    from hydromodpy.calibration.optim.objective import (
        refuse_a_normalisation_that_means_nothing,
        scores_network_distances,
    )

    try:
        refuse_a_normalisation_that_means_nothing("block", metric)
    except ValueError:
        return "refused"
    if scores_network_distances(criterion_for(metric).requirements()):
        return "validity length of the output"
    return "standard deviation of the observations"


def build() -> dict[str, Any]:
    """The whole payload: methods and metrics."""
    return {"methods": methods(), "metrics": metrics()}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out", nargs="?", help="JSON file to write; prints when omitted")
    args = ap.parse_args()
    text = json.dumps(build(), indent=1, ensure_ascii=False, default=str)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
