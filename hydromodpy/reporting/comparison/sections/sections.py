"""Modular sections for static comparison web reports."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from hydromodpy.reporting.comparison.context import ComparisonWebContext
from hydromodpy.reporting.comparison.html_utils import (
    render_links,
    safe,
)

from .io import (
    _base_config_payload,
    _boundary_condition_text,
    _boussinesq_method_text,
    _flow_payload_for_solver,
    _has_head_error_metrics,
    _initial_condition_text,
    _is_synthetic_patchy,
    _recharge_text,
    _simulation_config_payloads,
    _synthetic_context_rows,
)
from .templates import (
    _analysis_row_by_token,
    _analysis_row_text,
    _audit_block,
    _format_closure_rows,
    _format_metric_rows,
    _format_percent_value,
    _format_value,
    _mapping,
    _metric_analysis_row,
    _render_figures,
    _render_key_values,
    _render_metric_snapshot,
    _render_runtime_table,
    _render_table,
)


@dataclass(frozen=True)
class ReportSection:
    """One independently rendered block of the comparison report."""

    section_id: str
    title: str
    priority: int
    render: Callable[[ComparisonWebContext], str]
    is_available: Callable[[ComparisonWebContext], bool] = lambda _ctx: True


def default_sections() -> list[ReportSection]:
    """Return the standard section set for a comparison report."""
    return [
        ReportSection(
            "introduction",
            "Introduction",
            10,
            _render_introduction,
        ),
        ReportSection(
            "case_configuration",
            "Case context",
            20,
            _render_case_configuration,
            lambda ctx: bool(ctx.configuration_figures),
        ),
        ReportSection(
            "numerical_methods",
            "Numerical methods",
            25,
            _render_numerical_methods,
        ),
        ReportSection(
            "categorized_figures",
            "Result comparisons",
            30,
            _render_categorized_figures,
            lambda ctx: bool(ctx.figure_categories),
        ),
        ReportSection(
            "numerical_closure",
            "Solution accuracy",
            45,
            _render_numerical_closure,
            lambda ctx: bool(ctx.numerical_closure_rows),
        ),
        ReportSection("metrics", "Main metrics", 50, _render_metrics),
        ReportSection(
            "coherence_analysis",
            "Physical reading of the differences",
            55,
            _render_coherence_analysis,
            _has_head_error_metrics,
        ),
        ReportSection("simulations", "Simulations", 60, _render_simulations),
        ReportSection("audit", "Audit", 70, _render_audit),
        ReportSection("files", "Files", 80, _render_files),
    ]


def render_sections(ctx: ComparisonWebContext) -> str:
    """Render all available default report sections.

    Each block is wrapped in a stable anchor (``id="section-<section_id>"``)
    so tooling and tests can target sections without matching localized text.
    """
    blocks: list[str] = []
    for section in sorted(default_sections(), key=lambda item: item.priority):
        if section.is_available(ctx):
            anchor = f'<div id="section-{safe(section.section_id)}" data-section="{safe(section.section_id)}">'
            blocks.append(f"{anchor}\n{section.render(ctx)}\n</div>")
    return "\n\n".join(blocks)


def report_title(ctx: ComparisonWebContext) -> str:
    """Return a readable report title."""
    payload = ctx.manifest
    explicit = payload.get("title") or payload.get("comparison_title")
    if explicit:
        return str(explicit)
    comparison_id = str(payload.get("comparison_id", "")).strip()
    if "synthetic_patchy" in comparison_id:
        return "Synthetic MF6 / Boussinesq comparison, heterogeneous recharge"
    return comparison_id.replace("_", " ") or "Comparison report"


def render_header(ctx: ComparisonWebContext) -> str:
    """Render the report header."""
    payload = ctx.manifest
    if _is_synthetic_patchy(ctx):
        subtitle = (
            "Synthetic 2D case on a square domain, heterogeneous aquifer, "
            "surface drainage and a long monthly recharge series. The goal is "
            "to compare a MODFLOW 6 reference and a Boussinesq candidate on "
            "heads, global storage and the external budget."
        )
    else:
        subtitle = (
            "Comparison report between simulations. Figures and metrics "
            "are limited to the observables declared in the configuration."
        )
    return f"""
  <header>
    <h1>{safe(report_title(ctx))}</h1>
    <p>{safe(subtitle)}</p>
    <div class="pillrow">
      <span class="pill">Audit: {safe(payload.get("audit_status", ctx.audit.get("status", "")))}</span>
      <span class="pill">Reference: {safe(payload.get("reference_simulation", ""))}</span>
    </div>
  </header>
