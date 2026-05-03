"""Generate compact static assets for the code-comparison gallery pages."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyArrowPatch, Rectangle

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSET_ROOT = REPO_ROOT / "examples" / "projects" / "09_capability_gallery" / "code_comparison"

SOLVER_ORDER = (
    "modflownwt",
    "modflow6",
    "modflow6_irregular_tri",
    "boussinesq",
    "petsc_partition",
    "petsc",
)
SOLVER_LABELS = {
    "modflownwt": "MODFLOW-NWT",
    "modflow6": "MODFLOW 6",
    "modflow6_irregular_tri": "MODFLOW 6 irregular triangles",
    "boussinesq": "Boussinesq",
    "petsc_partition": "Boussinesq PETSc partition",
    "petsc": "Boussinesq PETSc complementarity",
}
SOLVER_COLORS = {
    "modflownwt": "#1f77b4",
    "modflow6": "#ff7f0e",
    "modflow6_irregular_tri": "#9467bd",
    "boussinesq": "#2ca02c",
    "petsc_partition": "#17becf",
    "petsc": "#d62728",
}


@dataclass(frozen=True, slots=True)
class ComparisonVariant:
    title: str
    run_dir: Path
    asset_dir: Path
    image_slug: str
    notes: tuple[str, ...]
    configuration: tuple[tuple[str, Any], ...]


@dataclass(frozen=True, slots=True)
class ComparisonCase:
    slug: str
    variants: tuple[ComparisonVariant, ...]


CASES = (
    ComparisonCase(
        slug="surface_interaction_ramp",
        variants=(
            ComparisonVariant(
                title="Reference K (6 methods)",
                run_dir=REPO_ROOT / "out" / "sih_tx_6cmp_linux_ramp_dirichlet_cell_20260416",
                asset_dir=ASSET_ROOT / "surface_interaction_ramp",
                image_slug="ramp_reference_k",
                notes=(
                    "Progressive recharge ramp followed by dry recovery.",
                    "Six methods: three MODFLOW variants plus three Boussinesq formulations.",
                ),
                configuration=(
                    ("geometry", "400 m x 30 m synthetic strip aquifer"),
                    ("topography", "5 m linear rise from east outlet to west divide"),
                    ("boundaries", "west no-flow, east fixed head, top drainage"),
                    ("east_fixed_head_m", 5.0625),
                    ("time_step_days", 15.0),
                    ("specific_yield", 0.10),
                    ("hydraulic_conductivity_scale", 0.2),
                    ("drainage_conductance_m2_s", 1.0e-4),
                    ("forcing", "progressive recharge ramp followed by dry recovery"),
                    (
                        "methods",
                        "MODFLOW-NWT, MODFLOW 6, MODFLOW 6 irregular triangles, "
                        "Boussinesq local partition, PETSc partition, PETSc complementarity",
                    ),
                ),
            ),
            ComparisonVariant(
                title="High K (Linux MF6 vs PETSc complementarity)",
                run_dir=REPO_ROOT / "out" / "sih_tx_highk_linux_mf6_petsc_comp_20260416",
                asset_dir=ASSET_ROOT / "surface_interaction_ramp",
                image_slug="ramp_high_k",
                notes=(
                    "Same ramp forcing with hydraulic conductivity multiplied by 8.",
                    "Linux PETSc benchmark: MODFLOW 6 compared against Boussinesq PETSc complementarity.",
                    "The previous high-K MODFLOW-NWT and local-partition comparison was dropped because it was poorly balanced.",
                ),
                configuration=(
                    ("geometry", "400 m x 30 m synthetic strip aquifer"),
                    ("topography", "5 m linear rise from east outlet to west divide"),
                    ("boundaries", "west no-flow, east fixed head, top drainage"),
                    ("east_fixed_head_m", 5.0625),
                    ("time_step_days", 15.0),
                    ("specific_yield", 0.10),
                    ("hydraulic_conductivity_scale", 1.6),
                    ("drainage_conductance_m2_s", 1.0e-4),
                    ("forcing", "same recharge ramp and dry recovery as the reference-K case"),
                    ("methods", "MODFLOW 6, Boussinesq PETSc complementarity"),
                ),
            ),
        ),
    ),
    ComparisonCase(
        slug="surface_interaction_no_seepage",
        variants=(
            ComparisonVariant(
                title="Reference K (4 methods)",
                run_dir=REPO_ROOT / "out" / "sih_tx_4cmp_linux_no_seepage_20260415",
                asset_dir=ASSET_ROOT / "surface_interaction_no_seepage",
                image_slug="no_seepage_reference_k",
                notes=(
                    "Surface lifted well above the imposed east head to suppress seepage.",
                    "Four cross-family methods on the same transient forcing.",
                ),
                configuration=(
                    ("geometry", "400 m x 30 m synthetic strip aquifer"),
                    ("topography", "surface lifted by +10 m relative to the ramp benchmark"),
                    (
                        "boundaries",
                        "west no-flow, east fixed head, top drainage inactive by design",
                    ),
                    ("time_step_days", 15.0),
                    ("specific_yield", 0.10),
                    ("hydraulic_conductivity_scale", 0.2),
                    ("drainage_conductance_m2_s", 1.0e-4),
                    ("forcing", "same recharge ramp and dry recovery as the ramp benchmark"),
                    (
                        "methods",
                        "MODFLOW-NWT, MODFLOW 6, MODFLOW 6 irregular triangles, "
                        "Boussinesq local partition",
                    ),
                ),
            ),
            ComparisonVariant(
                title="High K (4 methods)",
                run_dir=REPO_ROOT / "out" / "sih_tx_4cmp_linux_no_seepage_kx8_20260416",
                asset_dir=ASSET_ROOT / "surface_interaction_no_seepage",
                image_slug="no_seepage_high_k",
                notes=(
                    "Same no-seepage geometry with hydraulic conductivity multiplied by 8.",
                    "Used to check whether the cross-code agreement remains strong when lateral transmissivity is increased.",
                ),
                configuration=(
                    ("geometry", "400 m x 30 m synthetic strip aquifer"),
                    ("topography", "surface lifted by +10 m relative to the ramp benchmark"),
                    (
                        "boundaries",
                        "west no-flow, east fixed head, top drainage inactive by design",
                    ),
                    ("time_step_days", 15.0),
                    ("specific_yield", 0.10),
                    ("hydraulic_conductivity_scale", 1.6),
                    ("drainage_conductance_m2_s", 1.0e-4),
                    ("forcing", "same recharge ramp and dry recovery as the ramp benchmark"),
                    (
                        "methods",
                        "MODFLOW-NWT, MODFLOW 6, MODFLOW 6 irregular triangles, "
                        "Boussinesq local partition",
                    ),
                ),
            ),
        ),
    ),
)


def _solver_sort_key(solver: str) -> tuple[int, str]:
    if solver in SOLVER_ORDER:
        return (SOLVER_ORDER.index(solver), solver)
    return (len(SOLVER_ORDER), solver)


def _load_timeseries_rows(path: Path) -> list[dict[str, float | str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        rows: list[dict[str, float | str]] = []
        for row in reader:
            converted: dict[str, float | str] = {}
            for key, value in row.items():
                if value is None:
                    converted[key] = ""
                    continue
                text = str(value).strip()
                if key in {"solver", "solver_label"}:
                    converted[key] = text
                    continue
                try:
                    converted[key] = float(text)
                except ValueError:
                    converted[key] = text
            rows.append(converted)
    return rows


def _load_optional_csv_rows(path: Path) -> list[dict[str, float | str]]:
    if not path.is_file():
        return []
    return _load_timeseries_rows(path)


def _index_rows_by_solver(rows: list[dict[str, float | str]]) -> dict[str, dict[str, float | str]]:
    indexed: dict[str, dict[str, float | str]] = {}
    for row in rows:
        solver = str(row.get("solver", "")).strip()
        if solver:
            indexed[solver] = row
    return indexed


def _float_or_none(value: float | str | None) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _group_rows_by_solver(
    rows: list[dict[str, float | str]],
) -> dict[str, list[dict[str, float | str]]]:
    grouped: dict[str, list[dict[str, float | str]]] = {}
    for row in rows:
        solver = str(row["solver"])
        grouped.setdefault(solver, []).append(row)
    for solver_rows in grouped.values():
        solver_rows.sort(key=lambda item: float(item["elapsed_days"]))
    return grouped


def _plot_variant(
    rows: list[dict[str, float | str]], *, title: str, notes: tuple[str, ...], output_png: Path
) -> None:
    grouped = _group_rows_by_solver(rows)
    ordered_solvers = sorted(grouped, key=_solver_sort_key)

    fig, axes = plt.subplots(2, 1, figsize=(10.8, 8.2), sharex=True, constrained_layout=True)
    total_ax, storage_ax = axes
    reference_rows = grouped[ordered_solvers[0]]
    recharge_days = np.asarray([float(row["elapsed_days"]) for row in reference_rows], dtype=float)
    recharge_flux = np.asarray(
        [float(row["recharge_flux_m3_day"]) for row in reference_rows], dtype=float
    )
    recharge_ax = total_ax.twinx()
    recharge_fill = recharge_ax.fill_between(
        recharge_days,
        0.0,
        recharge_flux,
        step="post",
        color="#9ecae1",
        alpha=0.28,
        linewidth=0.0,
        zorder=0,
        label="Recharge",
    )
    recharge_ax.set_ylabel("Recharge [m3/day]")
    recharge_ax.set_ylim(0.0, max(float(np.max(recharge_flux)) * 1.1, 1.0))
    recharge_ax.tick_params(axis="y", colors="#4f81a8")
    recharge_ax.spines["right"].set_color("#4f81a8")
    for solver in ordered_solvers:
        solver_rows = grouped[solver]
        elapsed_days = np.asarray([float(row["elapsed_days"]) for row in solver_rows], dtype=float)
        total_outflow = np.asarray(
            [float(row["total_outflow_m3_day"]) for row in solver_rows], dtype=float
        )
        storage_change = np.asarray(
            [float(row["storage_change_m3_day"]) for row in solver_rows], dtype=float
        )
        style = {
            "color": SOLVER_COLORS.get(solver, "#444444"),
            "linewidth": 2.0,
        }
        if solver == "modflownwt":
            style.update({"marker": "o", "markersize": 3.8, "linewidth": 0.0})
        if solver == "petsc":
            style.update({"linestyle": "--"})
        total_ax.plot(elapsed_days, total_outflow, label=SOLVER_LABELS.get(solver, solver), **style)
        storage_ax.plot(
            elapsed_days, storage_change, label=SOLVER_LABELS.get(solver, solver), **style
        )

    total_ax.set_title("Total Outflow", fontsize=11.0)
    total_ax.set_ylabel("Flux [m3/day]")
    total_ax.grid(alpha=0.25, linewidth=0.6)
    handles, labels = total_ax.get_legend_handles_labels()
    total_ax.legend(
        handles + [recharge_fill],
        labels + ["Recharge"],
        loc="upper right",
        fontsize=8.6,
        frameon=False,
        ncols=2,
    )

    storage_ax.set_title("Storage Change", fontsize=11.0)
    storage_ax.set_xlabel("Time [days]")
    storage_ax.set_ylabel("Flux [m3/day]")
    storage_ax.axhline(0.0, color="#555555", linewidth=1.0, linestyle="--")
    storage_ax.grid(alpha=0.25, linewidth=0.6)

    note_text = "\n".join(f"- {item}" for item in notes)
    fig.suptitle(title, fontsize=12.4)
    fig.text(
        0.012,
        0.012,
        note_text,
        ha="left",
        va="bottom",
        fontsize=8.8,
        family="monospace",
    )
    output_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_png, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _write_surface_interaction_configuration_schematic(
    output_png: Path,
    *,
    no_seepage: bool = False,
) -> None:
    fig, ax = plt.subplots(1, 1, figsize=(10.8, 4.8), constrained_layout=True)
    ax.set_xlim(0.0, 1.0)
    ax.set_ylim(0.0, 1.0)
    ax.axis("off")

    top_x = np.array([0.08, 0.86])
    top_y = np.array([0.88, 0.58]) if no_seepage else np.array([0.82, 0.48])
    bottom_y = top_y - 0.22
    ax.fill_between(top_x, bottom_y, top_y, color="#f2d7b5", alpha=0.95)
    ax.plot(top_x, top_y, color="#8c510a", linewidth=2.4)
    ax.plot(top_x, bottom_y, color="#6c757d", linewidth=1.5)

    east_x = 0.86
    ax.add_patch(
        Rectangle(
            (east_x, 0.26),
            0.055,
            0.36,
            facecolor="#d9e6f2",
            edgecolor="#4f81a8",
            linewidth=1.4,
        )
    )
    ax.text(east_x + 0.028, 0.65, "East fixed head", ha="center", va="bottom", fontsize=10.0)
    if no_seepage:
        head_y = 0.43
        ax.plot([0.14, 0.86], [head_y, head_y], color="#2b6c9b", linewidth=1.8, linestyle="--")
        ax.text(
            0.5,
            head_y - 0.035,
            "Water table stays below lifted surface",
            ha="center",
            va="top",
            fontsize=9.8,
            color="#2b6c9b",
        )

    ax.text(0.085, 0.87, "West divide", ha="left", va="bottom", fontsize=10.0)
    surface_label = "Lifted ground surface (+10 m)" if no_seepage else "Sloping ground surface"
    ax.text(
        0.46, 0.72 if no_seepage else 0.69, surface_label, ha="center", va="bottom", fontsize=10.0
    )
    ax.text(
        0.47,
        0.37,
        "Unconfined aquifer strip\n400 m x 30 m",
        ha="center",
        va="center",
        fontsize=10.0,
    )

    for xpos in np.linspace(0.18, 0.72, 6):
        ax.add_patch(
            FancyArrowPatch(
                (xpos, 0.96),
                (xpos, 0.84 - 0.18 * (xpos - 0.18)),
                arrowstyle="-|>",
                mutation_scale=12,
                linewidth=1.1,
                color="#4f81a8",
            )
        )
    ax.text(
        0.43, 0.985, "Recharge ramp forcing", ha="center", va="top", fontsize=10.0, color="#2b6c9b"
    )

    if no_seepage:
        ax.text(
            0.47,
            0.62,
            "Top drainage remains inactive by construction",
            ha="center",
            va="bottom",
            fontsize=9.8,
            color="#a04d14",
        )
    else:
        for xpos in (0.28, 0.45, 0.62):
            ax.add_patch(
                FancyArrowPatch(
                    (xpos, np.interp(xpos, top_x, top_y) + 0.01),
                    (xpos, np.interp(xpos, top_x, top_y) - 0.07),
                    arrowstyle="-|>",
                    mutation_scale=10,
                    linewidth=1.0,
                    color="#c55a11",
                )
            )
        ax.text(
            0.47,
            0.58,
            "Top drainage / surface interaction",
            ha="center",
            va="bottom",
            fontsize=9.8,
            color="#a04d14",
        )

    footer = (
        "No-seepage variants: same recharge chronology and fixed east head, but the surface is lifted by +10 m. "
        "Displayed diagnostics focus on subsurface storage and east-boundary outflow."
        if no_seepage
        else "Compared variants: reference K and high K (K x8). Bulk diagnostics shown in the gallery: total outflow and storage change."
    )
    ax.text(
        0.5,
        0.08,
        footer,
        ha="center",
        va="center",
        fontsize=9.6,
    )

    output_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_png, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _write_variant_summary(
    rows: list[dict[str, float | str]],
    *,
    variant: ComparisonVariant,
    output_json: Path,
    execution_rows: list[dict[str, float | str]],
) -> None:
    grouped = _group_rows_by_solver(rows)
    execution_by_solver = _index_rows_by_solver(execution_rows)
    solver_payloads: list[dict[str, Any]] = []
    for solver, solver_rows in sorted(grouped.items(), key=lambda item: _solver_sort_key(item[0])):
        execution_row = execution_by_solver.get(solver, {})
        solver_payload: dict[str, Any] = {
            "solver": solver,
            "solver_label": SOLVER_LABELS.get(solver, solver),
            "peak_total_outflow_m3_day": max(
                float(row["total_outflow_m3_day"]) for row in solver_rows
            ),
            "final_storage_change_m3_day": float(solver_rows[-1]["storage_change_m3_day"]),
        }
        wall_time_seconds = _float_or_none(execution_row.get("wall_time_seconds"))
        if wall_time_seconds is not None:
            solver_payload["wall_time_seconds"] = wall_time_seconds
        for optional_key in ("runtime_backend", "surface_interaction_model", "results_dir"):
            optional_value = str(execution_row.get(optional_key, "")).strip()
            if optional_value:
                solver_payload[optional_key] = optional_value
        solver_payloads.append(solver_payload)

    payload = {
        "title": variant.title,
        "run_dir": str(variant.run_dir.relative_to(REPO_ROOT).as_posix()),
        "notes": list(variant.notes),
        "configuration": dict(variant.configuration),
        "execution_times_csv": (
            str((variant.run_dir / "execution_times.csv").relative_to(REPO_ROOT).as_posix())
            if execution_rows
            else None
        ),
        "execution_times_available": bool(execution_rows),
        "solvers": solver_payloads,
    }
    output_json.write_text(
        __import__("json").dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    for case in CASES:
        if case.slug == "surface_interaction_ramp":
            _write_surface_interaction_configuration_schematic(
                case.variants[0].asset_dir / "surface_interaction_ramp_configuration.png"
            )
        if case.slug == "surface_interaction_no_seepage":
            _write_surface_interaction_configuration_schematic(
                case.variants[0].asset_dir / "surface_interaction_no_seepage_configuration.png",
                no_seepage=True,
            )
        for variant in case.variants:
            rows = _load_timeseries_rows(variant.run_dir / "timeseries.csv")
            execution_rows = _load_optional_csv_rows(variant.run_dir / "execution_times.csv")
            output_png = variant.asset_dir / f"{variant.image_slug}.png"
            output_json = variant.asset_dir / f"{variant.image_slug}.json"
            _plot_variant(
                rows,
                title=variant.title,
                notes=variant.notes,
                output_png=output_png,
            )
            _write_variant_summary(
                rows,
                variant=variant,
                output_json=output_json,
                execution_rows=execution_rows,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
