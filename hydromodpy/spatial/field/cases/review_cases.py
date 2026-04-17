"""Sequential visual review launcher for the pedagogical `field/cases` examples.

The goal is the same as for `gmsh_grid/cases/review_cases.py`: run a small set
of representative examples one after another, keep the figure display blocking,
and wait for the user to close the current window before moving to the next
example.

For now the review set is built from the square-domain examples, with a few
controlled variations of mesh type and field heterogeneity. This keeps the
launcher lightweight while still giving a quick visual tour of the current
`field/cases` capabilities.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

# Ensure repository root is importable when the script is launched directly.
# ``review_cases.py`` lives under ``hydromodpy/spatial/field/cases/``, so the
# repository root is four levels up. Inserting ``.../hydromodpy`` here would
# shadow the legacy top-level ``launchers`` package with
# ``hydromodpy/launchers`` modules during test collection.
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CASES_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = CASES_DIR / "outputs" / "review_cases"

_BASE_HETEROGENEOUS_FIELD_PARAM = {
    "id": "K",
    "kind": "heterogeneous",
    "values": {
        "granite": 10.0,
        "micaschists": 2.0,
    },
    "field_spatial_id": "field_square",
}

_BASE_HETEROGENEOUS_FIELD = {
    "id": "field_square",
    "line": "diag_main",
    "zone1_side": "positive",
    "zone1_name": "granite",
    "zone2_name": "micaschists",
}

_BASE_HOMOGENEOUS_FIELD_PARAM = {
    "id": "K",
    "kind": "homogeneous",
    "value": 6.0,
}


@dataclass(frozen=True, slots=True)
class CaseReviewSpec:
    """Describe one visual `field/cases` example available for manual review."""

    name: str
    description: str
    runner: Callable[[], Any]


def _merge_config(base: Mapping[str, Any], /, **updates: Any) -> dict[str, Any]:
    payload = dict(base)
    payload.update(updates)
    return payload


def _output_path(case_name: str) -> Path:
    return (OUTPUT_DIR / f"{case_name}.png").resolve()


def _run_square_case(
    *,
    case_name: str,
    field_param_config: Mapping[str, Any],
    mesh_config: Mapping[str, Any],
    field_config: Mapping[str, Any] | None,
) -> dict[str, object]:
    from hydromodpy.spatial.field.cases.square import FieldMeshSquare, FieldSquare
    from hydromodpy.spatial.field.cases.square.run_field_demo import run_field_demo_case
    from hydromodpy.spatial.field.core.field_param import FieldParam

    field_param = FieldParam.from_dict(field_param_config)
    mesh = FieldMeshSquare.from_dict(mesh_config)
    field = None if field_config is None else FieldSquare.from_dict(field_config)
    return run_field_demo_case(
        field_param=field_param,
        mesh=mesh,
        field=field,
        output_file=_output_path(case_name),
        show_plot=True,
    )


def _run_square_diag_structured() -> dict[str, object]:
    return _run_square_case(
        case_name="square_diag_structured",
        field_param_config=_BASE_HETEROGENEOUS_FIELD_PARAM,
        mesh_config={"kind": "structured", "target_n_cells": 400},
        field_config=_BASE_HETEROGENEOUS_FIELD,
    )


def _run_square_diag_triangular_structured() -> dict[str, object]:
    return _run_square_case(
        case_name="square_diag_triangular_structured",
        field_param_config=_BASE_HETEROGENEOUS_FIELD_PARAM,
        mesh_config={"kind": "triangular_structured", "target_n_cells": 400},
        field_config=_BASE_HETEROGENEOUS_FIELD,
    )


def _run_square_diag_triangular_unstructured() -> dict[str, object]:
    return _run_square_case(
        case_name="square_diag_triangular_unstructured",
        field_param_config=_BASE_HETEROGENEOUS_FIELD_PARAM,
        mesh_config={
            "kind": "triangular_unstructured",
            "target_n_cells": 400,
            "seed": 42,
        },
        field_config=_BASE_HETEROGENEOUS_FIELD,
    )


def _run_square_vertical_structured() -> dict[str, object]:
    return _run_square_case(
        case_name="square_vertical_structured",
        field_param_config=_BASE_HETEROGENEOUS_FIELD_PARAM,
        mesh_config={"kind": "structured", "target_n_cells": 400},
        field_config=_merge_config(
            _BASE_HETEROGENEOUS_FIELD,
            line="axis_vertical",
            zone1_side="negative",
        ),
    )


def _run_square_homogeneous_structured() -> dict[str, object]:
    return _run_square_case(
        case_name="square_homogeneous_structured",
        field_param_config=_BASE_HOMOGENEOUS_FIELD_PARAM,
        mesh_config={"kind": "structured", "target_n_cells": 400},
        field_config=None,
    )


CASE_REVIEW_SPECS: tuple[CaseReviewSpec, ...] = (
    CaseReviewSpec(
        name="square_diag_structured",
        description="Structured quadrilateral mesh with diagonal heterogeneous split.",
        runner=_run_square_diag_structured,
    ),
    CaseReviewSpec(
        name="square_diag_triangular_structured",
        description="Structured triangular mesh with the same diagonal heterogeneous split.",
        runner=_run_square_diag_triangular_structured,
    ),
    CaseReviewSpec(
        name="square_diag_triangular_unstructured",
        description="Unstructured triangular mesh on the same diagonal heterogeneous split.",
        runner=_run_square_diag_triangular_unstructured,
    ),
    CaseReviewSpec(
        name="square_vertical_structured",
        description="Structured quadrilateral mesh with a vertical two-zone separation.",
        runner=_run_square_vertical_structured,
    ),
    CaseReviewSpec(
        name="square_homogeneous_structured",
        description="Structured quadrilateral mesh with one homogeneous field value.",
        runner=_run_square_homogeneous_structured,
    ),
)


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Run the visual field/cases examples sequentially, with blocking "
            "figure display for manual review."
        )
    )
    parser.add_argument(
        "--case",
        dest="case_names",
        action="append",
        default=None,
        help=(
            "Restrict the review to one named case. Repeat the option to keep "
            "multiple cases; execution order stays the built-in review order."
        ),
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List the available review cases and exit.",
    )
    return parser.parse_args(argv)


def available_case_review_names() -> tuple[str, ...]:
    return tuple(spec.name for spec in CASE_REVIEW_SPECS)


def resolve_case_review_specs(
    case_names: Sequence[str] | None = None,
) -> tuple[CaseReviewSpec, ...]:
    if not case_names:
        return CASE_REVIEW_SPECS

    requested = {str(name).strip() for name in case_names if str(name).strip()}
    available = available_case_review_names()
    unknown = sorted(requested.difference(available))
    if unknown:
        raise ValueError(
            "Unknown field/cases review case(s): "
            + ", ".join(repr(name) for name in unknown)
            + ". Available cases: "
            + ", ".join(available)
        )
    return tuple(spec for spec in CASE_REVIEW_SPECS if spec.name in requested)


def list_case_reviews(*, printer: Callable[[str], None] = print) -> None:
    for spec in CASE_REVIEW_SPECS:
        printer(f"{spec.name}: {spec.description}")


def run_case_reviews(
    case_names: Sequence[str] | None = None,
    *,
    printer: Callable[[str], None] = print,
) -> tuple[CaseReviewSpec, ...]:
    selected_specs = resolve_case_review_specs(case_names)
    total = len(selected_specs)
    for index, spec in enumerate(selected_specs, start=1):
        printer(f"[{index}/{total}] Running {spec.name}")
        printer(f"  {spec.description}")
        printer("  Close the figure window(s) to continue to the next case.")
        spec.runner()
        printer(f"[{index}/{total}] Completed {spec.name}")
    return selected_specs


def main(argv=None) -> int:
    args = _parse_args(argv)
    if args.list:
        list_case_reviews()
        return 0
    run_case_reviews(args.case_names)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
