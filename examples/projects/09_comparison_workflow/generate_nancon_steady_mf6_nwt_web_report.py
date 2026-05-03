"""Build a browser-readable report for the Nancon steady MF6/NWT comparison."""

from __future__ import annotations

import csv
import html
import json
import math
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
COMPARISON_ROOT = ROOT / "outputs" / "nancon_steady_mf6_disv_vs_nwt"
WEB_DIR = COMPARISON_ROOT / "web"
WEB_FIGURES_DIR = COMPARISON_ROOT / "web_figures"


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


def _rel(path: str | Path) -> str:
    try:
        return Path(path).resolve().relative_to(WEB_DIR.resolve()).as_posix()
    except Exception:
        try:
            return Path(path).resolve().relative_to(COMPARISON_ROOT.resolve()).as_posix()
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
            return ("../" + target.relative_to(COMPARISON_ROOT.resolve()).as_posix())
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
    by_id = {
        str(item.get("id", "")): item
        for item in variants
        if isinstance(item, dict)
    }
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
        return f"<p class=\"muted\">{html.escape(empty)}</p>"
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
        "<div class=\"table-wrap\"><table><thead><tr>"
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
    return "\n".join(cards) or "<p class=\"muted\">Aucune variante disponible.</p>"


def _figure_grid(figures: list[dict[str, Any]], *, empty: str) -> str:
    if not figures:
        return f"<p class=\"muted\">{html.escape(empty)}</p>"
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
    return "<div class=\"fig-grid\">" + "\n".join(items) + "</div>"


def _figure_by_filename(figures: list[dict[str, Any]], filename: str) -> dict[str, Any] | None:
    for figure in figures:
        if Path(str(figure.get("path", ""))).name == filename:
            return figure
    return None


def _figure_by_variant_name(
    figures: list[dict[str, Any]], variant_id: str, figure_name: str
) -> dict[str, Any] | None:
    for figure in figures:
        if (
            figure.get("variant_id") == variant_id
            and figure.get("figure_name") == figure_name
        ):
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
            "<figure class=\"missing-figure\">"
            f"<figcaption>{html.escape(title)}</figcaption>"
            "<p class=\"muted\">Figure non disponible.</p>"
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
        "<div class=\"figure-deck\">"
        + "\n".join(
            _render_figure(figure, title=title, note=note)
            for figure, title, note in items
        )
        + "</div>"
    )


def _wide_figure_grid(figures: list[dict[str, Any]], *, empty: str) -> str:
    if not figures:
        return f"<p class=\"muted\">{html.escape(empty)}</p>"
    return (
        "<div class=\"wide-fig-grid\">"
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


def _metric_value(
    rows: list[dict[str, str]], variant_id: str, observable: str, field: str
) -> str:
    for row in rows:
        if row.get("variant_id") == variant_id and row.get("observable") == observable:
            return _format_float(row.get(field))
    return ""


def _wide_value(
    rows: list[dict[str, str]], observable: str, variant_id: str
) -> str:
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
            simulation.get("overlay", {})
            .get("modflownwt", {})
            .get("sgrid", {})
            .get("planar", {})
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
        "<div class=\"table-wrap\"><table class=\"config-table\">"
        "<thead><tr><th>Element</th><th>Configuration</th><th>Commentaire</th></tr></thead>"
        f"<tbody>{body}</tbody></table></div>"
    )


