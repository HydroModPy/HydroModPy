"""Discovery helpers for analytical validation cases used by the doc gallery."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from pathlib import Path
import re
import tomllib
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATION_SOLVER_ORDER = ("modflownwt", "modflow6", "boussinesq")


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
        "boussinesq": "Boussinesq",
    }
    return mapping.get(solver, solver.replace("_", " ").title())


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


def _load_validation_case_tables(*, repo_root: Path) -> tuple[dict[str, ValidationInventoryEntry], dict[str, ValidationCaseSheetEntry]]:
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
        expected_shape = output.get("expected_shape_by_solver", {}).get(solver, output["expected_shape"])
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
    module_name = _repo_relative(run_case_path.with_suffix(""), repo_root=repo_root).replace("/", ".")
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
        "default_figure_name": getattr(module, "DEFAULT_FIGURE_NAME"),
        "run_description": getattr(module, "RUN_DESCRIPTION", ""),
    }


def _extra_source_paths_for_case(slug: str) -> tuple[str, ...]:
    extra_paths: list[str] = []
    if "piecewise_k" in slug:
        extra_paths.append("validation_cases/analytical/steady/boussinesq_piecewise.py")
    if slug in {
        "dupuit_fixed_head_1d",
        "dupuit_uniform_recharge_1d",
        "dupuit_divide_river_1d",
        "linearized_unconfined_boundary_piecewise_1d",
        "linearized_unconfined_recharge_periodic_1d",
    }:
        extra_paths.append("validation_cases/shared/boussinesq_uniform_strip.py")
    if slug.startswith("linearized_unconfined_") or slug == "boussinesq_hillslope_recharge_step_interception_1d":
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


def build_validation_case_records(*, repo_root: Path | None = None) -> tuple[ValidationCaseRecord, ...]:
    """Discover analytical validation cases and return gallery-ready records."""

    resolved_repo_root = _repo_root(repo_root)
    inventory_table, sheet_table = _load_validation_case_tables(repo_root=resolved_repo_root)
    case_dirs = sorted((resolved_repo_root / "validation_cases" / "analytical").rglob("metadata.toml"))
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
            metadata_payload.get("default_solver", ordered_solver_variants[0] if ordered_solver_variants else "")
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
            tolerance_files["default"] = _repo_relative(generic_tolerance, repo_root=resolved_repo_root)
        for solver in ordered_solver_variants:
            candidate = case_dir / f"tolerances_{solver}.toml"
            if candidate.exists():
                tolerance_files[solver] = _repo_relative(candidate, repo_root=resolved_repo_root)

        solver_details = {
            solver: {
                "display_name": _normalize_solver_name(solver),
                "config_path": _repo_relative(case_dir / config_files[solver], repo_root=resolved_repo_root),
                "expected_output": _format_expected_output(metadata_payload, solver),
                "tolerance_path": tolerance_files.get(solver, tolerance_files.get("default")),
            }
            for solver in ordered_solver_variants
        }

        reproduction_command = (
            f"python -m {_repo_relative(case_dir / 'run_case.py', repo_root=resolved_repo_root).replace('/', '.').removesuffix('.py')} --no-show"
        )

        discovered.append(
            ValidationCaseRecord(
                slug=slug,
                title=readme_info.title,
                deck=inventory_entry.purpose if inventory_entry is not None else (readme_info.summary or slug.replace("_", " ")),
                summary=readme_info.summary or (inventory_entry.purpose if inventory_entry is not None else ""),
                regime=str(metadata_payload.get("regime", inventory_entry.regime if inventory_entry is not None else "")),
                dimension=str(metadata_payload.get("dimension", inventory_entry.dimension if inventory_entry is not None else "")),
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
                    "run_case_file": _repo_relative(case_dir / "run_case.py", repo_root=resolved_repo_root),
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
                    "inventory_reference": inventory_entry.reference if inventory_entry is not None else "",
                    "case_sheet": {
                        "numerical_setup": sheet_entry.numerical_setup if sheet_entry is not None else "",
                        "analytical_target": sheet_entry.analytical_target if sheet_entry is not None else "",
                        "primary_metrics": sheet_entry.primary_metrics if sheet_entry is not None else "",
                        "what_it_validates": sheet_entry.what_it_validates if sheet_entry is not None else "",
                    },
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