"""


def _render_introduction(ctx: ComparisonWebContext) -> str:
    if not _is_synthetic_patchy(ctx):
        return """
  <section>
    <div class="card">
      <h2>Introduction</h2>
      <p>This report compares several simulations on a selection of common observables. The main reading is limited to quantities that have the same physical meaning across the methods.</p>
    </div>
  </section>
"""

    rows = _synthetic_context_rows(_base_config_payload(ctx))
    return f"""
  <section>
    <div class="card">
      <h2>Introduction</h2>
      <p>The case is a synthetic unconfined aquifer, in 2D plan view, on a square domain of about 5.0 km by 5.0 km. The topography is a tilted plane with about 20 m of lateral drop and a constant aquifer thickness of 80 m.</p>
      <p>The medium is deliberately heterogeneous: three vertical geological bands cross the whole domain. They set a poorly conductive west zone, a more conductive central corridor and an east zone of intermediate conductivity.</p>
      <p>The comparison checks that the Boussinesq method reproduces, on the same generated mesh and under the same recharge, the hydraulic heads, the global storage and the external budget obtained with MODFLOW 6.</p>
      <div class="info-grid">
        {_render_key_values(rows)}
      </div>
      <p>Native fluxes by process are not shown as comparison figures, because they do not always represent the same numerical object. The outputs are therefore read through global quantities that are aligned physically.</p>
      <p>For Boussinesq, the global outflow can be deduced from the budget when the boundary flux is not exposed as a native component. It is then identified by <code>balance_implied_outflow_total_m3_s</code>.</p>
    </div>
  </section>
"""


def _render_audit(ctx: ComparisonWebContext) -> str:
    return f"""
  <section>
    <div class="card">
      <h2>Audit</h2>
      {_audit_block(ctx.audit)}
    </div>
  </section>
"""


def _render_case_configuration(ctx: ComparisonWebContext) -> str:
    return f"""
  <section>
    <h2>Case context</h2>
    <p class="muted">Support, geological zones, comparison points, forcings and spatial context used by both simulations. This figure is deliberately larger than the results to set the case before the comparison.</p>
    <div class="figure-grid context-figure-grid">
      {_render_figures(ctx=ctx, figures=ctx.configuration_figures)}
    </div>
  </section>
