"""Declarative block specifications for catchment reports."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from hydromodpy.display.report_blocks import DetailLevel


@dataclass(frozen=True)
class FigureSpec:
    minimum_level: DetailLevel
    figure_id: str
    title: str
    required: bool = True


@dataclass(frozen=True)
class ReportBlockSpec:
    block_id: str
    title: str
    lead: str
    content_key: str
    minimum_level: DetailLevel = "compact"
    figures: tuple[FigureSpec, ...] = field(default_factory=tuple)


NANCON_BLOCK_SPECS: tuple[ReportBlockSpec, ...] = (
    ReportBlockSpec(
        block_id="site_context",
        title="Site",
        content_key="site_context",
        lead=(
            "Bloc d'identification du bassin jauge. Les figures viennent des sorties "
            "data-overview et non du smoke test synthetique."
        ),
        figures=(
            FigureSpec("compact", "identity_stats", "Carte d'identite observations"),
            FigureSpec("standard", "station_inventory", "Inventaire stations"),
        ),
    ),
    ReportBlockSpec(
        block_id="hydraulic_properties",
        title="Propriétés hydrauliques",
        content_key="hydraulic_properties",
        lead="Bloc generique des proprietes hydrauliques utilisees par le run de reference.",
    ),
    ReportBlockSpec(
        block_id="spatial_context",
        title="Contexte spatial: DEM et geologie",
        content_key="spatial_context",
        lead=(
            "Bloc de lecture du support physique avant simulation: relief, contours "
            "du bassin et informations geologiques disponibles."
        ),
        figures=(
            FigureSpec("compact", "regional_context", "Situation dans le Massif Armoricain"),
            FigureSpec("compact", "dem_context", "DEM, bassin versant et exutoire"),
            FigureSpec("standard", "geology_map", "Geologie du bassin"),
        ),
    ),
    ReportBlockSpec(
        block_id="hydrographic_network",
        title="Reseau hydrographique observe et genere",
        content_key="hydrographic_network",
        lead=(
            "Bloc central pour la future calibration naturelle: hydrographie de "
            "reference BD Topage, reseau genere depuis le DEM et differences locales. "
            "Le reseau DEM utilise ici un seuil d'aire contributive de 0.5 km2."
        ),
        figures=(
            FigureSpec("compact", "hydrography_map", "Reseau hydrographique BD Topage"),
            FigureSpec("standard", "network_generated", "Reseau genere DEM", required=False),
            FigureSpec("audit", "network_comparison", "Comparaison BD Topage / reseau derive DEM"),
            FigureSpec(
                "audit",
                "network_missing",
                "Segments reference absents du genere",
                required=False,
            ),
            FigureSpec("audit", "network_extra", "Segments generes hors reference", required=False),
        ),
    ),
    ReportBlockSpec(
        block_id="simulation_network_outputs",
        title="Simulation reseau actif et seepage",
        content_key="simulation_network_outputs",
        lead=(
            "Bloc dependant des resultats de simulation: cellules actives, comparaison "
            "au reseau BD Topage et zones de seepage quand la figure est disponible."
        ),
        figures=(
            FigureSpec("standard", "active_network_overlay", "Reseau actif simule vs reference"),
            FigureSpec("compact", "seepage_map", "Carte seepage simule", required=False),
        ),
    ),
    ReportBlockSpec(
        block_id="forcing_flux_context",
        title="Flux, debit observe et forcages",
        content_key="forcing_flux_context",
        lead=(
            "Bloc flux disponible avant tout lancement de modele: debit observe, "
            "recharge, runoff et contexte climatique."
        ),
        figures=(
            FigureSpec("compact", "forcing_window", "Fenetre 2000-2002: debit et forcages"),
            FigureSpec("audit", "observed_discharge_full", "Debit observe complet"),
            FigureSpec("audit", "climate_summary", "Monthly climatology"),
        ),
    ),
    ReportBlockSpec(
        block_id="simulation_outputs",
        title="Simulation flux",
        content_key="simulation_outputs",
        lead=(
            "Bloc de simulation des flux: comparaison des debits, hydrographes, "
            "carte de charge et bilan en eau du run transitoire de reference."
        ),
        figures=(
            FigureSpec("compact", "baseline_discharge_comparison", "Debits observes vs simules"),
            FigureSpec("standard", "simulated_hydrograph", "Rapport des hydrographes"),
            FigureSpec("audit", "piezometric_map", "Carte de charge"),
            FigureSpec("audit", "water_budget", "Bilan en eau du bassin"),
        ),
    ),
    ReportBlockSpec(
        block_id="artifacts",
        title="Artefacts et limites",
        content_key="artifacts",
        minimum_level="audit",
        lead=(
            "Bloc audit: chemins sources et limites de cette page. Le rapport prouve "
            "que la superstructure par blocs peut porter des figures {site_label} reelles; "
            "il ne ferme pas encore la calibration naturelle complete."
        ),
    ),
)


def _with_figure_titles(
    spec: ReportBlockSpec,
    titles_by_id: dict[str, str],
) -> ReportBlockSpec:
    return replace(
        spec,
        figures=tuple(
            replace(figure, title=titles_by_id.get(figure.figure_id, figure.title))
            for figure in spec.figures
        ),
    )


def _generic_block_spec(spec: ReportBlockSpec) -> ReportBlockSpec:
    if spec.block_id == "site_context":
        return replace(
            spec,
            lead=(
                "Bloc d'identification du bassin versant et des donnees disponibles "
                "pour le rapport."
            ),
        )
    if spec.block_id == "spatial_context":
        return _with_figure_titles(
            spec,
            {"regional_context": "Contexte regional"},
        )
    if spec.block_id == "hydrographic_network":
        return replace(
            _with_figure_titles(
                spec,
                {
                    "hydrography_map": "Reseau hydrographique de reference",
                    "network_comparison": "Comparaison reference / reseau derive DEM",
                },
            ),
            lead=(
                "Bloc central pour la lecture hydrographique: hydrographie de "
                "reference, reseau genere depuis le DEM et differences locales. "
                "Le seuil d'aire contributive est celui de la simulation source."
            ),
        )
    if spec.block_id == "simulation_network_outputs":
        return replace(
            _with_figure_titles(
                spec,
                {"active_network_overlay": "Reseau actif simule vs reference"},
            ),
            lead=(
                "Bloc dependant des resultats de simulation: cellules actives, "
                "comparaison au reseau de reference et zones de seepage quand la "
                "figure est disponible."
            ),
        )
    if spec.block_id == "forcing_flux_context":
        return _with_figure_titles(
            spec,
            {"forcing_window": "Fenetre de simulation: debit et forcages"},
        )
    if spec.block_id == "artifacts":
        return replace(
            spec,
            lead=(
                "Bloc audit: chemins sources et limites de cette page. Le rapport "
                "prouve que la superstructure par blocs peut porter des figures "
                "{site_label} reelles; il ne constitue pas un audit exhaustif du "
                "modele."
            ),
        )
    return spec


DEFAULT_BLOCK_SPECS: tuple[ReportBlockSpec, ...] = tuple(
    _generic_block_spec(spec) for spec in NANCON_BLOCK_SPECS
)

GENERIC_BLOCK_SPECS = DEFAULT_BLOCK_SPECS


__all__ = [
    "FigureSpec",
    "DEFAULT_BLOCK_SPECS",
    "GENERIC_BLOCK_SPECS",
    "NANCON_BLOCK_SPECS",
    "ReportBlockSpec",
]
