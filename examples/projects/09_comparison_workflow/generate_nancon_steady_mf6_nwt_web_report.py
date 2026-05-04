"""Build a browser-readable report for the Nancon steady MF6/NWT comparison."""

from __future__ import annotations

import csv
import html
import json
import math
import os
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CONFIG_PATH = ROOT / "compare_nancon_steady_mf6_disv_vs_nwt.toml"
BASE_CONFIG_PATH = ROOT / "base_nancon_steady_hydrography_mesh_input.toml"
TRANSIENT_BASE_CONFIG_PATH = ROOT / "base_nancon_transient_seasonal.toml"
TRANSIENT_HYDROGRAPHY_BASE_CONFIG_PATH = (
    ROOT / "base_nancon_transient_seasonal_with_hydrography.toml"
)
TRANSIENT_MONTHLY_BASE_CONFIG_PATH = (
    ROOT / "base_nancon_transient_monthly_hydrography_mesh_input.toml"
)
TRANSIENT_CONFIG_PATH = ROOT / "compare_nancon_transient_monthly_mf6_disv_vs_nwt.toml"
TRANSIENT_DIAGNOSTIC_CONFIG_PATH = (
    ROOT / "compare_nancon_transient_monthly_mf6_disv_vs_nwt_ic_diagnostic.toml"
)
TRANSIENT_DIAGNOSTIC_BASE_CONFIG_PATH = (
    ROOT / "base_nancon_transient_monthly_hydrography_mesh_input_ic10m.toml"
)
COMPARISON_ROOT = ROOT / "outputs" / "nancon_steady_mf6_disv_vs_nwt"
TRANSIENT_COMPARISON_ROOT = ROOT / "outputs" / "nancon_transient_monthly_mf6_disv_vs_nwt"
TRANSIENT_DIAGNOSTIC_COMPARISON_ROOT = (
    ROOT / "outputs" / "nancon_transient_monthly_mf6_disv_vs_nwt_ic_diagnostic"
)
WEB_DIR = COMPARISON_ROOT / "web"
WEB_FIGURES_DIR = COMPARISON_ROOT / "web_figures"
TRANSIENT_WEB_FIGURES_DIR = TRANSIENT_COMPARISON_ROOT / "web_figures"
TRANSIENT_DIAGNOSTIC_WEB_FIGURES_DIR = (
    TRANSIENT_DIAGNOSTIC_COMPARISON_ROOT / "web_figures"
)


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _load_resolved_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        from hydromodpy.core.toml_io.loader import load_toml_with_base_config

        return load_toml_with_base_config(path)
    except Exception:
        return _load_toml(path)


def _rel(path: str | Path) -> str:
    try:
        return Path(path).resolve().relative_to(WEB_DIR.resolve()).as_posix()
    except Exception:
        try:
            return Path(path).resolve().relative_to(COMPARISON_ROOT.resolve()).as_posix()
        except Exception:
            try:
                return Path(os.path.relpath(Path(path).resolve(), WEB_DIR.resolve())).as_posix()
            except Exception:
                return Path(path).as_posix()


def _link_from_web(path: str | Path) -> str:
    target = Path(path)
    if not target.is_absolute():
        target = (COMPARISON_ROOT / target).resolve()
    try:
        return target.relative_to(WEB_DIR.resolve()).as_posix()
    except Exception:
        try:
            return "../" + target.relative_to(COMPARISON_ROOT.resolve()).as_posix()
        except Exception:
            try:
                return Path(os.path.relpath(target.resolve(), WEB_DIR.resolve())).as_posix()
            except Exception:
                return target.as_posix()


def _float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except Exception:
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _format_float(value: Any, *, digits: int = 3) -> str:
    parsed = _float(value)
    if parsed is None:
        return ""
    if parsed == 0.0:
        return "0"
    if abs(parsed) >= 10000 or abs(parsed) < 0.001:
        return f"{parsed:.{digits}e}"
    return f"{parsed:.{digits}f}".rstrip("0").rstrip(".")


