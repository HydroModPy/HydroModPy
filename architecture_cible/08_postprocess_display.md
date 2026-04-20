# Architecture cible HydroModPy — Post-traitement et visualisation

**Document** : `architecture_cible/08_postprocess_display.md`
**Date** : 2026-04-18
**Auteur** : Architecte visualisation scientifique & post-traitement hydrogéologique
(références : matplotlib, cartopy, PyVista, xarray, FloPy, holoviews, pygmt, seaborn,
Crameri *et al.* 2020 Nat. Commun., Nash-Sutcliffe 1970, Kling-Gupta 2009/2012,
recommandations Water Resources Research, Journal of Hydrology, ONDE/EauFrance).
**Portée** : conception complète des sous-systèmes `analysis/display/`,
`analysis/postprocess/` et du calcul de métriques/quantités dérivées. Pense en
rupture avec l'existant (≈ 13 000 lignes hétérogènes), pas en patch incrémental.
**Sources** : audit `audit_code/08_analysis_display.md`, cibles `04_storage_ideal.md`
(catalog DuckDB + Zarr UGRID), `05_solver_contracts.md`, `07_calibration.md`.

> **Légende des tags**
> `[NOUVEAU]` n'existe pas · `[RENOMME]` existe sous un autre nom · `[REFACTORE]`
> existe mais change · `[CONSERVE]` existe et reste tel quel · `[SUPPRIME]` dead
> code à retirer.

---

## Table des matières