"""


def _render_numerical_methods(ctx: ComparisonWebContext) -> str:
    payload = _base_config_payload(ctx)
    flow = _mapping(payload.get("flow"))
    simulation_payloads = _simulation_config_payloads(ctx)
    mf6_flow = _flow_payload_for_solver(simulation_payloads, "modflow6") or flow
    bouss_flow = _flow_payload_for_solver(simulation_payloads, "boussinesq") or flow
    mf6 = _mapping(payload.get("modflow6"))
    mf6_runtime = _mapping(mf6.get("runtime"))
    mf6_sgrid = _mapping(_mapping(mf6.get("sgrid")).get("vertical"))
    bouss_method = _boussinesq_method_text(bouss_flow)
    hydraulic_rows = [
        ("Flow regime", _format_value(flow.get("flow_regime"), default="transient")),
        ("Transient recharge", _recharge_text(flow)),
        ("Initial conditions", _initial_condition_text(flow)),
        ("MODFLOW 6 boundary conditions", _boundary_condition_text(mf6_flow)),
        (
            "Boussinesq boundary conditions",
            _boundary_condition_text(bouss_flow, solver="boussinesq"),
        ),
        (
            "Hydraulic properties",
            "K and Sy heterogeneous by geological zone; Ss homogeneous; "
            "constant aquifer thickness in the synthetic case.",
        ),
    ]
    numerical_rows = [
        (
            "MODFLOW 6",
            "reference, finite volumes (control volumes) on a DISV mesh; "
            f"{_format_value(mf6_sgrid.get('nlay'), default='1')} layer(s); "
            f"IMS {_format_value(mf6_runtime.get('mf6_ims_complexity'), default='COMPLEX')}; "
            f"dvclose={_format_value(mf6_runtime.get('mf6_inner_dvclose'), default='1e-4')}",
        ),
        (
            "Boussinesq",
            bouss_method,
        ),
        (
            "Spatial discretization",
            "mesh generated for each simulation by mesh_catchment, conforming to the "
            "geological interfaces; no pre-existing mesh is given to the solver.",
        ),
    ]
    return f"""
  <section>
    <div class="card">
      <h2>Numerical methods</h2>
      <p>Both simulations follow the standard HydroModPy path: data preparation, mesh generation, solver assembly, computation, observable extraction and report generation. The hydraulic choices are kept apart below from the purely numerical ones.</p>
      <h3>Hydraulic configuration and boundary conditions</h3>
      <div class="info-grid">
        {_render_key_values(hydraulic_rows)}
      </div>
      <h3>Numerical settings</h3>
      <div class="info-grid">
        {_render_key_values(numerical_rows)}
      </div>
    </div>
  </section>
"""


def _render_categorized_figures(ctx: ComparisonWebContext) -> str:
    category_blocks: list[str] = []
    for category in ctx.figure_categories:
        if category.category_id == "configuration":
            continue
        category_blocks.append(
            f"""
    <article class="card figure-category category-{safe(category.category_id)}" id="figures-{safe(category.category_id)}">
      <h3>{safe(category.title)} <span class="muted">({safe(len(category.figures))})</span></h3>
      <p class="muted">{safe(category.description)}</p>
      <div class="figure-grid compact">
        {_render_figures(ctx=ctx, figures=category.figures)}
      </div>
    </article>
"""
        )
    if not category_blocks:
        return """
  <section>
    <h2>Result comparisons</h2>
    <p class="muted">No result figure besides the configuration.</p>
  </section>
"""
    return f"""
  <section>
    <h2>Result comparisons</h2>
    <p class="muted">Only one head map is kept, with the point time series. Global storage and the inflow/outflow budget are shown separately.</p>
    {"".join(category_blocks)}
  </section>
"""


def _render_simulations(ctx: ComparisonWebContext) -> str:
    return f"""
  <section>
    <div class="card">
      <h2>Simulations</h2>
      <p class="muted">Solve time of the flow part only, taken from the solver metrics. The preparation, meshing, extraction and rendering phases are not included in this comparison.</p>
      {_render_runtime_table(ctx.simulations)}
    </div>
  </section>
"""


def _render_files(ctx: ComparisonWebContext) -> str:
    return f"""
  <section>
    <div class="card">
      <h2>Source files</h2>
      {render_links(root=ctx.root, web_dir=ctx.web_dir, links=ctx.data_links)}
    </div>
  </section>
"""


def _render_numerical_closure(ctx: ComparisonWebContext) -> str:
    rows = _format_closure_rows(ctx.numerical_closure_rows)
    columns = [
        ("simulation_id", "simulation"),
        ("solver", "solver"),
        ("n_periods", "periods"),
        ("max_abs_closure_m3_s", "max |residual| flow rate"),
        ("max_abs_closure_mm_d", "max |residual| depth"),
        ("relative_closure_error_p95", "rel. error p95"),
        ("diagnostic", "verdict"),
    ]
    return f"""
  <section>
    <div class="card">
      <h2>Solution accuracy</h2>
      <p class="muted">Common diagnostic computed afterwards on the normalized budgets: inflows minus outflows minus storage change. It does not replace the internal criteria of the solvers, but shows whether the accepted state closes the water budget correctly.</p>
      {_render_table(rows, columns, empty="No budget closure diagnostic.")}
    </div>
  </section>
