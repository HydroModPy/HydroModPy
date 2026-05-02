"""Discovery helpers for analytical validation cases used by the doc gallery."""

from __future__ import annotations

import importlib
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATION_SOLVER_ORDER = ("modflownwt", "modflow6", "modflow6_irregular_tri", "boussinesq")


@dataclass(frozen=True, slots=True)
class ValidationInventoryEntry:
    """One row from the high-level validation inventory table."""

    purpose: str
    reference: str
    regime: str
    dimension: str


@dataclass(frozen=True, slots=True)
class ValidationCaseSheetEntry:
    """One row from the detailed steady/transient validation sheets."""

    numerical_setup: str
    analytical_target: str
    primary_metrics: str
    what_it_validates: str


@dataclass(frozen=True, slots=True)
class ValidationReadmeInfo:
    """Structured README information extracted from one validation case."""

    title: str
    summary: str
    sections: dict[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class ValidationCaseRecord:
    """Full gallery-facing description of one analytical validation case."""

    slug: str
    title: str
    deck: str
    summary: str
    regime: str
    dimension: str
    reproduction_command: str
    source_paths: tuple[str, ...]
    case_setup: tuple[str, ...]
    what_it_shows: tuple[str, ...]
    reference_highlights: tuple[str, ...]
    equations_rst: tuple[str, ...]
    metadata: dict[str, Any]


def _repo_root(repo_root: Path | None = None) -> Path:
    return REPO_ROOT if repo_root is None else Path(repo_root).resolve()


def _repo_relative(path: Path, *, repo_root: Path) -> str:
    return path.resolve().relative_to(repo_root).as_posix()


def _normalize_solver_name(solver: str) -> str:
    mapping = {
        "modflownwt": "MODFLOW-NWT",
        "modflow6": "MODFLOW 6",
        "modflow6_irregular_tri": "MODFLOW 6 irregular triangles",
        "boussinesq": "Boussinesq",
    }
    return mapping.get(solver, solver.replace("_", " ").title())


_VALIDATION_PROCESS_LABELS = {
    "flow": "Flow",
    "transport": "Transport",
    "particle_tracking": "Particle Tracking",
}

_VALIDATION_GEOMETRY_LABELS = {
    "strip_1d": "Strip 1D",
    "hillslope_1d": "Hillslope 1D",
    "island_2d": "Island 2D",
    "radial_2d": "Radial 2D",
    "planar_2d": "Planar 2D",
}

_VALIDATION_REFERENCE_TYPE_LABELS = {
    "analytical_exact": "Analytical Exact",
    "analytical_series": "Analytical Series",
    "semi_analytical": "Semi-Analytical / Diagnostic",
}

_VALIDATION_FAMILY_LABELS = {
    "core_1d_dupuit_baselines": "Core 1D Dupuit Baselines",
    "steady_1d_boussinesq_heterogeneous_conductivity": (
        "Steady 1D Boussinesq with Heterogeneous Conductivity"
    ),
    "steady_1d_boussinesq_topography_sloping_substratum": (
        "Steady 1D Boussinesq with Topography or Sloping Substratum"
    ),
    "steady_2d_radial_or_island": "Steady 2D Radial or Island Cases",
    "transient_1d_boundary_or_recharge_forcing": ("Transient 1D Boundary or Recharge Forcing"),
    "transient_1d_recession_or_interception_dynamics": (
        "Transient 1D Recession or Interception Dynamics"
    ),
    "transient_2d_radial_response": "Transient 2D Radial Response",
    "transport": "Transport",
    "particle_tracking": "Particle Tracking",
}

_VALIDATION_FAMILY_ORDER = {
    "core_1d_dupuit_baselines": 10,
    "steady_1d_boussinesq_heterogeneous_conductivity": 20,
    "steady_1d_boussinesq_topography_sloping_substratum": 30,
    "steady_2d_radial_or_island": 40,
    "transient_1d_boundary_or_recharge_forcing": 50,
    "transient_1d_recession_or_interception_dynamics": 60,
    "transient_2d_radial_response": 70,
    "transport": 60,
    "particle_tracking": 70,
}


def _normalize_taxonomy_token(value: Any) -> str:
    text = str(value).strip().lower()
    text = text.replace("-", "_")
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    return text.strip("_")


def _normalize_section_name(label: str) -> str:
    lowered = label.strip().rstrip(":").lower()
    lowered = lowered.replace("-", "_")
    lowered = re.sub(r"[^a-z0-9_]+", "_", lowered)
    return lowered.strip("_")


def _dedupe_preserve_order(items: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        clean_item = item.strip()
        if not clean_item or clean_item in seen:
            continue
        seen.add(clean_item)
        ordered.append(clean_item)
    return tuple(ordered)


def _infer_validation_process_family(metadata_payload: dict[str, Any]) -> str:
    process_family = _normalize_taxonomy_token(metadata_payload.get("process_family", "flow"))
    return process_family or "flow"


def _infer_validation_geometry_family(*, slug: str, metadata_payload: dict[str, Any]) -> str:
    explicit = _normalize_taxonomy_token(metadata_payload.get("geometry_family", ""))
    if explicit:
        return explicit
    if "hillslope" in slug or "sloping_substratum" in slug:
        return "hillslope_1d"
    if slug.endswith("_2d"):
        if "pumping" in slug:
            return "radial_2d"
        if "island" in slug:
            return "island_2d"
        return "planar_2d"
    return "strip_1d"


def _infer_validation_reference_type(*, slug: str, metadata_payload: dict[str, Any]) -> str:
    explicit = _normalize_taxonomy_token(metadata_payload.get("reference_type", ""))
    if explicit:
        return explicit
    if "interception" in slug:
        return "semi_analytical"
    if (
        "boundary_" in slug
        or "recharge_" in slug
        or "recession" in slug
        or slug == "late_time_unconfined_pumping_2d"
    ):
        return "analytical_series"
    return "analytical_exact"


def _infer_validation_family(
    *,
    slug: str,
    process_family: str,
    geometry_family: str,
    regime: str,
    metadata_payload: dict[str, Any],
) -> str:
    explicit = _normalize_taxonomy_token(metadata_payload.get("validation_family", ""))
    if explicit:
        return explicit
    if process_family == "transport":
        return "transport"
    if process_family == "particle_tracking":
        return "particle_tracking"

    if regime == "steady":
        if geometry_family in {"island_2d", "radial_2d", "planar_2d"}:
            return "steady_2d_radial_or_island"
        if slug.startswith("dupuit_") and geometry_family == "strip_1d":
            return "core_1d_dupuit_baselines"
        if "piecewise_k" in slug:
            return "steady_1d_boussinesq_heterogeneous_conductivity"
        if (
            "sloping_substratum" in slug
            or "hillslope" in slug
            or slug
            in {
                "linearized_unconfined_drainage_1d",
                "linearized_unconfined_hillslope_drainage_1d",
            }
        ):
            return "steady_1d_boussinesq_topography_sloping_substratum"
        return "core_1d_dupuit_baselines"

    if geometry_family in {"island_2d", "radial_2d", "planar_2d"}:
        return "transient_2d_radial_response"
    if "recession" in slug or "interception" in slug:
        return "transient_1d_recession_or_interception_dynamics"
    if regime == "transient":
        return "transient_1d_boundary_or_recharge_forcing"
    return "core_1d_dupuit_baselines"


def _build_validation_taxonomy(*, slug: str, metadata_payload: dict[str, Any]) -> dict[str, Any]:
    process_family = _infer_validation_process_family(metadata_payload)
    geometry_family = _infer_validation_geometry_family(
        slug=slug, metadata_payload=metadata_payload
    )
    reference_type = _infer_validation_reference_type(slug=slug, metadata_payload=metadata_payload)
    regime = str(metadata_payload.get("regime", "")).strip()
    validation_family = _infer_validation_family(
        slug=slug,
        process_family=process_family,
        geometry_family=geometry_family,
        regime=regime,
        metadata_payload=metadata_payload,
    )
    return {
        "process_family": process_family,
        "process_family_label": str(
            metadata_payload.get(
                "process_family_label",
                _VALIDATION_PROCESS_LABELS.get(
                    process_family, process_family.replace("_", " ").title()
                ),
            )
        ),
        "geometry_family": geometry_family,
        "geometry_family_label": str(
            metadata_payload.get(
                "geometry_family_label",
                _VALIDATION_GEOMETRY_LABELS.get(
                    geometry_family, geometry_family.replace("_", " ").title()
                ),
            )
        ),
        "reference_type": reference_type,
        "reference_type_label": str(
            metadata_payload.get(
                "reference_type_label",
                _VALIDATION_REFERENCE_TYPE_LABELS.get(
                    reference_type, reference_type.replace("_", " ").title()
                ),
            )
        ),
        "validation_family": validation_family,
        "validation_family_label": str(
            metadata_payload.get(
                "validation_family_label",
                _VALIDATION_FAMILY_LABELS.get(
                    validation_family, validation_family.replace("_", " ").title()
                ),
            )
        ),
        "validation_family_order": int(
            metadata_payload.get(
                "validation_family_order",
                _VALIDATION_FAMILY_ORDER.get(validation_family, 999),
            )
        ),
    }


def _parse_markdown_table(lines: list[str], start_index: int) -> tuple[list[dict[str, str]], int]:
    rows: list[str] = []
    index = start_index
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped.startswith("|"):
            break
        rows.append(stripped)
        index += 1

    if len(rows) < 2:
        return [], index

    headers = [cell.strip() for cell in rows[0].strip("|").split("|")]
    parsed_rows: list[dict[str, str]] = []
    for raw_row in rows[2:]:
        values = [cell.strip() for cell in raw_row.strip("|").split("|")]
        if len(values) != len(headers):
            continue
        parsed_rows.append(dict(zip(headers, values, strict=True)))
    return parsed_rows, index


def _load_validation_case_tables(
    *, repo_root: Path
) -> tuple[dict[str, ValidationInventoryEntry], dict[str, ValidationCaseSheetEntry]]:
    readme_path = repo_root / "validation_cases" / "README.md"
    lines = readme_path.read_text(encoding="utf-8").splitlines()

    inventory: dict[str, ValidationInventoryEntry] = {}
    sheets: dict[str, ValidationCaseSheetEntry] = {}

    current_heading = ""
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped.startswith("## ") or stripped.startswith("### "):
            current_heading = stripped.lstrip("#").strip()
            index += 1
            continue
        if stripped.startswith("|"):
            table_rows, index = _parse_markdown_table(lines, index)
            if current_heading == "Inventory":
                for row in table_rows:
                    path_value = row.get("Path", "").strip("`")
                    slug = path_value.rsplit("/", 1)[-1]
                    inventory[slug] = ValidationInventoryEntry(
                        purpose=row.get("Purpose", ""),
                        reference=row.get("Reference", ""),
                        regime=row.get("Regime", ""),
                        dimension="2d" if slug.endswith("_2d") else "1d",
                    )
            elif current_heading in {"Steady Cases", "Transient Cases"}:
                for row in table_rows:
                    slug = row.get("Case", "").strip("`")
                    sheets[slug] = ValidationCaseSheetEntry(
                        numerical_setup=row.get("Numerical setup", ""),
                        analytical_target=row.get("Analytical target", ""),
                        primary_metrics=row.get("Primary metrics", ""),
                        what_it_validates=row.get("What the case validates", ""),
                    )
            continue
        index += 1

    return inventory, sheets


def _load_readme_info(readme_path: Path) -> ValidationReadmeInfo:
    lines = readme_path.read_text(encoding="utf-8").splitlines()
    title = ""
    summary_lines: list[str] = []
    sections: dict[str, list[str]] = {}
    current_section: str | None = None
    in_code_block = False
    found_summary = False

    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped.startswith("# ") and not title:
            title = stripped[2:].strip()
            index += 1
            continue
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            index += 1
            continue
        if in_code_block:
            index += 1
            continue

        if title and not found_summary:
            if not stripped:
                if summary_lines:
                    found_summary = True
                index += 1
                continue
            if stripped.endswith(":") and not summary_lines:
                found_summary = True
            else:
                summary_lines.append(stripped)
                index += 1
                continue

        if stripped.endswith(":") and not stripped.startswith("- "):
            current_section = _normalize_section_name(stripped)
            sections.setdefault(current_section, [])
            index += 1
            continue

        if current_section is not None and stripped.startswith("- "):
            sections[current_section].append(stripped[2:].strip())
            index += 1
            continue
        if current_section is not None and stripped and sections.get(current_section):
            sections[current_section][-1] = sections[current_section][-1] + " " + stripped
        index += 1

    return ValidationReadmeInfo(
        title=title or readme_path.parent.name.replace("_", " ").title(),
        summary=" ".join(summary_lines).strip(),
        sections={key: tuple(value) for key, value in sections.items()},
    )


def _format_expected_output(case_metadata: dict[str, Any], solver: str) -> str | None:
    output = case_metadata.get("output", {})
    if not isinstance(output, dict):
        return None

    if "expected_shape" in output:
        expected_shape = output.get("expected_shape_by_solver", {}).get(
            solver, output["expected_shape"]
        )
        shape = " x ".join(str(item) for item in expected_shape)
        return f"Expected shape: {shape}"

    if "expected_spatial_shape" in output:
        spatial_shape = output.get("expected_spatial_shape_by_solver", {}).get(
            solver,
            output["expected_spatial_shape"],
        )
        spatial_text = " x ".join(str(item) for item in spatial_shape)
        periods = output.get("expected_periods")
        if periods is None:
            return f"Expected spatial shape: {spatial_text}"
        return f"Expected output: {periods} periods, spatial shape {spatial_text}"

    return None


def _discover_run_case_metadata(case_dir: Path, *, repo_root: Path) -> dict[str, Any]:
    run_case_path = case_dir / "run_case.py"
    module_name = _repo_relative(run_case_path.with_suffix(""), repo_root=repo_root).replace(
        "/", "."
    )
    module = importlib.import_module(module_name)

    run_functions = sorted(
        name
        for name, obj in vars(module).items()
        if callable(obj) and name.startswith("run_") and name.endswith("_comparison")
    )
    plot_functions = sorted(
        name
        for name, obj in vars(module).items()
        if callable(obj) and name.startswith("plot_") and name.endswith("_comparison")
    )
    if len(run_functions) != 1 or len(plot_functions) != 1:
        raise RuntimeError(
            f"Could not discover one comparison/plotting pair in {run_case_path.as_posix()}."
        )

    return {
        "run_case_module": module_name,
        "comparison_function_name": run_functions[0],
        "plotting_function_name": plot_functions[0],
        "metric_builder_name": "_build_metric_lines",
        "default_figure_name": module.DEFAULT_FIGURE_NAME,
        "run_description": getattr(module, "RUN_DESCRIPTION", ""),
    }


def _extra_source_paths_for_case(slug: str) -> tuple[str, ...]:
    extra_paths: list[str] = []
    if "piecewise_k" in slug:
        extra_paths.append("validation_cases/analytical/steady/boussinesq_piecewise.py")
    if slug.startswith("boussinesq_sloping_substratum_"):
        extra_paths.extend(
            [
                "validation_cases/analytical/steady/boussinesq_sloping_substratum.py",
                "validation_cases/shared/boussinesq_uniform_strip.py",
            ]
        )
    if slug in {
        "dupuit_fixed_head_1d",
        "dupuit_uniform_recharge_1d",
        "dupuit_divide_river_1d",
        "linearized_unconfined_boundary_piecewise_1d",
        "linearized_unconfined_recharge_periodic_1d",
    }:
        extra_paths.append("validation_cases/shared/boussinesq_uniform_strip.py")
    if (
        slug.startswith("linearized_unconfined_")
        or slug == "boussinesq_hillslope_recharge_step_interception_1d"
    ):
        extra_paths.append("validation_cases/analytical/transient/linearized_unconfined_1d.py")
    if slug == "late_time_unconfined_pumping_2d":
        extra_paths.append("validation_cases/analytical/transient/common.py")
    if slug.startswith("brutsaert_recession_"):
        extra_paths.extend(
            [
                "validation_cases/analytical/transient/brutsaert_common.py",
                "validation_cases/analytical/transient/brutsaert_reference.py",
                "validation_cases/analytical/transient/runtime_boussinesq_brutsaert_1d.py",
            ]
        )
    return tuple(extra_paths)


def _build_source_paths(
    case_dir: Path,
    *,
    repo_root: Path,
    config_files: dict[str, str],
    metadata_payload: dict[str, Any],
) -> tuple[str, ...]:
    relative_paths = [
        "validation_cases/README.md",
        _repo_relative(case_dir / "README.md", repo_root=repo_root),
        _repo_relative(case_dir / "reference.py", repo_root=repo_root),
        _repo_relative(case_dir / "comparison.py", repo_root=repo_root),
        _repo_relative(case_dir / "plotting.py", repo_root=repo_root),
        _repo_relative(case_dir / "run_case.py", repo_root=repo_root),
        _repo_relative(case_dir / "metadata.toml", repo_root=repo_root),
    ]
    base_config_name = str(metadata_payload.get("base_config", "")).strip()
    if base_config_name:
        relative_paths.append(_repo_relative(case_dir / base_config_name, repo_root=repo_root))
    for runtime_path in sorted(case_dir.glob("runtime_*.py")):
        relative_paths.append(_repo_relative(runtime_path, repo_root=repo_root))
    for tolerance_path in sorted(case_dir.glob("tolerances*.toml")):
        relative_paths.append(_repo_relative(tolerance_path, repo_root=repo_root))
    for config_file in config_files.values():
        relative_paths.append(_repo_relative(case_dir / config_file, repo_root=repo_root))
    relative_paths.extend(_extra_source_paths_for_case(case_dir.name))
    return _dedupe_preserve_order(relative_paths)


_SOLVER_CONFIG_SECTION_NAMES = {
    "modflownwt",
    "modflow6",
    "boussinesq",
    "petsc",
    "petsc_partition",
}


_REFERENCE_PARAMETER_MEANINGS: dict[str, str] = {
    "active_drainage_fraction": "Fraction of the domain where the analytical drainage condition is active.",
    "amplitude_mm_day": "Amplitude of the periodic recharge forcing used by the reference solution.",
    "aquifer_thickness_m": "Aquifer thickness used by the reference formulation.",
    "base_head_m": "Baseline hydraulic head around which the linearized reference is expressed.",
    "bottom_base_elevation_m": "Base elevation used by the synthetic reference substratum.",
    "bottom_right_to_left_amplitude_m": "Right-to-left amplitude used by the synthetic reference substratum.",
    "bottom_elevation_m": "Bottom elevation used by the reference domain.",
    "center_x_m": "Reference x coordinate of the domain centre or pumping location.",
    "center_y_m": "Reference y coordinate of the domain centre or pumping location.",
    "channel_length_m": "Characteristic channel length used by the recession reference.",
    "compare_start_day": "Start day retained when comparing the numerical and reference time series.",
    "comparison_radius_max_m": "Maximum radius used when sampling radial comparisons.",
    "crest_elevation_m": "Crest elevation used by the synthetic island topography.",
    "crs": "Coordinate reference system used by the synthetic geometry.",
    "divide_side": "Side of the domain where the analytical no-flow divide is enforced.",
    "drainage_conductance_m2_per_s": "Drainage conductance used by the analytical drainage boundary.",
    "drainage_elevation_m": "Drainage elevation used by the analytical drainage reference.",
    "east_head": "Fixed east-boundary hydraulic head used by the reference solution.",
    "east_head_m": "Fixed east-boundary hydraulic head used by the reference solution.",
    "hydraulic_conductivity_m_per_s": "Hydraulic conductivity used by the analytical or benchmark reference.",
    "inland_contact_threshold_x_m": "x threshold used to detect inland contact in the reference solution.",
    "interception_search_samples": "Number of samples used when locating the interception front in the reference helper.",
    "island_radius_m": "Island radius used by the radial reference domain.",
    "length_x_m": "Reference-domain length along the x axis.",
    "length_y_m": "Reference-domain length along the y axis.",
    "linearization_constant": "Constant used by the linearized analytical formulation.",
    "mean_recharge_mm_day": "Mean recharge applied in the periodic reference forcing.",
    "n_terms": "Number of terms retained in the analytical series expansion.",
    "numerical_contact_tolerance_m": "Tolerance used when comparing the numerical contact or interception position.",
    "nx": "Reference discretization count along the x axis used by the comparison helper.",
    "ny": "Reference discretization count along the y axis used by the comparison helper.",
    "ocean_floor_elevation_m": "Ocean-floor elevation used by the coastal reference geometry.",
    "period_days": "Period of the periodic forcing used by the reference solution.",
    "phase_radians": "Phase shift applied to the periodic reference forcing.",
    "profile_axis": "Axis along which the validation profile is extracted.",
    "pumping_rate_m3_day": "Pumping rate used by the radial pumping reference.",
    "radial_bin_width_m": "Radial bin width used when aggregating the numerical solution.",
    "recharge_mm_day": "Recharge rate used by the reference solution.",
    "reference_saturated_thickness_m": "Reference saturated thickness used by the linearized formulation.",
    "river_head": "River head imposed by the reference solution.",
    "sea_level_m": "Sea level used by the coastal or island reference.",
    "solution": "Named analytical solution variant used by the comparison helper.",
    "specific_yield": "Specific yield used by the transient reference formulation.",
    "substratum_elevation_m": "Substratum elevation used to build the analytical aquifer geometry.",
    "target_saturated_thickness_m": "Target saturated thickness enforced by the analytical reference profile.",
    "toe_elevation_m": "Toe elevation used by the hillslope reference geometry.",
    "topography_base_elevation_m": "Base elevation used by the synthetic reference topography.",
    "topography_right_to_left_amplitude_m": "Right-to-left topographic amplitude used by the hillslope reference.",
    "topography_slope_m_per_m": "Topographic slope used by the hillslope reference.",
    "watershed_area_m2": "Watershed area used by the recession reference.",
    "west_head": "Fixed west-boundary hydraulic head used by the reference solution.",
    "west_head_m": "Fixed west-boundary hydraulic head used by the reference solution.",
    "xmax": "Maximum x coordinate of the analytical reference domain.",
    "xmin": "Minimum x coordinate of the analytical reference domain.",
    "ymax": "Maximum y coordinate of the analytical reference domain.",
    "ymin": "Minimum y coordinate of the analytical reference domain.",
}


_TIME_PARAMETER_MEANINGS: dict[str, str] = {
    "dt_seconds": "Reference time step used by the analytical evaluator.",
    "nper": "Number of time periods used by the analytical or benchmark helper.",
}


_OUTPUT_PARAMETER_MEANINGS: dict[str, str] = {
    "observable_name": "Simulated observable compared against the reference solution.",
    "head_observable_name": "Head-like observable used when the case exposes more than one comparison target.",
    "expected_shape": "Expected spatial output shape checked by the validation helper.",
    "expected_periods": "Expected number of stored time periods checked by the validation helper.",
    "expected_spatial_shape": "Expected spatial shape for each stored time step.",
    "warmup_periods_by_solver": "Warmup periods dropped before comparing solver outputs to the reference.",
}


def _load_toml_file(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8-sig"))


def _split_path_tokens(path: str) -> list[str]:
    tokens: list[str] = []
    for chunk in str(path).split("."):
        parts = chunk.replace("]", "").split("[")
        tokens.extend(part for part in parts if part)
    return tokens


def _flatten_toml_values(value: Any, *, prefix: str = "") -> list[tuple[str, Any]]:
    items: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            items.extend(_flatten_toml_values(child, prefix=child_prefix))
        return items
    if isinstance(value, list):
        if not value or all(not isinstance(item, (dict, list)) for item in value):
            return [(prefix, value)]
        for index, child in enumerate(value):
            child_prefix = f"{prefix}[{index}]"
            items.extend(_flatten_toml_values(child, prefix=child_prefix))
        return items
    return [(prefix, value)]


def _format_numeric_value(value: float) -> str:
    return f"{float(value):.6g}"


def _unit_for_field(field: str) -> str:
    normalized = str(field)
    if normalized in {"west_head", "east_head", "river_head"} or normalized.endswith("_head_m"):
        return "m"
    if normalized == "flow.ic.value":
        return "m"
    if normalized.startswith("flow.bc.dirichlet.") and normalized.endswith(".value"):
        return "m"
    if normalized.startswith("flow.bc.cauchy.") and normalized.endswith(".value"):
        return "m2/s"
    if normalized.startswith("data.oceanic.sources") and normalized.endswith(".value"):
        return "m"
    if normalized.startswith("data.recharge.sources") and normalized.endswith(".values"):
        return "mm/day"
    if normalized.startswith("data.recharge.sources") and normalized.endswith(".amplitude"):
        return "mm/day"
    if normalized.endswith("period_days"):
        return "days"
    if normalized.endswith("base_elevation") or normalized.endswith("crest_elevation"):
        return "m"
    if normalized.endswith("substratum_elevation") or normalized.endswith("island_radius"):
        return "m"
    if normalized.endswith("thickness"):
        return "m"
    if normalized.endswith("_m_per_s"):
        return "m/s"
    if normalized.endswith("_m2_per_s"):
        return "m2/s"
    if normalized.endswith("_m3_day"):
        return "m3/day"
    if normalized.endswith("_mm_day"):
        return "mm/day"
    if normalized.endswith("_days"):
        return "days"
    if normalized.endswith("_seconds"):
        return "s"
    if normalized.endswith("_radians"):
        return "rad"
    if normalized.endswith("_m2"):
        return "m2"
    if normalized.endswith("_m"):
        return "m"
    if normalized.endswith("specific_yield"):
        return "-"
    return ""


def _format_parameter_value(field: str, value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        rendered = _format_numeric_value(float(value))
        unit = _unit_for_field(field)
        return f"{rendered} {unit}".strip()
    if isinstance(value, list):
        rendered_items = ", ".join(_format_parameter_value(field, item) for item in value)
        return f"[{rendered_items}]"
    if isinstance(value, dict):
        rendered_items = ", ".join(
            f"{key}={_format_parameter_value(field, item)}" for key, item in value.items()
        )
        return "{" + rendered_items + "}"
    return str(value)


def _meaning_for_reference_field(field: str) -> str:
    tokens = _split_path_tokens(field)
    key = tokens[-1] if tokens else field
    if len(tokens) >= 2 and tokens[-2] in {
        "hydraulic_conductivity_m_per_s_by_zone",
        "hydraulic_conductivity_m_per_s_by_ring",
    }:
        group = tokens[-2]
        label = tokens[-1]
        if group.endswith("_by_zone"):
            return f"Zone-specific hydraulic conductivity used by the reference for `{label}`."
        return f"Ring-specific hydraulic conductivity used by the radial reference for `{label}`."
    if len(tokens) >= 2 and tokens[-2] in {
        "comparison_radius_max_by_solver",
        "warmup_periods_by_solver",
    }:
        group = tokens[-2]
        solver = tokens[-1]
        if group == "comparison_radius_max_by_solver":
            return f"Maximum comparison radius retained for `{solver}`."
        return f"Warmup periods dropped before comparing `{solver}` to the reference."
    if key == "x_zone_breaks_m":
        return "x-coordinate breaks used to define conductivity zones in the reference solution."
    if key == "ring_radius_breaks_m":
        return (
            "Ring-radius breaks used to define heterogeneous conductivity in the radial reference."
        )
    if key == "west_head_levels_m":
        return "Sequence of west-boundary head levels used by the transient boundary forcing."
    if key in _REFERENCE_PARAMETER_MEANINGS:
        return _REFERENCE_PARAMETER_MEANINGS[key]
    if key in _TIME_PARAMETER_MEANINGS:
        return _TIME_PARAMETER_MEANINGS[key]
    return f"Reference parameter `{key}` used by the analytical or benchmark solution."


def _meaning_for_output_field(field: str) -> str:
    tokens = _split_path_tokens(field)
    key = tokens[-1] if tokens else field
    if len(tokens) >= 2 and tokens[-2] in {
        "expected_shape_by_solver",
        "expected_spatial_shape_by_solver",
        "warmup_periods_by_solver",
    }:
        group = tokens[-2]
        solver = tokens[-1]
        if group == "expected_shape_by_solver":
            return f"Expected spatial output shape checked for `{solver}`."
        if group == "expected_spatial_shape_by_solver":
            return f"Expected per-time-step spatial shape checked for `{solver}`."
        return f"Warmup periods dropped before comparing `{solver}` to the reference."
    if key in _OUTPUT_PARAMETER_MEANINGS:
        return _OUTPUT_PARAMETER_MEANINGS[key]
    return f"Acceptance field `{key}` checked by the validation helper."


def _humanize_name(token: str) -> str:
    return token.replace("_", " ").strip()


def _meaning_for_config_field(field: str) -> str:
    tokens = _split_path_tokens(field)
    if not tokens:
        return "Validation configuration value."

    if tokens[:3] == ["simulation", "time", "start_datetime"]:
        return "Simulation start time used by the benchmark."
    if tokens[:3] == ["simulation", "time", "end_datetime"]:
        return "Simulation end time used by the benchmark."
    if tokens[:3] == ["simulation", "time", "step_value"]:
        return "Nominal time step used by the benchmark."

    if tokens[:3] == ["geographic", "synthetic", "grid"]:
        leaf = tokens[-1]
        if leaf == "length_x":
            return "Synthetic-domain length along the x axis."
        if leaf == "length_y":
            return "Synthetic-domain length along the y axis."
        if leaf == "nx":
            return "Grid cell count along the x axis."
        if leaf == "ny":
            return "Grid cell count along the y axis."

    if tokens[:3] == ["geographic", "synthetic", "topography"]:
        leaf = tokens[-1]
        if leaf == "kind":
            return "Synthetic topography shape used by the benchmark."
        if leaf == "base_elevation":
            return "Base land-surface elevation of the synthetic topography."
        if leaf == "crest_elevation":
            return "Crest elevation used by the synthetic topography."
        if leaf == "island_radius":
            return "Island radius used by the synthetic topography."
        if leaf == "right_to_left_amplitude":
            return "Right-to-left topographic amplitude used by the synthetic topography."

    if tokens[:2] == ["domain", "depth_model"]:
        leaf = tokens[-1]
        if leaf == "type":
            return "Depth model used to build the aquifer support."
        if leaf == "thickness":
            return "Aquifer or support thickness used by the benchmark."
        if leaf == "substratum_elevation":
            return "Substratum elevation used to build the synthetic support."

    if len(tokens) >= 4 and tokens[:2] == ["domain", "supports"]:
        support_name = tokens[2]
        leaf = tokens[-1]
        if leaf == "provider":
            return f"How the support `{support_name}` is generated."
        if leaf == "axis":
            return f"Axis used to build support `{support_name}`."
        if leaf == "coordinate_mode":
            return f"Coordinate interpretation used to define support `{support_name}`."
        if leaf == "breaks":
            return f"Break values used to split support `{support_name}`."
        if leaf == "labels":
            return f"Labels assigned to the zones of support `{support_name}`."

    if field == "flow.flow_regime":
        return "Steady or transient flow regime used by the benchmark."
    if field == "flow.active_sinks_sources":
        return "Sink and source families activated in the benchmark."
    if field == "flow.active_bc":
        return "Boundary-condition families activated in the benchmark."
    if field == "flow.param_list":
        return "Hydraulic parameter families explicitly configured by the benchmark."

    if tokens[:2] == ["flow", "param"] and len(tokens) >= 5:
        parameter_name = tokens[2]
        if tokens[-1] == "kind":
            return f"Parameterization mode used for `{parameter_name}`."
        if tokens[-1] == "value" and "field_homogeneous" in tokens:
            return f"Homogeneous `{parameter_name}` value used by the benchmark."
        if tokens[-1] == "values_source" and "field_heterogeneous" in tokens:
            return f"Value source used for the heterogeneous `{parameter_name}` field."
        if tokens[-1] == "field_spatial_id" and "field_heterogeneous" in tokens:
            return (
                f"Support identifier used to distribute the heterogeneous `{parameter_name}` field."
            )
        if "field_heterogeneous" in tokens and "values" in tokens:
            zone_name = tokens[-1]
            return f"Heterogeneous `{parameter_name}` value applied on support zone `{zone_name}`."

    if field == "flow.ic.value":
        return "Initial hydraulic head used to start the benchmark."

    if len(tokens) >= 5 and tokens[:3] == ["flow", "bc", "dirichlet"]:
        boundary_name = _humanize_name(tokens[3])
        if tokens[-1] == "value":
            return f"Fixed head applied on the {boundary_name} boundary."
        if "forcing" in tokens and tokens[-1] == "values":
            return f"Time series applied to the {boundary_name} boundary."
        if "forcing" in tokens and tokens[-1] == "start_date":
            return f"Start date of the forcing applied to the {boundary_name} boundary."
        if "forcing" in tokens and tokens[-1] == "freq":
            return f"Sampling frequency of the forcing applied to the {boundary_name} boundary."
        if "forcing" in tokens and tokens[-1] == "periods":
            return f"Number of forcing periods applied to the {boundary_name} boundary."

    if len(tokens) >= 5 and tokens[:3] == ["flow", "bc", "cauchy"]:
        boundary_name = _humanize_name(tokens[3])
        if tokens[-1] == "application_domain":
            return f"Part of the domain where the {boundary_name} Cauchy boundary is applied."
        if tokens[-1] == "value":
            return f"Cauchy coefficient or conductance applied on the {boundary_name} boundary."

    if len(tokens) >= 5 and tokens[:3] == ["flow", "sinks_sources", "wells"]:
        well_name = tokens[3]
        if tokens[-1] == "cell":
            return f"Cell index used by pumping well `{well_name}`."
        if tokens[-1] == "units":
            return f"Units used by pumping well `{well_name}` forcing."
        if tokens[-1] == "description":
            return f"Short description of pumping well `{well_name}`."
        if "forcing" in tokens and tokens[-1] == "mode":
            return f"Forcing mode used by pumping well `{well_name}`."
        if "forcing" in tokens and tokens[-1] == "value":
            return f"Forcing value applied to pumping well `{well_name}`."

    if field == "data.types":
        return "External data families loaded by the benchmark."

    if len(tokens) >= 4 and tokens[:2] == ["data", "recharge"]:
        if tokens[-1] == "source":
            return "Recharge data source mode used by the benchmark."
        if tokens[-1] == "values":
            return "Recharge values used by the benchmark forcing."
        if tokens[-1] == "amplitude":
            return "Amplitude of the periodic recharge forcing."
        if tokens[-1] == "period_days":
            return "Period of the periodic recharge forcing."
        if tokens[-1] == "start_date":
            return "Start date of the recharge forcing."
        if tokens[-1] == "freq":
            return "Sampling frequency used for the recharge forcing."
        if tokens[-1] == "periods":
            return "Number of recharge forcing periods."
        if tokens[-1] == "runoff_ratio":
            return (
                "Runoff ratio applied when converting recharge forcing to effective infiltration."
            )

    if len(tokens) >= 4 and tokens[:2] == ["data", "oceanic"]:
        if tokens[-1] == "source":
            return "Oceanic data source mode used by the benchmark."
        if tokens[-1] == "value":
            return "Ocean level value supplied to the benchmark."

    if field.startswith("flow.runtime_backend"):
        return "Runtime backend selected for the in-house solver."

    if tokens[:2] == ["mesh_input", "mesh_path"]:
        return "Committed unstructured mesh file used by the irregular-mesh solver variant."
    if tokens[:2] == ["mesh_input", "bundle_dir"]:
        return "Committed mesh-bundle directory used to recover support metadata for the irregular-mesh solver variant."

    if tokens[0] in _SOLVER_CONFIG_SECTION_NAMES:
        solver_name = _normalize_solver_name(tokens[0])
        leaf = tokens[-1]
        if leaf == "mf6_ims_complexity":
            return f"Linear-solver complexity preset used by {solver_name}."
        if leaf == "vka":
            return f"Vertical anisotropy ratio passed to {solver_name}."
        if leaf == "mode":
            return f"Planar support construction mode used by {solver_name}."
        if leaf == "nx":
            return f"Planar support cell count along x used by {solver_name}."
        if leaf == "ny":
            return f"Planar support cell count along y used by {solver_name}."
        if leaf == "resampling":
            return f"Planar support resampling mode used by {solver_name}."
        if leaf == "nlay":
            return f"Number of vertical layers used by {solver_name}."
        if leaf == "firstpersteady":
            return f"Whether the first time period is treated as steady by {solver_name}."
        if leaf == "runtime_backend":
            return f"Runtime backend selected for {solver_name}."
        return f"Solver-specific override applied to {solver_name}."

    return f"Case-specific configuration field `{field}` used by the validation benchmark."


def _meaning_for_tolerance_field(field: str) -> str:
    tokens = _split_path_tokens(field)
    if not tokens:
        return "Acceptance threshold used by the validation helper."
    metric_group = _humanize_name(tokens[0])
    metric_name = tokens[-1]
    if metric_name == "rmse":
        return f"Maximum accepted root-mean-square error for {metric_group}."
    if metric_name == "max_abs_error":
        return f"Maximum accepted absolute error for {metric_group}."
    if metric_name == "row_spread":
        return f"Maximum accepted cross-row spread for {metric_group}."
    if metric_name == "mae":
        return f"Maximum accepted mean absolute error for {metric_group}."
    return f"Acceptance threshold for `{field}`."


def _build_parameter_row(*, field: str, meaning: str, value: Any, source: str) -> dict[str, str]:
    return {
        "field": field,
        "meaning": meaning,
        "value": _format_parameter_value(field, value),
        "source": source,
    }


def _should_include_common_config_field(field: str) -> bool:
    if not field:
        return False
    tokens = _split_path_tokens(field)
    if not tokens:
        return False
    if tokens[0] in _SOLVER_CONFIG_SECTION_NAMES:
        return False
    excluded_fields = {
        "simulation.name",
        "simulation.description",
        "workspace.project_root",
        "geographic.source_mode",
        "geographic.synthetic.case_id",
        "data.inference_mode",
        "display.enabled",
        "simulation.time.coverage_policy",
        "flow.ic.type",
        "flow.sinks_sources.recharge.first_clim",
        "flow.sinks_sources.recharge.negative_to_evt",
    }
    if field in excluded_fields:
        return False
    if field.startswith("simulation.process"):
        return False
    if field.endswith(".id"):
        return False
    if re.match(r"flow\.bc\.[^.]+\.[^.]+\.type$", field):
        return False
    return True


def _should_include_solver_override_field(field: str, *, solver: str) -> bool:
    if field.startswith(f"{solver}."):
        return True
    if solver == "modflow6_irregular_tri":
        return field.startswith("modflow6.") or field.startswith("mesh_input.")
    return solver == "boussinesq" and field == "flow.runtime_backend"


def _build_reference_parameter_docs(
    *,
    metadata_payload: dict[str, Any],
    metadata_rel_path: str,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for section_name in ("reference", "time"):
        section = metadata_payload.get(section_name)
        if not isinstance(section, dict):
            continue
        for field, value in _flatten_toml_values(section):
            rows.append(
                _build_parameter_row(
                    field=field,
                    meaning=_meaning_for_reference_field(field),
                    value=value,
                    source=metadata_rel_path,
                )
            )
    return rows


def _build_common_config_parameter_docs(
    *,
    case_dir: Path,
    metadata_payload: dict[str, Any],
    config_files: dict[str, str],
    default_solver: str,
    repo_root: Path,
) -> list[dict[str, str]]:
    base_config_name = str(metadata_payload.get("base_config", "")).strip()
    if not base_config_name:
        base_config_name = str(config_files.get(default_solver, "")).strip()
    if not base_config_name:
        return []
    config_path = case_dir / base_config_name
    config_rel_path = _repo_relative(config_path, repo_root=repo_root)
    payload = _load_toml_file(config_path)
    rows: list[dict[str, str]] = []
    for field, value in _flatten_toml_values(payload):
        if not _should_include_common_config_field(field):
            continue
        rows.append(
            _build_parameter_row(
                field=field,
                meaning=_meaning_for_config_field(field),
                value=value,
                source=config_rel_path,
            )
        )
    return rows


def _build_solver_override_docs(
    *,
    case_dir: Path,
    config_files: dict[str, str],
    solver_variants: tuple[str, ...],
    repo_root: Path,
) -> dict[str, list[dict[str, str]]]:
    overrides: dict[str, list[dict[str, str]]] = {}
    for solver in solver_variants:
        config_name = config_files.get(solver)
        if not config_name:
            overrides[solver] = []
            continue
        config_path = case_dir / config_name
        config_rel_path = _repo_relative(config_path, repo_root=repo_root)
        payload = _load_toml_file(config_path)
        rows: list[dict[str, str]] = []
        for field, value in _flatten_toml_values(payload):
            if not _should_include_solver_override_field(field, solver=solver):
                continue
            rows.append(
                _build_parameter_row(
                    field=field,
                    meaning=_meaning_for_config_field(field),
                    value=value,
                    source=config_rel_path,
                )
            )
        overrides[solver] = rows
    return overrides


def _build_acceptance_docs(
    *,
    metadata_payload: dict[str, Any],
    metadata_rel_path: str,
    tolerance_files: dict[str, str],
    solver_variants: tuple[str, ...],
    solver_details: dict[str, dict[str, Any]],
    repo_root: Path,
) -> dict[str, Any]:
    common_rows: list[dict[str, str]] = []
    output_payload = metadata_payload.get("output")
    if isinstance(output_payload, dict):
        for field, value in _flatten_toml_values(output_payload):
            if (
                field.endswith("_by_solver.modflownwt")
                or field.endswith("_by_solver.modflow6")
                or field.endswith("_by_solver.boussinesq")
            ):
                continue
            common_rows.append(
                _build_parameter_row(
                    field=f"output.{field}",
                    meaning=_meaning_for_output_field(field),
                    value=value,
                    source=metadata_rel_path,
                )
            )

    solver_rows: dict[str, list[dict[str, str]]] = {}
    for solver in solver_variants:
        rows: list[dict[str, str]] = []
        detail = solver_details.get(solver, {})
        expected_output = str(detail.get("expected_output", "")).strip()
        if expected_output:
            rows.append(
                _build_parameter_row(
                    field="expected_output",
                    meaning="Expected output shape or time-space layout checked for this solver.",
                    value=expected_output,
                    source=metadata_rel_path,
                )
            )
        tolerance_rel_path = str(
            tolerance_files.get(solver, tolerance_files.get("default", ""))
        ).strip()
        if tolerance_rel_path:
            tolerance_payload = _load_toml_file(repo_root / tolerance_rel_path)
            for field, value in _flatten_toml_values(tolerance_payload):
                rows.append(
                    _build_parameter_row(
                        field=field,
                        meaning=_meaning_for_tolerance_field(field),
                        value=value,
                        source=tolerance_rel_path,
                    )
                )
        solver_rows[solver] = rows

    return {
        "common": common_rows,
        "solver_specific": solver_rows,
    }


def _build_validation_parameter_docs(
    *,
    case_dir: Path,
    metadata_payload: dict[str, Any],
    config_files: dict[str, str],
    default_solver: str,
    solver_variants: tuple[str, ...],
    tolerance_files: dict[str, str],
    solver_details: dict[str, dict[str, Any]],
    repo_root: Path,
) -> dict[str, Any]:
    metadata_rel_path = _repo_relative(case_dir / "metadata.toml", repo_root=repo_root)
    return {
        "reference_parameters": _build_reference_parameter_docs(
            metadata_payload=metadata_payload,
            metadata_rel_path=metadata_rel_path,
        ),
        "common_setup": _build_common_config_parameter_docs(
            case_dir=case_dir,
            metadata_payload=metadata_payload,
            config_files=config_files,
            default_solver=default_solver,
            repo_root=repo_root,
        ),
        "solver_overrides": _build_solver_override_docs(
            case_dir=case_dir,
            config_files=config_files,
            solver_variants=solver_variants,
            repo_root=repo_root,
        ),
        "acceptance_criteria": _build_acceptance_docs(
            metadata_payload=metadata_payload,
            metadata_rel_path=metadata_rel_path,
            tolerance_files=tolerance_files,
            solver_variants=solver_variants,
            solver_details=solver_details,
            repo_root=repo_root,
        ),
    }


def _equations_for_case(slug: str) -> tuple[str, ...]:
    equation_map = {
        "dupuit_fixed_head_1d": (
            r"\frac{\mathrm{d}}{\mathrm{d}x}\left(K\,h\,\frac{\mathrm{d}h}{\mathrm{d}x}\right)=0",
            r"h(x)=\sqrt{h_w^2+\left(h_e^2-h_w^2\right)\frac{x-x_{\min}}{x_{\max}-x_{\min}}}",
        ),
        "dupuit_uniform_recharge_1d": (
            r"\frac{\mathrm{d}}{\mathrm{d}x}\left(K\,h\,\frac{\mathrm{d}h}{\mathrm{d}x}\right)+R=0",
            r"h(x)^2=h_w^2+\left(h_e^2-h_w^2\right)\frac{\xi}{L}+\frac{R}{K}\,\xi\left(L-\xi\right),\quad \xi=x-x_{\min}",
        ),
        "dupuit_divide_river_1d": (
            r"\frac{\mathrm{d}}{\mathrm{d}x}\left(K\,h\,\frac{\mathrm{d}h}{\mathrm{d}x}\right)+R=0,\qquad \frac{\mathrm{d}h}{\mathrm{d}x}(0)=0,\qquad h(L)=h_r",
            r"h(x)^2=h_r^2+\frac{R}{K}\left(L^2-x^2\right)",
        ),
        "dupuit_circular_island_ocean_2d": (
            r"\frac{1}{r}\frac{\mathrm{d}}{\mathrm{d}r}\left(r\,K\,H\,\frac{\mathrm{d}H}{\mathrm{d}r}\right)+R=0",
            r"H(r)^2=H(a)^2+\frac{R}{2K}\left(a^2-r^2\right)",
            r"h(r)=z_b+\sqrt{\left(h_{\mathrm{sea}}-z_b\right)^2+\frac{R}{2K}\left(a^2-r^2\right)}",
        ),
        "boussinesq_fixed_head_piecewise_k_1d": (
            r"U=h^2,\qquad \frac{\mathrm{d}}{\mathrm{d}x}\left(K(x)\,\frac{\mathrm{d}U}{\mathrm{d}x}\right)=0",
            r"U(x)=h_w^2+\left(h_e^2-h_w^2\right)\frac{\int_{x_{\min}}^{x}\frac{\mathrm{d}s}{K(s)}}{\int_{x_{\min}}^{x_{\max}}\frac{\mathrm{d}s}{K(s)}}",
        ),
        "boussinesq_uniform_recharge_piecewise_k_1d": (
            r"U=h^2,\qquad \frac{\mathrm{d}}{\mathrm{d}x}\left(K(x)\,\frac{\mathrm{d}U}{\mathrm{d}x}\right)+2R=0",
            r"U(x)=h_w^2+C\int_{x_{\min}}^{x}\frac{\mathrm{d}s}{K(s)}-2R\int_{x_{\min}}^{x}\frac{s\,\mathrm{d}s}{K(s)}",
        ),
        "boussinesq_divide_fixed_head_piecewise_k_1d": (
            r"U=h^2,\qquad \frac{\mathrm{d}}{\mathrm{d}x}\left(K(x)\,\frac{\mathrm{d}U}{\mathrm{d}x}\right)+2R=0",
            r"\frac{\mathrm{d}U}{\mathrm{d}x}(0)=0,\qquad U(L)=h_e^2,\qquad U(x)=h_e^2+2R\int_x^L \frac{s\,\mathrm{d}s}{K(s)}",
        ),
        "boussinesq_circular_island_piecewise_k_2d": (
            r"\frac{1}{r}\frac{\mathrm{d}}{\mathrm{d}r}\left(r\,K(r)\,H\,\frac{\mathrm{d}H}{\mathrm{d}r}\right)+R=0",
            r"U=H^2,\qquad U(r)=U(a)+R\int_r^a \frac{s}{K(s)}\,\mathrm{d}s",
        ),
        "boussinesq_sloping_substratum_constant_thickness_1d": (
            r"H(x)=z_b(x)+b^\ast,\qquad z_b(x)=z_{b,0}+\Delta z_b\left(1-\frac{x-x_{\min}}{L}\right)",
            r"q=-K\,b^\ast\,\frac{\mathrm{d}H}{\mathrm{d}x}=K\,b^\ast\,S_0,\qquad S_0=\frac{z_b(x_{\min})-z_b(x_{\max})}{L}",
        ),
        "boussinesq_sloping_substratum_fixed_head_1d": (
            r"q=K\,b\left(S_0-\frac{\mathrm{d}b}{\mathrm{d}x}\right),\qquad S_0=-\frac{\mathrm{d}z_b}{\mathrm{d}x}",
            r"x-x_{\min}=\int_{b_w}^{b(x)} \frac{K\,\beta\,\eta-q}{K\,\beta^2}\,\mathrm{d}\eta,\qquad \beta=S_0,\qquad H(x)=z_b(x)+b(x)",
        ),
        "boussinesq_sloping_substratum_uniform_recharge_1d": (
            r"\frac{\mathrm{d}q}{\mathrm{d}x}=R,\qquad q(x)=q_w+R\left(x-x_{\min}\right)",
            r"\frac{\mathrm{d}b}{\mathrm{d}x}=S_0-\frac{q(x)}{K\,b(x)},\qquad S_0=-\frac{\mathrm{d}z_b}{\mathrm{d}x},\qquad H(x)=z_b(x)+b(x)",
        ),
        "boussinesq_hillslope_interception_1d": (
            r"h(x)^2=h_e^2+\frac{R}{K}\left(L^2-x^2\right)",
            r"z_{\mathrm{top}}(x)=z_{\mathrm{toe}}+S\left(L-x\right),\qquad h(x_{\mathrm{int}})=z_{\mathrm{top}}(x_{\mathrm{int}})",
        ),
        "linearized_unconfined_drainage_1d": (
            r"T_0\,\frac{\mathrm{d}^2u}{\mathrm{d}x^2}-\lambda_d\,u=0,\qquad u=h-z_d,\qquad \lambda_d=\frac{C_d}{A}",
            r"u(x)=u_w\frac{\sinh\left(\beta(L-x)\right)}{\sinh\left(\beta L\right)}+u_e\frac{\sinh\left(\beta x\right)}{\sinh\left(\beta L\right)},\qquad \beta=\sqrt{\frac{\lambda_d}{T_0}}",
        ),
        "linearized_unconfined_hillslope_drainage_1d": (
            r"T_0\,\frac{\mathrm{d}^2u}{\mathrm{d}x^2}-\lambda_d\,u=0,\qquad u=h-z_{\mathrm{top}}(x)",
            r"z_{\mathrm{top}}(x)=z_0+A\left(1-\frac{x-x_{\min}}{L}\right),\qquad u(x)=u_w\frac{\sinh\left(\beta(L-x)\right)}{\sinh\left(\beta L\right)}+u_e\frac{\sinh\left(\beta x\right)}{\sinh\left(\beta L\right)}",
        ),
        "linearized_unconfined_recharge_step_1d": (
            r"S_y\frac{\partial \eta}{\partial t}=T_0\frac{\partial^2 \eta}{\partial x^2}+R_0\,H(t),\qquad h=h_0+\eta",
            r"\eta(x,t)=\frac{R_0}{2T_0}x(L-x)-\frac{4R_0L^2}{T_0\pi^3}\sum_{n=0}^{\infty}\frac{\sin\left((2n+1)\pi x/L\right)}{(2n+1)^3}\exp\left(-D\left((2n+1)\pi/L\right)^2 t\right)",
        ),
        "linearized_unconfined_recharge_step_deep_1d": (
            r"S_y\frac{\partial \eta}{\partial t}=T_0\frac{\partial^2 \eta}{\partial x^2}+R_0\,H(t),\qquad h=h_0+\eta",
            r"T_0=K\,h_{\mathrm{ref}},\qquad D=\frac{T_0}{S_y}",
        ),
        "linearized_unconfined_recharge_periodic_1d": (
            r"S_y\frac{\partial \eta}{\partial t}=T_0\frac{\partial^2 \eta}{\partial x^2}+R(t),\qquad h=h_0+\eta",
            r"R(t)=\overline{R}+A\sin\left(2\pi t/P+\phi\right)",
        ),
        "linearized_unconfined_boundary_step_1d": (
            r"S_y\frac{\partial \eta}{\partial t}=T_0\frac{\partial^2 \eta}{\partial x^2},\qquad \eta(0,t)=\Delta h\,H(t),\qquad \eta(L,t)=0",
            r"\eta(x,t)=\Delta h\left[1-\frac{x}{L}-\frac{2}{\pi}\sum_{n=1}^{\infty}\frac{\sin\left(n\pi x/L\right)}{n}\exp\left(-D\left(n\pi/L\right)^2 t\right)\right]",
        ),
        "linearized_unconfined_boundary_piecewise_1d": (
            r"S_y\frac{\partial \eta}{\partial t}=T_0\frac{\partial^2 \eta}{\partial x^2},\qquad \eta(L,t)=0",
            r"\eta(x,t)=\sum_k \Delta h_k\,\eta_{\mathrm{step}}(x,t-t_k)\,H(t-t_k)",
        ),
        "boussinesq_hillslope_recharge_step_interception_1d": (
            r"S_y\frac{\partial \eta}{\partial t}=T_0\frac{\partial^2 \eta}{\partial x^2}+R_0\,H(t),\qquad \eta_{\mathrm{steady}}(x)=\frac{R_0}{2T_0}\left(L^2-x^2\right)",
            r"z_{\mathrm{top}}(x)=z_{\mathrm{toe}}+S\left(L-x\right),\qquad h(x,t)=z_{\mathrm{top}}(x)\ \text{defines the interception front}",
        ),
        "late_time_unconfined_pumping_2d": (
            r"s(r,t)=\frac{Q}{4\pi T}E_1(u)",
            r"u=\frac{r^2S}{4Tt},\qquad T=K\,h_{\mathrm{ref}},\qquad S=S_y",
        ),
    }
    return equation_map.get(slug, ())


def build_validation_case_records(
    *, repo_root: Path | None = None
) -> tuple[ValidationCaseRecord, ...]:
    """Discover analytical validation cases and return gallery-ready records."""

    resolved_repo_root = _repo_root(repo_root)
    inventory_table, sheet_table = _load_validation_case_tables(repo_root=resolved_repo_root)
    case_dirs = sorted(
        (resolved_repo_root / "validation_cases" / "analytical").rglob("metadata.toml")
    )
    discovered: list[ValidationCaseRecord] = []

    solver_rank = {name: index for index, name in enumerate(VALIDATION_SOLVER_ORDER)}
    regime_rank = {"steady": 0, "transient": 1}

    for metadata_path in case_dirs:
        case_dir = metadata_path.parent
        slug = case_dir.name
        metadata_payload = tomllib.loads(metadata_path.read_text(encoding="utf-8"))
        readme_info = _load_readme_info(case_dir / "README.md")
        run_case_metadata = _discover_run_case_metadata(case_dir, repo_root=resolved_repo_root)

        inventory_entry = inventory_table.get(slug)
        sheet_entry = sheet_table.get(slug)

        config_files = dict(metadata_payload.get("config_files", {}))
        ordered_solver_variants = tuple(
            sorted(
                config_files,
                key=lambda solver: (solver_rank.get(solver, 999), solver),
            )
        )
        default_solver = str(
            metadata_payload.get(
                "default_solver", ordered_solver_variants[0] if ordered_solver_variants else ""
            )
        )

        case_setup_bullets = list(readme_info.sections.get("numerical_setup", ()))
        if not case_setup_bullets and sheet_entry is not None and sheet_entry.numerical_setup:
            case_setup_bullets.append(sheet_entry.numerical_setup)
        if ordered_solver_variants:
            case_setup_bullets.append(
                "Available solver variants: "
                + ", ".join(_normalize_solver_name(solver) for solver in ordered_solver_variants)
                + "."
            )

        what_it_shows = list(readme_info.sections.get("intent", ()))
        if sheet_entry is not None and sheet_entry.what_it_validates:
            what_it_shows.append(sheet_entry.what_it_validates)
        if sheet_entry is not None and sheet_entry.primary_metrics:
            what_it_shows.append(f"Primary metrics: {sheet_entry.primary_metrics}.")
        if len(ordered_solver_variants) > 1:
            what_it_shows.append(
                "Solver-specific figures and metrics are shown side by side so the same benchmark can be read across backends."
            )

        reference_highlights = list(readme_info.sections.get("reference_model", ()))
        for bullet in readme_info.sections.get("comparison", ()):
            lowered = bullet.lower()
            if lowered.startswith("reference:") or lowered.startswith("compared quantity:"):
                reference_highlights.append(bullet)
        if not reference_highlights and sheet_entry is not None and sheet_entry.analytical_target:
            reference_highlights.append(sheet_entry.analytical_target)

        tolerance_files: dict[str, str] = {}
        generic_tolerance = case_dir / "tolerances.toml"
        if generic_tolerance.exists():
            tolerance_files["default"] = _repo_relative(
                generic_tolerance, repo_root=resolved_repo_root
            )
        for solver in ordered_solver_variants:
            candidate = case_dir / f"tolerances_{solver}.toml"
            if candidate.exists():
                tolerance_files[solver] = _repo_relative(candidate, repo_root=resolved_repo_root)

        solver_details = {
            solver: {
                "display_name": _normalize_solver_name(solver),
                "config_path": _repo_relative(
                    case_dir / config_files[solver], repo_root=resolved_repo_root
                ),
                "expected_output": _format_expected_output(metadata_payload, solver),
                "tolerance_path": tolerance_files.get(solver, tolerance_files.get("default")),
            }
            for solver in ordered_solver_variants
        }
        parameter_docs = _build_validation_parameter_docs(
            case_dir=case_dir,
            metadata_payload=metadata_payload,
            config_files=config_files,
            default_solver=default_solver,
            solver_variants=ordered_solver_variants,
            tolerance_files=tolerance_files,
            solver_details=solver_details,
            repo_root=resolved_repo_root,
        )
        taxonomy = _build_validation_taxonomy(slug=slug, metadata_payload=metadata_payload)

        reproduction_command = f"python -m {_repo_relative(case_dir / 'run_case.py', repo_root=resolved_repo_root).replace('/', '.').removesuffix('.py')} --no-show"

        discovered.append(
            ValidationCaseRecord(
                slug=slug,
                title=readme_info.title,
                deck=inventory_entry.purpose
                if inventory_entry is not None
                else (readme_info.summary or slug.replace("_", " ")),
                summary=readme_info.summary
                or (inventory_entry.purpose if inventory_entry is not None else ""),
                regime=str(
                    metadata_payload.get(
                        "regime", inventory_entry.regime if inventory_entry is not None else ""
                    )
                ),
                dimension=str(
                    metadata_payload.get(
                        "dimension",
                        inventory_entry.dimension if inventory_entry is not None else "",
                    )
                ),
                reproduction_command=reproduction_command,
                source_paths=_build_source_paths(
                    case_dir,
                    repo_root=resolved_repo_root,
                    config_files=config_files,
                    metadata_payload=metadata_payload,
                ),
                case_setup=_dedupe_preserve_order(case_setup_bullets),
                what_it_shows=_dedupe_preserve_order(what_it_shows),
                reference_highlights=_dedupe_preserve_order(reference_highlights),
                equations_rst=_equations_for_case(slug),
                metadata={
                    "case_dir": _repo_relative(case_dir, repo_root=resolved_repo_root),
                    "run_case_file": _repo_relative(
                        case_dir / "run_case.py", repo_root=resolved_repo_root
                    ),
                    "run_case_module": run_case_metadata["run_case_module"],
                    "comparison_function_name": run_case_metadata["comparison_function_name"],
                    "plotting_function_name": run_case_metadata["plotting_function_name"],
                    "metric_builder_name": run_case_metadata["metric_builder_name"],
                    "default_figure_name": run_case_metadata["default_figure_name"],
                    "run_description": run_case_metadata["run_description"],
                    "default_solver": default_solver,
                    "solver_variants": ordered_solver_variants,
                    "solver_details": solver_details,
                    "regime": str(metadata_payload.get("regime", "")),
                    "dimension": str(metadata_payload.get("dimension", "")),
                    "inventory_reference": inventory_entry.reference
                    if inventory_entry is not None
                    else "",
                    "case_sheet": {
                        "numerical_setup": sheet_entry.numerical_setup
                        if sheet_entry is not None
                        else "",
                        "analytical_target": sheet_entry.analytical_target
                        if sheet_entry is not None
                        else "",
                        "primary_metrics": sheet_entry.primary_metrics
                        if sheet_entry is not None
                        else "",
                        "what_it_validates": sheet_entry.what_it_validates
                        if sheet_entry is not None
                        else "",
                    },
                    "parameter_docs": parameter_docs,
                    **taxonomy,
                },
            )
        )

    return tuple(
        sorted(
            discovered,
            key=lambda record: (
                regime_rank.get(record.regime, 999),
                record.dimension,
                record.slug,
            ),
        )
    )


__all__ = [
    "VALIDATION_SOLVER_ORDER",
    "ValidationCaseRecord",
    "build_validation_case_records",
]