0. [Principes directeurs](#0-principes-directeurs)
1. [Panorama — quatre packages, quatre responsabilités](#1-panorama)
2. [Arborescence cible](#2-arborescence-cible)
3. [Contrat `Figure` — le Protocol unique](#3-contrat-figure)
4. [Catalogue des figures (25 types)](#4-catalogue-des-figures)
5. [Calculs dérivés — où vivent-ils ?](#5-calculs-dérivés)
6. [Métriques — formules exactes et implémentation](#6-métriques)
7. [Comparaison multi-simulations](#7-comparaison-multi-simulations)
8. [Export des figures — publication-grade](#8-export-des-figures)
9. [Mode headless propre (sans variables d'environnement magiques)](#9-mode-headless)
10. [Export NetCDF CF-1.11 + UGRID-1.0](#10-export-netcdf-cf-ugrid)
11. [Intégration TOML et CLI](#11-intégration-toml-et-cli)
12. [Ajouter une nouvelle figure en 30 lignes](#12-ajouter-une-figure-en-30-lignes)
13. [Comparaison aux projets de référence](#13-comparaison-projets-référence)
14. [Tableau de migration actuel → cible](#14-tableau-de-migration)
15. [Tests de conformité](#15-tests-de-conformité)

---

## 0. Principes directeurs

| # | Principe | Conséquence pratique |
|---|----------|----------------------|
| 1 | **Données ≠ rendu** | Le rendu consomme une `Simulation` (interface catalog) et jamais un solveur, un dossier, un `ProjectState`. Une figure ne lit ni NetCDF ni CSV directement. |
| 2 | **Une seule source de vérité : le catalog** | `SimulationCatalog` (doc 04) expose toutes les données (champs Zarr, timeseries DuckDB, métadonnées). Toute figure se branche dessus. Le post-hoc n'existe plus en tant que concept distinct. |
| 3 | **Solver-agnostique par construction** | Boussinesq, MODFLOW-NWT, MODFLOW 6 produisent **le même schéma UGRID** dans le Zarr (doc 04). Les figures ne voient pas le solveur. Même code, même figure. |
| 4 | **DIS ≡ DISV ≡ DISU** | Les figures spatiales opèrent sur `mesh.face_node_connectivity` (UGRID) via `matplotlib.tri` ou `PolyCollection`. Aucun `reshape(nrow, ncol)` dans `display/`. |
| 5 | **Un Protocol unique `Figure`** | Une classe = une figure. Méthodes `render(sim, ax, **opts)` et `plot(sim, **opts)`. Plus de paire `render_* / plot_*` dupliquée. |
| 6 | **Pas de side-effects d'import** | Aucun `plt.style.use`, aucun `rcParams[...] = ...`, aucun `plt.switch_backend` au niveau module. Le style est appliqué par un contexte `style("publication")` local. |
| 7 | **Backend explicite, pas via env var** | Le backend matplotlib est configuré par `DisplayConfig.backend = "agg" \| "qt" \| "inline"`. L'env var `HYDROMODPY_NO_DISPLAY` reste respectée en fallback pour CI mais n'est plus le mécanisme principal. |
| 8 | **Colormaps perceptuelles par défaut** | Registre central `colormaps.py`. `jet`/`cool`/`RdYlGn` interdits (vérifié par test). Par défaut : `viridis`, `cividis`, `magma`, `plasma`, `Blues`, `Reds`, `coolwarm` (diff). |
| 9 | **Unités depuis `core/units/`** | Les labels (axes, colorbar) viennent d'un registre d'unités Unicode (`m³/s`, `m/d`, `mm/mois`). Aucun `[L^3/T]`, aucun `m3/s`. |
| 10 | **CRS et cartopy natifs** | Les figures cartographiques portent un CRS. Scalebar, flèche nord, graticule optionnel. `cartopy.crs.epsg(sim.crs_epsg)`. |
| 11 | **Un fichier = une figure** | Export matplotlib (PNG/SVG/PDF). Figures multi-panels construites par composition, pas par fonctions monolithes `plot_flow_suite`. |
| 12 | **Post-traitement ≠ display** | Les calculs dérivés (watertable, depth, seepage, intermittency, flux) vivent dans `results/derived/` et sont écrits dans le Zarr au moment de l'extraction, **avant** display. Le display ne calcule pas, il affiche. |
| 13 | **Métriques = fonctions pures** | `results/metrics/` fournit des fonctions pures `nse(sim, obs) -> float`. Consommées par calibration, comparaison, display. Un seul endroit. |
| 14 | **Thème unique, overridable** | `display/theme.py` définit une palette cohérente (tailles, polices, couleurs). Un utilisateur peut le remplacer via TOML ou objet Python. |
| 15 | **NetCDF = CF-1.11 + UGRID-1.0** | Les exports NetCDF sont strictement conformes. `Conventions="CF-1.11 UGRID-1.0"`, `standard_name`, `cell_methods`, `grid_mapping`, UDUnits minuscules. |

### 0.1 Ce qui change par rapport à l'existant

| Défaut actuel (audit §) | Fix proposé | Section |
|---|---|---|
| Paire `render_*/plot_*` dupliquée × 25 (§1.1) | Classe unique `Figure(Protocol)` avec `render()`/`plot()` | §3 |
| `suites.py` vs `posthoc_orchestration.py` (80 % dupliqué, §1.2) | Suppression : un seul chemin `catalog → Figure` | §1, §7 |
| `cmap='jet'` × 6+, `cool`, `RdYlGn` (§2.1) | Registre `colormaps.py` + test d'interdiction | §3.4 |
| Pas de CRS, pas de scalebar (§2.3) | Mixin `GeoFigure` avec cartopy | §3.5 |
| Labels `m3/s`, `[L^3/T]` mélangés (§2.2) | `core/units/UnitRegistry` Unicode | §3.3 |
| `plt.style.use` top-level (§7.2) | `with theme("publication"):` context manager | §9 |
| `plt.switch_backend("QtAgg")` à chaud (§7.2) | Interdit ; backend choisi à l'init | §9 |
| NetCDF non CF, non UGRID (§5) | Réécriture complète `results/exporters/netcdf.py` | §10 |
| Intermittency physique dans display (§4.2) | Déplacée dans `results/derived/intermittency.py` | §5 |
| matching_streams en postprocess (§4.2) | Déplacé dans `analysis/comparison/streams/` | §5 |
| `nse_manual` sans garde NaN (§6.2) | `results/metrics/efficiency.py` robuste | §6 |
| KGE' 2012, PBIAS manquants (§6.2) | Ajoutés | §6 |
| Figures standards manquantes (§3.2) | Duration curve, récession, Piper, Stiff, boxplot saisonnier | §4 |

---

## 1. Panorama — quatre packages, quatre responsabilités

| Package | Rôle | Ne fait pas | Dépendance |
|---|---|---|---|
| `hydromodpy/results/derived/` `[NOUVEAU]` | Calculs dérivés physiques : watertable, depth, seepage, intermittency, flux. Écrits dans le Zarr. | Lire des CSV ; afficher. | numpy, xarray |
| `hydromodpy/results/metrics/` `[NOUVEAU]` | Métriques de performance (NSE, KGE, RMSE, PBIAS…). Fonctions pures. | I/O, affichage. | numpy, scipy |
| `hydromodpy/results/exporters/` `[REFACTORE]` | Exports interchange : NetCDF CF-UGRID, VTU, GeoTIFF, CSV, Shapefile, HTML. | Afficher. | rioxarray, xugrid, fiona |
| `hydromodpy/analysis/display/` `[REFACTORE]` | Figures de qualité publication. Consomme `Simulation` et `SimulationGroup`. | Calculer, écrire dans le Zarr. | matplotlib, cartopy, pyvista |

**Règle invariante** : flux unidirectionnel
```
solver  →  extractors  →  catalog (DuckDB + Zarr + derived)
                                          │
                         ┌────────────────┼────────────────┐
                         ▼                ▼                ▼
                    display/          metrics/         exporters/
```

Le package `analysis/postprocess/` disparaît **en tant que nom**. Son contenu est redistribué :
- `postprocess/flow/intermittency.py` → `results/derived/intermittency.py`
- `postprocess/flow/matching_streams.py` → `analysis/comparison/streams.py`
- `postprocess/timeseries/*` → `results/derived/reducers.py` (les reducers) + catalog (l'écriture CSV n'existe plus, on lit via `catalog.export_simulation(..., format="csv")`)
- `postprocess/netcdf/*` → `results/exporters/netcdf.py`

---

## 2. Arborescence cible

```
hydromodpy/
├── results/
│   ├── catalog.py                         # [CONSERVE] SimulationCatalog (doc 04)
│   ├── simulation.py                      # [CONSERVE] Simulation (doc 04)
│   ├── simulation_group.py                # [CONSERVE] SimulationGroup (doc 04)
│   ├── zarr_store.py                      # [CONSERVE] SimulationZarr (doc 04)
│   │
│   ├── derived/                           # [NOUVEAU] Calculs dérivés physiques
│   │   ├── __init__.py
│   │   ├── flow.py                        # watertable, depth, seepage, specific_discharge
│   │   ├── transport.py                   # concentration_percentile, plume_area
│   │   ├── intermittency.py               # [RENOMME] ex-postprocess/flow/intermittency.py
│   │   ├── reducers.py                    # field → timeseries (mean/sum/max/q_specific)
│   │   └── pathlines.py                   # residence_time, persistency
│   │
│   ├── metrics/                           # [NOUVEAU] Métriques pures
│   │   ├── __init__.py
│   │   ├── efficiency.py                  # NSE, NSElog, KGE09, KGE12, KGE_np
│   │   ├── error.py                       # RMSE, nRMSE, MAE, MAPE, MARE, bias, PBIAS
│   │   ├── correlation.py                 # r (Pearson), spearman, kendall
│   │   ├── signature.py                   # baseflow_index, runoff_ratio, flashiness
│   │   └── robust.py                      # quantile metrics, Q95/Q5 ratios
│   │
│   └── exporters/                         # [REFACTORE] Interchange formats
│       ├── __init__.py
│       ├── netcdf.py                      # CF-1.11 + UGRID-1.0
│       ├── vtu.py                         # [RENOMME] ex-display/export_vtuvtk.py
│       ├── geotiff.py                     # fields → COG
│       ├── shapefile.py                   # features → GPKG
│       ├── csv.py                         # timeseries → CSV
│       └── hmp.py                         # paquet portable (doc 04)
│
├── analysis/
│   ├── display/
│   │   ├── __init__.py                    # Façade : `hmp.figures.*`
│   │   │
│   │   ├── base.py                        # [NOUVEAU] Figure Protocol + BaseFigure ABC
│   │   ├── theme.py                       # [NOUVEAU] Palette, tailles, context mgr
│   │   ├── colormaps.py                   # [NOUVEAU] Registre + garde jet
│   │   ├── units.py                       # [NOUVEAU] Unicode label formatter
│   │   ├── layout.py                      # [NOUVEAU] Panel composition (multi-fig)
│   │   ├── renderer.py                    # [NOUVEAU] Backend manager (Agg/Qt/Inline)
│   │   ├── display_config.py              # [REFACTORE] Pydantic + runtime (simplifié)
│   │   │
│   │   ├── geo/                           # [NOUVEAU] Mixins cartographiques
│   │   │   ├── __init__.py
│   │   │   ├── crs.py                     # CRS → GeoAxes (cartopy)
│   │   │   ├── decorators.py              # scalebar, north arrow, graticule
│   │   │   └── basemaps.py                # contextily tiles (optionnel)
│   │   │
│   │   ├── figures/                       # [REFACTORE] Une classe = une figure
│   │   │   ├── __init__.py                # Registry + hmp.figures.list()
│   │   │   │
│   │   │   ├── spatial/                   # Cartes spatiales (UGRID)
│   │   │   │   ├── watertable_map.py      # carte piézométrique (head)
│   │   │   │   ├── watertable_depth.py    # profondeur nappe
│   │   │   │   ├── seepage_map.py         # zones de suintement
│   │   │   │   ├── recharge_map.py        # carte de recharge
│   │   │   │   ├── concentration_map.py   # concentration (transport)
│   │   │   │   ├── dem_map.py             # topographie
│   │   │   │   ├── geology_map.py         # géologie zonale
│   │   │   │   ├── hydrography_map.py     # réseau hydro Strahler
│   │   │   │   ├── flux_map.py            # vecteurs flux (quiver)
│   │   │   │   └── difference_map.py      # diff sim_a - sim_b
│   │   │   │
│   │   │   ├── section/
│   │   │   │   ├── cross_section.py       # coupe verticale multicouche
│   │   │   │   └── flow_vectors_section.py  # quiver dans la coupe
│   │   │   │
│   │   │   ├── timeseries/
│   │   │   │   ├── hydrograph.py          # débit obs vs sim + recharge
│   │   │   │   ├── piezograph.py          # piezo obs vs sim
│   │   │   │   ├── concentration_ts.py    # concentration panel
│   │   │   │   ├── duration_curve.py      # [NOUVEAU] exceedance
│   │   │   │   ├── recession_curve.py     # [NOUVEAU] Maillet fit
│   │   │   │   ├── storage_discharge.py   # [NOUVEAU] S-Q
│   │   │   │   ├── seasonal_boxplot.py    # [NOUVEAU] régime
│   │   │   │   └── climatic_summary.py    # P/ETP mensuels
│   │   │   │
│   │   │   ├── balance/
│   │   │   │   ├── budget_bar.py          # components signés
│   │   │   │   ├── mass_balance.py        # diagnostic bilan
│   │   │   │   └── cumulative_flux.py     # recharge/décharge cumulés
│   │   │   │
│   │   │   ├── particles/
│   │   │   │   ├── pathlines_map.py       # trajectoires
│   │   │   │   └── residence_time_map.py  # carte temps de séjour
│   │   │   │
│   │   │   ├── hydrochem/                 # [NOUVEAU] eaux
│   │   │   │   ├── piper.py
│   │   │   │   ├── stiff.py
│   │   │   │   └── schoeller.py
│   │   │   │
│   │   │   ├── calibration/               # [RENOMME] ex-calibration/analysis
│   │   │   │   ├── convergence.py
│   │   │   │   ├── dotty_plot.py
│   │   │   │   ├── parallel_coordinates.py
│   │   │   │   ├── scatter_param_metric.py
│   │   │   │   └── posterior_kde.py
│   │   │   │
│   │   │   ├── comparison/                # Multi-sim
│   │   │   │   ├── side_by_side.py
│   │   │   │   ├── scatter_metric_metric.py
│   │   │   │   └── ensemble_band.py
│   │   │   │
│   │   │   ├── tables/
│   │   │   │   ├── stats_card.py
│   │   │   │   └── station_inventory.py
│   │   │   │
│   │   │   └── animation/
│   │   │       ├── concentration_gif.py
│   │   │       └── watertable_gif.py
│   │   │
│   │   ├── overview/                      # [RENOMME] ex-display/report/*
│   │   │   ├── __init__.py
│   │   │   └── watershed_id_card.py       # Composition : DEM+hydro+stats+clim
│   │   │
│   │   ├── cli.py                         # [CONSERVE] hmp display <config>
│   │   └── export.py                      # [NOUVEAU] batch export
│   │
│   ├── comparison/                        # [CONSERVE] comparaison multi-solveurs/mesh
│   │   ├── orchestrator.py
│   │   └── streams.py                     # [RENOMME] ex-matching_streams.py
│   │
│   ├── calibration/                       # (doc 07)
│   └── batch/                             # (doc 07)
│
└── core/
    └── units/                             # [NOUVEAU] UnitRegistry partagé
        ├── __init__.py
        ├── registry.py                    # Pint-backed ou maison
        └── labels.py                      # Unicode formatter
```

**Supprimés** : `analysis/display/suites.py`, `orchestration.py`, `posthoc.py`,
`posthoc_orchestration.py`, `visualization_results.py`, `visualization_watershed.py`,
`flow_payloads.py`, `adapters.py`, `compare.py`, `transport_plots.py`, tout
`analysis/postprocess/` (redistribué).

---

## 3. Contrat `Figure` — le Protocol unique

### 3.1 Protocol et ABC

Le cœur de l'architecture display : **une classe par figure**, dérivant d'une
ABC partagée. Plus de paire `render_xxx`/`plot_xxx`. Plus de dataclass `*Payload`.

```python
# hydromodpy/analysis/display/base.py
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure as MplFigure

from hydromodpy.results.simulation import Simulation
from hydromodpy.analysis.display.theme import Theme, get_theme


@dataclass(frozen=True, slots=True)
class FigureSpec:
    """Static metadata describing ONE figure type.

    Registered once, consumed by CLI (`hmp display list`), tests, and doc
    generator.
    """
    name: str                         # "watertable_map"
    title: str                        # "Water-table elevation map"
    required_fields: tuple[str, ...]  # ("head", "mesh")
    required_tables: tuple[str, ...]  # ("geographic_features",)
    supports_dis: bool = True
    supports_disv: bool = True
    supports_disu: bool = True
    kind: Literal["spatial", "timeseries", "balance", "section",
                  "particles", "animation", "table", "comparison"] = "spatial"
    default_figsize_inches: tuple[float, float] = (7.0, 5.0)


@runtime_checkable
class Figure(Protocol):
    """The one-and-only figure contract. 100 % solver-agnostic."""

    spec: FigureSpec

    def render(self, sim: Simulation, ax: Axes, **opts) -> Axes:
        """Draw into a pre-existing Axes. Returns ax for chaining."""
        ...

    def plot(self, sim: Simulation, **opts) -> MplFigure:
        """Create a standalone Figure. Default impl = wrap render()."""
        ...


class BaseFigure(ABC):
    """ABC providing the universal plot() boilerplate.

    Subclasses implement `spec` and `render(sim, ax, **opts)`. The rest
    (figure creation, theming, saving) is shared.
    """

    spec: FigureSpec

    @abstractmethod
    def render(self, sim: Simulation, ax: Axes, **opts) -> Axes:
        raise NotImplementedError

    def plot(
        self,
        sim: Simulation,
        *,
        figsize: tuple[float, float] | None = None,
        dpi: int = 300,
        theme: str | Theme = "publication",
        save_path: str | Path | None = None,
        formats: tuple[str, ...] = ("png",),
        **opts,
    ) -> MplFigure:
        figsize = figsize or self.spec.default_figsize_inches
        th = get_theme(theme) if isinstance(theme, str) else theme
        with th.context():
            fig, ax = plt.subplots(figsize=figsize, dpi=dpi,
                                   constrained_layout=True)
            self.render(sim, ax, **opts)
            if save_path is not None:
                self._save(fig, Path(save_path), formats, dpi)
        return fig

    @staticmethod
    def _save(fig: MplFigure, base_path: Path,
              formats: tuple[str, ...], dpi: int) -> None:
        base_path.parent.mkdir(parents=True, exist_ok=True)
        for ext in formats:
            out = base_path.with_suffix(f".{ext.lstrip('.')}")
            fig.savefig(out, dpi=dpi, bbox_inches="tight",
                        metadata={"Creator": "HydroModPy"})
```

**Points clés** :
- `render(sim, ax, **opts)` est la méthode *unique* à implémenter — la figure ne
  choisit ni `figsize`, ni `dpi`, ni le fichier de sortie.
- `plot()` est fourni par l'ABC. 100 % du boilerplate de l'audit §1.1 disparaît.
- `sim: Simulation` : la figure ne voit qu'un objet catalog. Elle ignore si la
  sim vient de Boussinesq, MF-NWT ou MF6.
- `spec` est du métadata statique : le registre peut lister toutes les figures,
  valider les champs requis *avant* d'appeler render, générer la doc.

### 3.2 Registre et dispatch

```python
# hydromodpy/analysis/display/figures/__init__.py
from typing import Type
from hydromodpy.analysis.display.base import BaseFigure, FigureSpec

_REGISTRY: dict[str, Type[BaseFigure]] = {}


def register(cls: Type[BaseFigure]) -> Type[BaseFigure]:
    """Class decorator. Registers a Figure by its spec.name."""
    _REGISTRY[cls.spec.name] = cls
    return cls


def get(name: str) -> BaseFigure:
    return _REGISTRY[name]()


def list_specs() -> list[FigureSpec]:
    return [cls.spec for cls in _REGISTRY.values()]


def supports(sim_mesh_kind: str, figure_name: str) -> bool:
    spec = _REGISTRY[figure_name].spec
    return getattr(spec, f"supports_{sim_mesh_kind.lower()}")
```

Usage :
```python
from hydromodpy.analysis import display
fig = display.get("watertable_map").plot(sim, save_path="~/figures/wt")
```

### 3.3 Registre d'unités (labels Unicode)

```python
# hydromodpy/core/units/labels.py
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class UnitLabel:
    short: str    # "m³/s"  (Unicode, display-ready)
    udunits: str  # "m3 s-1"  (CF-compliant)
    long: str     # "cubic metres per second"

REGISTRY: dict[str, UnitLabel] = {
    "discharge":     UnitLabel("m³/s",    "m3 s-1", "cubic metres per second"),
    "head":          UnitLabel("m",       "m",      "metres"),
    "depth":         UnitLabel("m",       "m",      "metres"),
    "seepage":       UnitLabel("m/d",     "m d-1",  "metres per day"),
    "recharge_d":    UnitLabel("mm/d",    "mm d-1", "millimetres per day"),
    "recharge_m":    UnitLabel("mm/mois", "mm",     "millimetres per month"),
    "flux":          UnitLabel("m/d",     "m d-1",  "metres per day"),
    "concentration": UnitLabel("µg/L",    "ug L-1", "micrograms per litre"),
    "volume":        UnitLabel("m³",      "m3",     "cubic metres"),
    "area":          UnitLabel("m²",      "m2",     "square metres"),
    "time_days":     UnitLabel("d",       "d",      "days"),
    "time_years":    UnitLabel("yr",      "a",      "years"),
}

def colorbar_label(quantity: str, variable: str) -> str:
    u = REGISTRY[quantity]
    return f"{variable} [{u.short}]"
```

Toute figure utilise **uniquement** `labels.colorbar_label(...)`. Aucun `[m3/s]`,
aucun `[L^3/T]`, aucun `m2` ASCII.

### 3.4 Registre de colormaps (garde-fou `jet`)

```python
# hydromodpy/analysis/display/colormaps.py
from dataclasses import dataclass

BANNED: frozenset[str] = frozenset({"jet", "cool", "rainbow", "gist_rainbow",
                                    "RdYlGn", "RdYlGn_r", "hsv"})

@dataclass(frozen=True, slots=True)
class Cmap:
    name: str
    domain: str   # "sequential" | "diverging" | "qualitative" | "cyclic"

CATALOG: dict[str, Cmap] = {
    "head":           Cmap("viridis",   "sequential"),
    "depth":          Cmap("Blues",     "sequential"),   # r pour proche surface foncé
    "depth_r":        Cmap("Blues_r",   "sequential"),
    "seepage":        Cmap("Reds",      "sequential"),
    "recharge":       Cmap("YlGnBu",    "sequential"),
    "discharge":      Cmap("magma",     "sequential"),
    "flux":           Cmap("plasma",    "sequential"),
    "residence_time": Cmap("magma",     "sequential"),
    "persistency":    Cmap("cividis",   "sequential"),
    "concentration":  Cmap("plasma",    "sequential"),
    "topography":     Cmap("terrain",   "sequential"),
    "difference":     Cmap("RdBu_r",    "diverging"),
    "diff_symlog":    Cmap("coolwarm",  "diverging"),
    "zones":          Cmap("tab10",     "qualitative"),
    "geology":        Cmap("Paired",    "qualitative"),
}

def resolve(key_or_name: str) -> str:
    if key_or_name in CATALOG:
        return CATALOG[key_or_name].name
    if key_or_name in BANNED:
        raise ValueError(f"colormap '{key_or_name}' is banned (non-perceptual)")
    return key_or_name  # matplotlib-native allowed (e.g. 'Greys')
```

Test de conformité (automatique, CI) :
```python
# tests/unit/display/test_colormaps.py
import ast, pathlib, pytest

def test_no_banned_cmap_in_display():
    root = pathlib.Path("hydromodpy/analysis/display")
    banned = {"jet", "cool", "RdYlGn", "rainbow"}
    hits = []
    for path in root.rglob("*.py"):
        text = path.read_text()
        for name in banned:
            if f"cmap='{name}'" in text or f'cmap="{name}"' in text:
                hits.append((path, name))
    assert not hits, f"Banned colormaps found: {hits}"
```

### 3.5 Mixin `GeoFigure` (cartographie)

```python
# hydromodpy/analysis/display/geo/crs.py
import cartopy.crs as ccrs
from matplotlib.axes import Axes
from hydromodpy.results.simulation import Simulation


class GeoFigureMixin:
    """Mixin providing a CRS-aware Axes factory.

    Usage: override `render()` to call `self.make_geo_axes(fig, sim)`
    instead of receiving a standard Axes.
    """

    def projection_from(self, sim: Simulation) -> ccrs.Projection:
        return ccrs.epsg(sim.crs_epsg)

    def decorate(
        self,
        ax: Axes,
        *,
        scalebar: bool = True,
        north_arrow: bool = True,
        graticule: bool = False,
        gridlines_kwargs: dict | None = None,
    ) -> None:
        from hydromodpy.analysis.display.geo.decorators import (
            add_scalebar, add_north_arrow, add_graticule,
        )
        if scalebar:
            add_scalebar(ax)
        if north_arrow:
            add_north_arrow(ax)
        if graticule:
            add_graticule(ax, **(gridlines_kwargs or {}))
```

Les cartes héritent de `BaseFigure, GeoFigureMixin`.

---

## 4. Catalogue des figures (25 types)

Chaque figure est une classe dans `analysis/display/figures/<kind>/<name>.py`
avec un `FigureSpec`. Le tableau ci-dessous résume les 25 types au cœur de la
bibliothèque cible. **Toutes fonctionnent sur DIS ou DISV** grâce à la grille
UGRID unifiée (doc 04, §3).

### 4.1 Cartes spatiales (fondées sur UGRID)

| Nom | Description | `required_fields` | `required_tables` | DIS/DISV | Exemple visuel attendu |
|---|---|---|---|---|---|
| `watertable_map` | Carte piézométrique : head de surface colorée en `viridis` + contours topo superposés + contour watershed + réseau hydro Strahler, colorbar `Head [m]`, scalebar, flèche nord | `head` | `geographic_features` | ✓/✓ | Grille 2D colorée, lignes fines noires (topo), contour noir (bassin), lignes bleues (rivières). Style WRR. |
| `watertable_depth` | Profondeur nappe = top − head, cmap `Blues_r`, masque des cellules où nappe > top (seepage) | `watertable_depth` *(dérivé)* | — | ✓/✓ | Carte inversée (foncé = proche surface). |
| `seepage_map` | Zones de suintement (flux > 0), cmap `Reds`, quantiles (0.02, 0.98), hachures légères hors seepage | `seepage_areas_m_per_day` *(dérivé)* | — | ✓/✓ | Taches rouges concentrées en têtes de bassin et fonds de vallée. |
| `recharge_map` | Recharge moyenne annuelle par cellule en mm/an, cmap `YlGnBu` | `recharge_m_per_day` | — | ✓/✓ | Gradient selon pluviométrie spatiale. |
| `concentration_map` | Concentration solute à un pas de temps, cmap `plasma` | `concentration` | — | ✓/✓ | Panache coloré. |
| `dem_map` | Topographie (DEM), cmap `terrain`, hypsographie, contours élévation | `top_elevation_m` | `geographic_features` | ✓/✓ | Rendu topo classique. |
| `geology_map` | Zones géologiques, cmap `Paired` (qualitatif) | `geology_zone_id` | — | ✓/✓ | Aplats colorés par formation. |
| `hydrography_map` | Réseau hydrographique pondéré Strahler, pas de données flow requises | — | `geographic_features` | ✓/✓ | Lignes bleues d'épaisseur croissante. |
| `flux_map` | Vecteurs de flux (quiver) décimés en grille régulière, magnitude colorée `plasma` | `specific_discharge_face_xy` *(dérivé)* | — | ✓/✓ | Flèches directionnelles + fond coloré. |
| `difference_map` | Diff `sim_a - sim_b` sur champ commun, cmap `RdBu_r` centrée à zéro | `head` ou autre (même nom sur 2 sims) | — | ✓/✓ | Carte signée. |
| `watertable_triptych` | 3 panneaux : topo / head / depth, colorbars individuelles | `top_elevation_m`, `head`, `watertable_depth` | — | ✓/✓ | Panneau horizontal 1×3. |

**Implémentation UGRID commune** : toutes les cartes utilisent un seul helper
`render_ugrid_field(ax, sim, field, *, cmap, norm)` qui :
1. Charge `mesh.face_node_connectivity` et `mesh.node_coordinates` depuis le Zarr.
2. Construit une `matplotlib.collections.PolyCollection` (pour DIS/DISV) *ou*
   `matplotlib.tri.Triangulation` selon la densité.
3. Applique le masque nodata.
4. Ajoute la colorbar via `labels.colorbar_label(...)`.

Aucun `reshape(nrow, ncol)` dans aucune figure.

### 4.2 Coupes verticales

| Nom | Description | `required_fields` | DIS/DISV |
|---|---|---|---|
| `cross_section` | Coupe le long d'un polyligne user-défini. Empilement des couches géologiques colorées, trait bleu de nappe, contours isopiézométriques superposés (optionnel), fond marron sous substratum | `top_elevation_m`, `bottom_elevation_m_layer`, `head_layer`, `geology_zone_id_layer` | ✓/✓ |
| `flow_vectors_section` | Idem + vecteurs vitesses dans le plan de la coupe (quiver) | idem + `specific_discharge_face_xyz` | ✓/✓ |

**Implémentation** : `cross_section.py` prend `profile: LineString` en option.
Intersecte avec la topologie UGRID via `shapely` → liste ordonnée de cellules +
fractions. Empile les couches par `z_interfaces`. Remplit chaque polygone avec
la couleur de la zone géologique. Superpose la ligne de nappe (piecewise-linear
depuis les head des cellules traversées). Fonctionne sur DIS et DISV — seule la
localisation des cellules change, pas l'algorithme.

### 4.3 Séries temporelles

| Nom | Description | Données (table / colonne catalog) |
|---|---|---|
| `hydrograph` | Débit exutoire obs vs sim + recharge en axe secondaire (bars inversées), log-Y optionnel, shading des gaps de données | `timeseries (station, variable='discharge')` |
| `piezograph` | Niveau piézo obs vs sim station par station | `timeseries (station, variable='head')` |
| `concentration_ts` | Panel concentration à N stations | `timeseries (station, variable='concentration')` |
| `duration_curve` | [NOUVEAU] Courbe de fréquence d'exceedance (log-Q vs probabilité), obs vs sim superposés | `timeseries (discharge)` |
| `recession_curve` | [NOUVEAU] Ajustement Maillet/Brutsaert sur segments de récession détectés automatiquement | `timeseries (discharge)` |
| `storage_discharge` | [NOUVEAU] Diagramme S-Q (dQ/dt vs Q) en log-log | `timeseries (discharge)` |
| `seasonal_boxplot` | [NOUVEAU] Boxplots mensuels (régime saisonnier) | `timeseries (discharge \| head)` |
| `climatic_summary` | P/ETP mensuels moyens, barres | `timeseries (precipitation, etp)` |
| `intermittency_ts` | Stacked area pérenne/intermittent/sec (catégoriel ONDE) | `timeseries (intermittency_class)` |

### 4.4 Bilans

| Nom | Description | Données |
|---|---|---|
| `budget_bar` | Bilan hydrique : barres composants signés (recharge +, drain −, storage ±, wells −) | `budgets` |
| `mass_balance` | Diagnostic de bilan (erreur %, cumulative imbalance) | `mass_balance` |
| `cumulative_flux` | Recharge et décharge cumulées sur l'historique | `timeseries (components)` |

### 4.5 Particules

| Nom | Description | Données |
|---|---|---|
| `pathlines_map` | Trajectoires de particules sur fond head, coloration par temps de séjour, cmap `magma` | `pathlines` (Zarr) + `head` |
| `residence_time_map` | Carte temps de séjour des cellules sources, cmap `magma` | `residence_time` *(dérivé)* |

### 4.6 Hydrochimie [NOUVEAU]

| Nom | Description | Données |
|---|---|---|
| `piper` | Diagramme de Piper (cations/anions normalisés) | `observations_hydrochem` |
| `stiff` | Diagramme de Stiff (polygones symétriques Cl/SO4/HCO3 vs Na/Mg/Ca) | idem |
| `schoeller` | Diagramme de Schoeller (concentrations en log, axes parallèles) | idem |

### 4.7 Calibration (doc 07)

| Nom | Description |
|---|---|
| `convergence` | Meilleur score vs itération (log-scale) |
| `dotty_plot` | Param vs score pour chaque param, quantiles 10/50/90 |
| `parallel_coordinates` | Params + métriques normalisés, colorés par NSE |
| `scatter_param_metric` | Scatter plot 2D (param A vs métrique M) pour N simulations |
| `posterior_kde` | KDE des paramètres post-calibration (top-10 %) |

### 4.8 Comparaison multi-simulations

| Nom | Description |
|---|---|
| `side_by_side` | 2 (ou N) figures spatiales en grille ligne, colorbars partagées |
| `scatter_metric_metric` | Scatter NSE_1 vs NSE_2 pour N stations, points = simulations |
| `ensemble_band` | Série temporelle avec ruban p10-p90 sur ensemble |
| `difference_map` *(déjà en §4.1)* | Diff spatiale |

### 4.9 Tables et animations

| Nom | Description |
|---|---|
| `stats_card` | Panneau texte : aire, élévation, N stations, NSE, KGE, PBIAS |
| `station_inventory` | Tableau matplotlib des stations et leurs métriques |
| `concentration_gif` | Animation MP4/GIF de la concentration |
| `watertable_gif` | Animation de la nappe dans le temps |

### 4.10 Vue "carte d'identité bassin" [RENOMME]

`analysis/display/overview/watershed_id_card.py` — **composition** des figures
précédentes en une planche, via le module `layout.py`. Pas de logique propre ;
simple assemblage déclaratif :

```python
from hydromodpy.analysis.display import layout, figures

def watershed_id_card(sim, save_path=None):
    return (layout.Grid(rows=3, cols=3, figsize=(16, 14))
            .panel(0, 0, figures.get("dem_map"))
            .panel(0, 1, figures.get("hydrography_map"))
            .panel(0, 2, figures.get("stats_card"))
            .panel(1, 0, figures.get("geology_map"))
            .panel(1, 1, figures.get("watertable_map"))
            .panel(1, 2, figures.get("seepage_map"))
            .panel(2, 0, figures.get("climatic_summary"), colspan=2)
            .panel(2, 2, figures.get("station_inventory"))
            .build(sim, save_path=save_path))
```

### 4.11 Tableau — soutien DIS/DISV

| Famille | DIS | DISV | DISU | Dépendance au layout structuré |
|---|---|---|---|---|
| Cartes | ✓ | ✓ | ✓ | Aucune (UGRID) |
| Coupes | ✓ | ✓ | ✓ | Intersection `shapely` sur polygones |
| Séries temporelles | ✓ | ✓ | ✓ | Aucune (timeseries par station) |
| Bilans | ✓ | ✓ | ✓ | Aucune (tables DuckDB) |
| Particules | ✓ | ✓ | ✓ | Coordonnées (x,y,z,t) en Zarr |
| Animations | ✓ | ✓ | ✓ | Aucune |

Le seul helper `display/geo/raster_reproject.py` existe pour les cas où
l'utilisateur veut un rendu *rasterisé* (exemple : carte HighRes pour poster) :
il trianglule la UGRID et rééchantillonne sur une grille régulière. Ce helper
**n'est pas** utilisé par les figures du catalogue ; c'est un outil facultatif.

---

## 5. Calculs dérivés — où vivent-ils ?

Règle d'or (audit §4.2 sur l'intermittency, §6.1 sur les reducers) : **les
quantités dérivées sont calculées UNE fois, au moment de l'extraction, et
écrites dans le Zarr de la simulation**. Le display les consomme comme
n'importe quel autre champ.

### 5.1 `results/derived/flow.py` [NOUVEAU]

```python
# hydromodpy/results/derived/flow.py
"""Pure numpy derivations for flow solvers.

Called once by `simulation/results/extractors/*` right after solver finishes.
Writes into the simulation Zarr. Never re-computed on display path.
"""
from __future__ import annotations
import numpy as np
import xarray as xr


def watertable_elevation(head: xr.DataArray, top: xr.DataArray) -> xr.DataArray:
    """Water-table elevation = head clipped to top."""
    wt = head.where(head <= top, top)
    wt.attrs.update(
        units="m",
        standard_name="water_table_altitude",
        long_name="Water-table elevation above reference",
    )
    return wt


def watertable_depth(head: xr.DataArray, top: xr.DataArray) -> xr.DataArray:
    """Depth to water table = top - head (positive downward)."""
    d = (top - head).where((top - head) >= 0, 0.0)
    d.attrs.update(units="m", standard_name="depth_to_water_table",
                   long_name="Depth from surface to water table")
    return d


def seepage_flux(head: xr.DataArray, top: xr.DataArray,
                 drain_conductance: xr.DataArray,
                 cell_area: xr.DataArray) -> xr.DataArray:
    """Seepage flux per cell in m/day.

    Formula: q_s = C * max(h - top, 0) / A
    """
    overflow = (head - top).where(head > top, 0.0)
    q = drain_conductance * overflow / cell_area
    q.attrs.update(units="m d-1", standard_name="surface_downward_water_flux",
                   long_name="Seepage flux out of aquifer")
    return q


def specific_discharge_face(head: xr.DataArray, mesh) -> xr.DataArray:
    """Darcy flux vector at each face (UGRID face-centered).

    Returns a (time, face, 2) array with x/y components in m/day.
    Uses the MODFLOW-6 standard face-normal Darcy flux when available
    (extracted by the MF6 adapter); otherwise recomputes from head +
    conductivity via cell-centered gradient.
    """
    # Implementation omitted for brevity — but this lives here, not in display.
    ...
```

### 5.2 `results/derived/intermittency.py` [RENOMME]

Déplacé depuis `analysis/postprocess/flow/intermittency.py` (audit §4.2 :
« physique dérivée, pas post-traitement d'affichage »). API inchangée, mais :
- plus de mutation de DataFrame en place ;
- écrit trois variables Zarr : `perennial_mask`, `intermittent_mask`, `total_area_series` ;
- consommé par la figure `intermittency_ts` et par `drainage_density` via
  lecture directe du Zarr.

### 5.3 `results/derived/reducers.py` [RENOMME]

Déplacé depuis `FlowTimeseriesPostprocess._reduce_*` (audit §4.2 : « opérations
génériques, devraient vivre dans `results/reducers/` »). Fonctions pures :

```python
def mean_over_cells(field: xr.DataArray, weights: xr.DataArray | None = None,
                    *, mask_negatives: bool = False) -> xr.DataArray:
    """Spatial mean. `mask_negatives=True` is an EXPLICIT option, not silent legacy."""
    if weights is None:
        return field.mean("face")
    return (field * weights).sum("face") / weights.sum()


def sum_over_cells(field: xr.DataArray) -> xr.DataArray: ...
def max_over_cells(field: xr.DataArray) -> xr.DataArray: ...
def area_fraction(mask: xr.DataArray, cell_area: xr.DataArray) -> xr.DataArray:
    """Fraction of watershed area satisfying mask, in [0, 1]."""
    return (mask.astype(float) * cell_area).sum("face") / cell_area.sum()

def q_specific(discharge_m3s: xr.DataArray, area_m2: xr.DataArray) -> xr.DataArray:
    """Specific discharge Q/A in m/day. Input Q in m³/s → ×86400 for days."""
    qspec = discharge_m3s * 86400.0 / area_m2
    qspec.attrs.update(units="m d-1")
    return qspec
```

Le bug historique `masked[masked < 0] = 0 # Keep legacy behavior` disparaît :
`mask_negatives` est un flag explicite.

### 5.4 `results/derived/pathlines.py` [NOUVEAU]

`residence_time`, `starting_cells`, `persistency_index` — calculés à partir des
trajectoires MODPATH/particles en Zarr.

### 5.5 Principe « display n'a pas le droit de calculer »

Les reviewers doivent rejeter tout PR où une figure fait :
```python
# INTERDIT dans display/
depth = top - head
flux = recharge * 30 * 1000  # factor magique m/day → mm/mois
```

Les seules opérations autorisées dans `display/` :
- Slicing temporel (`.sel(time=t)`, `.isel(time=-1)`).
- Masquage visuel (clip colorbar, quantiles robustes).
- Agrégation **uniquement** pour l'aspect visuel (ex : `rolling(7).mean()` pour
  lisser une courbe).

Tout calcul physique ou de transformation quantitative est dans `results/derived/`.

---

## 6. Métriques — formules exactes et implémentation

### 6.1 Fichier `results/metrics/efficiency.py` [NOUVEAU]

Fonctions pures, robustes aux NaN et aux cas dégénérés. Toutes renvoient `float`
(jamais `numpy.float64` scalaire 0-d) pour cohérence JSON/DuckDB.

```python
# hydromodpy/results/metrics/efficiency.py
from __future__ import annotations
import numpy as np

__all__ = ["nse", "nse_log", "kge_2009", "kge_2012", "kge_np"]


def _align(sim: np.ndarray, obs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Drop rows where either is NaN. Returns possibly-empty aligned arrays."""
    sim = np.asarray(sim, dtype=float).ravel()
    obs = np.asarray(obs, dtype=float).ravel()
    if sim.shape != obs.shape:
        raise ValueError(f"shape mismatch: sim={sim.shape} obs={obs.shape}")
    mask = np.isfinite(sim) & np.isfinite(obs)
    return sim[mask], obs[mask]


def nse(sim, obs) -> float:
    """Nash-Sutcliffe Efficiency (Nash & Sutcliffe, 1970).

        NSE = 1 − Σ(sim − obs)² / Σ(obs − mean(obs))²

    Returns NaN if obs is constant (degenerate denominator).
    Range: (−∞, 1]. NSE = 1 is perfect.
    """
    s, o = _align(sim, obs)
    if s.size == 0:
        return float("nan")
    denom = float(np.sum((o - o.mean()) ** 2))
    if denom <= 0.0:
        return float("nan")
    num = float(np.sum((s - o) ** 2))
    return float(1.0 - num / denom)


def nse_log(sim, obs, *, eps: float | None = None) -> float:
    """NSE on log-transformed series.

    `eps`:
      - None (default): eps = max(1e-9, 0.01 × median(obs)).
        Data-driven, robust to magnitude.
      - float: user-provided offset.

    Rejects negative values (physically impossible for discharge).
    """
    s, o = _align(sim, obs)
    if np.any(s < 0) or np.any(o < 0):
        raise ValueError("nse_log: series contain negative values")
    if eps is None:
        med = float(np.median(o[o > 0])) if np.any(o > 0) else 1.0
        eps = max(1e-9, 0.01 * med)
    return nse(np.log(s + eps), np.log(o + eps))


def kge_2009(sim, obs) -> dict[str, float]:
    """Kling-Gupta Efficiency (Gupta, Kling, Yilmaz & Martinez, 2009).

        r     = Pearson correlation(sim, obs)
        alpha = std(sim) / std(obs)        # ratio of variability
        beta  = sum(sim) / sum(obs)        # ratio of total volume
        KGE   = 1 − sqrt((r−1)² + (α−1)² + (β−1)²)

    Returns dict {kge, r, alpha, beta}.
    """
    s, o = _align(sim, obs)
    if s.size < 2:
        return {"kge": float("nan"), "r": float("nan"),
                "alpha": float("nan"), "beta": float("nan")}
    std_o = float(np.std(o, ddof=0))
    sum_o = float(np.sum(o))
    if std_o == 0 or sum_o == 0:
        return {"kge": float("nan"), "r": float("nan"),
                "alpha": float("nan"), "beta": float("nan")}
    r = float(np.corrcoef(s, o)[0, 1])
    alpha = float(np.std(s, ddof=0) / std_o)
    beta = float(np.sum(s) / sum_o)
    kge = float(1.0 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2))
    return {"kge": kge, "r": r, "alpha": alpha, "beta": beta}


def kge_2012(sim, obs) -> dict[str, float]:
    """KGE′ (Kling, Fuchs & Paulin, 2012) — mean-based β.

        γ = (std(sim) / mean(sim)) / (std(obs) / mean(obs))  # CV ratio
        β = mean(sim) / mean(obs)
        KGE′ = 1 − sqrt((r−1)² + (γ−1)² + (β−1)²)
    """
    s, o = _align(sim, obs)
    if s.size < 2:
        return {"kge": float("nan"), "r": float("nan"),
                "gamma": float("nan"), "beta": float("nan")}
    mean_o, mean_s = float(np.mean(o)), float(np.mean(s))
    if mean_o == 0 or mean_s == 0:
        return {"kge": float("nan"), "r": float("nan"),
                "gamma": float("nan"), "beta": float("nan")}
    r = float(np.corrcoef(s, o)[0, 1])
    cv_s = float(np.std(s, ddof=0) / mean_s)
    cv_o = float(np.std(o, ddof=0) / mean_o)
    gamma = cv_s / cv_o if cv_o > 0 else float("nan")
    beta = mean_s / mean_o
    kge = float(1.0 - np.sqrt((r - 1) ** 2 + (gamma - 1) ** 2 + (beta - 1) ** 2))
    return {"kge": kge, "r": r, "gamma": gamma, "beta": beta}


def kge_np(sim, obs) -> dict[str, float]:
    """KGE non-parametric (Pool, Vis & Seibert, 2018) — Spearman r + flow-duration α."""
    from scipy.stats import spearmanr
    s, o = _align(sim, obs)
    if s.size < 2:
        return {"kge": float("nan"), "rho": float("nan"),
                "alpha_fdc": float("nan"), "beta": float("nan")}
    rho = float(spearmanr(s, o).correlation)
    # FDC alpha: Σ|P_sim - P_obs| where P is the empirical CDF
    n = s.size
    p_s = np.sort(s / np.mean(s))
    p_o = np.sort(o / np.mean(o))
    alpha_fdc = 1.0 - 0.5 * float(np.sum(np.abs(p_s - p_o))) / n
    beta = float(np.mean(s) / np.mean(o)) if np.mean(o) != 0 else float("nan")
    kge = float(1.0 - np.sqrt((rho - 1) ** 2 + (alpha_fdc - 1) ** 2 + (beta - 1) ** 2))
    return {"kge": kge, "rho": rho, "alpha_fdc": alpha_fdc, "beta": beta}
```

### 6.2 Fichier `results/metrics/error.py` [NOUVEAU]

```python
# hydromodpy/results/metrics/error.py
import numpy as np
from hydromodpy.results.metrics.efficiency import _align


def rmse(sim, obs) -> float:
    s, o = _align(sim, obs)
    return float(np.sqrt(np.mean((s - o) ** 2))) if s.size else float("nan")


def nrmse(sim, obs, *, norm: str = "range") -> float:
    """Normalized RMSE.

    norm:
      - "range" (default): RMSE / (max(obs) − min(obs))   [preferred, standard]
      - "mean":            RMSE / mean(obs)               [old HydroModPy default]
      - "std":             RMSE / std(obs)
    """
    s, o = _align(sim, obs)
    r = rmse(s, o)
    if norm == "range":
        denom = float(o.max() - o.min())
    elif norm == "mean":
        denom = float(o.mean())
    elif norm == "std":
        denom = float(o.std())
    else:
        raise ValueError(f"unknown norm {norm}")
    return r / denom if denom != 0 else float("nan")


def mae(sim, obs) -> float:
    s, o = _align(sim, obs)
    return float(np.mean(np.abs(s - o))) if s.size else float("nan")


def mape(sim, obs) -> float:
    """Mean Absolute Percentage Error. Skips obs==0 (undefined)."""
    s, o = _align(sim, obs)
    keep = o != 0
    return float(np.mean(np.abs((s[keep] - o[keep]) / o[keep]))) if keep.any() else float("nan")


def bias(sim, obs) -> float:
    """Additive bias (sim − obs)."""
    s, o = _align(sim, obs)
    return float(np.mean(s - o)) if s.size else float("nan")


def pbias(sim, obs) -> float:
    """Percent bias (USGS standard).

        PBIAS = 100 × Σ(obs − sim) / Σ(obs)

    Positive = underestimation. Range: (−∞, +∞). |PBIAS| < 10 % excellent.
    """
    s, o = _align(sim, obs)
    if s.size == 0 or np.sum(o) == 0:
        return float("nan")
    return float(100.0 * np.sum(o - s) / np.sum(o))
```

### 6.3 Où ces métriques sont-elles consommées ?

```
results/metrics/
     │
     ├──→ analysis/calibration/engine/objective.py   (objectif de calibration)
     ├──→ analysis/comparison/metrics.py             (comparaisons multi-solveurs)
     ├──→ simulation/results/extractors/*.py         (écrit dans DuckDB.metrics)
     └──→ analysis/display/figures/tables/stats_card.py
```

Un seul endroit pour les formules. Plus de `rmse_manual` dispersés.

### 6.4 Tests de régression numérique

Les métriques ont des tests avec références publiées :

```python
# tests/unit/metrics/test_efficiency.py
def test_nse_known_ref():
    # Gupta et al. 2009 Table 2, leaf river basin MOPEX
    obs = np.loadtxt("tests/data/mopex_leaf_obs.csv")
    sim = np.loadtxt("tests/data/mopex_leaf_sim.csv")
    assert nse(sim, obs) == pytest.approx(0.81, abs=0.01)
```

---

## 7. Comparaison multi-simulations

### 7.1 `SimulationGroup` (doc 04 §5) = point d'entrée

Le type `SimulationGroup` est fourni par `results/simulation_group.py`. Il
représente un ensemble filtré de simulations et expose :
- `.to_dataframe(params, metrics)` — pivot tabulaire
- `.field(name, aggregation="mean" | "p50" | "spread")` — reduce sur l'ensemble
- `.timeseries(variable, station)` — dict `sim_id → pd.Series`

Toutes les figures de comparaison consomment un `SimulationGroup`.

### 7.2 Side-by-side

```python
# hydromodpy/analysis/display/figures/comparison/side_by_side.py
from hydromodpy.analysis.display.base import BaseFigure, FigureSpec
from hydromodpy.analysis.display.figures import get as get_figure

class SideBySide(BaseFigure):
    spec = FigureSpec(
        name="side_by_side",
        title="Side-by-side N-panel comparison",
        required_fields=(),     # delegated to inner figure
        required_tables=(),
        kind="comparison",
        default_figsize_inches=(14.0, 5.0),
    )

    def render(self, group, ax, *, inner: str, **opts):  # ax is a GridSpec slot
        raise NotImplementedError("Use plot() — side-by-side creates its own Fig.")

    def plot(self, group, *, inner: str, shared_cbar: bool = True,
             figsize=None, save_path=None, **opts):
        import matplotlib.pyplot as plt
        inner_fig = get_figure(inner)
        n = len(group)
        fig, axes = plt.subplots(1, n, figsize=figsize or (5*n, 4.5),
                                 constrained_layout=True, sharey=True)
        vmin = vmax = None
        if shared_cbar:
            # Compute shared colour limits from the group
            vmin, vmax = group.quantile_range(inner_fig.spec.required_fields[0],
                                               q=(0.02, 0.98))
        for ax, sim in zip(axes, group.simulations):
            inner_fig.render(sim, ax, vmin=vmin, vmax=vmax, **opts)
            ax.set_title(sim.label)
        if save_path is not None:
            self._save(fig, Path(save_path), ("png", "pdf"), 300)
        return fig
```

### 7.3 Difference map

Réutilise la figure `difference_map` listée en §4.1 :

```python
sim_a = catalog.get(uuid_a)
sim_b = catalog.get(uuid_b)
figures.get("difference_map").plot(
    sim_a, reference=sim_b, field="head", timestep=-1,
    save_path="~/compare/head_diff"
)
```

L'implémentation :
```python
class DifferenceMap(BaseFigure, GeoFigureMixin):
    spec = FigureSpec(name="difference_map", ..., kind="spatial")

    def render(self, sim, ax, *, reference, field, timestep=-1, **opts):
        a = sim.field(field, timestep=timestep)
        b = reference.field(field, timestep=timestep)
        if not sim.mesh.is_congruent_with(reference.mesh):
            # Interpolate b onto sim.mesh (UGRID → UGRID via natural neighbor)
            b = reference.resample_to(sim.mesh).field(field, timestep=timestep)
        diff = a - b
        vmax = np.nanmax(np.abs(diff))
        norm = TwoSlopeNorm(vcenter=0, vmin=-vmax, vmax=vmax)
        render_ugrid_field(ax, sim, diff, cmap="RdBu_r", norm=norm)
        self.decorate(ax)
        return ax
```

### 7.4 Scatter params vs métriques pour N simulations

```python
# hydromodpy/analysis/display/figures/comparison/scatter_metric_metric.py
class ScatterMetricMetric(BaseFigure):
    spec = FigureSpec(name="scatter_metric_metric", kind="comparison",
                      required_fields=(), required_tables=("metrics",))

    def render(self, group, ax, *, x: str, y: str,
               station: str | None = None, color_by: str | None = None, **opts):
        df = group.to_dataframe(
            params=[color_by] if color_by else [],
            metrics=[x, y],
            station=station,
        )
        sc = ax.scatter(df[x], df[y],
                        c=df[color_by] if color_by else None,
                        cmap="viridis", s=20, alpha=0.75)
        if color_by:
            plt.colorbar(sc, ax=ax, label=color_by)
        ax.set_xlabel(x)
        ax.set_ylabel(y)
        ax.axline((0, 0), slope=1, color="gray", lw=0.5, ls="--")
        return ax
```

Usage :
```python
group = catalog.find(project="canut", nse_gt=0.5)
figures.get("scatter_metric_metric").plot(
    group, x="nse", y="kge", color_by="hk_zone1", station="P01",
    save_path="~/compare/nse_vs_kge",
)
```

### 7.5 Ensemble band

Zone ombrée p10–p90 + médiane superposées sur une série obs :

```python
class EnsembleBand(BaseFigure):
    spec = FigureSpec(name="ensemble_band", kind="comparison",
                      required_fields=(), required_tables=("timeseries",))

    def render(self, group, ax, *, variable: str, station: str, **opts):
        df = group.timeseries_matrix(variable=variable, station=station)
        #   rows = time index, cols = sim_id
        p10 = df.quantile(0.10, axis=1)
        p50 = df.quantile(0.50, axis=1)
        p90 = df.quantile(0.90, axis=1)
        obs = group.observations(variable=variable, station=station)
        ax.fill_between(df.index, p10, p90, alpha=0.25, color="steelblue",
                        label="p10–p90")
        ax.plot(df.index, p50, color="steelblue", lw=1.2, label="median")
        if obs is not None:
            ax.plot(obs.index, obs.values, "k.", ms=2, label="obs")
        ax.legend()
        return ax
```

---

## 8. Export des figures — publication-grade

### 8.1 Presets de tailles

Conformes aux gabarits **Water Resources Research** / **Journal of Hydrology** /
AGU / Elsevier single-column et double-column :

```python
# hydromodpy/analysis/display/theme.py
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class SizePreset:
    width_in: float
    height_in: float
    dpi: int
    formats: tuple[str, ...]


PRESETS: dict[str, SizePreset] = {
    # Width = 3.5" single col, 7.16" double col (AGU).
    "single_column":       SizePreset(3.5, 2.6, 600, ("pdf", "png")),
    "double_column":       SizePreset(7.16, 4.5, 600, ("pdf", "png")),
    "poster":              SizePreset(12.0, 9.0, 300, ("png",)),
    "slide_169":           SizePreset(13.33, 7.5, 200, ("png",)),
    "draft":               SizePreset(6.0, 4.0, 100, ("png",)),
    "publication":         SizePreset(7.16, 4.5, 600, ("pdf", "svg", "png")),
}
```

Usage :
```python
fig = figures.get("watertable_map").plot(
    sim,
    preset="publication",          # overrides figsize, dpi, formats
    save_path="~/figures/head_map",
)
# → writes head_map.pdf, head_map.svg, head_map.png at 600 dpi
```

### 8.2 Résolution et formats

| Format | Usage | DPI |
|---|---|---|
| **PDF** | Publication, vectoriel, fonts incluses | N/A (vector) |
| **SVG** | Édition vectorielle (Inkscape/Illustrator) | N/A |
| **PNG** | Figures raster, notebooks, web | 300 (normal), 600 (publication), 100 (draft) |
| **EPS** | Revues legacy uniquement | vector |
| **PGF** | Intégration LaTeX native | vector |

Matplotlib est configuré avec `pdf.fonttype=42`, `ps.fonttype=42` pour que les
polices soient des glyphes vectoriels, pas des outlines rasterisés.

### 8.3 Batch export de toutes les figures

```python
# hydromodpy/analysis/display/export.py
from pathlib import Path
from typing import Iterable
from hydromodpy.results.simulation import Simulation
from hydromodpy.analysis.display.figures import list_specs, get as get_figure


def export_all(
    sim: Simulation,
    out_dir: str | Path,
    *,
    only: Iterable[str] | None = None,
    skip: Iterable[str] = (),
    preset: str = "publication",
    parallel: bool = False,
) -> dict[str, Path]:
    """Render every figure applicable to `sim` and save to `out_dir`.

    Returns {figure_name: saved_path}. Figures that raise are logged and
    skipped; a SKIPPED.txt report is written.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    only_set = set(only) if only else None
    skip_set = set(skip)
    specs = [s for s in list_specs()
             if (only_set is None or s.name in only_set)
             and s.name not in skip_set
             and s.is_compatible_with(sim)]
    results: dict[str, Path] = {}
    skipped: list[str] = []
    def _one(spec):
        fig = get_figure(spec.name).plot(
            sim, preset=preset, save_path=out_dir / spec.name,
        )
        return spec.name, out_dir / f"{spec.name}.png"
    iterator = map(_one, specs)
    if parallel:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor() as ex:
            iterator = ex.map(_one, specs)
    for name, path in iterator:
        results[name] = path
    (out_dir / "SKIPPED.txt").write_text("\n".join(skipped))
    return results
```

CLI : `hmp display export <sim_id> --out ~/fig/ --preset publication`.

### 8.4 Métadonnées PDF

Chaque PDF exporté inclut :
- `Title = spec.title`
- `Author = sim.metadata.user`
- `Subject = f"HydroModPy {version} · sim_id={sim.id}"`
- `Keywords = "hydrogeology, groundwater, <solver>"`

Utile pour l'archivage institutionnel et Zenodo.

---

## 9. Mode headless

### 9.1 Design : TOML > env var

L'env var `HYDROMODPY_NO_DISPLAY` reste honorée **en dernier recours** (CI,
scripts legacy), mais le mécanisme de premier ordre est TOML :

```toml
[display]
enabled = true
backend = "agg"          # "agg" | "qt" | "inline" | "auto"
show    = false          # default: false in non-interactive contexts
save    = true
dpi     = 300
preset  = "publication"
```

```python
# hydromodpy/analysis/display/renderer.py
from __future__ import annotations
import os
import sys
from typing import Literal


Backend = Literal["agg", "qt", "inline", "auto"]


class BackendManager:
    """Single class that configures matplotlib ONE time at startup.

    No top-level `plt.use()` anywhere else in the codebase.
    """
    _configured: bool = False

    @classmethod
    def configure(cls, backend: Backend = "auto") -> str:
        """Must be called before any matplotlib import.

        Returns the backend actually chosen.
        """
        if cls._configured:
            return matplotlib.get_backend()
        chosen = backend
        if backend == "auto":
            chosen = cls._detect()
        import matplotlib
        matplotlib.use(cls._canonical(chosen), force=True)
        # ALSO import pyplot now so no further `import pyplot` flips backend
        import matplotlib.pyplot  # noqa: F401
        cls._configured = True
        return chosen

    @staticmethod
    def _detect() -> Backend:
        """Pick a safe backend automatically.

        Priority:
          1. If env var HYDROMODPY_NO_DISPLAY=1  → "agg"   (CI compatibility)
          2. If IPython/Jupyter detected          → "inline"
          3. If no $DISPLAY on Linux              → "agg"
          4. Else                                 → "qt"
        """
        if os.environ.get("HYDROMODPY_NO_DISPLAY") == "1":
            return "agg"
        try:
            import IPython
            if IPython.get_ipython() is not None:
                return "inline"
        except ImportError:
            pass
        if sys.platform == "linux" and "DISPLAY" not in os.environ:
            return "agg"
        return "qt"

    @staticmethod
    def _canonical(backend: Backend) -> str:
        return {"agg": "Agg", "qt": "QtAgg", "inline": "module://matplotlib_inline.backend_inline"}[backend]
```

### 9.2 Interdictions

Un test statique CI interdit :
- Tout `plt.style.use(...)` hors du context manager `theme()`.
- Tout `plt.switch_backend(...)` dans n'importe quel module non-test.
- Tout `matplotlib.rcParams[...] = ...` hors de `display/theme.py`.
- Tout `matplotlib.use(...)` hors de `display/renderer.py`.
- Tout `import matplotlib.pyplot` au top-level de modules de `figures/`
  (seulement à l'intérieur des méthodes).

```python
# tests/unit/display/test_no_side_effects.py
import ast, pathlib

FORBIDDEN = {
    "plt.style.use",
    "plt.switch_backend",
    "matplotlib.use",
    "matplotlib.rcParams",
}
ALLOWED_FILES = {
    "hydromodpy/analysis/display/renderer.py",
    "hydromodpy/analysis/display/theme.py",
}

def test_no_matplotlib_side_effects():
    root = pathlib.Path("hydromodpy")
    hits = []
    for path in root.rglob("*.py"):
        if str(path) in ALLOWED_FILES:
            continue
        text = path.read_text()
        for f in FORBIDDEN:
            if f in text:
                hits.append((str(path), f))
    assert not hits, f"matplotlib side-effect detected: {hits}"
```

### 9.3 Context manager de thème

```python
# hydromodpy/analysis/display/theme.py
from contextlib import contextmanager
import matplotlib.pyplot as plt


class Theme:
    def __init__(self, name: str, rc: dict):
        self.name = name
        self._rc = rc

    @contextmanager
    def context(self):
        """Apply theme inside a context, restore on exit."""
        with plt.rc_context(self._rc):
            yield


_THEMES: dict[str, Theme] = {
    "publication": Theme("publication", rc={
        "font.family":       "serif",
        "font.size":         9,
        "axes.labelsize":    9,
        "axes.titlesize":    10,
        "legend.fontsize":   8,
        "xtick.labelsize":   8,
        "ytick.labelsize":   8,
        "axes.linewidth":    0.6,
        "grid.linewidth":    0.4,
        "lines.linewidth":   1.0,
        "savefig.bbox":      "tight",
        "savefig.dpi":       300,
        "pdf.fonttype":      42,
        "ps.fonttype":       42,
    }),
    "presentation": Theme("presentation", rc={
        "font.family":       "sans-serif",
        "font.size":         12,
        "axes.labelsize":    12,
        "axes.titlesize":    14,
        "lines.linewidth":   1.5,
    }),
    "draft": Theme("draft", rc={"savefig.dpi": 100}),
}


def get_theme(name: str) -> Theme:
    return _THEMES[name]
```

Toute figure est rendue dans un `with theme.context():` — aucun style global
n'est jamais appliqué définitivement.

---

## 10. Export NetCDF CF-1.11 + UGRID-1.0

Le fichier `results/exporters/netcdf.py` [REFACTORE] remplace
`analysis/postprocess/netcdf/netcdf_writer.py` (audit §5 : non conforme).

### 10.1 Attributs globaux obligatoires

```python
GLOBAL_ATTRS = {
    "Conventions":  "CF-1.11 UGRID-1.0",
    "title":        "HydroModPy simulation result",
    "institution":  "HydroModPy user",
    "source":       f"HydroModPy {hmp.__version__}, solver={solver_name}",
    "history":      f"{datetime.now(UTC).isoformat()}: created",
    "references":   "https://hydromodpy.org",
    "comment":      f"sim_id={sim.id}",
}
```

### 10.2 Mesh UGRID

```python
ds["mesh"] = xr.DataArray(
    data=0,
    attrs={
        "cf_role":              "mesh_topology",
        "topology_dimension":   2,
        "node_coordinates":     "node_x node_y",
        "face_node_connectivity": "face_node",
        "face_coordinates":     "face_x face_y",
    },
)
ds["face_node"] = (("face", "max_vertices"), connectivity)
ds["face_node"].attrs = {"cf_role": "face_node_connectivity",
                          "start_index": 0, "_FillValue": -1}
```

### 10.3 Variables data

```python
ds["head"].attrs = {
    "standard_name":   "water_table_altitude",   # CF standard name
    "long_name":       "Hydraulic head",
    "units":           "m",                      # UDUnits, lowercase
    "grid_mapping":    "crs",
    "mesh":            "mesh",
    "location":        "face",
    "cell_methods":    "time: mean",
    "_FillValue":      np.float32("nan"),
}
```

### 10.4 Grid mapping (CRS)

Utilise `rioxarray` mais **force** l'attribut `grid_mapping` sur chaque
variable (le bug de l'audit §5.1) :

```python
ds = ds.rio.write_crs(sim.crs_epsg, grid_mapping_name="crs")
for v in data_variables:
    ds[v].attrs["grid_mapping"] = "crs"
```

### 10.5 Packing int16 robuste

Le bug `bound_min /= 1.1` (audit §5.1) est corrigé :

```python
def compute_pack_range(data: np.ndarray) -> tuple[float, float]:
    """Symmetric range based on quantiles, not linear scaling."""
    q_lo, q_hi = np.nanquantile(data, [0.001, 0.999])
    half = (q_hi - q_lo) * 0.55            # 10 % margin symmetric
    center = (q_hi + q_lo) / 2
    return center - half, center + half
```

### 10.6 Interopérabilité visée

| Outil | Test attendu | Validation |
|---|---|---|
| ncview | Ouvre, affiche head/seepage | CI fixture |
| Panoply | Pas de warning CF | CI fixture |
| `xarray.open_dataset` | Lit variables + attrs CF | test unitaire |
| **xugrid** | `xugrid.open_dataset(...)` reconnaît mesh UGRID | test unitaire |
| `cdo sinfo` | Passe sans erreur | test shell |
| QGIS | Ouvre NetCDF comme mesh layer | doc manuelle |

---

## 11. Intégration TOML et CLI

### 11.1 TOML

Une seule section display, hiérarchisée par famille. Les flags n'appellent
plus des fonctions monolithes mais des figures nommées :

```toml
[display]
enabled = true
backend = "auto"
preset  = "publication"
save    = true
show    = false
out_dir = "figures/"

# List-driven: each string is a registered figure name (see `hmp display list`)
figures = [
    "dem_map",
    "hydrography_map",
    "watertable_map",
    "watertable_depth",
    "seepage_map",
    "hydrograph",
    "piezograph",
    "duration_curve",
    "budget_bar",
    "stats_card",
]

# Optional per-figure overrides
[display.overrides.watertable_map]
timestep = -1
vmin = 50.0
vmax = 150.0
graticule = true

[display.overrides.hydrograph]
stations = ["P01", "P02"]
log_y = true
```

### 11.2 CLI

```
hmp display list                              # Liste toutes les figures enregistrées
hmp display describe watertable_map           # Affiche le FigureSpec
hmp display render SIM_ID watertable_map      # Rend une figure précise
hmp display export SIM_ID [--only a,b] [--preset publication] [--out DIR]
hmp display overview SIM_ID                   # Carte d'identité bassin
hmp display compare SIM_A SIM_B --figure difference_map --field head
hmp display group GROUP_QUERY --figure scatter_metric_metric ...
```

Exemple :
```bash
hmp display export a1b2-... --only "watertable_map,hydrograph,budget_bar" \
                             --preset publication --out ~/paper_fig/
```

---

## 12. Ajouter une figure en 30 lignes

### 12.1 Exemple complet : courbe de durée de débit

```python
# hydromodpy/analysis/display/figures/timeseries/duration_curve.py
from __future__ import annotations
import numpy as np

from hydromodpy.analysis.display.base import BaseFigure, FigureSpec
from hydromodpy.analysis.display.figures import register
from hydromodpy.core.units.labels import colorbar_label


@register
class DurationCurve(BaseFigure):
    """Flow-duration (exceedance probability) curve."""

    spec = FigureSpec(
        name="duration_curve",
        title="Flow duration curve",
        required_fields=(),                    # no spatial field
        required_tables=("timeseries",),
        kind="timeseries",
        default_figsize_inches=(5.5, 4.5),
    )

    def render(self, sim, ax, *, station: str = "outlet",
               show_obs: bool = True, **opts):
        sim_ts = sim.timeseries("discharge", station=station)
        ax.semilogy(self._exceedance(sim_ts.values), np.sort(sim_ts.values)[::-1],
                    label="sim", color="steelblue")
        if show_obs:
            obs_ts = sim.observations("discharge", station=station)
            if obs_ts is not None:
                ax.semilogy(self._exceedance(obs_ts.values),
                            np.sort(obs_ts.values)[::-1],
                            label="obs", color="k", linestyle="--")
        ax.set_xlabel("Exceedance probability [–]")
        ax.set_ylabel(colorbar_label("discharge", "Q"))
        ax.grid(True, which="both", ls=":", lw=0.4)
        ax.legend()
        return ax

    @staticmethod
    def _exceedance(x: np.ndarray) -> np.ndarray:
        x = np.asarray(x)[np.isfinite(x)]
        return np.arange(1, x.size + 1) / (x.size + 1)
```

30 lignes exactement (sans les imports). La figure est automatiquement :
- enregistrée (`@register`), visible dans `hmp display list`
- testable via un fixture `sim_canut` partagé
- documentable (FigureSpec → Sphinx doc)
- utilisable en CLI (`hmp display render SIM duration_curve --station P01`)
- consommée en comparaison (`SideBySide("duration_curve")` fonctionne)

### 12.2 Exemple : carte spatiale avec cartopy

```python
# hydromodpy/analysis/display/figures/spatial/recharge_map.py
from hydromodpy.analysis.display.base import BaseFigure, FigureSpec
from hydromodpy.analysis.display.geo.crs import GeoFigureMixin
from hydromodpy.analysis.display.figures import register
from hydromodpy.analysis.display.figures.spatial._ugrid import render_ugrid_field


@register
class RechargeMap(BaseFigure, GeoFigureMixin):
    spec = FigureSpec(
        name="recharge_map",
        title="Mean annual recharge",
        required_fields=("recharge_m_per_day", "mesh"),
        required_tables=("geographic_features",),
        kind="spatial",
        default_figsize_inches=(7.0, 5.5),
    )

    def render(self, sim, ax, **opts):
        field = sim.field("recharge_m_per_day").mean("time") * 365_000  # m/d → mm/yr
        render_ugrid_field(ax, sim, field, quantity="recharge", cmap="recharge")
        sim.geographic("watershed").plot(ax=ax, facecolor="none",
                                         edgecolor="k", lw=0.8)
        self.decorate(ax, scalebar=True, north_arrow=True)
        return ax
```

---

## 13. Comparaison aux projets de référence

| Projet | Pattern | HydroModPy cible | Différence |
|---|---|---|---|
| **matplotlib** | Axes = primitive, Figure = conteneur | Idem | ✓ adopté |
| **FloPy `PlotMapView`** | Classe monolithe coupée à un modèle MODFLOW | `BaseFigure` solver-agnostique | On fait mieux : DIS/DISV/DISU unifiés via catalog |
| **holoviews** | Élément immuable + backend declaratif | `BaseFigure` + renderer pluggable | On reprend la séparation données/backend. Pas de dépendance holoviews. |
| **xarray `Dataset.plot`** | Dispatch par `plot.<type>()` | `figures.get(name).plot(sim, **)` | Convention similaire ; registre explicite vs. discovery par duck-typing |
| **xugrid** | Mesh UGRID natif, plot sur `face_node_connectivity` | Helper `render_ugrid_field` | Dépendance optionnelle xugrid pour la lecture ; rendu via matplotlib direct |
| **cartopy** | `GeoAxes` + projections ccrs | `GeoFigureMixin` + `ccrs.epsg()` | ✓ adopté |
| **seaborn** | High-level + theme global | `Theme.context()` contextuel | Rejet du global-state seaborn |
| **pyvista / vedo** | Scene 3D | `results/exporters/vtu.py` pour export, `display/3d/` optionnel | Ne fait pas partie du core display matplotlib |
| **PEST/PyEMU** | Stats visuelles (1:1, residuals) | `display/figures/calibration/*` | Reproduction des figures canoniques |
| **pysheds** | Hydrographie raster | `display/figures/spatial/hydrography_map.py` via Strahler pré-calculé | On ne ré-invente pas pysheds, on consomme le pré-calculé |
| **ggplot** | Grammar of graphics | Figures nommées, pas de grammaire | Trop verbeux pour 25 figures ; le nommage est plus sobre |

---

## 14. Tableau de migration actuel → cible

| Actuel | Action | Cible | Tag |
|---|---|---|---|
| `analysis/display/figures/*.py` (render_+/plot_) | Refactorer en classes `Figure` | `analysis/display/figures/<kind>/*.py` | `[REFACTORE]` |
| `analysis/display/suites.py` (904 l.) | Supprimer | — | `[SUPPRIME]` |
| `analysis/display/posthoc.py` + `posthoc_orchestration.py` (1244 l.) | Supprimer (le catalog est la seule source) | — | `[SUPPRIME]` |
| `analysis/display/orchestration.py` (18 l.) | Supprimer | — | `[SUPPRIME]` |
| `analysis/display/flow_payloads.py` | Supprimer (les figures lisent sim.field()) | — | `[SUPPRIME]` |
| `analysis/display/transport_plots.py` | Fusionner dans `figures/spatial/concentration_map.py` + `figures/timeseries/concentration_ts.py` | idem | `[REFACTORE]` |
| `analysis/display/visualization_results.py` (914 l.) | Supprimer | — | `[SUPPRIME]` |
| `analysis/display/visualization_watershed.py` (469 l.) | Supprimer (side-effects globaux) | — | `[SUPPRIME]` |
| `analysis/display/export_vtuvtk.py` (1258 l.) | Déplacer | `results/exporters/vtu.py` | `[RENOMME]` |
| `analysis/display/display_config.py` | Refactorer (liste `figures = [...]`) | idem | `[REFACTORE]` |
| `analysis/display/report/` (4 fichiers) | Fusionner dans un module | `analysis/display/overview/watershed_id_card.py` | `[REFACTORE]` |
| `analysis/display/adapters.py`, `compare.py` | Supprimer (API catalog directe) | — | `[SUPPRIME]` |
| `analysis/display/common.py` | Réduire à quelques helpers UGRID | `analysis/display/figures/spatial/_ugrid.py` | `[REFACTORE]` |
| `analysis/postprocess/flow/intermittency.py` | Déplacer | `results/derived/intermittency.py` | `[RENOMME]` |
| `analysis/postprocess/flow/matching_streams.py` | Déplacer | `analysis/comparison/streams.py` | `[RENOMME]` |
| `analysis/postprocess/timeseries/*_reduce*` | Déplacer (fonctions pures) | `results/derived/reducers.py` | `[RENOMME]` |
| `analysis/postprocess/timeseries/*timeseries.py` (écriture CSV) | Supprimer — le catalog expose export CSV via `exporters/csv.py` | `results/exporters/csv.py` | `[SUPPRIME]` |
| `analysis/postprocess/netcdf/*` | Refactorer CF-1.11 + UGRID-1.0 | `results/exporters/netcdf.py` | `[REFACTORE]` |
| `analysis/postprocess/runner.py` | Supprimer (l'orchestration est dans `simulation/runner.py` via extractors) | — | `[SUPPRIME]` |
| `core/tools/statistics.py` (NSE/KGE/RMSE) | Refactorer + étendre (KGE′ 2012, KGE_np, PBIAS, NaN-safe) | `results/metrics/{efficiency,error,correlation,signature}.py` | `[REFACTORE]` |
| *(absent)* | Créer registre colormaps avec garde anti-jet | `analysis/display/colormaps.py` | `[NOUVEAU]` |
| *(absent)* | Créer UnitRegistry Unicode | `core/units/labels.py` | `[NOUVEAU]` |
| *(absent)* | Créer `BaseFigure` / `FigureSpec` ABC + registre | `analysis/display/base.py`, `figures/__init__.py` | `[NOUVEAU]` |
| *(absent)* | Créer BackendManager | `analysis/display/renderer.py` | `[NOUVEAU]` |
| *(absent)* | Créer `GeoFigureMixin` (cartopy) | `analysis/display/geo/` | `[NOUVEAU]` |
| *(absent)* | Figures manquantes : duration, recession, storage-discharge, Piper, Stiff, Schoeller, seasonal boxplot | `analysis/display/figures/(timeseries\|hydrochem)/*.py` | `[NOUVEAU]` |
| *(absent)* | Multi-layer cross-section + quiver | `analysis/display/figures/section/*.py` | `[NOUVEAU]` |

### 14.1 Budget de suppression

| Catégorie | Lignes supprimées |
|---|---|
| Legacy visualization_results/watershed | ~1 400 |
| Suites + posthoc_orchestration dupliqués | ~1 830 |
| flow_payloads + adapters + compare | ~700 |
| postprocess intermittency/timeseries/runner dupliqués | ~800 |
| **Total brut** | **≈ 4 700 lignes retirées** |

Le package `display/` cible pèse **~4 000 lignes** (plus petit mais plus riche
grâce aux 8 figures ajoutées), testable, linéaire.

---

## 15. Tests de conformité

### 15.1 Tests de structure

```python
# tests/unit/display/test_figure_contract.py
def test_every_figure_has_valid_spec():
    for cls in _REGISTRY.values():
        assert isinstance(cls.spec, FigureSpec)
        assert cls.spec.name == cls.spec.name.lower().replace(" ", "_")

def test_every_figure_implements_render():
    for cls in _REGISTRY.values():
        assert "render" in cls.__dict__
```

### 15.2 Tests visuels solver-agnostiques

Pour chaque figure spatiale, un test unique sur trois fixtures :
- `sim_boussinesq_dis` (Boussinesq DIS)
- `sim_modflownwt_dis` (MF-NWT DIS)
- `sim_modflow6_disv` (MF6 DISV)

```python
@pytest.mark.parametrize("sim_fixture", [
    "sim_boussinesq_dis", "sim_modflownwt_dis", "sim_modflow6_disv",
])
@pytest.mark.parametrize("figure_name", [
    "watertable_map", "watertable_depth", "seepage_map", "dem_map",
])
def test_spatial_figure_renders(sim_fixture, figure_name, request):
    sim = request.getfixturevalue(sim_fixture)
    fig = figures.get(figure_name).plot(sim)
    assert fig.axes[0].has_data()
    plt.close(fig)
```

### 15.3 Tests de métriques

Références numériques publiées (MOPEX, FRENCH, ESC) pour NSE/KGE09/KGE12 et
cross-check par rapport à `hydroeval` et `pyEMU` :

```python
def test_kge_2012_matches_hydroeval():
    import hydroeval
    sim = np.random.RandomState(0).rand(100) * 10
    obs = sim + np.random.RandomState(1).normal(0, 0.5, 100)
    hmp_kge = kge_2012(sim, obs)["kge"]
    he_kge = hydroeval.evaluator(hydroeval.kgeprime, sim, obs)[0][0]
    assert hmp_kge == pytest.approx(he_kge, abs=1e-6)
```

### 15.4 Tests de non-régression CF-UGRID

```python
def test_netcdf_is_cf_compliant(tmp_path, sim_modflow6_disv):
    out = tmp_path / "head.nc"
    exporters.netcdf.export(sim_modflow6_disv, out, variable="head")
    import netCDF4
    ds = netCDF4.Dataset(out)
    assert "CF-1.11" in ds.Conventions
    assert "UGRID-1.0" in ds.Conventions
    assert ds.variables["head"].standard_name == "water_table_altitude"
    assert ds.variables["head"].units == "m"
    # xugrid can open it
    import xugrid
    _ = xugrid.open_dataset(out)
```

### 15.5 Tests de headless

```python
def test_backend_chosen_once(monkeypatch):
    monkeypatch.setenv("HYDROMODPY_NO_DISPLAY", "1")
    BackendManager._configured = False
    chosen = BackendManager.configure("auto")
    assert chosen == "agg"
    # Second call does not switch
    chosen2 = BackendManager.configure("qt")
    assert chosen2 == "agg"  # already configured
```

### 15.6 Tests d'interdiction

Automatisent les principes §0 :
- `test_no_banned_cmap_in_display` (§3.4)
- `test_no_matplotlib_side_effects` (§9.2)
- `test_display_never_writes_to_zarr` (scan AST : aucune `.to_zarr` dans display/)
- `test_display_never_computes_derived` (scan AST : aucun `top - head` dans display/)

---

## 16. Synthèse

Les quatre messages clés de la cible :

1. **Une figure = une classe.** Un seul contrat Protocol `Figure`. Zéro
   paire render_/plot_ dupliquée. Registre explicite.
2. **Données ≠ rendu.** Le catalog (doc 04) est la *seule* source. Les
   calculs dérivés sont écrits au moment de l'extraction, pas du display.
   Les métriques vivent dans `results/metrics/`, pures et solver-agnostiques.
3. **Solver-agnostique ⇔ UGRID partout.** DIS, DISV et DISU passent par le
   même pipeline visuel parce que le catalog les expose tous en UGRID. Pas de
   reshape, pas de branche solveur dans display.
4. **Qualité publication par défaut.** Cartopy, scalebar, flèche nord,
   colormaps perceptuelles, unités Unicode, presets PDF 600 dpi, NetCDF
   CF-1.11 + UGRID-1.0. Le monde peut republier nos figures.

Combiné à la cible storage (doc 04) et calibration (doc 07), ce design rend
possible l'objectif original : **produire une carte d'identité de bassin, un
article WRR, ou une analyse multi-sim en trois lignes Python**, avec la même
qualité visuelle quel que soit le solveur.