"""


def _render_metrics(ctx: ComparisonWebContext) -> str:
    rows = _format_metric_rows(ctx.metrics_rows[:24])
    return f"""
  <section>
    <h2>Main metrics</h2>
    <p class="muted">Compact reading of the differences on the common observables. Units are explicit: heads are in metres, and the percentage is <code>RMSE / ref value</code>. Here, <code>ref value</code> is the amplitude of the reference quantity used to normalize the observable.</p>
    {_render_metric_snapshot(rows)}
  </section>
"""


def _render_coherence_analysis(ctx: ComparisonWebContext) -> str:
    head_rows = [
        _metric_analysis_row(row)
        for row in ctx.metrics_rows
        if str(row.get("observable", "")).startswith("head")
    ]
    head_rows = [row for row in head_rows if row["rmse_percent"] is not None]
    if not head_rows:
        return ""
    first = _analysis_row_by_token(head_rows, "first")
    wet = _analysis_row_by_token(head_rows, "wet")
    dry = _analysis_row_by_token(head_rows, "dry")
    last = _analysis_row_by_token(head_rows, "last")
    best = min(head_rows, key=lambda item: item["rmse_percent"])
    worst = max(head_rows, key=lambda item: item["rmse_percent"])
    max_percent = float(worst["rmse_percent"] or 0.0)
    if max_percent < 2.0:
        verdict = "very close agreement"
    elif max_percent < 5.0:
        verdict = "good overall agreement"
    elif max_percent < 10.0:
        verdict = "overall consistency with notable differences"
    else:
        verdict = "marked differences to investigate"

    evidence_rows = [
        ("Best agreement", _analysis_row_text(best)),
        ("Largest difference", _analysis_row_text(worst)),
    ]
    if first is not None:
        evidence_rows.append(("First computed step", _analysis_row_text(first)))
    if wet is not None:
        evidence_rows.append(("After the wet season", _analysis_row_text(wet)))
    if dry is not None:
        evidence_rows.append(("Dry state", _analysis_row_text(dry)))
    if last is not None:
        evidence_rows.append(("Final state", _analysis_row_text(last)))

    messages = [
        (
            f"On the compared heads, this case shows {verdict}: the normalized RMSE "
            f"ranges from {_format_percent_value(best['rmse_percent'])} to "
            f"{_format_percent_value(worst['rmse_percent'])}."
        ),
        (
            "The smallest differences usually appear at the start or just after "
            "a wet episode: the water table is then controlled mostly by recharge "
            "and by the conductivity field shared by both solvers."
        ),
        (
            "The differences grow when the state gets drier or closer to the "
            "surface. This is the zone most sensitive to formulation differences: "
            "MODFLOW 6 accepts heads above the top and represents drainage "
            "with a drain conductance, while the Boussinesq computation uses an "
            "unconfined formulation with a surface obstacle and a different "
            "drainage treatment."
        ),
        (
            "Synthetic cases remain the consistency benchmark: support, geometry, "
            "forcing and observables are controlled there, so the differences should "
            "mostly come from the numerical formulation and from flux terms that are "
            "not strictly identical. Natural cases add topography, geology and local "
            "contrasts, so they amplify the differences where the water table "
            "interacts with the top, the drains and steep slopes."
        ),
    ]
    return f"""
  <section>
    <div class="card">
      <h2>Physical reading of the differences</h2>
      {_render_key_values(evidence_rows)}
      {"".join(f"<p>{safe(message)}</p>" for message in messages)}
    </div>
  </section>
"""
