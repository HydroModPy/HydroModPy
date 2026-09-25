"""Declarative block specifications for generic catchment reports."""

from __future__ import annotations

from dataclasses import dataclass, field

from hydromodpy.display.report_blocks import DetailLevel


@dataclass(frozen=True)
class BlockFigureSpec:
    """Where one PNG goes in a report block, and from which detail level.

    Not the ``FigureSpec`` of a registered figure (``hydromodpy.display.figure``).
    """

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
    figures: tuple[BlockFigureSpec, ...] = field(default_factory=tuple)


DEFAULT_BLOCK_SPECS: tuple[ReportBlockSpec, ...] = (
    ReportBlockSpec(
        block_id="site_context",
        title="Site",
        content_key="site_context",
        lead="Bloc d'identification du bassin versant et des donnees disponibles.",
        figures=(
            BlockFigureSpec("compact", "identity_stats", "Carte d'identite"),
            BlockFigureSpec("standard", "station_inventory", "Inventaire stations"),
        ),
    ),
    ReportBlockSpec(
        block_id="hydraulic_properties",
        title="Proprietes hydrauliques",
        content_key="hydraulic_properties",
        lead="Parametres hydrauliques utilises par la simulation de reference.",
    ),
    ReportBlockSpec(
        block_id="spatial_context",
        title="Contexte spatial: DEM et geologie",
        content_key="spatial_context",
        lead="Support physique du bassin: situation regionale, relief et geologie.",
        figures=(
            BlockFigureSpec("compact", "regional_context", "Contexte regional"),
            BlockFigureSpec("compact", "dem_context", "DEM, bassin versant et exutoire"),
            BlockFigureSpec("standard", "geology_map", "Geologie du bassin"),
        ),
    ),
    ReportBlockSpec(
        block_id="hydrographic_network",
        title="Reseau hydrographique observe et genere",
        content_key="hydrographic_network",
        lead=(
            "Hydrographie de reference, reseau derive du DEM et differences locales. "
            "Le seuil d'aire contributive est celui de la simulation source."
        ),
        figures=(
            BlockFigureSpec("compact", "hydrography_map", "Reseau hydrographique de reference"),
            BlockFigureSpec("standard", "network_generated", "Reseau genere DEM", required=False),
            BlockFigureSpec("audit", "network_comparison", "Comparaison reference / reseau DEM"),
            BlockFigureSpec(
                "audit",
                "network_missing",
                "Segments reference absents du genere",
                required=False,
            ),
            BlockFigureSpec(
                "audit", "network_extra", "Segments generes hors reference", required=False
            ),
        ),
    ),
    ReportBlockSpec(
        block_id="simulation_network_outputs",
        title="Simulation reseau actif et seepage",
        content_key="simulation_network_outputs",
        lead=(
            "Resultats spatiaux de simulation: reseau actif, comparaison au reseau "
            "de reference et zones de seepage quand la figure est disponible."
        ),
        figures=(
            BlockFigureSpec(
                "standard", "active_network_overlay", "Reseau actif simule vs reference"
            ),
            BlockFigureSpec("compact", "seepage_map", "Carte seepage simule", required=False),
        ),
    ),
    ReportBlockSpec(
        block_id="forcing_flux_context",
        title="Flux, debit observe et forcages",
        content_key="forcing_flux_context",
        lead=(
            "Debit observe, debit simule de reference et contexte climatique "
            "associe a la fenetre de simulation."
        ),
        figures=(
            BlockFigureSpec(
                "compact", "forcing_window", "Fenetre de simulation: debit observe et simule"
            ),
            BlockFigureSpec("audit", "observed_discharge_full", "Debit observe complet"),
            BlockFigureSpec("audit", "climate_summary", "Climatologie mensuelle"),
        ),
    ),
    ReportBlockSpec(
        block_id="simulation_outputs",
        title="Simulation flux",
        content_key="simulation_outputs",
        lead="Hydrographe, carte de charge et bilan en eau de la simulation de reference.",
        figures=(
            BlockFigureSpec(
                "compact", "baseline_discharge_comparison", "Debits observes vs simules"
            ),
            BlockFigureSpec("standard", "simulated_hydrograph", "Hydrographe simule"),
            BlockFigureSpec("audit", "piezometric_map", "Carte de charge"),
            BlockFigureSpec("audit", "water_budget", "Bilan en eau du bassin"),
        ),
    ),
    ReportBlockSpec(
        block_id="artifacts",
        title="Artefacts et limites",
        content_key="artifacts",
        minimum_level="audit",
        lead=(
            "Chemins sources, manifeste et limites du rapport. Cette page agrege "
            "les artefacts produits par les etapes overview, contexte et simulation."
        ),
    ),
)


__all__ = [
    "BlockFigureSpec",
    "DEFAULT_BLOCK_SPECS",
    "ReportBlockSpec",
]