def _safe_text(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _figure_artifacts(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    figures = manifest.get("comparison_figures", [])
    if not isinstance(figures, list):
        return []
    return [item for item in figures if isinstance(item, dict) and item.get("path")]


def _figures_by_keywords(
    figures: list[dict[str, Any]],
    keywords: tuple[str, ...],
    *,
    extensions: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".webp"),
    limit: int = 12,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for item in figures:
        path = str(item.get("path", ""))
        name = Path(path).name.lower()
        kind = str(item.get("kind", "")).lower()
        if extensions and Path(path).suffix.lower() not in extensions:
            continue
        if any(keyword in name or keyword in kind for keyword in keywords):
            selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def _read_metric_rows() -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    return (
        _load_csv(COMPARISON_ROOT / "comparison_metrics.csv"),
        _load_csv(COMPARISON_ROOT / "simulated_active_network_overlap_metrics.csv"),
        _load_csv(COMPARISON_ROOT / "execution_times.csv"),
    )


def _cell_counts_from_rows(rows: list[dict[str, str]]) -> dict[str, str]:
    counts: dict[str, str] = {}
    for row in rows:
        variant_id = str(row.get("variant_id", ""))
        count = _float(row.get("catchment_cell_count"))
        if not variant_id or count is None:
            continue
        counts[variant_id] = str(int(round(count)))
    return counts


def _enrich_execution_rows(
    rows: list[dict[str, str]], manifest: dict[str, Any], cell_counts: dict[str, str]
) -> list[dict[str, str]]:
    variants = manifest.get("variants", [])
    by_id = {str(item.get("id", "")): item for item in variants if isinstance(item, dict)}
    enriched: list[dict[str, str]] = []
    for row in rows:
        variant = by_id.get(str(row.get("variant_id", "")), {})
        merged = dict(row)
        if isinstance(variant, dict):
            merged.setdefault("status", str(variant.get("status", "")))
            if not merged.get("status"):
                merged["status"] = str(variant.get("status", ""))
        merged["cell_count"] = cell_counts.get(str(row.get("variant_id", "")), "")
        enriched.append(merged)
    return enriched


def _render_table(
    rows: list[dict[str, Any]],
    columns: tuple[tuple[str, str], ...],
    *,
    empty: str,
    max_rows: int = 12,
) -> str:
    if not rows:
        return f'<p class="muted">{html.escape(empty)}</p>'
    head = "".join(f"<th>{html.escape(label)}</th>" for _, label in columns)
    body_rows = []
    for row in rows[:max_rows]:
        cells = []
        for key, _ in columns:
            value = row.get(key, "")
            if key in {
                "bias",
                "mae",
                "rmse",
                "max_abs_error",
                "mean_relative_error",
                "runtime_seconds",
                "runtime_minutes",
                "speedup_vs_reference",
                "network_coverage_ratio",
                "active_precision_ratio",
                "cell_f1_ratio",
                "cell_jaccard_ratio",
            } or key.startswith("value__"):
                value = _format_float(value)
            cells.append(f"<td>{_safe_text(value)}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    return (
        '<div class="table-wrap"><table><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body_rows)
        + "</tbody></table></div>"
    )


def _variant_cards(
    manifest: dict[str, Any],
    config: dict[str, Any],
    cell_counts: dict[str, str],
) -> str:
    variants = manifest.get("variants", [])
    simulations = {
        str(item.get("id", "")): item
        for item in config.get("comparison", {}).get("simulation", [])
        if isinstance(item, dict)
    }
    cards = []
    for variant in variants if isinstance(variants, list) else []:
        variant_id = str(variant.get("id", ""))
        sim_cfg = simulations.get(variant_id, {})
        overlay = sim_cfg.get("overlay", {}) if isinstance(sim_cfg, dict) else {}
        grid_text = ""
        if isinstance(overlay, dict):
            nwt = overlay.get("modflownwt", {})
            if isinstance(nwt, dict):
                planar = nwt.get("sgrid", {}).get("planar", {})
                if isinstance(planar, dict):
                    nx = planar.get("nx", "")
                    ny = planar.get("ny", "")
                    if nx and ny:
                        grid_text = f"{nx} x {ny}"
        if not grid_text:
            grid_text = str(variant.get("mesh_label", ""))
        cards.append(
            f"""
            <article class="variant">
              <h3>{_safe_text(variant_id)}</h3>
              <p>{_safe_text(variant.get("label", ""))}</p>
              <dl>
                <dt>Solver</dt><dd>{_safe_text(variant.get("solver", ""))}</dd>
                <dt>Maillage</dt><dd>{_safe_text(grid_text)}</dd>
                <dt>Mailles</dt><dd>{_safe_text(cell_counts.get(variant_id, ""))}</dd>
                <dt>Statut</dt><dd>{_safe_text(variant.get("status", ""))}</dd>
                <dt>Temps</dt><dd>{_format_float(variant.get("wall_time_seconds"))} s</dd>
                <dt>Run</dt><dd><code>{_safe_text(_rel(variant.get("run_folder", "")))}</code></dd>
              </dl>
            </article>
            """
        )
    return "\n".join(cards) or '<p class="muted">Aucune variante disponible.</p>'


def _figure_grid(figures: list[dict[str, Any]], *, empty: str) -> str:
    if not figures:
        return f'<p class="muted">{html.escape(empty)}</p>'
    items = []
    for figure in figures:
        path = figure.get("path", "")
        label = figure.get("observable") or figure.get("kind") or Path(str(path)).stem
        items.append(
            f"""
            <figure>
              <a href="{_safe_text(_link_from_web(path))}">
                <img src="{_safe_text(_link_from_web(path))}" alt="{_safe_text(label)}">
              </a>
              <figcaption>{_safe_text(label)}</figcaption>
            </figure>
            """
        )
    return '<div class="fig-grid">' + "\n".join(items) + "</div>"


def _figure_by_filename(figures: list[dict[str, Any]], filename: str) -> dict[str, Any] | None:
    for figure in figures:
        if Path(str(figure.get("path", ""))).name == filename:
            return figure
    return None


def _figure_by_variant_name(
    figures: list[dict[str, Any]], variant_id: str, figure_name: str
) -> dict[str, Any] | None:
    for figure in figures:
        if figure.get("variant_id") == variant_id and figure.get("figure_name") == figure_name:
            return figure
    return None


def _render_figure(
    figure: dict[str, Any] | None,
    *,
    title: str,
    note: str = "",
) -> str:
    if not figure:
        return (
            '<figure class="missing-figure">'
            f"<figcaption>{html.escape(title)}</figcaption>"
            '<p class="muted">Figure non disponible.</p>'
            "</figure>"
        )
    path = figure.get("path", "")
    return f"""
    <figure>
      <a href="{_safe_text(_link_from_web(path))}">
        <img src="{_safe_text(_link_from_web(path))}" alt="{_safe_text(title)}">
      </a>
      <figcaption><strong>{_safe_text(title)}</strong>{f"<span>{_safe_text(note)}</span>" if note else ""}</figcaption>
    </figure>
    """


def _theme_panel(
    figures: list[dict[str, Any]],
    *,
    observable: str,
    title: str,
    reading: str,
) -> str:
    fine = _figure_by_filename(figures, f"{observable}__fine_raster_map_comparison.png")
    native = _figure_by_filename(figures, f"{observable}__map_comparison.png")
    return f"""
    <article class="theme-panel">
      <div class="theme-copy">
        <h3>{_safe_text(title)}</h3>
        <p>{_safe_text(reading)}</p>
      </div>
      <div class="paired-figs">
        {_render_figure(fine, title="Raster commun 250 m", note="A privilegier pour comparer les maillages.")}
        {_render_figure(native, title="Maillages natifs", note="Diagnostic brut, sensible aux supports.")}
      </div>
    </article>
    """


def _figure_deck(items: list[tuple[dict[str, Any] | None, str, str]]) -> str:
    return (
        '<div class="figure-deck">'
        + "\n".join(_render_figure(figure, title=title, note=note) for figure, title, note in items)
        + "</div>"
    )


def _wide_figure_grid(figures: list[dict[str, Any]], *, empty: str) -> str:
    if not figures:
        return f'<p class="muted">{html.escape(empty)}</p>'
    return (
        '<div class="wide-fig-grid">'
        + "\n".join(
            _render_figure(
                figure,
                title=str(figure.get("title") or figure.get("observable") or "Carte"),
                note=str(figure.get("note") or ""),
            )
            for figure in figures
        )
        + "</div>"
    )


def _metric_value(rows: list[dict[str, str]], variant_id: str, observable: str, field: str) -> str:
    for row in rows:
        if row.get("variant_id") == variant_id and row.get("observable") == observable:
            return _format_float(row.get(field))
    return ""


def _wide_value(rows: list[dict[str, str]], observable: str, variant_id: str) -> str:
    key = f"value__{variant_id}"
    for row in rows:
        if row.get("observable") == observable:
            return _format_float(row.get(key))
    return ""


def _runtime_value(rows: list[dict[str, str]], variant_id: str, field: str) -> str:
    for row in rows:
        if row.get("variant_id") == variant_id:
            return _format_float(row.get(field))
    return ""


def _config_detail_table(base: dict[str, Any], config: dict[str, Any]) -> str:
    flow = base.get("flow", {})
    geo = base.get("geographic", {})
    comparison = config.get("comparison", {})
    fine = comparison.get("fine_raster", {})
    simulations = comparison.get("simulation", [])
    nwt_grids: list[str] = []
    for simulation in simulations if isinstance(simulations, list) else []:
        if simulation.get("solver") != "modflownwt":
            continue
        planar = (
            simulation.get("overlay", {}).get("modflownwt", {}).get("sgrid", {}).get("planar", {})
        )
        nx = planar.get("nx", "")
        ny = planar.get("ny", "")
        if nx and ny:
            nwt_grids.append(f"{simulation.get('id')}: {nx} x {ny}")
    rows = [
        (
            "Cas",
            f"{base.get('simulation', {}).get('name', '')}; {base.get('simulation', {}).get('description', '')}",
            "Un seul pas steady pour isoler la geometrie, les conditions aux limites et le solveur.",
        ),
        (
            "Domaine",
            f"Outlet ({geo.get('x_outlet', '')}, {geo.get('y_outlet', '')}), CRS {geo.get('crs_project', '')}, snap {geo.get('snap_dist', '')}",
            "Le bassin reste identique pour les trois variantes.",
        ),
        (
            "Donnees",
            "DEM Armorican massif, hydrographie BD TOPAGE, recharge synthetique annuelle",
            "La comparaison ne teste pas encore une calibration hydrologique complete.",
        ),
        (
            "Parametres communs",
            (
                f"K={flow.get('param', {}).get('K', {}).get('field_homogeneous', {}).get('value', '')}; "
                f"Ss={flow.get('param', {}).get('Ss', {}).get('field_homogeneous', {}).get('value', '')}; "
                f"Sy={flow.get('param', {}).get('Sy', {}).get('field_homogeneous', {}).get('value', '')}; "
                f"drainage={flow.get('bc', {}).get('cauchy', {}).get('drainage', {}).get('value', '')}"
            ),
            "Ces valeurs sont imposees de facon identique pour MF6 et NWT.",
        ),
        (
            "Recharge",
            f"{_format_float(_float(_config_summary(base)['recharge_mm_year']))} mm/an",
            "Moyenne annuelle synthetique; runoff_ratio = 0 dans ce cas.",
        ),
        (
            "Maillage MF6",
            str(base.get("mesh_input", {}).get("bundle_dir", "")),
            "Maillage DISV triangulaire contraint par le reseau hydrographique.",
        ),
        (
            "Maillages NWT",
            "; ".join(nwt_grids),
            "Grilles structurees plus fines pour compenser l'absence de contrainte geometrique directe sur les rivieres.",
        ),
        (
            "Raster commun",
            f"{fine.get('resolution', '')} m, extent={fine.get('extent_mode', '')}, interpolation={fine.get('interpolation', '')}",
            "Support le plus lisible pour comparer les cartes entre maillages differents.",
        ),
        (
            "Audit",
            f"mode={comparison.get('audit', {}).get('mode', '')}; on_mismatch={comparison.get('audit', {}).get('on_mismatch', '')}",
            "Le statut warn est attendu parce que les supports de discretisation different.",
        ),
    ]
    body = "".join(
        "<tr>"
        f"<td>{_safe_text(label)}</td>"
        f"<td>{_safe_text(value)}</td>"
        f"<td>{_safe_text(comment)}</td>"
        "</tr>"
        for label, value, comment in rows
    )
    return (
        '<div class="table-wrap"><table class="config-table">'
        "<thead><tr><th>Element</th><th>Configuration</th><th>Commentaire</th></tr></thead>"
        f"<tbody>{body}</tbody></table></div>"
    )


def _comparison_cfg_from_manifest(
    config: dict[str, Any],
    manifest: dict[str, Any],
    *,
    config_path: Path = CONFIG_PATH,
    base_config_path: Path = BASE_CONFIG_PATH,
    comparison_root: Path = COMPARISON_ROOT,
) -> Any | None:
    try:
        from hydromodpy.analysis.comparison.config import (
            ComparisonConfig,
            ComparisonSection,
            ComparisonVariant,
        )
    except Exception:
        return None

    comparison = config.get("comparison", {})
    variants: list[Any] = []
    for item in manifest.get("variants", []):
        if not isinstance(item, dict) or not item.get("enabled", True):
            continue
        variants.append(
            ComparisonVariant(
                id=str(item.get("id", "")),
                label=str(item.get("label", item.get("id", ""))),
                solver=str(item.get("solver", "")),
                mesh_label=str(item.get("mesh_label", "")),
                mesh_mode=str(item.get("mesh_mode", "unknown")),  # type: ignore[arg-type]
                simulation_config=str(item.get("config_path", "")),
                run_folder=str(item.get("run_folder", "")),
            )
        )
    if not variants:
        return None
    try:
        section = ComparisonSection(
            comparison_id=str(comparison.get("comparison_id", "")),
            base_simulation_config=str(base_config_path),
            output_root=str(comparison_root),
            run_variants=False,
            continue_on_error=bool(comparison.get("continue_on_error", False)),
            reference_variant=comparison.get("reference_simulation"),
            fine_raster=comparison.get("fine_raster"),
            variant=variants,
            observable=comparison.get("observable", []),
        )
        return ComparisonConfig(
            config_path=config_path.resolve(),
            base_dir=ROOT.resolve(),
            comparison_root=comparison_root.resolve(),
            base_simulation_config_path=base_config_path.resolve(),
            anchors_path=None,
            anchors={},
            comparison=section,
        )
    except Exception:
        return None


def _write_three_case_map_figure(
    *,
    path: Path,
    observable_name: str,
    payloads: list[Any],
    cell_counts: dict[str, str],
    overlay: dict[str, Any] | None,
    mesh_geometries: dict[str, dict[str, Any]],
) -> bool:
    try:
        import matplotlib.pyplot as plt
        import numpy as np

        from hydromodpy.analysis.comparison.visuals import (
            _finite_limits,
            _pretty_label,
            _robust_limits,
        )
    except Exception:
        return False

    if not payloads:
        return False
    limits = _robust_limits(payload.values for payload in payloads)
    if limits is None:
        limits = _finite_limits(payload.values for payload in payloads)
    if limits is None:
        return False
    vmin, vmax = limits
    if math.isclose(vmin, vmax):
        delta = abs(vmin) * 0.05 or 1.0
        vmin -= delta
        vmax += delta

    ncols = len(payloads)
    figure, axes = plt.subplots(1, ncols, figsize=(5.0 * ncols, 5.0), squeeze=False)
    axes_array = np.asarray(axes, dtype=object).ravel().tolist()
    artist = None
    for ax, payload in zip(axes_array, payloads, strict=False):
        artist = _render_payload_georef_subplot(
            ax,
            payload,
            cmap="viridis",
            vmin=vmin,
            vmax=vmax,
            mesh_geometries=mesh_geometries,
        )
        _overlay_watershed_context(ax, overlay)
        count = cell_counts.get(str(payload.variant_id), "")
        count_text = f"{count} mailles" if count else "mailles n/d"
        ax.set_title(
            f"{payload.variant_id}\n{payload.solver or payload.mesh_mode} - {count_text}",
            fontsize=9,
            pad=6,
        )
    if artist is not None:
        colorbar = figure.colorbar(
            artist,
            ax=axes_array,
            orientation="horizontal",
            pad=0.07,
            fraction=0.055,
            aspect=44,
        )
        colorbar.set_label(payloads[0].unit or "valeur", fontsize=9, labelpad=4)
        colorbar.ax.tick_params(labelsize=8)
    figure.suptitle(
        f"{_pretty_label(observable_name)} - bassin, exutoire et cartes completes par cas",
        fontsize=12,
        y=0.98,
    )
    figure.subplots_adjust(left=0.025, right=0.985, top=0.84, bottom=0.16, wspace=0.05)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return path.exists()


def _generate_three_case_map_figures(
    *,
    config: dict[str, Any],
    manifest: dict[str, Any],
    cell_counts: dict[str, str],
    overlay: dict[str, Any] | None,
    mesh_geometries: dict[str, dict[str, Any]],
    output_dir: Path = WEB_FIGURES_DIR,
    config_path: Path = CONFIG_PATH,
    base_config_path: Path = BASE_CONFIG_PATH,
    comparison_root: Path = COMPARISON_ROOT,
) -> list[dict[str, Any]]:
    try:
        from hydromodpy.analysis.comparison.visuals import _build_map_payload, _slug
    except Exception:
        return []

    comparison_cfg = _comparison_cfg_from_manifest(
        config,
        manifest,
        config_path=config_path,
        base_config_path=base_config_path,
        comparison_root=comparison_root,
    )
    if comparison_cfg is None:
        return []
    summaries = {
        str(item.get("id", "")): item
        for item in manifest.get("variants", [])
        if isinstance(item, dict) and item.get("status") in {"completed", "reused"}
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    variants = [variant for variant in comparison_cfg.comparison.variant if variant.enabled]
    artifacts: list[dict[str, Any]] = []
    for observable in comparison_cfg.comparison.observable:
        if observable.support != "map":
            continue
        payloads: list[Any] = []
        for variant in variants:
            summary = summaries.get(variant.id)
            if summary is None:
                continue
            try:
                payload = _build_map_payload(
                    cfg=comparison_cfg,
                    variant=variant,
                    summary=summary,
                    observable=observable,
                    rows=[],
                )
            except Exception:
                payload = None
            if payload is not None:
                payloads.append(payload)
        if len(payloads) < 2:
            continue
        path = output_dir / f"{_slug(observable.name)}__three_cases_complete.png"
        if _write_three_case_map_figure(
            path=path,
            observable_name=observable.name,
            payloads=payloads,
            cell_counts=cell_counts,
            overlay=overlay,
            mesh_geometries=mesh_geometries,
        ):
            artifacts.append(
                {
                    "kind": "three_case_complete_map",
                    "observable": observable.name,
                    "title": _complete_map_title(str(observable.name)),
                    "note": "Meme echelle de couleur, meme cadre cartographique, contour du bassin et exutoire superposes.",
                    "path": str(path),
                }
            )
    return artifacts


def _complete_map_title(observable_name: str) -> str:
    labels = {
        "head_map_last": "Charge hydraulique - 3 cas",
        "watertable_depth_map_last": "Profondeur de nappe - 3 cas",
        "seepage_map_last": "Zones de suintement - 3 cas",
        "outflow_drain_map_last": "Drainage distribue - 3 cas",
        "active_network_flux_map_last": "Flux accumule / reseau actif - 3 cas",
    }
    return labels.get(observable_name, observable_name)


def _resolve_output_path(path_value: Any) -> Path | None:
    if path_value in ("", None):
        return None
    path = Path(str(path_value)).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def _variant_workspace_path(config: dict[str, Any], variant_id: str) -> Path | None:
    for simulation in config.get("comparison", {}).get("simulation", []):
        if not isinstance(simulation, dict) or simulation.get("id") != variant_id:
            continue
        workspace = simulation.get("overlay", {}).get("workspace", {})
        if not isinstance(workspace, dict):
            return None
        return _resolve_output_path(workspace.get("root") or workspace.get("project_root"))
    return None


def _open_zarr_group(path: Path) -> tuple[Any | None, Any | None]:
    try:
        import zarr
        from zarr.storage import ZipStore
    except Exception:
        return None, None
    try:
        if path.suffix.lower() == ".zip":
            store = ZipStore(str(path), mode="r")
            return zarr.open_group(store=store, mode="r"), store
        return zarr.open_group(str(path), mode="r"), None
    except Exception:
        return None, None


def _load_watershed_overlay(
    config: dict[str, Any], manifest: dict[str, Any], base: dict[str, Any]
) -> dict[str, Any] | None:
    try:
        import numpy as np
    except Exception:
        return None

    reference_id = (
        config.get("comparison", {}).get("reference_simulation")
        or manifest.get("reference_variant")
        or "mf6_disv_ref"
    )
    variant = next(
        (
            item
            for item in manifest.get("variants", [])
            if isinstance(item, dict) and item.get("id") == reference_id
        ),
        None,
    )
    if not isinstance(variant, dict):
        return None
    workspace = _variant_workspace_path(config, str(reference_id))
    sim_id = str(variant.get("sim_id", ""))
    candidates: list[Path] = []
    if workspace is not None:
        sim_dir = workspace / "simulations"
        if sim_id:
            candidates.extend(sorted(sim_dir.glob(f"*{sim_id[:8]}*.zarr.zip")))
            candidates.extend(sorted(sim_dir.glob(f"*{sim_id[:8]}*.zarr")))
        candidates.extend(
            sorted(sim_dir.glob("*.zarr.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
        )
        candidates.extend(
            sorted(sim_dir.glob("*.zarr"), key=lambda p: p.stat().st_mtime, reverse=True)
        )

    for candidate in candidates:
        group, store = _open_zarr_group(candidate)
        try:
            if group is None or "geographic" not in group:
                continue
            geographic = group["geographic"]
            raster_name = "watershed_dem" if "watershed_dem" in geographic else "watershed_fill"
            if raster_name not in geographic:
                continue
            raster = geographic[raster_name]
            array = np.asarray(raster[:], dtype=float)
            attrs = dict(raster.attrs)
            transform = attrs.get("transform")
            if not transform or len(transform) < 6:
                continue
            nodata = _float(attrs.get("nodata"))
            valid = np.isfinite(array)
            if nodata is not None:
                valid &= ~np.isclose(array, nodata, rtol=0.0, atol=1.0e-6)
            if not np.any(valid):
                continue
            a, _b, c, _d, e, f = [float(value) for value in transform[:6]]
            rows, cols = array.shape
            x = c + a * (np.arange(cols, dtype=float) + 0.5)
            y = f + e * (np.arange(rows, dtype=float) + 0.5)
            xx, yy = np.meshgrid(x, y)
            xv = xx[valid]
            yv = yy[valid]
            pad = (
                max(float(np.nanmax(xv) - np.nanmin(xv)), float(np.nanmax(yv) - np.nanmin(yv)))
                * 0.035
            )
            outlet_x = _float(base.get("geographic", {}).get("x_outlet"))
            outlet_y = _float(base.get("geographic", {}).get("y_outlet"))
            return {
                "x_grid": xx,
                "y_grid": yy,
                "mask": valid.astype(float),
                "extent": (
                    float(np.nanmin(xv) - pad),
                    float(np.nanmax(xv) + pad),
                    float(np.nanmin(yv) - pad),
                    float(np.nanmax(yv) + pad),
                ),
                "outlet": (outlet_x, outlet_y)
                if outlet_x is not None and outlet_y is not None
                else None,
            }
        finally:
            if store is not None:
                try:
                    store.close()
                except Exception:
                    pass
    return None


def _variant_zarr_path(
    config: dict[str, Any], manifest: dict[str, Any], variant_id: str
) -> Path | None:
    variant = next(
        (
            item
            for item in manifest.get("variants", [])
            if isinstance(item, dict) and item.get("id") == variant_id
        ),
        None,
    )
    if not isinstance(variant, dict):
        return None
    workspace = _variant_workspace_path(config, variant_id)
    if workspace is None:
        return None
    sim_id = str(variant.get("sim_id", ""))
    sim_dir = workspace / "simulations"
    candidates: list[Path] = []
    if sim_id:
        candidates.extend(sorted(sim_dir.glob(f"*{sim_id[:8]}*.zarr.zip")))
        candidates.extend(sorted(sim_dir.glob(f"*{sim_id[:8]}*.zarr")))
    candidates.extend(
        sorted(sim_dir.glob("*.zarr.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    )
    candidates.extend(sorted(sim_dir.glob("*.zarr"), key=lambda p: p.stat().st_mtime, reverse=True))
    return candidates[0] if candidates else None


def _mesh_geometries_from_zarr(
    config: dict[str, Any], manifest: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    try:
        import numpy as np
    except Exception:
        return {}
    geometries: dict[str, dict[str, Any]] = {}
    for variant in manifest.get("variants", []):
        if not isinstance(variant, dict):
            continue
        variant_id = str(variant.get("id", ""))
        zarr_path = _variant_zarr_path(config, manifest, variant_id)
        if zarr_path is None:
            continue
        group, store = _open_zarr_group(zarr_path)
        try:
            if group is None or "mesh" not in group:
                continue
            mesh = group["mesh"]
            if "vertices" not in mesh or "face_node_connectivity" not in mesh:
                continue
            vertices = np.asarray(mesh["vertices"][:], dtype=float)
            faces = np.asarray(mesh["face_node_connectivity"][:], dtype=int)
            if vertices.ndim != 2 or vertices.shape[1] < 2 or faces.ndim != 2:
                continue
            geometries[variant_id] = {
                "vertices": vertices[:, :2],
                "faces": faces,
            }
        finally:
            if store is not None:
                try:
                    store.close()
                except Exception:
                    pass
    return geometries


def _mask_values(values: Any) -> Any:
    import numpy as np

    masked = np.asarray(values, dtype=float).copy()
    for sentinel in (-9999.0, -99999.0, -999999.0):
        masked[np.isclose(masked, sentinel, rtol=0.0, atol=1.0e-6)] = np.nan
    return masked


def _render_payload_georef_subplot(
    ax: Any,
    payload: Any,
    *,
    cmap: str,
    vmin: float,
    vmax: float,
    mesh_geometries: dict[str, dict[str, Any]] | None = None,
) -> Any:
    import numpy as np
    from matplotlib.collections import PolyCollection

    from hydromodpy.analysis.comparison.visuals import _render_map_subplot

    values = _mask_values(payload.values).ravel()
    geometry = (mesh_geometries or {}).get(str(payload.variant_id))
    if geometry is not None:
        vertices = np.asarray(geometry["vertices"], dtype=float)
        faces = np.asarray(geometry["faces"], dtype=int)
        if faces.shape[0] == values.size:
            polygons = []
            valid_values = []
            for face, value in zip(faces, values, strict=False):
                valid_nodes = face[(face >= 0) & (face < vertices.shape[0])]
                if valid_nodes.size < 3 or not np.isfinite(value):
                    continue
                polygon = vertices[valid_nodes, :2]
                if np.all(np.isfinite(polygon)):
                    polygons.append(polygon)
                    valid_values.append(float(value))
            if polygons:
                n_polygons = len(polygons)
                edge_width = 0.10
                if n_polygons > 30000:
                    edge_width = 0.035
                elif n_polygons > 10000:
                    edge_width = 0.055
                collection = PolyCollection(
                    polygons,
                    array=np.asarray(valid_values, dtype=float),
                    cmap=cmap,
                    edgecolors=(1.0, 1.0, 1.0, 0.38),
                    linewidths=edge_width,
                    antialiaseds=True,
                )
                collection.set_clim(vmin, vmax)
                ax.add_collection(collection)
                ax.autoscale_view()
                return collection

    x = getattr(payload, "x", None)
    y = getattr(payload, "y", None)
    if x is not None and y is not None:
        x_arr = np.asarray(x, dtype=float).ravel()
        y_arr = np.asarray(y, dtype=float).ravel()
        if x_arr.size == y_arr.size == values.size:
            finite = np.isfinite(x_arr) & np.isfinite(y_arr)
            size = max(1.3, min(14.0, 52000.0 / max(1, values.size)))
            artist = ax.scatter(
                x_arr[finite],
                y_arr[finite],
                c=values[finite],
                cmap=cmap,
                vmin=vmin,
                vmax=vmax,
                s=size,
                marker="s",
                linewidths=0.0,
            )
            return artist
    return _render_map_subplot(ax, payload, cmap=cmap, vmin=vmin, vmax=vmax)


def _overlay_watershed_context(ax: Any, overlay: dict[str, Any] | None) -> None:
    if not overlay:
        return
    try:
        ax.contour(
            overlay["x_grid"],
            overlay["y_grid"],
            overlay["mask"],
            levels=[0.5],
            colors="#111111",
            linewidths=1.25,
            zorder=6,
        )
    except Exception:
        pass
    outlet = overlay.get("outlet")
    if outlet is not None:
        ax.scatter(
            [outlet[0]],
            [outlet[1]],
            marker="*",
            s=95,
            c="#d82626",
            edgecolors="#111111",
            linewidths=0.6,
            zorder=8,
        )
    extent = overlay.get("extent")
    if extent is not None:
        xmin, xmax, ymin, ymax = extent
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin, ymax)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_linewidth(0.8)
        spine.set_color("#222222")


def _write_mesh_runtime_figure(rows: list[dict[str, str]]) -> dict[str, Any] | None:
    try:
        import matplotlib.pyplot as plt
        import numpy as np
    except Exception:
        return None
    valid_rows = [
        row
        for row in rows
        if _float(row.get("cell_count")) is not None
        and _float(row.get("runtime_seconds")) is not None
    ]
    if not valid_rows:
        return None
    labels = [str(row.get("variant_id", "")) for row in valid_rows]
    cells = np.asarray([float(row.get("cell_count", 0.0)) for row in valid_rows], dtype=float)
    runtimes = np.asarray(
        [float(row.get("runtime_seconds", 0.0)) for row in valid_rows],
        dtype=float,
    )
    path = WEB_FIGURES_DIR / "mesh_count_runtime_comparison.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    colors = ["#1f6b8f", "#57785d", "#a55d2a"][: len(labels)]
    fig, axes = plt.subplots(1, 2, figsize=(11.8, 4.4), squeeze=False)
    ax_cells, ax_time = axes.ravel().tolist()
    x = np.arange(len(labels))
    ax_cells.bar(x, cells, color=colors)
    ax_time.bar(x, runtimes, color=colors)
    for ax, values, ylabel in (
        (ax_cells, cells, "Nombre de mailles"),
        (ax_time, runtimes, "Temps de calcul [s]"),
    ):
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=18, ha="right", fontsize=8)
        ax.set_ylabel(ylabel, fontsize=9)
        ax.grid(axis="y", color="#d7ddd7", linewidth=0.7, alpha=0.8)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        for index, value in enumerate(values):
            label = f"{int(round(value))}" if ylabel.startswith("Nombre") else f"{value:.1f}"
            ax.text(index, value, label, ha="center", va="bottom", fontsize=8)
    ax_cells.set_title("Discretisation", fontsize=10)
    ax_time.set_title("Cout de calcul", fontsize=10)
    fig.suptitle("Nombre de mailles et temps de calcul", fontsize=12, y=0.98)
    fig.subplots_adjust(left=0.07, right=0.98, top=0.82, bottom=0.22, wspace=0.25)
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return {
        "kind": "mesh_runtime_comparison",
        "title": "Mailles et temps de calcul",
        "note": "Barres comparant la discretisation et le temps de run pour chaque variante.",
        "path": str(path),
    }


def _interpretation_cards(
    *,
    metrics: list[dict[str, str]],
    active_overlap: list[dict[str, str]],
    execution_rows: list[dict[str, str]],
    timeseries_rows: list[dict[str, str]],
) -> str:
    rmse_120 = _metric_value(metrics, "nwt_structured_120", "head_map_last", "rmse")
    rmse_180 = _metric_value(metrics, "nwt_structured_180", "head_map_last", "rmse")
    depth_120 = _metric_value(metrics, "nwt_structured_120", "watertable_depth_map_last", "mae")
    depth_180 = _metric_value(metrics, "nwt_structured_180", "watertable_depth_map_last", "mae")
    q_mf6 = _wide_value(timeseries_rows, "outlet_accumulated_flux", "mf6_disv_ref")
    q_120 = _wide_value(timeseries_rows, "outlet_accumulated_flux", "nwt_structured_120")
    q_180 = _wide_value(timeseries_rows, "outlet_accumulated_flux", "nwt_structured_180")
    h_out_mf6 = _wide_value(timeseries_rows, "outlet_head", "mf6_disv_ref")
    h_out_120 = _wide_value(timeseries_rows, "outlet_head", "nwt_structured_120")
    h_out_180 = _wide_value(timeseries_rows, "outlet_head", "nwt_structured_180")
    speed_120 = _runtime_value(execution_rows, "nwt_structured_120", "speedup_vs_reference")
    speed_180 = _runtime_value(execution_rows, "nwt_structured_180", "speedup_vs_reference")

    coverage = {
        row.get("variant_id"): _format_float(row.get("network_coverage_ratio"))
        for row in active_overlap
    }
    f1 = {row.get("variant_id"): _format_float(row.get("cell_f1_ratio")) for row in active_overlap}

    cards = [
        (
            "Temps de calcul",
            (
                f"NWT 120 est environ {speed_120} fois plus rapide que MF6 sur ce run, "
                f"NWT 180 environ {speed_180} fois. Ce gain ne suffit pas a conclure: "
                "la qualite des charges et du reseau actif doit etre lue en meme temps."
            ),
        ),
        (
            "Charges",
            (
                f"Sur la carte de charge, le RMSE vaut {rmse_120} m pour NWT 120 et {rmse_180} m pour NWT 180. "
                f"A l'exutoire, les charges sont MF6={h_out_mf6} m, NWT120={h_out_120} m, NWT180={h_out_180} m."
            ),
        ),
        (
            "Suintement et profondeur",
            (
                f"L'ecart moyen de profondeur de nappe est {depth_120} m pour NWT 120 et {depth_180} m pour NWT 180. "
                "La maille plus fine n'ameliore donc pas automatiquement ce premier cas steady."
            ),
        ),
        (
            "Debits et reseau actif",
            (
                f"Le debit outlet extrait vaut MF6={q_mf6} m3/s, NWT120={q_120} m3/s, NWT180={q_180} m3/s. "
                f"La couverture du reseau de reference est MF6={coverage.get('mf6_disv_ref', '')}, "
                f"NWT120={coverage.get('nwt_structured_120', '')}, NWT180={coverage.get('nwt_structured_180', '')}; "
                f"les F1 associes sont {f1.get('mf6_disv_ref', '')}, {f1.get('nwt_structured_120', '')}, {f1.get('nwt_structured_180', '')}."
            ),
        ),
    ]
    return (
        '<div class="comment-grid">'
        + "\n".join(
            f'<article class="comment-card"><h3>{_safe_text(title)}</h3><p>{_safe_text(text)}</p></article>'
            for title, text in cards
        )
        + "</div>"
    )


def _config_summary(base: dict[str, Any]) -> dict[str, Any]:
    flow = base.get("flow", {})
    recharge_sources = base.get("data", {}).get("recharge", {}).get("sources", [])
    recharge = recharge_sources[0] if recharge_sources else {}
    values = recharge.get("values", [])
    recharge_mm_day = values[0] if values else ""
    recharge_mm_year = ""
    parsed_recharge = _float(recharge_mm_day)
    if parsed_recharge is not None:
        recharge_mm_year = parsed_recharge * 365.25
    return {
        "regime": flow.get("flow_regime", ""),
        "k": flow.get("param", {}).get("K", {}).get("field_homogeneous", {}).get("value", ""),
        "sy": flow.get("param", {}).get("Sy", {}).get("field_homogeneous", {}).get("value", ""),
        "ss": flow.get("param", {}).get("Ss", {}).get("field_homogeneous", {}).get("value", ""),
        "drain": flow.get("bc", {}).get("cauchy", {}).get("drainage", {}).get("value", ""),
        "recharge_mm_day": recharge_mm_day,
        "recharge_mm_year": recharge_mm_year,
        "mesh_input": base.get("mesh_input", {}).get("bundle_dir", ""),
    }


def _comparison_point_rows(config: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    labels = {
        "outlet_head": "Exutoire",
        "head_outlet_series": "Exutoire",
        "mid_catchment_head": "Milieu de bassin",
        "head_mid_catchment_series": "Milieu de bassin",
        "eastern_plateau_head": "Plateau est",
        "head_eastern_plateau_series": "Plateau est",
    }
    for observable in config.get("comparison", {}).get("observable", []):
        if not isinstance(observable, dict):
            continue
        if observable.get("support") != "point":
            continue
        if observable.get("variable") != "watertable_elevation":
            continue
        x = str(observable.get("x", ""))
        y = str(observable.get("y", ""))
        if not x or not y:
            continue
        key = (x, y)
        if key in seen:
            continue
        seen.add(key)
        name = str(observable.get("name", ""))
        rows.append(
            {
                "point": labels.get(name, name),
                "observable": name,
                "x": x,
                "y": y,
                "usage": "serie de charge h(t)",
            }
        )
    return rows


def _transient_source_rows() -> list[dict[str, Any]]:
    base = _load_toml(TRANSIENT_BASE_CONFIG_PATH)
    sim_time = base.get("simulation", {}).get("time", {})
    recharge_sources = base.get("data", {}).get("recharge", {}).get("sources", [])
    recharge = recharge_sources[0] if recharge_sources else {}
    recharge_values = recharge.get("values", [])
    rows = [
        {
            "item": "Base disponible",
            "value": TRANSIENT_HYDROGRAPHY_BASE_CONFIG_PATH.name,
            "comment": "Cas Nancon transitoire avec hydrographie observee deja present dans le depot.",
        },
        {
            "item": "Chronique source",
            "value": f"{sim_time.get('start_datetime', '')} -> {sim_time.get('end_datetime', '')}",
            "comment": "Fenetre d'un an hydrologique utilisable pour le pilote.",
        },
        {
            "item": "Pas source",
            "value": sim_time.get("step_value", ""),
            "comment": "La proposition commence par une aggregation mensuelle, puis revient a ce pas si le pilote converge.",
        },
        {
            "item": "Recharge source",
            "value": f"{len(recharge_values)} valeurs" if isinstance(recharge_values, list) else "",
            "comment": "Chronique saisonniere synthetique; a conserver identique pour MF6 et NWT.",
        },
    ]
    return rows


def _build_transient_proposal_page(base: dict[str, Any], config: dict[str, Any]) -> Path:
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    cfg_summary = _config_summary(base)
    point_rows = _comparison_point_rows(config)
    source_rows = _transient_source_rows()
    source_table = _render_table(
        source_rows,
        (
            ("item", "Element"),
            ("value", "Valeur"),
            ("comment", "Commentaire"),
        ),
        empty="Aucune base transitoire Nancon detectee.",
        max_rows=8,
    )
    point_table = _render_table(
        point_rows,
        (
            ("point", "Point"),
            ("observable", "Observable steady"),
            ("x", "X Lambert-93"),
            ("y", "Y Lambert-93"),
            ("usage", "Usage transitoire"),
        ),
        empty="Aucun point de charge n'est declare dans la comparaison steady.",
        max_rows=8,
    )
    proposal_snippet = html.escape(
        "\n".join(
            [
                "# compare_nancon_transient_seasonal_mf6_disv_vs_nwt.toml",
                'base_simulation_config = "base_nancon_transient_seasonal_with_hydrography.toml"',
                'output_root = "outputs/nancon_transient_seasonal_mf6_disv_vs_nwt"',
                'reference_simulation = "mf6_disv_ref"',
                "",
                "# Variante 1: MF6 DISV, meme maillage hydrographie que la page steady",
                "# Variante 2: MODFLOW-NWT 120 x 120, grille structuree",
                "# Variante 3: MODFLOW-NWT 180 x 180, grille structuree",
                "",
                "# Observables minimum",
                '# - head_*_series: support="point", time="all"',
                '# - recharge_total, storage_change, drainage_total, outlet_flux: time="all"',
                "# - head/depth/seepage/outflow/active-network maps: high water, recession, low water, last",
            ]
        )
    )
    html_text = f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Nancon transitoire MF6 DISV vs MODFLOW-NWT - proposition</title>
  <style>
    :root {{
      --bg: #f7f7f4;
      --ink: #1d2528;
      --muted: #667174;
      --panel: #ffffff;
      --line: #d7ddd7;
      --blue: #1f6b8f;
      --green: #57785d;
      --orange: #a55d2a;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Arial, Helvetica, sans-serif;
      line-height: 1.45;
    }}
    main {{
      max-width: 1480px;
      margin: 0 auto;
      padding: 28px 24px 64px;
    }}
    header {{
      border-bottom: 1px solid var(--line);
      padding: 18px 0 22px;
      margin-bottom: 22px;
    }}
    h1, h2, h3 {{ margin: 0; line-height: 1.15; }}
    h1 {{ font-size: 2.0rem; max-width: 980px; }}
    h2 {{ font-size: 1.22rem; margin-bottom: 12px; }}
    h3 {{ font-size: 0.98rem; color: var(--blue); }}
    p {{ margin: 8px 0 0; color: var(--muted); }}
    a {{ color: var(--blue); text-decoration-thickness: 1px; }}
    code, pre {{
      font-family: Consolas, "Courier New", monospace;
      font-size: 0.9em;
    }}
    pre {{
      margin: 12px 0 0;
      padding: 12px;
      overflow-x: auto;
      background: #f2f6f7;
      border: 1px solid var(--line);
      border-radius: 8px;
      color: var(--ink);
    }}
    .section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
      margin-top: 18px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }}
    .card {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfb;
      padding: 12px;
      min-width: 0;
    }}
    .card strong {{
      display: block;
      margin-bottom: 5px;
      color: var(--ink);
    }}
    .callout {{
      border-left: 4px solid var(--blue);
      padding: 10px 12px;
      background: #f2f6f7;
      color: var(--ink);
      margin-top: 12px;
    }}
    .warn {{ border-left-color: var(--orange); background: #fbf4ee; }}
    .pillrow {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 12px;
    }}
    .pill {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 5px 9px;
      background: #fbfcfb;
      font-size: 0.86rem;
    }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
    th, td {{ text-align: left; padding: 7px 8px; border-bottom: 1px solid #e8ece8; }}
    th {{ color: var(--muted); font-weight: 600; white-space: nowrap; }}
    .muted {{ color: var(--muted); }}
    @media (max-width: 980px) {{
      main {{ padding: 18px 14px 44px; }}
      .grid, .cards {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
<main>
  <header>
    <h1>Nancon transitoire: proposition de comparaison MF6 DISV vs MODFLOW-NWT</h1>
    <p>
      Cette page est une proposition de protocole, pas une page de resultats calcules.
      Elle decrit comment passer de la comparaison steady actuelle a une comparaison transitoire lisible sur les
      charges, les flux, les zones de suintement et le reseau actif.
    </p>
    <div class="pillrow">
      <span class="pill"><a href="index.html">Retour page steady</a></span>
      <span class="pill"><a href="transient_results.html">Resultats pilotes si disponibles</a></span>
      <span class="pill">Parametres physiques steady: K={_safe_text(cfg_summary["k"])}, Sy={_safe_text(cfg_summary["sy"])}, Ss={_safe_text(cfg_summary["ss"])}</span>
      <span class="pill">Drainage: {_safe_text(cfg_summary["drain"])}</span>
    </div>
  </header>

  <section class="section">
    <h2>Ce que l'on veut trancher</h2>
    <div class="cards">
      <div class="card">
        <strong>Effet de representation</strong>
        <p>Verifier si les ecarts steady viennent surtout du support spatial: DISV suit mieux les rivieres, NWT les approxime par une grille reguliere.</p>
      </div>
      <div class="card">
        <strong>Effet dynamique</strong>
        <p>Comparer phase, amplitude et retour a l'etiage des charges et des flux, pas seulement la derniere carte.</p>
      </div>
      <div class="card">
        <strong>Effet solveur</strong>
        <p>Suivre convergence, temps de calcul et bilan de stockage pour detecter les cas ou NWT devient couteux ou instable.</p>
      </div>
    </div>
    <p class="callout">
      Proposition clarifiee: on ne lance pas tout de suite un transitoire lourd. On fait d'abord un pilote court,
      avec les memes parametres physiques que le steady et les memes trois variantes. La page de resultats
      transitoires ne sera produite qu'apres ce pilote.
    </p>
  </section>

  <section class="section">
    <h2>Base transitoire disponible</h2>
    <p>
      Le depot contient deja un cas Nancon transitoire saisonnier. Pour une comparaison MF6 DISV vs NWT,
      il faut le reprendre en remplacant la comparaison MF6/Boussinesq par les trois variantes de la page steady.
    </p>
    {source_table}
  </section>

  <section class="section">
    <h2>Plan de calcul propose</h2>
    <div class="grid">
      <div class="card">
        <strong>Phase 1 - pilote mensuel</strong>
        <p>Agreger la chronique hebdomadaire disponible en 12 periodes mensuelles. Objectif: valider les sorties, la fermeture de bilan et la convergence NWT sans cout excessif.</p>
      </div>
      <div class="card">
        <strong>Phase 2 - resolution hebdomadaire</strong>
        <p>Revenir au pas 7 jours deja present si le pilote est stable. Objectif: lire les pics de drainage, les dephasages de charge et les episodes de reseau actif.</p>
      </div>
      <div class="card">
        <strong>Phase 3 - sensibilite NWT</strong>
        <p>Conserver MF6 DISV comme reference et tester NWT 120, NWT 180, puis eventuellement une grille plus fine ou un raffinement cible pres des thalwegs.</p>
      </div>
      <div class="card">
        <strong>Condition initiale</strong>
        <p>Utiliser un steady de warm-up coherent pour les trois variantes. Cela evite de comparer des transitoires contamines par des etats initiaux differents.</p>
      </div>
    </div>
  </section>

  <section class="section">
    <h2>Configuration candidate</h2>
    <p>
      Le fichier a creer serait voisin de <code>compare_nancon_steady_mf6_disv_vs_nwt.toml</code>,
      mais avec la base transitoire et des observables <code>time="all"</code> pour les series.
    </p>
    <pre><code>{proposal_snippet}</code></pre>
  </section>

  <section class="section">
    <h2>Charges aux points</h2>
    <p>
      Les memes points que dans le steady peuvent devenir des series h(t). Il faut garder les points fixes en
      Lambert-93, puis extraire dans chaque modele la cellule qui contient le point ou la valeur interpolee.
    </p>
    {point_table}
  </section>

  <section class="section">
    <h2>Flux et cartes a comparer</h2>
    <div class="grid">
      <div class="card">
        <strong>Series de flux</strong>
        <p>Recharge totale, drainage total, variation de stockage, erreur de bilan et flux a l'exutoire. Ces courbes doivent etre tracees cote a cote pour les trois variantes.</p>
      </div>
      <div class="card">
        <strong>Cartes aux dates clefs</strong>
        <p>Haute eau, recession, basse eau et derniere date. Pour chaque date: charge, profondeur de nappe, suintement, drainage distribue et flux accumule.</p>
      </div>
      <div class="card">
        <strong>Reseau actif</strong>
        <p>Comparer l'extension active par date et une carte de persistance: fraction du temps ou chaque secteur est actif.</p>
      </div>
      <div class="card">
        <strong>Performance</strong>
        <p>Tableau unique avec nombre de mailles, nombre de periodes, temps total, temps par periode, statut et indicateurs de convergence.</p>
      </div>
    </div>
  </section>

  <section class="section">
    <h2>Risques a controler</h2>
    <p class="callout warn">
      La principale difficulte n'est pas de lancer du transitoire: NWT et MF6 savent le faire dans le depot.
      Le point sensible est l'equivalence du support. Le flux d'exutoire et le reseau actif doivent etre extraits
      sur une geometrie commune, sinon les ecarts peuvent venir du post-traitement plutot que du modele.
    </p>
    <div class="cards">
      <div class="card">
        <strong>Support outlet</strong>
        <p>Definir une zone d'extraction commune autour de l'exutoire, pas seulement une cellule differente par modele.</p>
      </div>
      <div class="card">
        <strong>Stockage</strong>
        <p>Verifier que Sy et Ss sont interpretes de facon comparable dans les deux solveurs sur les cellules seches/humides.</p>
      </div>
      <div class="card">
        <strong>Cout calcul</strong>
        <p>Ne passer au pas hebdomadaire qu'apres validation mensuelle, surtout pour la grille NWT la plus fine.</p>
      </div>
    </div>
  </section>

  <section class="section">
    <h2>Sortie attendue</h2>
    <p>
      La page de resultats transitoires devrait reprendre la meme logique que la page steady:
      configuration en tete, comparaison du nombre de mailles et du temps de calcul, courbes de charge,
      courbes de flux, puis planches de cartes avec le bassin versant, l'exutoire et le maillage visibles.
    </p>
  </section>
</main>
</body>
</html>
"""
    out = WEB_DIR / "transient_proposal.html"
    out.write_text(html_text, encoding="utf-8")
    return out


def _audit_issue_rows(audit: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for issue in audit.get("issues", [])[:18]:
        if not isinstance(issue, dict):
            continue
        rows.append(
            {
                "level": issue.get("level", ""),
                "kind": issue.get("kind", ""),
                "variant_id": issue.get("variant_id", ""),
                "field": issue.get("field", ""),
                "fraction": _format_float(issue.get("above_top_fraction")),
                "max_m": _format_float(issue.get("above_top_max_m")),
                "message": issue.get("message", ""),
            }
        )
    return rows


def _transient_interpretation_cards(
    *,
    manifest: dict[str, Any],
    metrics: list[dict[str, str]],
    execution_rows: list[dict[str, str]],
) -> str:
    h_out_120 = _metric_value(metrics, "nwt_structured_120", "head_outlet_series", "rmse")
    h_out_180 = _metric_value(metrics, "nwt_structured_180", "head_outlet_series", "rmse")
    h_plateau_120 = _metric_value(
        metrics, "nwt_structured_120", "head_eastern_plateau_series", "rmse"
    )
    h_plateau_180 = _metric_value(
        metrics, "nwt_structured_180", "head_eastern_plateau_series", "rmse"
    )
    q_120 = _metric_value(metrics, "nwt_structured_120", "outlet_flux_series", "rmse")
    q_180 = _metric_value(metrics, "nwt_structured_180", "outlet_flux_series", "rmse")
    speed_120 = _runtime_value(execution_rows, "nwt_structured_120", "speedup_vs_reference")
    speed_180 = _runtime_value(execution_rows, "nwt_structured_180", "speedup_vs_reference")
    completed = sum(
        1
        for variant in manifest.get("variants", [])
        if isinstance(variant, dict) and variant.get("status") == "completed"
    )
    total = len([item for item in manifest.get("variants", []) if isinstance(item, dict)])
    cards = [
        (
            "Executions",
            f"{completed}/{total} variantes terminees; audit={manifest.get('audit_status', '')}. "
            f"NWT120 speedup={speed_120}, NWT180 speedup={speed_180}.",
        ),
        (
            "Charges h(t)",
            f"RMSE a l'exutoire: NWT120={h_out_120} m, NWT180={h_out_180} m. "
            f"Sur le plateau est: NWT120={h_plateau_120} m, NWT180={h_plateau_180} m.",
        ),
        (
            "Flux outlet",
            f"RMSE du flux d'exutoire: NWT120={q_120} m3/s, NWT180={q_180} m3/s. "
            "La lecture doit rester prudente car l'extraction outlet depend du support.",
        ),
        (
            "Statut physique",
            "Le pilote calcule, mais l'audit signale des charges souvent au-dessus du toit. "
            "La page sert donc d'abord a diagnostiquer les ecarts et les reglages a corriger.",
        ),
    ]
    return (
        '<div class="comment-grid">'
        + "\n".join(
            f"""
            <article class="comment-card">
              <h3>{_safe_text(title)}</h3>
              <p>{_safe_text(text)}</p>
            </article>
            """
            for title, text in cards
        )
        + "</div>"
    )


def _build_transient_results_page() -> Path | None:
    manifest_path = TRANSIENT_COMPARISON_ROOT / "comparison_manifest.json"
    if not manifest_path.exists():
        return None
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    config = _load_resolved_toml(TRANSIENT_CONFIG_PATH)
    base = _load_resolved_toml(TRANSIENT_MONTHLY_BASE_CONFIG_PATH)
    manifest = _load_json(manifest_path)
    audit = _load_json(TRANSIENT_COMPARISON_ROOT / "comparison_audit.json")
    figures = _figure_artifacts(manifest)
    active_metrics_rows = _load_csv(
        TRANSIENT_COMPARISON_ROOT / "simulated_active_network_metrics.csv"
    )
    cell_counts = _cell_counts_from_rows(active_metrics_rows)
    execution_rows = _enrich_execution_rows(
        _load_csv(TRANSIENT_COMPARISON_ROOT / "execution_times.csv"),
        manifest,
        cell_counts,
    )
    metrics_rows = _load_csv(TRANSIENT_COMPARISON_ROOT / "comparison_metrics.csv")
    overlap_rows = _load_csv(
        TRANSIENT_COMPARISON_ROOT / "simulated_active_network_overlap_metrics.csv"
    )
    budget_rows = _load_csv(TRANSIENT_COMPARISON_ROOT / "budget_timeseries_wide.csv")
    watershed_overlay = _load_watershed_overlay(config, manifest, base)
    mesh_geometries = _mesh_geometries_from_zarr(config, manifest)
    complete_case_maps = _generate_three_case_map_figures(
        config=config,
        manifest=manifest,
        cell_counts=cell_counts,
        overlay=watershed_overlay,
        mesh_geometries=mesh_geometries,
        output_dir=TRANSIENT_WEB_FIGURES_DIR,
        config_path=TRANSIENT_CONFIG_PATH,
        base_config_path=TRANSIENT_MONTHLY_BASE_CONFIG_PATH,
        comparison_root=TRANSIENT_COMPARISON_ROOT,
    )

    execution_table = _render_table(
        execution_rows,
        (
            ("variant_id", "Variante"),
            ("solver", "Solver"),
            ("mesh_mode", "Maillage"),
            ("cell_count", "Mailles"),
            ("status", "Statut"),
            ("runtime_seconds", "Temps s"),
            ("speedup_vs_reference", "Speedup"),
        ),
        empty="Les temps d'execution ne sont pas disponibles.",
        max_rows=10,
    )
    metrics_table = _render_table(
        metrics_rows,
        (
            ("variant_id", "Variante"),
            ("observable", "Observable"),
            ("unit", "Unite"),
            ("n_pairs", "Paires"),
            ("bias", "Biais"),
            ("mae", "MAE"),
            ("rmse", "RMSE"),
            ("max_abs_error", "Max abs."),
        ),
        empty="Les metriques ne sont pas disponibles.",
        max_rows=24,
    )
    overlap_table = _render_table(
        overlap_rows,
        (
            ("variant_id", "Variante"),
            ("network_role", "Reseau"),
            ("active_cell_count", "Cellules actives"),
            ("network_coverage_ratio", "Coverage"),
            ("active_precision_ratio", "Precision"),
            ("cell_f1_ratio", "F1"),
            ("cell_jaccard_ratio", "Jaccard"),
        ),
        empty="Les metriques de reseau actif ne sont pas disponibles.",
        max_rows=12,
    )
    audit_table = _render_table(
        _audit_issue_rows(audit),
        (
            ("level", "Niveau"),
            ("kind", "Type"),
            ("variant_id", "Variante"),
            ("field", "Champ"),
            ("fraction", "Fraction"),
            ("max_m", "Max m"),
            ("message", "Message"),
        ),
        empty="Aucun avertissement d'audit.",
        max_rows=18,
    )
    budget_table = _render_table(
        budget_rows,
        (
            ("time_label", "Temps"),
            ("component", "Composante"),
            ("unit", "Unite"),
            ("value__mf6_disv_ref", "MF6 DISV"),
            ("value__nwt_structured_120", "NWT 120"),
            ("value__nwt_structured_180", "NWT 180"),
        ),
        empty="Le bilan transitoire n'est pas disponible.",
        max_rows=18,
    )
    point_figures = [
        _figure_by_filename(figures, "head_points_dashboard.png"),
        _figure_by_filename(figures, "head_outlet_series__timeseries.png"),
        _figure_by_filename(figures, "head_mid_catchment_series__timeseries.png"),
        _figure_by_filename(figures, "head_eastern_plateau_series__timeseries.png"),
    ]
    flux_figures = [
        _figure_by_filename(figures, "outlet_flux_series__timeseries.png"),
        _figure_by_filename(figures, "mf6_disv_ref__budget_diagnostics.png"),
        _figure_by_filename(figures, "nwt_structured_120__budget_diagnostics.png"),
        _figure_by_filename(figures, "nwt_structured_180__budget_diagnostics.png"),
    ]
    runtime_figures = [
        _figure_by_filename(figures, "execution_time_comparison.png"),
        _figure_by_filename(figures, "case_configuration.png"),
    ]
    network_deck = _figure_deck(
        [
            (
                _figure_by_variant_name(
                    figures, "mf6_disv_ref", "simulated_active_network_reference_overlay"
                ),
                "MF6 DISV - reseau actif",
                "Overlay avec hydrographie de reference.",
            ),
            (
                _figure_by_variant_name(
                    figures, "nwt_structured_120", "simulated_active_network_reference_overlay"
                ),
                "NWT 120 x 120 - reseau actif",
                "Lecture sur grille structuree.",
            ),
            (
                _figure_by_variant_name(
                    figures, "nwt_structured_180", "simulated_active_network_reference_overlay"
                ),
                "NWT 180 x 180 - reseau actif",
                "Lecture apres raffinement.",
            ),
        ]
    )
    cfg_summary = _config_summary(base)
    html_text = f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Nancon transitoire mensuel MF6 DISV vs MODFLOW-NWT</title>
  <style>
    :root {{
      --bg: #f7f7f4;
      --ink: #1d2528;
      --muted: #667174;
      --panel: #ffffff;
      --line: #d7ddd7;
      --blue: #1f6b8f;
      --orange: #a55d2a;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Arial, Helvetica, sans-serif;
      line-height: 1.45;
    }}
    main {{ max-width: 1760px; margin: 0 auto; padding: 28px 24px 64px; }}
    header {{ border-bottom: 1px solid var(--line); padding: 18px 0 22px; margin-bottom: 22px; }}
    h1, h2, h3 {{ margin: 0; line-height: 1.15; }}
    h1 {{ font-size: 2.05rem; max-width: 980px; }}
    h2 {{ font-size: 1.25rem; margin-bottom: 12px; }}
    h3 {{ font-size: 0.95rem; color: var(--blue); }}
    p {{ margin: 8px 0 0; color: var(--muted); }}
    a {{ color: var(--blue); text-decoration-thickness: 1px; }}
    code {{ font-family: Consolas, "Courier New", monospace; font-size: 0.9em; color: var(--blue); }}
    .section {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 18px; margin-top: 18px; }}
    .facts, .comment-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }}
    .fact, .comment-card {{ border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #fbfcfb; min-width: 0; }}
    .fact span {{ display: block; color: var(--muted); font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em; }}
    .fact strong {{ display: block; margin-top: 4px; overflow-wrap: anywhere; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
    th, td {{ text-align: left; padding: 7px 8px; border-bottom: 1px solid #e8ece8; }}
    th {{ color: var(--muted); font-weight: 600; white-space: nowrap; }}
    .fig-grid, .wide-fig-grid, .figure-deck {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }}
    .wide-fig-grid {{ margin-top: 12px; }}
    .figure-deck {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
    figure {{ margin: 0; border: 1px solid var(--line); border-radius: 8px; background: #fbfcfb; padding: 10px; }}
    img {{ width: 100%; display: block; border-radius: 6px; border: 1px solid #e2e7e2; background: white; }}
    figcaption {{ margin-top: 7px; color: var(--muted); font-size: 0.88rem; }}
    figcaption strong {{ display: block; color: var(--ink); font-size: 0.92rem; }}
    .callout {{ border-left: 4px solid var(--blue); padding: 10px 12px; background: #f2f6f7; color: var(--ink); margin-top: 12px; }}
    .warn {{ border-left-color: var(--orange); background: #fbf4ee; }}
    .pillrow {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }}
    .pill {{ border: 1px solid var(--line); border-radius: 999px; padding: 5px 9px; background: #fbfcfb; font-size: 0.86rem; }}
    .muted {{ color: var(--muted); }}
    @media (max-width: 980px) {{
      main {{ padding: 18px 14px 44px; }}
      .facts, .comment-grid, .fig-grid, .wide-fig-grid, .figure-deck {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
<main>
  <header>
    <h1>Nancon transitoire mensuel: MF6 DISV vs MODFLOW-NWT</h1>
    <p>
      Resultats du pilote mensuel autonome. Les trois variantes ont ete lancees sur les memes parametres physiques,
      avec MF6 sur maillage DISV contraint par les rivieres et NWT sur grilles 120 x 120 puis 180 x 180.
    </p>
    <div class="pillrow">
      <span class="pill"><a href="index.html">Retour steady</a></span>
      <span class="pill"><a href="transient_proposal.html">Protocole transitoire</a></span>
      <span class="pill"><a href="transient_ic_diagnostic.html">Diagnostic IC</a></span>
      <span class="pill">Config: <code>{_safe_text(TRANSIENT_CONFIG_PATH.relative_to(ROOT))}</code></span>
      <span class="pill">Audit: <code>{_safe_text(manifest.get("audit_status", ""))}</code></span>
    </div>
  </header>

  <section class="section">
    <h2>Lecture rapide</h2>
    {_transient_interpretation_cards(manifest=manifest, metrics=metrics_rows, execution_rows=execution_rows)}
    <p class="callout warn">
      Point important: l'audit signale des charges au-dessus du toit du modele sur de larges fractions de cellules.
      Les sorties ci-dessous sont donc utiles pour comparer les comportements numeriques et les supports, mais le
      cas doit encore etre stabilise physiquement avant d'etre presente comme simulation definitive.
    </p>
  </section>

  <section class="section">
    <h2>Configuration</h2>
    <div class="facts">
      <div class="fact"><span>Regime</span><strong>{_safe_text(cfg_summary["regime"])}</strong></div>
      <div class="fact"><span>Pas</span><strong>12 mois</strong></div>
      <div class="fact"><span>K homogene</span><strong>{_safe_text(cfg_summary["k"])}</strong></div>
      <div class="fact"><span>Drainage top</span><strong>{_safe_text(cfg_summary["drain"])}</strong></div>
      <div class="fact"><span>Sy</span><strong>{_safe_text(cfg_summary["sy"])}</strong></div>
      <div class="fact"><span>Ss</span><strong>{_safe_text(cfg_summary["ss"])}</strong></div>
      <div class="fact"><span>Observables</span><strong>{_safe_text(len(config.get("comparison", {}).get("observable", [])))}</strong></div>
      <div class="fact"><span>Lignes extraites</span><strong>{_safe_text(manifest.get("n_observable_rows", ""))}</strong></div>
    </div>
  </section>

  <section class="section">
    <h2>Mailles et temps de calcul</h2>
    {execution_table}
    {_figure_grid([figure for figure in runtime_figures if figure], empty="Aucune figure runtime disponible.")}
  </section>

  <section class="section">
    <h2>Charges transitoires aux points</h2>
    <p>Les courbes utilisent les trois points du steady: exutoire, milieu de bassin et plateau est.</p>
    {_figure_grid([figure for figure in point_figures if figure], empty="Aucune serie de charge disponible.")}
  </section>

  <section class="section">
    <h2>Flux et bilan</h2>
    <p>Les flux comparent le drainage, le stockage et le flux extrait a l'exutoire sur les 12 periodes mensuelles.</p>
    {_figure_grid([figure for figure in flux_figures if figure], empty="Aucune figure de flux disponible.")}
    {budget_table}
  </section>

  <section class="section">
    <h2>Cartes comparables</h2>
    <p>
      Ces planches sont generees a partir des resultats natifs, avec le contour du bassin, l'exutoire et les aretes
      de maillage visibles pour DISV comme pour NWT. Elles completent les figures standards du workflow.
    </p>
    {_wide_figure_grid(complete_case_maps, empty="Aucune carte complete transitoire disponible.")}
  </section>

  <section class="section">
    <h2>Reseau actif</h2>
    {overlap_table}
    {network_deck}
  </section>

  <section class="section">
    <h2>Metriques et audit</h2>
    {metrics_table}
    <h3 style="margin-top:16px;">Avertissements d'audit</h3>
    {audit_table}
  </section>

  <section class="section">
    <h2>Fichiers produits</h2>
    <div class="pillrow">
      <span class="pill"><code>{_safe_text(TRANSIENT_COMPARISON_ROOT.relative_to(ROOT))}</code></span>
      <span class="pill"><code>timeseries_wide.csv</code></span>
      <span class="pill"><code>budget_timeseries_wide.csv</code></span>
      <span class="pill"><code>comparison_metrics.csv</code></span>
      <span class="pill"><code>comparison_figures/</code></span>
      <span class="pill"><code>web_figures/</code></span>
    </div>
  </section>
</main>
</body>
</html>
"""
    out = WEB_DIR / "transient_results.html"
    out.write_text(html_text, encoding="utf-8")
    return out


def _series_values(
    rows: list[dict[str, str]],
    observable: str,
    variant_id: str,
) -> list[float]:
    values: list[float] = []
    key = f"value__{variant_id}"
    for row in rows:
        if row.get("observable") != observable:
            continue
        parsed = _float(row.get(key))
        if parsed is not None:
            values.append(parsed)
    return values


def _head_diagnostic_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    labels = {
        "head_outlet_series": "Exutoire",
        "head_mid_catchment_series": "Milieu bassin",
        "head_eastern_plateau_series": "Plateau est",
    }
    variants = ("nwt_structured_120", "nwt_structured_180")
    output: list[dict[str, str]] = []
    for observable, label in labels.items():
        reference = _series_values(rows, observable, "mf6_disv_ref")
        if not reference:
            continue
        ref_anomaly = [value - reference[0] for value in reference]
        for variant_id in variants:
            candidate = _series_values(rows, observable, variant_id)
            if len(candidate) != len(reference) or not candidate:
                continue
            diffs = [cand - ref for cand, ref in zip(candidate, reference, strict=False)]
            cand_anomaly = [value - candidate[0] for value in candidate]
            anomaly_diffs = [
                cand - ref
                for cand, ref in zip(cand_anomaly, ref_anomaly, strict=False)
            ]
            anomaly_rmse = math.sqrt(
                sum(value * value for value in anomaly_diffs) / len(anomaly_diffs)
            )
            output.append(
                {
                    "point": label,
                    "variant": variant_id,
                    "diff_first": _format_float(diffs[0]),
                    "diff_last": _format_float(diffs[-1]),
                    "range_ref": _format_float(max(reference) - min(reference)),
                    "range_variant": _format_float(max(candidate) - min(candidate)),
                    "anomaly_rmse": _format_float(anomaly_rmse),
                    "anomaly_last": _format_float(anomaly_diffs[-1]),
                }
            )
    return output


def _budget_delta_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    components = (
        ("recharge_total_m3_s", "Recharge"),
        ("drainage_total_m3_s", "Drainage"),
        ("storage_change_total_m3_s", "Stockage"),
        ("closure_residual_m3_s", "Fermeture"),
    )
    variants = ("nwt_structured_120", "nwt_structured_180")
    output: list[dict[str, str]] = []
    for component, label in components:
        component_rows = [row for row in rows if row.get("component") == component]
        for variant_id in variants:
            abs_diffs: list[float] = []
            rel_diffs: list[float] = []
            for row in component_rows:
                reference = _float(row.get("value__mf6_disv_ref"))
                candidate = _float(row.get(f"value__{variant_id}"))
                if reference is None or candidate is None:
                    continue
                diff = abs(candidate - reference)
                abs_diffs.append(diff)
                if abs(reference) > 1.0e-12:
                    rel_diffs.append(diff / abs(reference))
            output.append(
                {
                    "component_label": label,
                    "variant": variant_id,
                    "max_abs": _format_float(max(abs_diffs) if abs_diffs else None),
                    "max_rel": _format_float(max(rel_diffs) if rel_diffs else None),
                }
            )
    return output


def _diagnostic_config_rows(
    manifest: dict[str, Any],
    cell_counts: dict[str, str],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for variant in manifest.get("variants", []):
        if not isinstance(variant, dict):
            continue
        config_path_raw = variant.get("config_path")
        config_path = Path(str(config_path_raw)) if config_path_raw else None
        payload = _load_toml(config_path) if config_path is not None else {}
        solver = str(variant.get("solver", ""))
        solver_section = payload.get(solver, {}) if isinstance(payload, dict) else {}
        tgrid = solver_section.get("tgrid", {}) if isinstance(solver_section, dict) else {}
        ic = payload.get("flow", {}).get("ic", {}) if isinstance(payload, dict) else {}
        rows.append(
            {
                "variant_id": str(variant.get("id", "")),
                "solver": solver,
                "cell_count": cell_counts.get(str(variant.get("id", "")), ""),
                "ic": f"{ic.get('type', '')} {ic.get('value', '')}".strip(),
                "firstpersteady": str(tgrid.get("firstpersteady", "")),
                "status": str(variant.get("status", "")),
            }
        )
    return rows


def _diagnostic_overview_rows(base: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    flow = base.get("flow", {})
    simulation_time = base.get("simulation", {}).get("time", {})
    geo = base.get("geographic", {})
    depth = base.get("domain", {}).get("depth_model", {})
    recharge_sources = base.get("data", {}).get("recharge", {}).get("sources", [])
    recharge = recharge_sources[0] if recharge_sources else {}
    recharge_values = [
        value for value in recharge.get("values", []) if _float(value) is not None
    ]
    recharge_mean = (
        sum(float(value) for value in recharge_values) / len(recharge_values)
        if recharge_values
        else None
    )
    fine = config.get("comparison", {}).get("fine_raster", {})
    observables = config.get("comparison", {}).get("observable", [])
    map_count = sum(
        1 for observable in observables if isinstance(observable, dict) and observable.get("support") == "map"
    )
    point_count = sum(
        1 for observable in observables if isinstance(observable, dict) and observable.get("support") == "point"
    )
    outlet_count = sum(
        1 for observable in observables if isinstance(observable, dict) and observable.get("support") == "outlet"
    )
    tgrid_values: list[str] = []
    for simulation in config.get("comparison", {}).get("simulation", []):
        if not isinstance(simulation, dict):
            continue
        solver = str(simulation.get("solver", ""))
        solver_overlay = simulation.get("overlay", {}).get(solver, {})
        tgrid = solver_overlay.get("tgrid", {}) if isinstance(solver_overlay, dict) else {}
        if "firstpersteady" in tgrid:
            tgrid_values.append(f"{simulation.get('id')}: {tgrid.get('firstpersteady')}")

    return [
        {
            "item": "Objectif",
            "value": "Isoler recharge, condition initiale et extraction ponctuelle",
            "comment": "Meme recharge que le pilote mensuel; comparaison MF6 DISV vs deux grilles NWT.",
        },
        {
            "item": "Fenetre temporelle",
            "value": (
                f"{simulation_time.get('start_datetime', '')} -> "
                f"{simulation_time.get('end_datetime', '')}; pas {simulation_time.get('step_value', '')}"
            ),
            "comment": "Douze periodes mensuelles en regime transitoire.",
        },
        {
            "item": "Condition initiale",
            "value": (
                f"{flow.get('ic', {}).get('type', '')}; "
                f"value={flow.get('ic', {}).get('value', '')}; "
                f"firstpersteady={'; '.join(tgrid_values)}"
            ),
            "comment": "On evite le premier equilibre steady propre a chaque maillage.",
        },
        {
            "item": "Recharge",
            "value": (
                f"{len(recharge_values)} valeurs mensuelles; "
                f"moyenne={_format_float(recharge_mean)} mm/j; "
                f"equivalent={_format_float(None if recharge_mean is None else recharge_mean * 365.25)} mm/an"
            ),
            "comment": f"Source {recharge.get('source', '')}; runoff_ratio={recharge.get('runoff_ratio', '')}.",
        },
        {
            "item": "Parametres aquifere",
            "value": (
                f"K={flow.get('param', {}).get('K', {}).get('field_homogeneous', {}).get('value', '')}; "
                f"Sy={flow.get('param', {}).get('Sy', {}).get('field_homogeneous', {}).get('value', '')}; "
                f"Ss={flow.get('param', {}).get('Ss', {}).get('field_homogeneous', {}).get('value', '')}; "
                f"epaisseur={depth.get('thickness', '')}"
            ),
            "comment": "Valeurs communes aux trois variantes.",
        },
        {
            "item": "Drainage",
            "value": flow.get("bc", {}).get("cauchy", {}).get("drainage", {}).get("value", ""),
            "comment": "Condition de Cauchy appliquee sur le toit.",
        },
        {
            "item": "Domaine",
            "value": (
                f"CRS {geo.get('crs_project', '')}; exutoire "
                f"({geo.get('x_outlet', '')}, {geo.get('y_outlet', '')}); "
                f"snap={geo.get('snap_dist', '')}"
            ),
            "comment": "Meme bassin du Nancon et hydrographie BD TOPAGE.",
        },
        {
            "item": "Comparaison spatiale",
            "value": (
                f"Raster commun {fine.get('resolution', '')} m; "
                f"extent={fine.get('extent_mode', '')}; interpolation={fine.get('interpolation', '')}"
            ),
            "comment": "Les cartes completes conservent aussi les maillages natifs superposes.",
        },
        {
            "item": "Observables",
            "value": f"{map_count} cartes; {point_count} points de charge; {outlet_count} flux outlet",
            "comment": "Charges, zones de suintement, drainage, reseau actif et flux.",
        },
    ]


def _diagnostic_recharge_rows(base: dict[str, Any]) -> list[dict[str, str]]:
    recharge_sources = base.get("data", {}).get("recharge", {}).get("sources", [])
    recharge = recharge_sources[0] if recharge_sources else {}
    values = recharge.get("values", [])
    rows: list[dict[str, str]] = []
    for index, value in enumerate(values, start=1):
        rows.append(
            {
                "period": str(index),
                "recharge_mm_day": _format_float(value, digits=4),
                "source": str(recharge.get("source", "")),
                "freq": str(recharge.get("freq", "")),
            }
        )
    return rows


def _build_transient_diagnostic_page() -> Path | None:
    manifest_path = TRANSIENT_DIAGNOSTIC_COMPARISON_ROOT / "comparison_manifest.json"
    if not manifest_path.exists():
        return None
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    config = _load_resolved_toml(TRANSIENT_DIAGNOSTIC_CONFIG_PATH)
    base = _load_resolved_toml(TRANSIENT_DIAGNOSTIC_BASE_CONFIG_PATH)
    manifest = _load_json(manifest_path)
    audit = _load_json(TRANSIENT_DIAGNOSTIC_COMPARISON_ROOT / "comparison_audit.json")
    figures = _figure_artifacts(manifest)
    active_metrics_rows = _load_csv(
        TRANSIENT_DIAGNOSTIC_COMPARISON_ROOT / "simulated_active_network_metrics.csv"
    )
    cell_counts = _cell_counts_from_rows(active_metrics_rows)
    execution_rows = _enrich_execution_rows(
        _load_csv(TRANSIENT_DIAGNOSTIC_COMPARISON_ROOT / "execution_times.csv"),
        manifest,
        cell_counts,
    )
    timeseries_rows = _load_csv(TRANSIENT_DIAGNOSTIC_COMPARISON_ROOT / "timeseries_wide.csv")
    budget_rows = _load_csv(
        TRANSIENT_DIAGNOSTIC_COMPARISON_ROOT / "budget_timeseries_wide.csv"
    )
    metrics_rows = _load_csv(TRANSIENT_DIAGNOSTIC_COMPARISON_ROOT / "comparison_metrics.csv")
    overlap_rows = _load_csv(
        TRANSIENT_DIAGNOSTIC_COMPARISON_ROOT
        / "simulated_active_network_overlap_metrics.csv"
    )
    watershed_overlay = _load_watershed_overlay(config, manifest, base)
    mesh_geometries = _mesh_geometries_from_zarr(config, manifest)
    complete_case_maps = _generate_three_case_map_figures(
        config=config,
        manifest=manifest,
        cell_counts=cell_counts,
        overlay=watershed_overlay,
        mesh_geometries=mesh_geometries,
        output_dir=TRANSIENT_DIAGNOSTIC_WEB_FIGURES_DIR,
        config_path=TRANSIENT_DIAGNOSTIC_CONFIG_PATH,
        base_config_path=TRANSIENT_DIAGNOSTIC_BASE_CONFIG_PATH,
        comparison_root=TRANSIENT_DIAGNOSTIC_COMPARISON_ROOT,
    )

    config_table = _render_table(
        _diagnostic_config_rows(manifest, cell_counts),
        (
            ("variant_id", "Variante"),
            ("solver", "Solver"),
            ("cell_count", "Mailles"),
            ("ic", "Condition initiale"),
            ("firstpersteady", "firstpersteady"),
            ("status", "Statut"),
        ),
        empty="Configuration diagnostic non disponible.",
        max_rows=10,
    )
    overview_table = _render_table(
        _diagnostic_overview_rows(base, config),
        (
            ("item", "Element"),
            ("value", "Configuration"),
            ("comment", "Role dans le diagnostic"),
        ),
        empty="Resume de configuration non disponible.",
        max_rows=12,
    )
    recharge_table = _render_table(
        _diagnostic_recharge_rows(base),
        (
            ("period", "Periode"),
            ("recharge_mm_day", "Recharge mm/j"),
            ("source", "Source"),
            ("freq", "Freq."),
        ),
        empty="Chronique de recharge non disponible.",
        max_rows=12,
    )
    head_table = _render_table(
        _head_diagnostic_rows(timeseries_rows),
        (
            ("point", "Point"),
            ("variant", "Variante"),
            ("diff_first", "Ecart t1 m"),
            ("diff_last", "Ecart final m"),
            ("range_ref", "Amplitude MF6 m"),
            ("range_variant", "Amplitude NWT m"),
            ("anomaly_rmse", "RMSE anomalie m"),
            ("anomaly_last", "Anomalie finale m"),
        ),
        empty="Series de charge non disponibles.",
        max_rows=10,
    )
    budget_delta_table = _render_table(
        _budget_delta_rows(budget_rows),
        (
            ("component_label", "Composante"),
            ("variant", "Variante"),
            ("max_abs", "Max abs. m3/s"),
            ("max_rel", "Max relatif"),
        ),
        empty="Bilan non disponible.",
        max_rows=12,
    )
    execution_table = _render_table(
        execution_rows,
        (
            ("variant_id", "Variante"),
            ("solver", "Solver"),
            ("mesh_mode", "Maillage"),
            ("cell_count", "Mailles"),
            ("status", "Statut"),
            ("runtime_seconds", "Temps s"),
        ),
        empty="Temps d'execution non disponibles.",
        max_rows=10,
    )
    metrics_table = _render_table(
        metrics_rows,
        (
            ("variant_id", "Variante"),
            ("observable", "Observable"),
            ("unit", "Unite"),
            ("n_pairs", "Paires"),
            ("rmse", "RMSE"),
            ("max_abs_error", "Max abs."),
        ),
        empty="Metriques non disponibles.",
        max_rows=18,
    )
    overlap_table = _render_table(
        overlap_rows,
        (
            ("variant_id", "Variante"),
            ("network_role", "Reseau"),
            ("active_cell_count", "Cellules actives"),
            ("network_coverage_ratio", "Coverage"),
            ("cell_f1_ratio", "F1"),
        ),
        empty="Metriques de reseau actif non disponibles.",
        max_rows=10,
    )
    point_figures = [
        _figure_by_filename(figures, "head_points_dashboard.png"),
        _figure_by_filename(figures, "head_outlet_series__timeseries.png"),
        _figure_by_filename(figures, "head_mid_catchment_series__timeseries.png"),
        _figure_by_filename(figures, "head_eastern_plateau_series__timeseries.png"),
    ]
    flux_figures = [
        _figure_by_filename(figures, "outlet_flux_series__timeseries.png"),
        _figure_by_filename(figures, "mf6_disv_ref__budget_diagnostics.png"),
        _figure_by_filename(figures, "nwt_structured_120__budget_diagnostics.png"),
        _figure_by_filename(figures, "nwt_structured_180__budget_diagnostics.png"),
    ]
    audit_table = _render_table(
        _audit_issue_rows(audit),
        (
            ("level", "Niveau"),
            ("kind", "Type"),
            ("variant_id", "Variante"),
            ("field", "Champ"),
            ("fraction", "Fraction"),
            ("max_m", "Max m"),
            ("message", "Message"),
        ),
        empty="Aucun avertissement d'audit.",
        max_rows=14,
    )

    html_text = f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Nancon diagnostic initial MF6 DISV vs MODFLOW-NWT</title>
  <style>
    :root {{
      --bg: #f7f7f4;
      --ink: #1d2528;
      --muted: #667174;
      --panel: #ffffff;
      --line: #d7ddd7;
      --blue: #1f6b8f;
      --orange: #a55d2a;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--ink); font-family: Arial, Helvetica, sans-serif; line-height: 1.45; }}
    main {{ max-width: 1760px; margin: 0 auto; padding: 28px 24px 64px; }}
    header {{ border-bottom: 1px solid var(--line); padding: 18px 0 22px; margin-bottom: 22px; }}
    h1, h2, h3 {{ margin: 0; line-height: 1.15; }}
    h1 {{ font-size: 2.05rem; max-width: 980px; }}
    h2 {{ font-size: 1.25rem; margin-bottom: 12px; }}
    h3 {{ font-size: 0.95rem; color: var(--blue); }}
    p {{ margin: 8px 0 0; color: var(--muted); }}
    a {{ color: var(--blue); text-decoration-thickness: 1px; }}
    code {{ font-family: Consolas, "Courier New", monospace; font-size: 0.9em; color: var(--blue); }}
    .section {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 18px; margin-top: 18px; }}
    .comment-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }}
    .comment-card {{ border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #fbfcfb; min-width: 0; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
    th, td {{ text-align: left; padding: 7px 8px; border-bottom: 1px solid #e8ece8; }}
    th {{ color: var(--muted); font-weight: 600; white-space: nowrap; }}
    .fig-grid, .wide-fig-grid, .figure-deck {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }}
    .wide-fig-grid {{ margin-top: 12px; }}
    figure {{ margin: 0; border: 1px solid var(--line); border-radius: 8px; background: #fbfcfb; padding: 10px; }}
    img {{ width: 100%; display: block; border-radius: 6px; border: 1px solid #e2e7e2; background: white; }}
    figcaption {{ margin-top: 7px; color: var(--muted); font-size: 0.88rem; }}
    figcaption strong {{ display: block; color: var(--ink); font-size: 0.92rem; }}
    .callout {{ border-left: 4px solid var(--blue); padding: 10px 12px; background: #f2f6f7; color: var(--ink); margin-top: 12px; }}
    .warn {{ border-left-color: var(--orange); background: #fbf4ee; }}
    .pillrow {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }}
    .pill {{ border: 1px solid var(--line); border-radius: 999px; padding: 5px 9px; background: #fbfcfb; font-size: 0.86rem; }}
    .muted {{ color: var(--muted); }}
    @media (max-width: 980px) {{
      main {{ padding: 18px 14px 44px; }}
      .comment-grid, .fig-grid, .wide-fig-grid, .figure-deck {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
<main>
  <header>
    <h1>Nancon transitoire: diagnostic condition initiale et extraction des points</h1>
    <p>
      Variante voisine du pilote mensuel: meme recharge, memes parametres physiques, mais condition initiale
      top - 10 m et aucun premier pas steady. Les series ponctuelles utilisent l'extraction corrigee depuis
      le maillage reel stocke dans le Zarr.
    </p>
    <div class="pillrow">
      <span class="pill"><a href="index.html">Retour steady</a></span>
      <span class="pill"><a href="transient_results.html">Pilote transitoire</a></span>
      <span class="pill">Config: <code>{_safe_text(TRANSIENT_DIAGNOSTIC_CONFIG_PATH.relative_to(ROOT))}</code></span>
      <span class="pill">Audit: <code>{_safe_text(manifest.get("audit_status", ""))}</code></span>
    </div>
  </header>

  <section class="section">
    <h2>Configuration du diagnostic</h2>
    <p>
      Ce bloc fixe le protocole lu dans les fichiers TOML: meme forcage de recharge, meme physique,
      condition initiale explicite a 10 m sous le toit et aucun premier pas steady. Les variantes ne
      changent que le code et le support de maillage.
    </p>
    {overview_table}
    <h3 style="margin-top:16px;">Variantes, mailles et etat initial</h3>
    {config_table}
    <h3 style="margin-top:16px;">Recharge mensuelle imposee</h3>
    {recharge_table}
    <h3 style="margin-top:16px;">Execution</h3>
    {execution_table}
  </section>

  <section class="section">
    <h2>Conclusion du diagnostic</h2>
    <div class="comment-grid">
      <article class="comment-card">
        <h3>Recharge</h3>
        <p>La recharge reste equivalente entre les codes. Les ecarts max restent de l'ordre de 0.0065 m3/s, soit moins de 0.5%.</p>
      </article>
      <article class="comment-card">
        <h3>Charges ponctuelles</h3>
        <p>Apres correction de l'extraction, le cas sans firstpersteady rapproche fortement les points: les ecarts finaux sont metriques a quelques metres, pas plusieurs dizaines.</p>
      </article>
      <article class="comment-card">
        <h3>Difference restante</h3>
        <p>Les divergences residuelles portent surtout sur le drainage, le stockage et l'exutoire. Elles relevent du support de drainage et du maillage, pas d'une recharge differente.</p>
      </article>
    </div>
    <p class="callout warn">
      Le pilote precedent etait donc contamine par deux effets: un etat initial effectif different via firstpersteady,
      et une extraction ponctuelle NWT qui reutilisait le bundle DISV herite. Les cartes restent a lire, mais les
      anciennes series ponctuelles NWT ne doivent pas etre interpretees telles quelles.
    </p>
  </section>

  <section class="section">
    <h2>Charges aux points corriges</h2>
    <p>
      Les anomalies h(t)-h(t1) retirent l'offset initial local et comparent la dynamique. Elles confirment que
      le diagnostic sans firstpersteady donne une reponse beaucoup plus comparable aux points de controle.
    </p>
    {head_table}
    {_figure_grid([figure for figure in point_figures if figure], empty="Aucune serie de charge disponible.")}
  </section>

  <section class="section">
    <h2>Recharge, drainage et flux</h2>
    <p>
      La recharge appliquee reste pratiquement identique. Les ecarts de drainage et stockage restent les vrais
      indicateurs a travailler pour rapprocher MF6 DISV et NWT.
    </p>
    {budget_delta_table}
    {_figure_grid([figure for figure in flux_figures if figure], empty="Aucune figure de flux disponible.")}
  </section>

  <section class="section">
    <h2>Cartes comparables</h2>
    {_wide_figure_grid(complete_case_maps, empty="Aucune carte complete diagnostic disponible.")}
  </section>

  <section class="section">
    <h2>Reseau actif et metriques</h2>
    {overlap_table}
    {metrics_table}
  </section>

  <section class="section">
    <h2>Audit</h2>
    {audit_table}
  </section>

  <section class="section">
    <h2>Fichiers produits</h2>
    <div class="pillrow">
      <span class="pill"><code>{_safe_text(TRANSIENT_DIAGNOSTIC_COMPARISON_ROOT.relative_to(ROOT))}</code></span>
      <span class="pill"><code>timeseries_wide.csv</code></span>
      <span class="pill"><code>budget_timeseries_wide.csv</code></span>
      <span class="pill"><code>comparison_metrics.csv</code></span>
      <span class="pill"><code>web_figures/</code></span>
    </div>
  </section>
</main>
</body>
</html>
"""
    out = WEB_DIR / "transient_ic_diagnostic.html"
    out.write_text(html_text, encoding="utf-8")
    return out


def build_report() -> Path:
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    config = _load_toml(CONFIG_PATH)
    base = _load_toml(BASE_CONFIG_PATH)
    manifest = _load_json(COMPARISON_ROOT / "comparison_manifest.json")
    summary_metrics, active_overlap, execution_rows = _read_metric_rows()
    active_metrics_rows = _load_csv(COMPARISON_ROOT / "simulated_active_network_metrics.csv")
    cell_counts = _cell_counts_from_rows(active_metrics_rows)
    execution_rows = _enrich_execution_rows(execution_rows, manifest, cell_counts)
    timeseries_rows = _load_csv(COMPARISON_ROOT / "timeseries_wide.csv")
    budget_rows = _load_csv(COMPARISON_ROOT / "budget_timeseries_wide.csv")
    figures = _figure_artifacts(manifest)
    cfg_summary = _config_summary(base)
    transient_page = _build_transient_proposal_page(base, config)
    transient_results_page = _build_transient_results_page()
    transient_diagnostic_page = _build_transient_diagnostic_page()
    transient_results_pill = (
        f'<span class="pill"><a href="{_safe_text(transient_results_page.name)}">'
        "Resultats transitoires</a></span>"
        if transient_results_page is not None
        else ""
    )
    transient_diagnostic_pill = (
        f'<span class="pill"><a href="{_safe_text(transient_diagnostic_page.name)}">'
        "Diagnostic IC</a></span>"
        if transient_diagnostic_page is not None
        else ""
    )
    watershed_overlay = _load_watershed_overlay(config, manifest, base)
    mesh_geometries = _mesh_geometries_from_zarr(config, manifest)
    complete_case_maps = _generate_three_case_map_figures(
        config=config,
        manifest=manifest,
        cell_counts=cell_counts,
        overlay=watershed_overlay,
        mesh_geometries=mesh_geometries,
    )

    selected_runtime = _figures_by_keywords(figures, ("execution_time",), limit=2)
    mesh_runtime_figure = _write_mesh_runtime_figure(execution_rows)
    runtime_figures = (
        [mesh_runtime_figure] if mesh_runtime_figure is not None else []
    ) + selected_runtime
    case_configuration_figure = _figure_by_filename(figures, "case_configuration.png")

    interpretation_cards = _interpretation_cards(
        metrics=summary_metrics,
        active_overlap=active_overlap,
        execution_rows=execution_rows,
        timeseries_rows=timeseries_rows,
    )
    configuration_table = _config_detail_table(base, config)
    network_deck = _figure_deck(
        [
            (
                _figure_by_variant_name(
                    figures, "mf6_disv_ref", "simulated_active_network_reference_overlay"
                ),
                "MF6 DISV - overlay hydrographie",
                "Reference sur maillage contraint par les rivieres.",
            ),
            (
                _figure_by_variant_name(
                    figures, "nwt_structured_120", "simulated_active_network_reference_overlay"
                ),
                "NWT 120 x 120 - overlay hydrographie",
                "Premiere grille structuree candidate.",
            ),
            (
                _figure_by_variant_name(
                    figures, "nwt_structured_180", "simulated_active_network_reference_overlay"
                ),
                "NWT 180 x 180 - overlay hydrographie",
                "Grille plus fine, a confronter aux metriques.",
            ),
        ]
    )
    budget_deck = _figure_deck(
        [
            (
                _figure_by_filename(figures, "mf6_disv_ref__budget_diagnostics.png"),
                "Budget MF6 DISV",
                "Recharge, drainage et fermeture du bilan.",
            ),
            (
                _figure_by_filename(figures, "nwt_structured_120__budget_diagnostics.png"),
                "Budget NWT 120 x 120",
                "A comparer directement avec MF6.",
            ),
            (
                _figure_by_filename(figures, "nwt_structured_180__budget_diagnostics.png"),
                "Budget NWT 180 x 180",
                "Controle du bilan apres raffinement.",
            ),
        ]
    )

    metrics_table = _render_table(
        summary_metrics,
        (
            ("variant_id", "Variante"),
            ("observable", "Observable"),
            ("unit", "Unite"),
            ("n_pairs", "Paires"),
            ("bias", "Biais"),
            ("mae", "MAE"),
            ("rmse", "RMSE"),
            ("max_abs_error", "Max abs."),
        ),
        empty="Les metriques numeriques ne sont pas encore disponibles.",
        max_rows=18,
    )
    overlap_table = _render_table(
        active_overlap,
        (
            ("variant_id", "Variante"),
            ("network_role", "Reseau"),
            ("mode", "Mode"),
            ("active_cell_count", "Cellules actives"),
            ("network_coverage_ratio", "Coverage"),
            ("active_precision_ratio", "Precision"),
            ("cell_f1_ratio", "F1"),
            ("cell_jaccard_ratio", "Jaccard"),
        ),
        empty="Les metriques de recouvrement du reseau actif ne sont pas encore disponibles.",
        max_rows=12,
    )
    timeseries_table = _render_table(
        timeseries_rows,
        (
            ("observable", "Observable"),
            ("unit", "Unite"),
            ("value__mf6_disv_ref", "MF6 DISV"),
            ("value__nwt_structured_120", "NWT 120"),
            ("value__nwt_structured_180", "NWT 180"),
        ),
        empty="Les points de controle ne sont pas encore disponibles.",
        max_rows=12,
    )
    budget_table = _render_table(
        budget_rows,
        (
            ("component", "Composante"),
            ("unit", "Unite"),
            ("value__mf6_disv_ref", "MF6 DISV"),
            ("value__nwt_structured_120", "NWT 120"),
            ("value__nwt_structured_180", "NWT 180"),
        ),
        empty="Le bilan hydrologique n'est pas encore disponible.",
        max_rows=12,
    )
    execution_table = _render_table(
        execution_rows,
        (
            ("variant_id", "Variante"),
            ("solver", "Solver"),
            ("mesh_mode", "Maillage"),
            ("cell_count", "Mailles"),
            ("status", "Statut"),
            ("runtime_seconds", "Temps s"),
        ),
        empty="Les temps d'execution ne sont pas encore disponibles.",
        max_rows=12,
    )

    html_text = f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Nancon steady MF6 DISV vs MODFLOW-NWT</title>
  <style>
    :root {{
      --bg: #f7f7f4;
      --ink: #1d2528;
      --muted: #667174;
      --panel: #ffffff;
      --line: #d7ddd7;
      --blue: #1f6b8f;
      --green: #57785d;
      --orange: #a55d2a;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Arial, Helvetica, sans-serif;
      line-height: 1.45;
    }}
    main {{
      max-width: 1760px;
      margin: 0 auto;
      padding: 28px 24px 64px;
    }}
    header {{
      border-bottom: 1px solid var(--line);
      padding: 18px 0 22px;
      margin-bottom: 22px;
    }}
    h1, h2, h3 {{ margin: 0; line-height: 1.15; }}
    h1 {{ font-size: 2.1rem; max-width: 900px; }}
    h2 {{ font-size: 1.25rem; margin-bottom: 12px; }}
    h3 {{ font-size: 0.95rem; color: var(--blue); }}
    p {{ margin: 8px 0 0; color: var(--muted); }}
    a {{ color: var(--blue); text-decoration-thickness: 1px; }}
    code {{
      font-family: Consolas, "Courier New", monospace;
      font-size: 0.9em;
      color: var(--blue);
    }}
    .section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
      margin-top: 18px;
    }}
    .intro-grid {{
      display: grid;
      grid-template-columns: minmax(0, 1.1fr) minmax(320px, 0.9fr);
      gap: 16px;
      align-items: start;
    }}
    .facts, .variants, .comment-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }}
    .fact, .variant, .comment-card {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: #fbfcfb;
      min-width: 0;
    }}
    .fact span {{
      display: block;
      color: var(--muted);
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .fact strong {{
      display: block;
      margin-top: 4px;
      font-size: 1rem;
      overflow-wrap: anywhere;
    }}
    dl {{
      display: grid;
      grid-template-columns: 82px minmax(0, 1fr);
      gap: 5px 10px;
      margin: 10px 0 0;
      font-size: 0.9rem;
    }}
    dt {{ color: var(--muted); }}
    dd {{ margin: 0; min-width: 0; overflow-wrap: anywhere; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
    th, td {{ text-align: left; padding: 7px 8px; border-bottom: 1px solid #e8ece8; }}
    th {{ color: var(--muted); font-weight: 600; white-space: nowrap; }}
    .config-table td:first-child {{
      width: 170px;
      font-weight: 600;
      color: var(--blue);
    }}
    .fig-grid, .figure-deck {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }}
    .figure-deck {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
    .wide-fig-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
      margin: 14px 0 18px;
    }}
    .theme-panel {{
      border-top: 1px solid var(--line);
      padding-top: 16px;
      margin-top: 16px;
    }}
    .theme-panel:first-child {{
      border-top: 0;
      padding-top: 0;
      margin-top: 0;
    }}
    .theme-copy {{
      max-width: 980px;
      margin-bottom: 12px;
    }}
    .paired-figs {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }}
    figure {{
      margin: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfb;
      padding: 10px;
    }}
    img {{
      width: 100%;
      display: block;
      border-radius: 6px;
      border: 1px solid #e2e7e2;
      background: white;
    }}
    figcaption {{
      margin-top: 7px;
      color: var(--muted);
      font-size: 0.88rem;
    }}
    figcaption strong {{
      display: block;
      color: var(--ink);
      font-size: 0.92rem;
    }}
    figcaption span {{
      display: block;
      margin-top: 2px;
    }}
    .muted {{ color: var(--muted); }}
    .callout {{
      border-left: 4px solid var(--blue);
      padding: 10px 12px;
      background: #f2f6f7;
      color: var(--ink);
      margin-top: 12px;
    }}
    .pillrow {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 12px;
    }}
    .pill {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 5px 9px;
      background: #fbfcfb;
      font-size: 0.86rem;
    }}
    @media (max-width: 980px) {{
      .intro-grid, .facts, .variants, .comment-grid, .fig-grid, .figure-deck, .wide-fig-grid, .paired-figs {{ grid-template-columns: 1fr; }}
      main {{ padding: 18px 14px 44px; }}
    }}
  </style>
</head>
<body>
<main>
  <header>
    <h1>Nancon steady: MODFLOW 6 DISV river-constrained mesh vs MODFLOW-NWT structured grids</h1>
    <p>
      Comparaison operationnelle steady. La reference est MF6 sur le maillage triangulaire contraint par les rivieres;
      NWT est lance sur deux grilles structurees plus denses pour approximer le reseau et les zones de drainage.
    </p>
    <div class="pillrow">
      <span class="pill">Config: <code>{_safe_text(CONFIG_PATH.relative_to(ROOT))}</code></span>
      <span class="pill">Sorties: <code>{_safe_text(COMPARISON_ROOT.relative_to(ROOT))}</code></span>
      <span class="pill">Audit: <code>{_safe_text(manifest.get("audit_status", "pending"))}</code></span>
      <span class="pill"><a href="{_safe_text(transient_page.name)}">Proposition transitoire</a></span>
      {transient_results_pill}
      {transient_diagnostic_pill}
    </div>
  </header>

  <section class="section">
    <h2>Lecture rapide</h2>
    {interpretation_cards}
    <p class="callout">
      Interpretation provisoire: sur ce premier cas steady, le raffinement structure NWT accelere les runs mais
      ne reproduit pas encore correctement le comportement MF6 DISV sur les rivieres, les zones de suintement et
      le debit outlet. La prochaine etape utile est de tester des reglages de drainage/recharge et des grilles NWT
      plus ciblees autour des thalwegs.
    </p>
  </section>

  <section class="section">
    <h2>Configuration du cas</h2>
    <div class="intro-grid">
      <div>
        <div class="facts">
          <div class="fact"><span>Regime</span><strong>{_safe_text(cfg_summary["regime"])}</strong></div>
          <div class="fact"><span>K homogene</span><strong>{_safe_text(cfg_summary["k"])}</strong></div>
          <div class="fact"><span>Recharge</span><strong>{_format_float(cfg_summary["recharge_mm_year"])} mm/an</strong></div>
          <div class="fact"><span>Drainage top</span><strong>{_safe_text(cfg_summary["drain"])}</strong></div>
          <div class="fact"><span>Sy</span><strong>{_safe_text(cfg_summary["sy"])}</strong></div>
          <div class="fact"><span>Ss</span><strong>{_safe_text(cfg_summary["ss"])}</strong></div>
          <div class="fact"><span>Hydrographie</span><strong>BD TOPAGE</strong></div>
          <div class="fact"><span>Raster commun</span><strong>250 m</strong></div>
        </div>
        <p>
          Les parametres physiques sont partages par les trois simulations. La difference portee par cette page
          est principalement numerique et geometrique: DISV contraint par les rivieres pour MF6, grilles structurees
          120 x 120 et 180 x 180 pour NWT.
        </p>
      </div>
      {_render_figure(case_configuration_figure, title="Schema du cas et des variantes", note="Figure issue du workflow de comparaison.")}
    </div>
    {configuration_table}
  </section>

  <section class="section">
    <h2>Variantes executees</h2>
    <div class="variants">
      {_variant_cards(manifest, config, cell_counts)}
    </div>
  </section>

  <section class="section">
    <h2>Temps de calcul</h2>
    <p>
      Les temps incluent l'execution de chaque simulation enfant dans le workflow de comparaison. Ils ne doivent pas
      etre lus seuls: NWT est plus rapide ici, mais les sections suivantes montrent que le reseau et les debits restent
      tres differents de la reference MF6.
    </p>
    {execution_table}
    {_figure_grid(runtime_figures, empty="Aucune figure de temps de calcul disponible.")}
  </section>

  <section class="section">
    <h2>Charges et debits aux points de controle</h2>
    <p>
      Ces valeurs sont les plus directes a lire. Elles donnent une premiere mesure de l'ecart avant d'aller regarder
      les cartes. Le debit outlet est un debit de drainage/baseflow extrait du modele, pas une comparaison a un debit
      observe complet avec ruissellement.
    </p>
    {timeseries_table}
  </section>

  <section class="section">
    <h2>Metriques scalaires et points de controle</h2>
    <p>
      Les metriques de carte cellule-a-cellule sont utiles comme diagnostic brut, mais les cartes sur maillages
      differents doivent etre lues en priorite via les triptyques rasterises ci-dessous.
    </p>
    {metrics_table}
  </section>

  <section class="section">
    <h2>Cartes comparables par variable</h2>
    <p>
      Chaque planche affiche les trois cas dans le meme sens et dans le meme cadre: nord en haut,
      limites communes, contour du bassin versant en noir et exutoire en etoile rouge. Les panneaux
      restent sur leur support spatial complet, avec une echelle de couleur commune par variable. Les
      aretes de cellules sont superposees pour le maillage DISV et pour les grilles regulieres NWT.
    </p>
    <p class="callout">
      Le nombre de mailles est indique dans le titre de chaque panneau. Cette disposition remplace les
      comparaisons empilees: elle permet de lire directement MF6 DISV, NWT 120 x 120 et NWT 180 x 180
      cote a cote pour chaque variable.
    </p>
    {_wide_figure_grid(complete_case_maps, empty="Les cartes completes par cas ne sont pas encore disponibles.")}
  </section>

  <section class="section">
    <h2>Bilan hydrologique</h2>
    <p>
      Le bilan verifie que les differences de cartes ne viennent pas simplement d'un run non ferme. Ici, les recharges
      et drainages totaux restent proches, alors que la repartition spatiale et le debit outlet divergent.
    </p>
    {budget_table}
    {budget_deck}
  </section>

  <section class="section">
    <h2>Reseau actif simule</h2>
    <p>
      Cette section compare le reseau simule au reseau hydrographique de reference. Une couverture elevee signifie que
      les cellules du reseau de reference sont retrouvees; une precision faible signifie que beaucoup de cellules actives
      sont hors du reseau attendu.
    </p>
    {overlap_table}
    {network_deck}
  </section>

  <section class="section">
    <h2>Fichiers produits</h2>
    <div class="pillrow">
      <span class="pill"><code>comparison_report.md</code></span>
      <span class="pill"><code>comparison_metrics.csv</code></span>
      <span class="pill"><code>comparison_differences.csv</code></span>
      <span class="pill"><code>execution_times.csv</code></span>
      <span class="pill"><code>simulated_active_network_overlap_metrics.csv</code></span>
      <span class="pill"><code>comparison_figures/</code></span>
      <span class="pill"><code>{_safe_text(transient_page.name)}</code></span>
      {f'<span class="pill"><code>{_safe_text(transient_results_page.name)}</code></span>' if transient_results_page is not None else ""}
      {f'<span class="pill"><code>{_safe_text(transient_diagnostic_page.name)}</code></span>' if transient_diagnostic_page is not None else ''}
    </div>
  </section>
</main>
</body>
</html>
"""
    out = WEB_DIR / "index.html"
    out.write_text(html_text, encoding="utf-8")
    return out


def main() -> int:
    path = build_report()
    print(path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