def _method_comparison_cfg_from_manifest(
    config: dict[str, Any], manifest: dict[str, Any]
) -> Any | None:
    try:
        from hydromodpy.analysis.comparison.config import (
            MethodComparisonConfig,
            MethodComparisonSection,
            MethodComparisonVariant,
        )
    except Exception:
        return None

    comparison = config.get("comparison", {})
    variants: list[Any] = []
    for item in manifest.get("variants", []):
        if not isinstance(item, dict) or not item.get("enabled", True):
            continue
        variants.append(
            MethodComparisonVariant(
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
        section = MethodComparisonSection(
            comparison_id=str(comparison.get("comparison_id", "")),
            base_simulation_config=str(BASE_CONFIG_PATH),
            output_root=str(COMPARISON_ROOT),
            run_variants=False,
            continue_on_error=bool(comparison.get("continue_on_error", False)),
            reference_variant=comparison.get("reference_simulation"),
            fine_raster=comparison.get("fine_raster"),
            variant=variants,
            observable=comparison.get("observable", []),
        )
        return MethodComparisonConfig(
            config_path=CONFIG_PATH.resolve(),
            base_dir=ROOT.resolve(),
            comparison_root=COMPARISON_ROOT.resolve(),
            base_simulation_config_path=BASE_CONFIG_PATH.resolve(),
            anchors_path=None,
            anchors={},
            method_comparison=section,
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
) -> bool:
    try:
        import numpy as np
        from hydromodpy.analysis.comparison.visuals import (
            _finite_limits,
            _pretty_label,
            _robust_limits,
        )
        import matplotlib.pyplot as plt
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
) -> list[dict[str, Any]]:
    try:
        from hydromodpy.analysis.comparison.visuals import _build_map_payload, _slug
    except Exception:
        return []

    method_cfg = _method_comparison_cfg_from_manifest(config, manifest)
    if method_cfg is None:
        return []
    summaries = {
        str(item.get("id", "")): item
        for item in manifest.get("variants", [])
        if isinstance(item, dict) and item.get("status") in {"completed", "reused"}
    }
    WEB_FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    variants = [variant for variant in method_cfg.method_comparison.variant if variant.enabled]
    artifacts: list[dict[str, Any]] = []
    for observable in method_cfg.method_comparison.observable:
        if observable.support != "map":
            continue
        payloads: list[Any] = []
        for variant in variants:
            summary = summaries.get(variant.id)
            if summary is None:
                continue
            try:
                payload = _build_map_payload(
                    cfg=method_cfg,
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
        path = WEB_FIGURES_DIR / f"{_slug(observable.name)}__three_cases_complete.png"
        if _write_three_case_map_figure(
            path=path,
            observable_name=observable.name,
            payloads=payloads,
            cell_counts=cell_counts,
            overlay=overlay,
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
        candidates.extend(sorted(sim_dir.glob("*.zarr.zip"), key=lambda p: p.stat().st_mtime, reverse=True))
        candidates.extend(sorted(sim_dir.glob("*.zarr"), key=lambda p: p.stat().st_mtime, reverse=True))

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
            pad = max(float(np.nanmax(xv) - np.nanmin(xv)), float(np.nanmax(yv) - np.nanmin(yv))) * 0.035
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
                "outlet": (outlet_x, outlet_y) if outlet_x is not None and outlet_y is not None else None,
            }
        finally:
            if store is not None:
                try:
                    store.close()
                except Exception:
                    pass
    return None


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
) -> Any:
    import numpy as np
    from hydromodpy.analysis.comparison.visuals import _render_map_subplot

    values = _mask_values(payload.values).ravel()
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


def _write_mesh_runtime_figure(rows: list[dict[str, str]]) -> dict[str, Any] | None:
    try:
        import numpy as np
        import matplotlib.pyplot as plt
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
    f1 = {
        row.get("variant_id"): _format_float(row.get("cell_f1_ratio"))
        for row in active_overlap
    }

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
        "<div class=\"comment-grid\">"
        + "\n".join(
            f"<article class=\"comment-card\"><h3>{_safe_text(title)}</h3><p>{_safe_text(text)}</p></article>"
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
    watershed_overlay = _load_watershed_overlay(config, manifest, base)
    complete_case_maps = _generate_three_case_map_figures(
        config=config,
        manifest=manifest,
        cell_counts=cell_counts,
        overlay=watershed_overlay,
    )

    selected_network = _figures_by_keywords(
        figures,
        ("simulated_active", "active_network", "reference_overlay"),
        limit=8,
    )
    selected_runtime = _figures_by_keywords(figures, ("execution_time",), limit=2)
    mesh_runtime_figure = _write_mesh_runtime_figure(execution_rows)
    runtime_figures = (
        ([mesh_runtime_figure] if mesh_runtime_figure is not None else []) + selected_runtime
    )
    case_configuration_figure = _figure_by_filename(figures, "case_configuration.png")

    interpretation_cards = _interpretation_cards(
        metrics=summary_metrics,
        active_overlap=active_overlap,
        execution_rows=execution_rows,
        timeseries_rows=timeseries_rows,
    )
    configuration_table = _config_detail_table(base, config)
    map_theme_panels = "\n".join(
        [
            _theme_panel(
                figures,
                observable="head_map_last",
                title="Charge hydraulique",
                reading=(
                    "Comparer d'abord le raster commun: il neutralise une partie de l'effet de support. "
                    "Le diagnostic brut sur maillages natifs reste utile pour reperer ou les ecarts se forment."
                ),
            ),
            _theme_panel(
                figures,
                observable="watertable_depth_map_last",
                title="Profondeur de nappe",
                reading=(
                    "Cette carte montre si les ecarts de charge se traduisent en zones trop humides ou trop profondes. "
                    "Elle est plus directement interpretable pour les zones de suintement."
                ),
            ),
            _theme_panel(
                figures,
                observable="seepage_map_last",
                title="Zones de suintement",
                reading=(
                    "La variable est binaire ou quasi binaire; de petits decalages geometriques peuvent produire "
                    "des erreurs fortes. Le cote a cote raster commun / maillage natif aide a distinguer effet numerique et effet support."
                ),
            ),
            _theme_panel(
                figures,
                observable="outflow_drain_map_last",
                title="Drainage distribue",
                reading=(
                    "Ce panneau localise les sorties vers la condition de drainage. Les differences expliquent en partie "
                    "les debits d'exutoire tres differents entre MF6 et NWT."
                ),
            ),
            _theme_panel(
                figures,
                observable="active_network_flux_map_last",
                title="Flux accumule et reseau actif",
                reading=(
                    "Le flux accumule est une lecture operationnelle du reseau simule. C'est le meilleur panneau pour "
                    "discuter la continuite des rivieres obtenues."
                ),
            ),
        ]
    )
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
      restent sur leur support spatial complet, avec une echelle de couleur commune par variable.
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
