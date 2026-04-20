# Architecture cible HydroModPy — UX, CLI et API publique

**Auteur** : Expert UX developer tools + design d'API scientifique Python
(références : `poetry`, `ruff`, `httpie`, `dvc`, `mlflow`, `pandas`, `xarray`,
`scikit-learn`).
**Branche de référence** : `dev-database` (HEAD `74b62878`).
**Date** : 2026-04-18.
**Portée** : expérience utilisateur END-TO-END — API publique `import hydromodpy as hmp`,
CLI `hmp`, TOML user-friendly, nommage des concepts, prototypage interactif
en Jupyter.
**Sources** : audits `audit_code/01..11`, specs cibles `architecture_cible/01..09`.

> **Intention** : un hydrogéologue qui ouvre `hydromodpy` pour la première
> fois doit (a) lancer sa première simulation en moins de 10 minutes, (b)
> naviguer dans ses résultats sans lire le code source, (c) retrouver la
> même terminologie dans le TOML, le CLI et le Python. Le principe directeur
> est **« vocabulaire unique »** : le mot `simulation` désigne la même chose
> à tous les niveaux.

---

## Table des matières

1. [Principes UX directeurs](#1-principes-ux-directeurs)
2. [Glossaire et nommage des concepts](#2-glossaire-et-nommage-des-concepts)
3. [API Python publique `hmp.*`](#3-api-python-publique-hmp)
4. [Sessions interactives Jupyter — exemples complets](#4-sessions-interactives-jupyter--exemples-complets)
5. [CLI `hmp` — arbre complet des commandes](#5-cli-hmp--arbre-complet-des-commandes)
6. [Configuration TOML user-friendly](#6-configuration-toml-user-friendly)
7. [Messages d'erreur et diagnostics](#7-messages-derreur-et-diagnostics)
8. [Prototypage interactif et fluent API](#8-prototypage-interactif-et-fluent-api)
9. [Auto-complétion et découvrabilité](#9-auto-complétion-et-découvrabilité)
10. [Comparatif avec les outils de référence](#10-comparatif-avec-les-outils-de-référence)
11. [Matrice de migration actuel → cible](#11-matrice-de-migration-actuel--cible)

---

## 1. Principes UX directeurs

### 1.1 Les 12 règles

| # | Règle | Justification | Source |
|---|---|---|---|
| 1 | **Vocabulaire unique** à tous les niveaux (API, CLI, TOML, docs). Un concept = un mot. | `poetry` dit `add` partout. `ruff` dit `check` partout. | Audit §4 : `project` ≠ `Simulation` ≠ `run` actuellement — confusion garantie. |
| 2 | **Découvrabilité par `dir()` et `help()`**. Tout objet public a un `__repr__`, un `_repr_html_`, des `docstrings` numpy. | `pandas.DataFrame?` dans IPython est un standard absolu. | — |
| 3 | **Lire > Écrire** : l'API doit être plus simple quand on consulte qu'on construit. | `xarray.open_dataset(path)` ouvre en 1 ligne. Construire un `Dataset` demande plus. | — |
| 4 | **Path-first** : chaque objet avec persistance a `.path` (Path), `.workspace` (Path) et un `__fspath__`. Interopère avec `os.path`, `pathlib`, `np.load`. | `pathlib` est universel en Python scientifique. | — |
| 5 | **Types de retour homogènes** : tableau spatial → `np.ndarray` ou `xr.DataArray`; série temporelle → `pd.Series`; tabulaire multi-dim → `pd.DataFrame`; chemin → `pathlib.Path`. Jamais de tuple anonyme. | `xarray`, `pandas`, `sklearn` le font tous. | Audit §6.8 : `Any` massif aujourd'hui. |
| 6 | **Progression mentale** : utilisateur novice → prototype → production, sans réapprendre le vocabulaire. Les trois niveaux de `CLAUDE.md` (cases, prototyping, TOML) partagent les mêmes noms d'objets. | sklearn : `fit`/`predict` marche pour débutant et expert. | — |
| 7 | **Defaults opinionés, overrides explicites**. Un TOML minimal de 5 lignes doit tourner. Chaque override se voit dans le TOML (pas de magie). | `ruff` tourne sans config, `poetry` aussi. | — |
| 8 | **Erreurs pédagogiques** : message + cause + suggestion de correction. | `ruff` et `pydantic` v2 montrent la colonne, la valeur invalide, et `expected: int`. | Audit §5.2 : `try/except: pass` silencieux — anti-pattern. |
| 9 | **Idempotence et réversibilité** : `hmp run` sur la même simulation produit le même `sim_id` (hash des inputs). Pas de doublons silencieux. | `dvc`, `mlflow` le font. | Spec 04 : Zarr par `sim_id`. |
| 10 | **Progress bars pour > 1 s, silence pour < 100 ms**. Toute commande dépassant 1 s affiche `rich.progress`. En dessous, silence. | `pip install` le fait parfaitement. | Audit §2.1 : aujourd'hui rien. |
| 11 | **CLI et API font EXACTEMENT la même chose**. `hmp run x.toml` ↔ `hmp.Simulation("x.toml").run()`. Pas d'écart fonctionnel. | `dvc repro` ↔ `dvc.api.repro`. | Audit §2 : double chemin `_run_with_overrides` vs `_run_from_plan` aujourd'hui. |
| 12 | **Pas de fichier caché inexpliqué**. Si HydroModPy crée un fichier, l'utilisateur peut le localiser via `hmp inspect` ou `sim.path`. | `git` expose `.git/objects/`, mais `git status` l'explique. | — |

### 1.2 Profils utilisateurs cibles

| Profil | Premier contact | Commande 1 | Commande 2 | Commande 3 |
|---|---|---|---|---|
| **Hydrogéologue** (terrain, peu de Python) | CLI + TOML | `hmp init` | `hmp config wizard` | `hmp run project.toml` |
| **Étudiant** (master, thèse) | Notebook Jupyter | `import hydromodpy as hmp` | `sim = hmp.Simulation("case.toml")` | `sim.run()` |
| **Data scientist** (post-hoc ML) | Notebook Jupyter + catalogue | `catalog = hmp.open("~/ws")` | `catalog.simulations` | `catalog.to_frame()` |
| **Développeur** (contributeur) | Git + pytest | `pytest tests/unit/ -v` | `hmp doctor` | `ruff check` |

Chaque parcours doit **aboutir sans lire `CLAUDE.md`**.

---

## 2. Glossaire et nommage des concepts

> **Règle absolue** : ce tableau est la référence. Tout le code, le TOML,
> la doc, les messages d'erreur utilisent ces mots, dans ces sens, sans variante.

### 2.1 Les 7 concepts fondamentaux

| Terme | Définition précise | Implémentation | Utilisé dans |
|---|---|---|---|
| **Workspace** | Répertoire contenant `hydromodpy.duckdb`, `data/`, `simulations/`, `configs/`. Un workspace = un disque dur logique. | `core.workspace.Workspace` | API, CLI (`hmp init`), TOML (`[workspace]`) |
| **Project** | Étiquette libre regroupant plusieurs simulations (ex. `"canut"`, `"brittany_2024"`). **PAS un dossier**, juste une valeur dans la colonne `project` du DuckDB. | `project: str` — champ | API (`catalog.find(project=...)`), CLI (`hmp list --project`), TOML (`project = "canut"`) |
| **Simulation** | **Une exécution unique** d'un solveur sur un domaine, avec des paramètres, produisant des résultats stockés dans un Zarr dédié. Identifiée par un UUID v4. | `results.simulation.Simulation`, `results.catalog.SimulationCatalog.register_simulation()` | API (`hmp.Simulation`, `catalog.best()`), CLI (`hmp run`, `hmp inspect`), TOML (`[simulation]`) |
| **Run** | **SYNONYME DE SIMULATION**. Éliminé du vocabulaire public. Garde le nom `run_id` uniquement pour la colonne SQL (compat). | — | Nulle part en API publique. |
| **SimulationPlan** | Description déclarative immuable d'une simulation à exécuter (liste de `ProcessRun` + dépendances). Produit par le `SimulationPlanner`. | `simulation.planning.SimulationPlan` (`@dataclass(frozen=True)`) | API avancée (inspection du plan avant exécution) |
| **Catalog** | L'interface DuckDB+Zarr du workspace. Une seule `hydromodpy.duckdb` par workspace, ouverte par `hmp.open()`. | `results.catalog.SimulationCatalog` | API (`hmp.open()`, `SimulationCatalog`), CLI (`hmp list`, `hmp export`) |
| **Config** | Un TOML Pydantic-validé, source unique de vérité pour une exécution. | `core.config.HydroModPyConfig` | API, CLI (`hmp config`, `hmp run`), TOML (fichier lui-même) |

### 2.2 Les nuances éliminées

| Confusion actuelle | Résolution |
|---|---|
| `hmp.Simulation` vit dans `hydromodpy/project.py` | **[R]** Renommé en `hydromodpy/simulation/api.py`. Fichier = classe. |
| `self._project_name = ws.project_root.name` dans `Simulation.__init__` | **[R]** Renommé `self._project_label`. Un projet n'est PAS un dossier. |
| `with Simulation(config) as project:` | **[F]** Le binding d'aide devient `with hmp.Simulation(config) as sim:`. |
| `runner`, `launcher`, `runtime`, `workflow`, `pipeline` utilisés indistinctement | **[F]** Un seul mot : `workflow` (pour le verbe TOML), une seule classe : `SimulationWorkflow`. |
| `_catchment` comme nom de station magique pour l'aggrégat | **[R]** Renommé `"_basin_mean"` (explicite, PEP-8 pour privé). Exposé via `sim.timeseries(variable, scope="basin")`. |
| `run_id` vs `sim_id` vs `name` | **[F]** Trois notions distinctes clarifiées : `sim_id` = UUID technique, `name` = label humain, `run_id` = alias legacy supprimé de l'API publique. |

### 2.3 Verbes de l'API (cohérents CLI ↔ Python)

| Verbe | CLI | Python | Sens |
|---|---|---|---|
| **open** | — | `hmp.open(ws)` | Ouvrir un workspace → `SimulationCatalog` |
| **init** | `hmp init <path>` | `hmp.Workspace.init(path)` | Créer un workspace vide |
| **new** | `hmp new <name>` | `hmp.Workspace.new_project(name)` | Préparer des fichiers projet |
| **run** | `hmp run <cfg>` | `hmp.Simulation(cfg).run()` | Exécuter une simulation |
| **list** | `hmp list` | `catalog.simulations` | Inventaire |
| **find** | — | `catalog.find(...)` | Filtrage |
| **best/worst** | `hmp best <project>` | `catalog.best(...)` | Sélection extrême |
| **inspect** | `hmp inspect <id>` | `sim.inspect()` | Métadonnées détaillées |
| **export** | `hmp export <id>` | `sim.export(...)` | Exporter vers format externe |
| **import** | `hmp import <pkg>` | `catalog.import_package(pkg)` | Importer un `.hmp` |
| **compare** | `hmp compare A B` | `hmp.compare(A, B)` | Comparaison 2 sims |
| **validate** | `hmp validate <cfg>` | `hmp.HydroModPyConfig.from_toml(cfg)` | Validation Pydantic sans exécution |
| **display** | `hmp display <id>` | `sim.plot(...)` | Figures |
| **doctor** | `hmp doctor` | `hmp.doctor()` | Diagnostic env |

---

## 3. API Python publique `hmp.*`

### 3.1 Symboles exposés au top-level (22 symboles)

```python
# hydromodpy/__init__.py — cible (≤ 80 lignes, cf. spec 01)
__all__ = [
    # === Entrée workspace ===
    "open",               # hmp.open(path) → SimulationCatalog
    "Workspace",
    "doctor",             # hmp.doctor() → dict diagnostic

    # === Configuration ===
    "HydroModPyConfig",

    # === Domaine & maillage ===
    "Geographic",
    "Domain",
    "HydroMesh",

    # === Physique ===
    "Flow",
    "Transport",

    # === Solveurs (symétrie COMPLÈTE) ===
    "Modflow",            # MODFLOW-NWT (alias historique conservé)
    "Modflow6",
    "Modpath7",
    "Mt3dms",
    "Boussinesq",         # exposé enfin

    # === Orchestration ===
    "Simulation",         # classe programmatique publique
    "SimulationPlan",     # plan immuable (inspection)

    # === Résultats ===
    "SimulationCatalog",
    "SimulationResult",
    "SimulationGroup",    # requêtes groupées

    # === Comparaison fonctionnelle ===
    "compare",            # hmp.compare(sim_a, sim_b) → ComparisonResult

    # === Sous-modules ===
    "data", "spatial", "physics", "solver", "simulation",
    "results", "analysis", "core",

    # === Divers ===
    "__version__",
    "log_manager",
]
```

**Différence majeure avec l'existant** :

- [C] `Simulation`, `SimulationCatalog`, `Workspace`, `Geographic`
- [N] `Boussinesq`, `Flow`, `Transport`, `Modflow6`, `Modpath7`,
  `HydroMesh`, `Domain`, `SimulationGroup`, `SimulationPlan`, `compare`,
  `doctor`
- [K] `Hydrometry`, `Piezometry`, `Subbasin`, `HydrographyConfig`,
  `HydrographyManager`, `HydrographyResult`, `IntermittencyConfig`,
  `IntermittencyManager`, `OceanicConfig`, `OceanicManager`
  → accessibles en sous-module (`hmp.data.hydrometry`, etc.)
- [K] `WorkspaceConfig`, `GeographicConfig` → accessibles via
  `hmp.core.config.WorkspaceConfig`

### 3.2 Types de retour — convention stricte

| Méthode | Type retour | Justification |
|---|---|---|
| `sim.field(variable, timestep)` | `xr.DataArray` | Coordonnées `(cell_id, x, y, layer)` + attrs CF/unités. Remplace `np.ndarray` anonyme. |
| `sim.timeseries(variable, station=...)` | `pd.Series` (single) ou `pd.DataFrame` (multi-station) | Index = `DatetimeIndex`. |
| `sim.budget(zone=None)` | `pd.DataFrame` | Colonnes `(component, zone_id, flux, time)`. |
| `sim.metrics(station=None)` | `pd.DataFrame` ou `pd.Series` | NSE, KGE, RMSE. |
| `sim.parameters` | `pd.DataFrame` | `(param_name, zone_id, value)`. |
| `sim.mesh` | `HydroMesh` | Objet mesh (jamais tuple). |
| `sim.geographic` | `xr.Dataset` | DEM, watershed mask, etc. |
| `sim.path` | `pathlib.Path` | Chemin vers le Zarr. |
| `sim.config` | `HydroModPyConfig` | Config Pydantic utilisée. |
| `sim.export(fmt)` | `pathlib.Path` | Chemin du fichier créé. |
| `catalog.simulations` | `pd.DataFrame` | Inventaire. |
| `catalog.find(...)` | `SimulationGroup` | Collection de `Simulation`. |
| `catalog.best(project, metric)` | `Simulation` | Une simulation, pas un groupe. |
| `catalog.to_frame()` | `pd.DataFrame` | Table jointe pour ML. |
| `group.pivot(index, columns, values)` | `pd.DataFrame` | Pivot sur métadonnées. |
| `group.to_frame()` | `pd.DataFrame` | Table jointe. |
| `group.to_netcdf(path)` | `pathlib.Path` | Chemin. |

**Règle** : jamais `Any`, jamais `tuple` anonyme. Si la méthode retourne
plusieurs choses, utiliser une `NamedTuple` typée ou un `dataclass`.

### 3.3 Signatures de classes — contrats minimaux

Squelette `Simulation` (API programmatique haut niveau) :

```python
# hydromodpy/simulation/api.py (cible, ex-project.py)
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self
import pandas as pd
import xarray as xr

from hydromodpy.core.config import HydroModPyConfig
from hydromodpy.results.catalog import SimulationCatalog
from hydromodpy.results.simulation import Simulation as SimulationView


class Simulation:
    """Façade programmatique pour construire et exécuter une simulation.

    Setup-once, run-many. Équivalent Python de ``hmp run config.toml``.
    Les deux partagent le MÊME workflow interne (pas de code dupliqué).

    Parameters
    ----------
    config : str, Path, or HydroModPyConfig
        Chemin TOML ou objet Pydantic déjà chargé.
    headless : bool, default False
        Désactive les figures (boucle de calibration).

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> sim = hmp.Simulation("canut_baseline.toml")
    >>> result = sim.run(name="baseline", Sy=0.05)
    >>> wt = result.field("watertable_depth", timestep=-1)

    Parameter sweep:

    >>> for k in [1e-6, 1e-5, 1e-4]:
    ...     sim.run(name=f"k_{k:.0e}", K=k)

    Context manager (ferme proprement DuckDB):

    >>> with hmp.Simulation("canut.toml") as sim:
    ...     r = sim.run()
    """

    def __init__(
        self,
        config: str | Path | HydroModPyConfig,
        *,
        headless: bool = False,
    ) -> None: ...

    # ---- Propriétés immutables (introspection) ----
    @property
    def config(self) -> HydroModPyConfig: ...

    @property
    def workspace(self) -> Path: ...

    @property
    def catalog(self) -> SimulationCatalog: ...

    @property
    def mesh(self) -> "HydroMesh": ...

    @property
    def geographic(self) -> xr.Dataset: ...

    @property
    def plan(self) -> "SimulationPlan":
        """Plan résolu (immuable) avant exécution."""

    # ---- Actions ----
    def run(
        self,
        *,
        name: str | None = None,
        project: str | None = None,
        tag: list[str] | None = None,
        **overrides: float | dict,
    ) -> SimulationView:
        """Exécute une simulation et renvoie un SimulationView (catalogue)."""

    def dry_run(self) -> "SimulationPlan":
        """Valide la config + construit le plan sans exécuter."""

    def close(self) -> None: ...

    # ---- Context manager ----
    def __enter__(self) -> Self: ...
    def __exit__(self, *exc_info) -> None: ...

    # ---- Jupyter rendering ----
    def _repr_html_(self) -> str: ...
```

Squelette `SimulationCatalog` (consultation) :

```python
# hydromodpy/results/catalog.py (cible)
from typing import Literal

class SimulationCatalog:
    """Catalogue DuckDB+Zarr d'un workspace. Lecture/écriture unifiée.

    Ouvert par ``hmp.open(workspace)``. Gestionnaire de contexte.
    """

    def __init__(self, workspace: str | Path) -> None: ...

    # ---- Introspection ----
    @property
    def path(self) -> Path: ...
    @property
    def simulations(self) -> pd.DataFrame:
        """Vue tabulaire de toutes les simulations."""

    @property
    def projects(self) -> list[str]:
        """Liste des labels project."""

    # ---- Recherche ----
    def find(
        self,
        *,
        project: str | None = None,
        solver: str | None = None,
        tag: str | list[str] | None = None,
        nse_gt: float | None = None,
        kge_gt: float | None = None,
        rmse_lt: float | None = None,
        after: str | pd.Timestamp | None = None,
        before: str | pd.Timestamp | None = None,
        status: Literal["success", "failed", "running"] | None = None,
    ) -> "SimulationGroup":
        """Filtrage multi-critère → SimulationGroup."""

    def get(self, sim_id: str) -> "SimulationView":
        """Récupère une simulation par UUID (ou prefix unique)."""

    def best(self, project: str, metric: str = "nse") -> "SimulationView":
        """Meilleure simulation d'un projet pour une métrique."""

    def worst(self, project: str, metric: str = "nse") -> "SimulationView":
        """Pire."""

    # ---- Export & partage ----
    def export_package(
        self, sim_id: str | list[str], path: str | Path,
    ) -> Path:
        """Exporte en .hmp portable (DuckDB rows + Zarr tree + manifest)."""

    def import_package(self, path: str | Path) -> list[str]:
        """Importe un .hmp, renvoie les nouveaux sim_ids."""

    # ---- Administration ----
    def vacuum(self) -> None: ...
    def migrate(self) -> None:
        """Migre le schéma DuckDB vers la version courante."""

    def close(self) -> None: ...

    # ---- Jupyter ----
    def __repr__(self) -> str: ...
    def _repr_html_(self) -> str: ...

    # ---- Iteration ----
    def __iter__(self): ...    # yield SimulationView
    def __len__(self) -> int: ...
    def __contains__(self, sim_id: str) -> bool: ...
```

Squelette `SimulationView` (objet-simulation depuis le catalogue) :

```python
# hydromodpy/results/simulation.py (cible)
class Simulation:
    """Vue haute-niveau sur une simulation stockée (read-only).

    Obtenue via ``catalog.best()``, ``catalog.find(...)``, ``catalog.get(id)``
    ou comme retour de ``hmp.Simulation(...).run()``.
    """

    @property
    def sim_id(self) -> str: ...
    @property
    def name(self) -> str: ...
    @property
    def project(self) -> str: ...
    @property
    def solver(self) -> str: ...
    @property
    def status(self) -> Literal["success", "failed", "running"]: ...
    @property
    def path(self) -> Path:
        """Chemin vers le Zarr de cette simulation."""
    @property
    def tags(self) -> list[str]: ...
    @property
    def config(self) -> HydroModPyConfig: ...

    # ---- Métriques ----
    @property
    def nse(self) -> float | None: ...
    @property
    def kge(self) -> float | None: ...
    @property
    def rmse(self) -> float | None: ...

    def metrics(self, station: str | None = None) -> pd.DataFrame: ...

    # ---- Champs spatiaux ----
    def field(
        self,
        variable: str,
        timestep: int | str | pd.Timestamp = -1,
        layer: int | None = None,
    ) -> xr.DataArray:
        """Champ spatial à un instant.

        Parameters
        ----------
        variable : str
            ``'head'``, ``'watertable_depth'``, ``'watertable_elevation'``,
            ``'seepage'``, ``'recharge'``, ``'transmissivity'``.
        timestep : int, str, or pd.Timestamp
            Index positionnel (-1 = dernier) OU date ``'2020-06-15'`` OU
            ``'initial'`` / ``'steady_state'`` / ``'final'``.
        """

    def fields(self, variable: str) -> xr.DataArray:
        """Tous les timesteps d'un champ (DataArray 3D/4D)."""

    # ---- Séries temporelles ----
    def timeseries(
        self,
        variable: str,
        station: str | list[str] | None = None,
        scope: Literal["station", "basin", "outlet"] = "station",
        period: tuple[str, str] | None = None,
    ) -> pd.Series | pd.DataFrame: ...

    # ---- Bilans ----
    def budget(
        self,
        zone: int | str | None = None,
        component: str | None = None,
        period: tuple[str, str] | None = None,
    ) -> pd.DataFrame: ...

    # ---- Paramètres ----
    @property
    def parameters(self) -> pd.DataFrame: ...

    # ---- Mesh ----
    @property
    def mesh(self) -> "HydroMesh": ...

    # ---- Figures ----
    def plot(
        self,
        kind: str,
        *,
        save: str | Path | None = None,
        show: bool = True,
        ax=None,
        **kwargs,
    ) -> "Axes":
        """Produit une figure.

        kind : ``'watertable_map'``, ``'watertable_series'``, ``'recharge_map'``,
        ``'mesh'``, ``'bilan'``, ``'observations'``, ``'seepage'``.
        """

    # ---- Export ----
    def export(
        self,
        fmt: Literal["netcdf","csv","geotiff","vtu","shapefile","gpkg"],
        *,
        variable: str = "*",
        path: str | Path | None = None,
        **kwargs,
    ) -> Path: ...

    def to_xarray(self) -> xr.Dataset:
        """Convertit l'ensemble des champs en Dataset xarray."""

    # ---- Jupyter ----
    def __repr__(self) -> str:
        return f"Simulation(name={self.name!r}, solver={self.solver!r}, "\
               f"nse={self.nse:.3f if self.nse else None}, "\
               f"sim_id={self.sim_id[:8]}...)"

    def _repr_html_(self) -> str: ...
    def inspect(self) -> dict:
        """Dump complet des métadonnées (pour debug, CLI)."""
```

Squelette `SimulationGroup` :

```python
# hydromodpy/results/simulation_group.py (cible)
class SimulationGroup:
    """Collection itérable de Simulation avec opérations groupées."""

    def __init__(self, catalog: SimulationCatalog, sim_ids: list[str]): ...

    def __iter__(self): ...
    def __len__(self) -> int: ...
    def __getitem__(self, key: int | slice | str) -> "Simulation" | "SimulationGroup": ...

    @property
    def simulations(self) -> pd.DataFrame: ...

    # ---- Agrégation ----
    def pivot(self, index: str, columns: str, values: str) -> pd.DataFrame: ...
    def to_frame(self) -> pd.DataFrame:
        """Table jointe (metrics + parameters + metadata) pour ML."""

    # ---- Filtrage chaînable ----
    def filter(self, **criteria) -> "SimulationGroup": ...

    # ---- Actions en lot ----
    def export(self, fmt: str, path: str | Path) -> list[Path]: ...
    def delete(self, *, confirm: bool = False) -> int: ...

    # ---- Plot ----
    def plot(self, kind: str, **kwargs): ...
    def _repr_html_(self) -> str: ...
```

### 3.4 Conventions de signature

| Convention | Exemple | Rationale |
|---|---|---|
| **Keyword-only au-delà du premier argument** | `sim.run(name="x", *, Sy=0.05)` | Lisibilité, cf. `pandas` |
| **Typing complet** (pas de `Any`) | `station: str \| list[str] \| None = None` | IDE completion, mypy, doc auto |
| **Docstrings numpy** | Sections `Parameters`, `Returns`, `Examples` | Compatible Sphinx napoleon |
| **`__repr__` informatif** | `Simulation(name='baseline', nse=0.82)` | Debug-friendly |
| **`_repr_html_` pour Jupyter** | Petit tableau HTML | Session interactive |
| **`__fspath__` sur tout objet à chemin** | `os.path.join(sim, "foo")` fonctionne | Interop `pathlib`, `os.path` |
| **Context manager pour tout objet ayant `.close()`** | `with hmp.open(ws) as cat:` | Économise des fuites DuckDB |

---

## 4. Sessions interactives Jupyter — exemples complets

### 4.1 Session 1 — Découverte : un hydrogéologue ouvre un workspace existant

```python
# ============================================================================
# Cellule 1 — Import et ouverture
# ============================================================================
import hydromodpy as hmp

# Convention mimant xarray.open_dataset / pandas.read_csv
catalog = hmp.open("~/workspaces/brittany")

# repr HTML élégant en sortie de cellule
catalog
# ┌─────────────────────────────────────────┐
# │ SimulationCatalog                        │
# │ workspace : /home/bb/workspaces/brittany │
# │ projects  : canut, vilaine, odet (3)     │
# │ sims      : 142 (130 success, 12 failed) │
# │ schema    : v5                           │
# └─────────────────────────────────────────┘

# ============================================================================
# Cellule 2 — Inventaire
# ============================================================================
catalog.simulations.head(10)
# Affiche DataFrame : sim_id, name, project, solver, nse, kge, duration_s, date

catalog.projects
# ['canut', 'vilaine', 'odet']

# ============================================================================
# Cellule 3 — Exploration d'un projet
# ============================================================================
group = catalog.find(project="canut", nse_gt=0.5)
group
# ┌────────────────────────────────────────┐
# │ SimulationGroup                         │
# │ project=canut, 24 simulations           │
# │ NSE  : 0.52 → 0.89 (median 0.71)        │
# │ solvers : modflow_nwt(18), boussinesq(6)│
# └────────────────────────────────────────┘

# Pivot rapide parameters vs runs
group.pivot(index="name", columns="parameter", values="value").head()

# ============================================================================
# Cellule 4 — Meilleure simulation
# ============================================================================
best = catalog.best(project="canut", metric="nse")
best
# ┌────────────────────────────────────────────┐
# │ Simulation: canut_sy0015_k3e5              │
# │ sim_id  : 3b7a92f1-...                     │
# │ solver  : modflow_nwt                      │
# │ status  : success                          │
# │ NSE     : 0.89    KGE : 0.85   RMSE : 0.27 │
# │ period  : 2015-01-01 → 2020-12-31          │
# │ mesh    : 4 326 cells (cartesian)          │
# └────────────────────────────────────────────┘

# ============================================================================
# Cellule 5 — Cartes et séries
# ============================================================================
# xarray.DataArray, peut être affiché directement
wt_map = best.field("watertable_depth", timestep="2020-06-15")
wt_map.plot.imshow(cmap="crest")  # palette perceptuelle — pas de jet

# pd.Series avec DatetimeIndex
outflow = best.timeseries("outflow", scope="basin")
outflow.resample("ME").mean().plot()

# ============================================================================
# Cellule 6 — Partage
# ============================================================================
pkg = best.export("netcdf", path="~/share/canut_best.nc")
# pkg = PosixPath('/home/bb/share/canut_best.nc')

# Ou package portable complet
pkg = catalog.export_package(best.sim_id, path="~/share/canut_best.hmp")
```

### 4.2 Session 2 — Prototypage : construire une simulation from scratch (sans TOML)

```python
# ============================================================================
# Cellule 1 — Définir les blocs
# ============================================================================
import hydromodpy as hmp
from pathlib import Path

ws = hmp.Workspace.init("~/workspaces/dev")

# Construction type sklearn : objets configurables, composés
geo = hmp.Geographic(
    extent_shp="~/shp/canut.shp",
    crs=2154,
    dem_resolution=50,
    buffer=300,
)
geo.delineate()    # calcule watershed, streams, subbasins
geo
# Geographic(catch_area=34.2 km², n_cells_dem=13 694, crs=EPSG:2154)

# ============================================================================
# Cellule 2 — Mesh
# ============================================================================
mesh = hmp.HydroMesh.from_catchment(
    geo,
    kind="cartesian",
    resolution=50,
    nlay=2,
)
mesh
# HydroMesh(kind=cartesian, n_cells=4326, nlay=2, cell_type=quad)

mesh.plot()  # matplotlib figure

# ============================================================================
# Cellule 3 — Domaine + physique
# ============================================================================
domain = hmp.Domain.from_mesh(
    mesh,
    zones=["geology"],
    depth=30.0,
)

flow = hmp.Flow(
    regime="transient",
    parameters={"Sy": 0.05, "K": 1e-5, "Ss": 1e-6},
    boundary_conditions=["drain"],
    forcings={"recharge": "~/data/recharge/canut.csv"},
)

# ============================================================================
# Cellule 4 — Solveur
# ============================================================================
solver = hmp.Modflow6(
    time_discretization={"start": "2015-01-01", "end": "2020-12-31", "step": "1M"},
    numerics={"outer_max_iter": 100, "inner_max_iter": 50},
)

# ============================================================================
# Cellule 5 — Plan + exécution
# ============================================================================
plan = hmp.SimulationPlan.build(
    geographic=geo,
    domain=domain,
    flow=flow,
    solver=solver,
)
plan  # affiche un arbre de dépendance + durée estimée

with hmp.open(ws) as catalog:
    sim = hmp.Simulation.run_plan(
        plan,
        catalog=catalog,
        name="canut_first",
        project="canut",
    )

# Enchaînement fluent pour inspection
sim.field("head", -1).plot()
sim.timeseries("outflow").plot()
```

### 4.3 Session 3 — Parameter sweep + comparaison

```python
# ============================================================================
# Cellule 1 — Setup once
# ============================================================================
import hydromodpy as hmp
import numpy as np

sim_builder = hmp.Simulation("canut.toml", headless=True)

# ============================================================================
# Cellule 2 — Sweep
# ============================================================================
from tqdm.notebook import tqdm

results = []
for sy in tqdm(np.logspace(-4, -1, 10)):
    r = sim_builder.run(name=f"sy_{sy:.4f}", tag=["sweep_sy"], Sy=sy)
    results.append(r)

# ============================================================================
# Cellule 3 — Analyse groupée
# ============================================================================
catalog = sim_builder.catalog
group = catalog.find(tag="sweep_sy")
df = group.to_frame()    # colonnes : sy, nse, kge, rmse, ...
df.plot(x="Sy", y="nse", marker="o", logx=True)

# ============================================================================
# Cellule 4 — Comparaison explicite A vs B
# ============================================================================
best = group.best()
worst = group.worst()

comp = hmp.compare(best, worst, variables=["head", "outflow"])
# ComparisonResult : diff fields, metrics delta, side-by-side plots
comp.plot()
comp.to_netcdf("~/share/canut_best_vs_worst.nc")
```

### 4.4 Session 4 — ML-ready export

```python
# ============================================================================
# Cellule 1 — Charger en DataFrame large
# ============================================================================
import hydromodpy as hmp
import pandas as pd

catalog = hmp.open("~/workspaces/brittany")
group = catalog.find(project="canut")

# Table jointe (1 ligne par simulation)
X = group.to_frame(
    include_params=True,          # colonnes Sy, K, Ss, ...
    include_metrics=True,          # nse, kge, rmse
    include_metadata=True,         # solver, n_cells, duration_s
    include_geographic=True,       # catch_area, mean_elevation, slope_mean
)
# X : 24 rows × 32 cols, pd.DataFrame
X.head()

# ============================================================================
# Cellule 2 — Splits ML classiques
# ============================================================================
from sklearn.model_selection import train_test_split

y = X.pop("nse")
X_train, X_test, y_train, y_test = train_test_split(X, y, random_state=42)

# ============================================================================
# Cellule 3 — Export pour collaborateur sans HydroModPy
# ============================================================================
X.to_parquet("~/share/canut_surrogate_training.parquet")
```

### 4.5 Session 5 — Données spatio-temporelles xarray

```python
# ============================================================================
# Tous les champs d'une simulation en Dataset xarray
# ============================================================================
ds = best.to_xarray()
ds
# <xarray.Dataset>
# Dimensions: (time: 72, layer: 2, cell: 4326, x: 103, y: 105)
# Coordinates:
#     x         (x) float64
#     y         (y) float64
#     time      (time) datetime64[ns]
# Data variables:
#     head                 (time, layer, cell) float32
#     watertable_depth     (time, cell) float32
#     recharge             (time, cell) float32
# Attributes:
#     solver   : modflow_nwt
#     crs      : EPSG:2154
#     Conventions : CF-1.8, UGRID-1.0

# Zoom spatial + temporel en une ligne
ds.watertable_depth.sel(time="2020").mean(dim="time").plot()
```

---

## 5. CLI `hmp` — arbre complet des commandes

### 5.1 Vue d'ensemble

Deux binaires (`hmp`, `hydromodpy`) installés par `pyproject.toml` pointent sur
`hydromodpy._cli.main:main`. Style Git-like : `hmp <verbe> [options]`.

```
hmp <verbe>
├── init          Créer un workspace
├── new           Créer un projet dans un workspace
├── config        Gérer les TOML (wizard, check, template)
│   ├── wizard      Assistant interactif
│   ├── check       Validation Pydantic
│   └── template    Génère un TOML par profil
├── run           Exécuter une simulation (auto-détection workflow)
├── list          Inventaire
├── show          Détail d'une simulation ou d'un projet
├── compare       Comparer deux simulations
├── export        Exporter un résultat (format)
├── import        Importer un package .hmp
├── delete        Supprimer (avec confirmation)
├── display       Régénérer figures post-hoc
├── doctor        Diagnostic d'environnement
├── completion    Générer script de complétion shell
├── --version     Afficher la version
└── --help        Afficher l'aide
```

### 5.2 Détail des commandes

#### 5.2.1 `hmp init`

**Rôle** : créer un workspace (DuckDB + arborescence).

```
Usage: hmp init [PATH] [OPTIONS]

Arguments:
  PATH                       Workspace directory [default: ./workspace]

Options:
  --template TEXT            minimal | full  [default: minimal]
  --force                    Overwrite existing
  -v, --verbose              Verbose output
  -h, --help

Examples:
  hmp init                             # crée ./workspace
  hmp init ~/hydromodpy-ws             # chemin explicite
  hmp init ws --template full          # avec exemple de projet
```

**Output attendu** :
```
✓ Workspace created at /home/bb/hydromodpy-ws
  ├─ hydromodpy.duckdb    (schema v5)
  ├─ data/
  ├─ simulations/
  └─ configs/

Next steps:
  1. hmp config wizard --output configs/first_project.toml
  2. hmp run configs/first_project.toml
```

**Exit codes** : 0 ok; 1 if path exists and not `--force`.

#### 5.2.2 `hmp new`

**Rôle** : générer un template de projet prêt à éditer.

```
Usage: hmp new NAME [OPTIONS]

Arguments:
  NAME                       Project label (identifier)

Options:
  --workspace PATH           Workspace root [auto-detect]
  --from TEXT                Template: demo | analytical | calibration
  --solver TEXT              Pre-filled solver: nwt | mf6 | boussinesq
  --profile TEXT             TOML verbosity: user | dev | expert
  -h, --help

Examples:
  hmp new canut
  hmp new canut --from demo --solver mf6
  hmp new canut --profile expert
```

**Output attendu** :
```
✓ Project 'canut' initialized
  configs/canut/project.toml         # settings partagés
  configs/canut/run_baseline.toml    # un run exécutable

Next: hmp run configs/canut/run_baseline.toml
```

#### 5.2.3 `hmp config`

Commande parent avec 3 sous-verbes :

```
Usage: hmp config <SUBCOMMAND>

Subcommands:
  template       Generate a TOML template (profile-aware)
  wizard         Interactive prompt-based TOML builder
  check          Validate a TOML against the Pydantic schema

Common options:
  --output PATH              Write path (or stdout if omitted)
  --profile TEXT             user | dev | expert  [default: user]
```

**`hmp config template`** :
```
hmp config template --output configs/canut.toml --profile user --solver mf6
```

**`hmp config wizard`** :
```
$ hmp config wizard

HydroModPy configuration wizard
┌─────────────────────────────────────┐
│  Let's build your simulation TOML.  │
└─────────────────────────────────────┘

? Project label: canut
? Workspace path: ~/workspaces/brittany
? Catchment identification method:
    > 1. From shapefile
      2. From outlet coordinates
      3. From DEM + streams
? Shapefile path: ~/shp/canut.shp
? CRS (EPSG): 2154
? Solver:
    > 1. MODFLOW-NWT (unstructured, fast)
      2. MODFLOW 6 (structured + DISV)
      3. Boussinesq (native, analytical-validated)
? Flow regime: transient
? Period start: 2015-01-01
? Period end: 2020-12-31
? Time step: 1 month
? Recharge source:
    > 1. CSV timeseries
      2. Météo-France SIM2 API
      3. Synthetic

Writing to configs/canut/project.toml... ✓
Validating... ✓

Try it: hmp run configs/canut/project.toml
```

**`hmp config check`** — critical for UX :
```
$ hmp config check configs/canut.toml
✗ Configuration error in configs/canut.toml

  line 24, col 15  flow.parameters.Sy: value 1.5 exceeds maximum 1.0
                   │
                   │   Sy = 1.5          # ← invalide (specific yield ∈ [0, 1])
                   │         ^^^
                   │
                   │   ⇒ Suggestion: use a value between 0 and 1 (typical: 0.01..0.3)

  line 38, col 1   mesh_catchment: unknown section
                   │
                   │   [mesh_catchment]   # ← peut-être `[mesh]` ?
                   │
                   │   ⇒ Suggestion: did you mean [mesh]?

2 errors found — no simulation executed.
```

#### 5.2.4 `hmp run`

**Rôle** : exécuter une simulation depuis un TOML (auto-détection du workflow).

```
Usage: hmp run CONFIG [OPTIONS]

Arguments:
  CONFIG                     Path to .toml

Options:
  --workflow TEXT            Override auto-detection:
                               simulation | overview | mesh
                               | calibration | batch | comparison
  --override KEY=VALUE       Override a config value (repeatable)
  --dry-run                  Validate + build plan, don't execute
  --tag TEXT                 Add tag (repeatable)
  --name TEXT                Override run name
  --project TEXT             Override project label
  --headless                 Disable all figure output
  -j, --jobs INT             Parallel processes for batch  [default: 1]
  -v, --verbose              Verbose logging
  -q, --quiet                Quiet logging
  -h, --help

Examples:
  hmp run configs/canut.toml
  hmp run configs/canut.toml --override flow.parameters.Sy=0.05 --name sy005
  hmp run configs/sweep.toml --workflow batch -j 8
  hmp run configs/canut.toml --dry-run

Exit codes:
  0   success
  1   runtime error
  2   invalid arguments
  3   configuration invalid (Pydantic)
  4   solver failure (convergence, crash)
  5   data error (external API, missing file)
  130 interrupted (SIGINT)
```

**Output attendu (rich console)** :
```
HydroModPy 0.4.0 — MODFLOW-NWT simulation

[1/6] Loading config............ configs/canut.toml           ✓ 0.05s
[2/6] Building geographic....... canut (34.2 km²)             ✓ 2.30s
[3/6] Generating mesh........... 4 326 cells, 2 layers        ✓ 1.12s
[4/6] Loading data.............. 3 sources (recharge, piezo)  ✓ 0.80s
[5/6] Running MODFLOW-NWT....... Sy=0.05 K=1e-5               ⠋
      ┝━━━━━━━━━━━━━━━━━━━━━━━━┥  47%  00:00:08 / 00:00:18
      Converged step 12/72 (residual 3.2e-6)
[6/6] Writing Zarr + DuckDB..... simulations/3b7a92f1...      ✓ 0.40s

✓ Simulation 'canut_baseline_01' complete (sim_id 3b7a92f1)
  project  : canut
  duration : 19.8s
  NSE      : 0.82   KGE : 0.78   RMSE : 0.31

Inspect: hmp show 3b7a92f1
```

#### 5.2.5 `hmp list`

```
Usage: hmp list [SCOPE] [OPTIONS]

Arguments:
  SCOPE                      projects | sims  [default: sims]

Options:
  --project TEXT             Filter by project label
  --solver TEXT              Filter by solver name
  --status TEXT              success | failed | running
  --tag TEXT                 Filter by tag (repeatable)
  --nse FLOAT                Min NSE
  --last INT                 Last N simulations
  --format TEXT              table | json | csv  [default: table]
  --sort TEXT                Sort by column (e.g. `-nse`, `duration_s`)
  -w, --workspace PATH       Workspace root [auto-detect]
  -h, --help

Examples:
  hmp list                                    # toutes les simulations
  hmp list projects                           # liste des projets
  hmp list --project canut --nse 0.7          # top runs
  hmp list --last 5
  hmp list --format json | jq '.[] | .sim_id' # pipeline shell
```

**Output table** (rich) :
```
 Workspace: /home/bb/workspaces/brittany   142 simulations

 Name                    Project  Solver      NSE    KGE    Duration  Date
 ──────────────────────────────────────────────────────────────────────────────
 canut_best              canut    modflow_nwt 0.89   0.85   18.2 s    2026-04-17
 canut_Sy005             canut    modflow_nwt 0.84   0.80   17.9 s    2026-04-17
 canut_boussinesq        canut    boussinesq  0.77   0.72   32.1 s    2026-04-16
 vilaine_calib_iter42    vilaine  modflow_nwt 0.68   0.64   12.3 s    2026-04-14
 ...
 Showing 20 of 142. Use --last or --project to narrow.
```

#### 5.2.6 `hmp show`

**Rôle** : détail d'une simulation (métadonnées + métriques + liens fichiers).

```
Usage: hmp show SIM_ID [OPTIONS]

Arguments:
  SIM_ID                     Full UUID or unique prefix (min 4 chars)

Options:
  --json                     Raw JSON output
  --figures                  Generate/open figures
  --config                   Print the TOML config
  -h, --help

Examples:
  hmp show 3b7a
  hmp show canut_baseline_01                  # accepts name too
  hmp show 3b7a --json | jq '.metrics'
```

**Output** :
```
 Simulation: canut_baseline_01
 sim_id       : 3b7a92f1-8a04-4e6b-8e72-91d70e4b7c90
 project      : canut
 solver       : modflow_nwt
 status       : success
 created      : 2026-04-17 14:02:33
 duration     : 18.2 s
 n_cells      : 4 326
 period       : 2015-01-01 → 2020-12-31 (72 steps)
 tags         : baseline, dev

 Metrics
 ─────────────────────────────────────────────
 station   nse    kge    rmse   n_obs
 P01       0.89   0.85   0.27   1460
 P02       0.82   0.78   0.31   1460
 _basin    0.85   0.81   0.29   —

 Parameters
 ─────────────────────────────────────────────
 name    zone   value       unit
 Sy      _all   0.05        —
 K       _all   1.0e-05     m/s
 Ss      _all   1.0e-06     1/m

 Files
 ─────────────────────────────────────────────
 zarr     simulations/3b7a92f1-....zarr  (14 MB)
 config   configs/canut/run_baseline.toml
 log      logs/3b7a92f1.log
```

#### 5.2.7 `hmp compare`

```
Usage: hmp compare SIM_A SIM_B [OPTIONS]

Options:
  --variables TEXT           Comma-sep: head,watertable_depth,outflow
  --output PATH              Output dir for figures + delta NetCDF
  --format TEXT              pdf | png | netcdf  [default: pdf]
  -h, --help

Examples:
  hmp compare 3b7a canut_worst --variables head,watertable_depth
  hmp compare 3b7a canut_worst --output comp/ --format pdf
```

#### 5.2.8 `hmp export`

**Rôle** : exporter vers UN format externe (pas de cumul).

```
Usage: hmp export SIM_ID [OPTIONS]

Options:
  --format TEXT              hmp | netcdf | geotiff | vtu
                             | shp | gpkg | csv | waterml  [default: hmp]
  --variable TEXT            Variable to export ('*' = all)  [default: *]
  --output PATH              Output path [default: exports/<name>.<ext>]
  -h, --help

Examples:
  hmp export 3b7a --format netcdf
  hmp export 3b7a --format hmp --output share/canut_best.hmp
  hmp export canut --format csv                 # exports a project
```

#### 5.2.9 `hmp import`

```
Usage: hmp import PACKAGE [OPTIONS]

Arguments:
  PACKAGE                    Path to .hmp package

Options:
  -w, --workspace PATH       Target workspace
  --project TEXT             Override project label on import
  --dry-run                  Show what would be imported
  -h, --help

Example:
  hmp import ~/Downloads/canut_best.hmp -w ~/ws
```

#### 5.2.10 `hmp delete`

```
Usage: hmp delete SIM_ID [OPTIONS]

Options:
  --confirm                  Required (safety)
  --dry-run                  Show what would be deleted
  --force                    No prompts
  -h, --help

Examples:
  hmp delete 3b7a --dry-run
  hmp delete 3b7a --confirm
  hmp delete --project old_sweep --confirm
```

#### 5.2.11 `hmp doctor`

```
Usage: hmp doctor [OPTIONS]

Options:
  -v, --verbose              Show all checks (passing + failing)
  --fix                      Attempt automatic fixes (PROJ_DATA, permissions)
  -h, --help
```

**Output** :
```
 HydroModPy environment diagnostics

 ✓ Python 3.13.0
 ✓ hydromodpy 0.4.0 (installed editable)
 ✓ pyproj    3.7.0   PROJ 9.5.0 (layout OK)
 ✓ flopy     3.8.2
 ✓ gmsh      4.13.1
 ✗ modflow-nwt executable not on PATH
   → Suggestion: pip install modflow-bin
 ✓ modflow6  6.5.0
 ✓ whitebox_workflows 1.2.0
 ✓ DuckDB    1.0.0
 ✓ Zarr      2.17.0
 ✓ libglu1-mesa installed (required by gmsh/VTK)

 Workspace auto-detection: /home/bb/workspaces/brittany (schema v5, 142 sims)

 1 issue found. Run with --fix to attempt repair.
```

Exit code : 0 if all checks pass, 1 otherwise.

#### 5.2.12 `hmp completion`

```
Usage: hmp completion SHELL

Arguments:
  SHELL                      bash | zsh | fish

Examples:
  hmp completion fish > ~/.config/fish/completions/hmp.fish
  eval "$(hmp completion bash)"
```

#### 5.2.13 `hmp --version`

```
$ hmp --version
hmp 0.4.0
  python   3.13.0
  flopy    3.8.2
  pyproj   3.7.0 (PROJ 9.5.0)
  duckdb   1.0.0
  gmsh     4.13.1
```

### 5.3 Auto-détection `hmp run` (table stable et documentée)

| Section dominante du TOML | Workflow activé | Classe interne |
|---|---|---|
| `[calibration]` | `calibration` | `CalibrationWorkflow` |
| `[batch]` | `batch` | `BatchWorkflow` |
| `[comparison]` | `comparison` | `ComparisonWorkflow` |
| `[overview]` (sans `[simulation]`) | `overview` | `OverviewWorkflow` |
| `[mesh]` (sans `[simulation]`) | `mesh` | `MeshWorkflow` |
| `[simulation]` ou `[flow]` (défaut) | `simulation` | `SimulationWorkflow` |

Override explicite : `hmp run cfg.toml --workflow batch`.

### 5.4 Exit codes POSIX (uniformes)

| Code | Sémantique | Exemple |
|---|---|---|
| 0 | Succès | simulation terminée, metrics écrites |
| 1 | Erreur runtime | erreur I/O, erreur Zarr, etc. |
| 2 | Erreur d'usage | arguments incompatibles (`--fast --slow`) |
| 3 | Erreur de config | Pydantic validation failed |
| 4 | Erreur solveur | MODFLOW n'a pas convergé |
| 5 | Erreur données | Hub'Eau 503, CSV malformé |
| 130 | SIGINT (Ctrl-C) | interruption utilisateur |

Utile pour scripts shell :
```bash
if ! hmp run cfg.toml; then
    case $? in
        3) echo "config invalide" ;;
        4) echo "le solveur a divergé" ;;
        5) echo "données manquantes" ;;
    esac
fi
```

### 5.5 Couleurs, progress bars, messages (rich)

- **Stack** : `rich.console`, `rich.progress`, `rich.table`, `rich.syntax`.
- **Détection TTY** : couleurs uniquement si `sys.stdout.isatty()`. CI et
  pipes → texte brut automatiquement.
- **Override** : `NO_COLOR=1` désactive (standard
  [no-color.org](https://no-color.org)).
- **Niveaux** :
  - vert `✓` — succès,
  - jaune `⚠` — avertissement,
  - rouge `✗` — erreur,
  - cyan `ℹ` — info,
  - gris `·` — détail technique.

---

## 6. Configuration TOML user-friendly

### 6.1 TOML minimal qui marche (5 lignes)

Principe **convention over configuration** : n'importe quel hydrogéologue doit
pouvoir écrire un TOML valide en 5 lignes.

```toml
# configs/canut_minimal.toml — 5 lignes réelles
project = "canut"
[geographic]  shp = "canut.shp"  crs = 2154
[flow]        solver = "modflow6"  regime = "transient"
[period]      start = "2015-01-01"  end = "2020-12-31"
[recharge]    source = "sim2"
```

Tout le reste (mesh, domain, boundary conditions, numerics) utilise des
**defaults opinionés**, identiques aux cas validés
(`validation_cases/analytical_*`).

### 6.2 TOML complet avec commentaires explicatifs en français

```toml
# =========================================================================
# HydroModPy — configuration de simulation
# =========================================================================
# Documentation complète : https://hydromodpy.readthedocs.io/toml
# Valide via : hmp config check <ce-fichier>
# =========================================================================

# Identifiant libre du projet, sert de label dans le catalogue.
# (ce n'est PAS un dossier, juste une étiquette pour hmp list --project)
project = "canut"

# -------------------------------------------------------------------------
# [workspace] — emplacement des données et du catalogue
# -------------------------------------------------------------------------
[workspace]
root = "~/workspaces/brittany"   # DuckDB + Zarr iront ici

# -------------------------------------------------------------------------
# [geographic] — délinéation du bassin versant
# -------------------------------------------------------------------------
[geographic]
# Méthode : shp | outlet | dem
method = "shp"
shp    = "shp/canut.shp"         # shapefile du contour
crs    = 2154                    # EPSG code (Lambert-93 pour la France)
# Résolution du MNT à rééchantillonner (mètres). IGN BD ALTI = 25m.
dem_resolution = 50
# Marge autour du contour (mètres), pour éviter les effets de bord.
buffer = 300

# -------------------------------------------------------------------------
# [mesh] — maillage
# -------------------------------------------------------------------------
[mesh]
# Type : cartesian | gmsh
kind       = "cartesian"
resolution = 50                  # taille de maille horizontale (m)
nlay       = 2                   # nombre de couches verticales
# Profondeur totale du modèle depuis la surface (m).
depth      = 30.0

# -------------------------------------------------------------------------
# [flow] — écoulement souterrain
# -------------------------------------------------------------------------
[flow]
# Solveur : modflow_nwt (rapide) | modflow6 (moderne) | boussinesq (natif)
solver = "modflow6"
# Régime : steady | transient
regime = "transient"

# Conditions aux limites actives. Les valeurs disponibles :
#   "drain"  = drains dans les rivières (RIV package)
#   "stream" = rivières prescrites
#   "ocean"  = interface océan (GHB)
#   "chd"    = conditions de charge imposées
active_bc = ["drain", "stream"]

# Paramètres hydrauliques (moyens, par zone si multi-zones).
[flow.parameters]
Sy = 0.05        # emmagasinement libre   [-]        [0..1]
K  = 1.0e-5      # conductivité hydraulique [m/s]
Ss = 1.0e-6      # emmagasinement spécifique [1/m]

# -------------------------------------------------------------------------
# [period] — discrétisation temporelle
# -------------------------------------------------------------------------
[period]
start = "2015-01-01"
end   = "2020-12-31"
step  = "1M"        # pas de temps (pandas freq : 1D, 1W, 1M, 1Y)
# Une période de chauffe optionnelle, exclue des métriques.
warmup = "1Y"

# -------------------------------------------------------------------------
# [recharge] — forçage climatique
# -------------------------------------------------------------------------
[recharge]
# Source : sim2 (Météo-France) | csv | synthetic | pyhelp
source = "sim2"
# Si source = "csv", préciser le chemin.
# path = "data/recharge/canut_daily.csv"

# -------------------------------------------------------------------------
# [observations] — données de calibration (optionnel)
# -------------------------------------------------------------------------
[observations]
piezometry = "data/piezometry/stations.csv"
hydrometry = "data/hydrometry/outlet.csv"

# -------------------------------------------------------------------------
# [simulation] — options d'exécution
# -------------------------------------------------------------------------
[simulation]
# Nom humain de cette simulation (défaut = stem du fichier TOML).
name = "canut_baseline"
# Étiquettes libres, pour filtrage ultérieur (hmp list --tag).
tags = ["baseline", "dev"]

# -------------------------------------------------------------------------
# [display] — figures (optionnel)
# -------------------------------------------------------------------------
[display]
enabled = true
save    = true
figures = ["watertable_map", "outflow_series", "mesh", "bilan"]
```

### 6.3 TOML de calibration

```toml
# configs/canut_calibration.toml
project = "canut"
extends = "canut_baseline.toml"   # héritage (clé magique, cf. §6.6)

[calibration]
method = "dream"          # dream | latin_hypercube | pest | grid
n_iter = 500
seed   = 42

[calibration.parameters]
Sy = { min = 0.001, max = 0.3,  prior = "log-uniform" }
K  = { min = 1e-7,  max = 1e-3, prior = "log-uniform" }

[calibration.objective]
function = "nse"
stations = ["P01", "P02", "_basin"]
weights  = [1.0, 1.0, 0.5]
```

### 6.4 TOML de batch régional

```toml
# configs/brittany_batch.toml
project = "brittany"

[batch]
# Grille d'exécutions cartésiennes.
catchments = ["canut", "vilaine", "odet", "blavet"]
solvers    = ["modflow_nwt", "modflow6"]

[batch.defaults]
# Overrides appliqués à chaque combinaison.
"mesh.resolution" = 100
"flow.regime"     = "transient"

[batch.parallelism]
jobs = 4
```

### 6.5 TOML de comparaison

```toml
# configs/canut_compare.toml
project = "canut"

[comparison]
references = ["canut_best_nwt", "canut_best_mf6", "canut_boussinesq"]
variables  = ["head", "watertable_depth", "outflow"]
metrics    = ["nse", "kge", "rmse"]
```

### 6.6 Fonctionnalités avancées

| Feature | Syntaxe | Rationale |
|---|---|---|
| **Héritage** | `extends = "base.toml"` | Surcharge partielle, cf. `tox.ini`, `tsconfig.json`. |
| **Variables d'environnement** | `root = "${HOME}/workspaces"` | Portabilité machines. |
| **Références croisées** | `period.end = "${reference.end}"` | Éviter duplication. |
| **Includes multi-fichiers** | `includes = ["data.toml", "flow.toml"]` | Composition. |
| **Profils** | `hmp config check --profile user` | Vérifie seulement les champs `user`-level. |

### 6.7 `ParamLevel` : trois profils de verbosité

| Profil | Contenu du template généré | Cible utilisateur |
|---|---|---|
| `user` | ~30 clés, defaults agressifs | hydrogéologue grand public |
| `dev` | ~80 clés, numérique visible | utilisateur confirmé |
| `expert` | ~200 clés, tout sauf internals | développeur, benchmark |

Implémentation : `ParamLevel` enum sur chaque champ Pydantic via `Field(json_schema_extra={"level": "user"})`. Le générateur de template filtre.

### 6.8 `hmp config wizard` interactif

Stack : `questionary` (prompt tolkit) + `rich`. Aucune dépendance lourde
(< 500 kB).

Flow :
1. Détection workspace (cwd ou parent).
2. Prompt par section dans l'ordre du TOML.
3. Validation live via Pydantic après chaque section.
4. Prévisualisation du TOML final (`rich.syntax.Syntax`).
5. Confirmation → écriture + `hmp config check`.

### 6.9 Noms de sections — ce qu'un hydrogéologue attend

Fruit d'une enquête interne (entretiens 4 hydrogéologues, avril 2026) :

| Concept métier | Nom attendu | Nom retenu (cible) | Nom actuel (rejeté) |
|---|---|---|---|
| Bassin versant | `[bassin]` ou `[catchment]` | `[geographic]` | `[watershed]` (abstrait en FR) |
| Maillage | `[mesh]` | `[mesh]` | `[mesh_catchment]` (verbeux) |
| Écoulement | `[flow]` | `[flow]` | — |
| Période | `[period]` ou `[temps]` | `[period]` | `[time]` (ambigu) |
| Recharge | `[recharge]` | `[recharge]` | `[climatic]` (trop large) |
| Paramètres | `[parameters]` | intégré à `[flow.parameters]` | — |
| Observations | `[observations]` | `[observations]` | — |
| Solveur | clé `solver=` dans `[flow]` | clé `solver=` dans `[flow]` | — |

---

## 7. Messages d'erreur et diagnostics

### 7.1 Principes

Un bon message d'erreur a **quatre composantes** (d'après `ruff`, `rustc`, `pydantic`):

1. **Localisation** : fichier, ligne, colonne.
2. **Description** : ce qui s'est passé.
3. **Cause probable** : pourquoi.
4. **Suggestion** : comment corriger.

### 7.2 Exemple — Pydantic validation

```
✗ Invalid configuration

  configs/canut.toml:24:15   flow.parameters.Sy
  │
  │   23 | [flow.parameters]
  │   24 |   Sy = 1.5
  │      |        ^^^ value out of range
  │   25 |   K  = 1.0e-5
  │
  │   specific_yield must lie in [0, 1] (typical values: 0.01 – 0.30)
  │   ⇒ did you confuse Sy (specific yield) with S (storativity)?

  configs/canut.toml:38:1    [mesh_catchment]
  │
  │   38 | [mesh_catchment]
  │      | ^^^^^^^^^^^^^^^^ unknown section
  │
  │   ⇒ did you mean [mesh]?

2 issues prevent execution.
```

### 7.3 Exemple — Solveur non convergent

```
✗ MODFLOW-NWT did not converge

  at outer iteration 87 / 100, time step 42
  │
  │   max head change   : 3.2e-2 m  (target 1e-5)
  │   residual L2 norm  : 1.8      (diverging)
  │
  │   Likely causes:
  │     • mesh too coarse near boundary (try resolution=25)
  │     • hydraulic conductivity too low (K < 1e-8)
  │     • time step too large for transient (try step='7D')
  │
  │   Artifacts written to simulations/3b7a92f1-.../
  │     head.dat (partial, steps 0..41)
  │     listing.log (see last 200 lines)
  │
  │   Re-run with --override solver.outer_max_iter=200 to retry.
```

### 7.4 Exemple — API externe indisponible

```
✗ Failed to fetch recharge data from Météo-France SIM2

  endpoint : https://public.opendatasoft.com/api/records/1.0/search/
  status   : 503 Service Unavailable (after 3 retries, 27s total)

  The API is likely down. You can:
    1. Retry later               (hmp doctor may confirm network issues)
    2. Use a cached copy         (~/.cache/hydromodpy/sim2/canut_2015_2020.csv)
    3. Switch to CSV             (recharge.source = "csv", recharge.path = ...)
```

### 7.5 Exemple — Erreur avec stack trace optionnelle

```
✗ Simulation failed: RuntimeError while reading MODFLOW binary output

  hint: enable --verbose for the full Python traceback
```

Avec `--verbose` :
```
  Traceback (most recent call last):
    File "hydromodpy/solver/modflow_common/binary_reader.py", line 142, ...
    ...
  RuntimeError: head.hds truncated at byte 4096 (expected 16384)
```

### 7.6 Table centrale des codes d'erreur

Pour permettre au support utilisateur de référencer un code.

| Code | Catégorie | Exemple |
|---|---|---|
| `HMPY.E001` | Config | Section inconnue |
| `HMPY.E002` | Config | Valeur hors bornes |
| `HMPY.E003` | Config | Type incompatible |
| `HMPY.E010` | Data | API externe 5xx |
| `HMPY.E011` | Data | Fichier introuvable |
| `HMPY.E012` | Data | Schéma CSV invalide |
| `HMPY.E020` | Mesh | gmsh crash |
| `HMPY.E021` | Mesh | Qualité insuffisante |
| `HMPY.E030` | Solver | Non-convergence |
| `HMPY.E031` | Solver | Executable manquant |
| `HMPY.E032` | Solver | Input FloPy rejeté |
| `HMPY.E040` | Storage | Zarr corruption |
| `HMPY.E041` | Storage | DuckDB schema mismatch |

Chaque code a une page de doc (`docs/errors/HMPY.E030.md`).

---

## 8. Prototypage interactif et fluent API

### 8.1 Fluent API — évaluation

La tentation : `sim.field('head').at(timestep=5).plot()`.

**Verdict** : **non recommandé** comme pattern dominant.

| Pour | Contre |
|---|---|
| Lecture naturelle chez le néophyte. | Ordre de fluent réversible (at → field ? field → at ?) génère ambiguïté. |
| Imite `pandas` avec `query().groupby().agg()`. | Nécessite des proxies intermédiaires (`FieldView`) qui complexifient l'API. |
| Moins de `,` dans les signatures. | Teste les IDE : ils ne voient plus qui retourne quoi sans type hints exhaustifs. |

**Recommandation** : `pandas`-style **keyword arguments par méthode**, pas de
chaînage profond. Une méthode = un effet direct. Pour les cas de chaînage
utile, on ajoute des raccourcis spécifiques :

```python
# ✅ Recommandé (direct, keyword-only)
sim.field("head", timestep=5).plot()

# ✅ Aussi (xarray-idiomatique)
sim.fields("head").isel(time=5).plot()

# ❌ À éviter (fluent proxy builder)
sim.field("head").at(timestep=5).plot()
```

### 8.2 `_repr_html_` — tableau HTML en Jupyter

Tous les objets publics (`Simulation`, `SimulationCatalog`,
`SimulationGroup`, `SimulationPlan`, `HydroMesh`, `Geographic`) ont un
`_repr_html_()`.

**Exemple `Simulation._repr_html_`** :

```html
<div class='hmp-repr'>
  <h4>Simulation <code>canut_baseline_01</code></h4>
  <table>
    <tr><td>sim_id</td><td>3b7a92f1-…</td></tr>
    <tr><td>project</td><td>canut</td></tr>
    <tr><td>solver</td><td>modflow_nwt</td></tr>
    <tr><td>status</td><td><span class='ok'>✓ success</span></td></tr>
    <tr><td>NSE</td><td>0.89</td></tr>
    <tr><td>duration</td><td>18.2 s</td></tr>
  </table>
  <details>
    <summary>Parameters (3)</summary>
    <table>...</table>
  </details>
  <details>
    <summary>Files</summary>
    <code>simulations/3b7a92f1-….zarr (14 MB)</code>
  </details>
</div>
```

Style léger (≤ 3 kB CSS inline, style `xarray`).

### 8.3 Pattern `setup_once, run_many` (prototypage)

Un cas canonique : balayer des paramètres en Jupyter sans relire TOML/mesh/data
à chaque run. L'API doit l'exprimer directement :

```python
sim = hmp.Simulation("canut.toml", headless=True)

for sy in np.logspace(-3, -1, 20):
    r = sim.run(name=f"sy_{sy:.0e}", Sy=sy)
```

- `__init__` fait Phase 1-7 (config, mesh, data).
- Chaque `run()` fait UNIQUEMENT Phase 8 (exécution).
- Le catalogue reste ouvert entre les runs.
- Les figures sont désactivées (`headless=True`).

Gain typique : un sweep de 100 runs passe de 50 min à 8 min (audit §5).

### 8.4 Pattern `extends` pour prototypage rapide

```toml
# configs/prototype_quick.toml
extends = "canut_baseline.toml"
[mesh]
resolution = 200   # plus grossier pour itérer vite
[flow.parameters]
Sy = 0.1
```

```bash
hmp run configs/prototype_quick.toml --name proto_01
```

### 8.5 Notebook pré-rempli (`hmp new --from demo`)

Fournit directement :
- `configs/<project>/run_baseline.toml`
- `configs/<project>/explore.ipynb` (notebook pré-rempli avec 5 cellules :
  ouvrir workspace, lister, inspecter, exporter, plot).

Inspirés par `dvc init --from example`.

### 8.6 Magic `%hmp` IPython (optionnel, nice-to-have)

```python
%load_ext hydromodpy

%hmp run canut.toml        # lance dans le process Jupyter (pas subprocess)
%hmp status                 # affiche l'état du dernier run
%hmp best canut            # retourne directement un objet Simulation
```

---

## 9. Auto-complétion et découvrabilité

### 9.1 Python / IDE

- **`__all__` exhaustif** dans chaque sous-module.
- **`py.typed` marker** à la racine du package (PEP 561) — active mypy/pyright
  chez les consommateurs.
- **Type hints à 100 %** (zero `Any` dans l'API publique).
- **Docstrings numpy** : `Parameters`, `Returns`, `Raises`, `Examples`,
  `See Also`, `Notes`.
- **Sphinx-autosummary** : index alphabétique de tous les symboles publics
  avec lien profond.

### 9.2 Shell (bash/fish/zsh)

- **argcomplete** intégré dans `hydromodpy/_cli/main.py` (3 lignes).
- **`hmp completion bash > /etc/bash_completion.d/hmp`** pour installer.
- Complétion **sémantique** : `hmp show <TAB>` propose les sim_ids récents,
  `hmp run <TAB>` propose les `*.toml` du workspace, `hmp list --project
  <TAB>` propose les projets existants (via un call rapide DuckDB).

### 9.3 `hmp --help` riche

L'epilog du parseur principal contient 3 exemples canoniques :

```
$ hmp --help
usage: hmp [-h] [--version] <command> ...

HydroModPy — catchment-scale groundwater modeling toolbox.

Commands:
  init        Create a workspace
  new         Create a project from a template
  config      Manage TOML configs (wizard, check, template)
  run         Execute a simulation
  list        Inventory
  show        Details of one simulation
  compare     Compare two simulations
  export      Export results (NetCDF, GeoTIFF, VTU, ...)
  import      Import a .hmp portable package
  delete      Remove simulation(s)
  display     Regenerate figures post-hoc
  doctor      Environment diagnostics
  completion  Generate shell completion script

Examples:
  hmp init ~/ws && hmp new canut
  hmp run configs/canut.toml --name baseline
  hmp list --project canut --nse 0.7 --format table
  hmp export 3b7a --format netcdf --output share/canut.nc

Documentation: https://hydromodpy.readthedocs.io/
Exit codes:    0 ok, 1 runtime, 2 usage, 3 config, 4 solver, 5 data.
```

### 9.4 `hmp <verb> --help` — aide locale riche

Chaque sous-commande a :
- Description (1 phrase).
- Arguments + options (auto via argparse).
- **Epilog avec 2-3 exemples** (manuel).
- Liens vers doc (`https://hydromodpy.readthedocs.io/cli/run`).

---

## 10. Comparatif avec les outils de référence

### 10.1 CLI

| Feature | `hmp` cible | `poetry` | `ruff` | `dvc` | `mlflow` |
|---|---|---|---|---|---|
| Sous-commandes | ✓ | ✓ | ✓ | ✓ | ✓ |
| `--version` | ✓ | ✓ | ✓ | ✓ | ✓ |
| Completion shell | ✓ (argcomplete) | ✓ | ✓ | ✓ | — |
| `--help` avec exemples | ✓ | ✓ | ✓ | ✓ | partiel |
| Couleurs ANSI (rich) | ✓ | ✓ | ✓ | ✓ | — |
| Progress bars | ✓ | ✓ | — | ✓ | — |
| Exit codes documentés | ✓ | ✓ | ✓ | ✓ | — |
| Dry-run | ✓ | — | ✓ (`--check`) | ✓ | — |
| Config file TOML | ✓ | ✓ | ✓ | ✓ (`.dvc/config`) | — |
| Dispatch auto-détecté | ✓ (TOML section) | — | — | — | — |
| Doctor / diag | ✓ (`hmp doctor`) | — | — | ✓ (`dvc doctor`) | — |
| Wizard interactif | ✓ | ✓ (`poetry init`) | — | ✓ | — |

### 10.2 API Python

| Feature | HydroModPy cible | `pandas` | `xarray` | `sklearn` | `mlflow.tracking` |
|---|---|---|---|---|---|
| Top-level facade | `hmp.open()` | `pd.read_csv()` | `xr.open_dataset()` | `sklearn.datasets.load_*` | `mlflow.search_runs()` |
| `_repr_html_` | ✓ | ✓ | ✓ | partiel | partiel |
| `__repr__` riche | ✓ | ✓ | ✓ | ✓ | ✓ |
| Lazy top-level imports | ✓ (PEP 562) | — | ✓ | partiel | — |
| `py.typed` | ✓ | ✓ | ✓ | ✓ (sklearn 1.2+) | partiel |
| Context manager | ✓ | partiel | ✓ | — | ✓ |
| Fluent chaining | modéré | extensif | extensif | modéré | modéré |
| Subclass-friendly | ✓ | ✓ | ✓ | ✓ | — |

### 10.3 TOML

| Feature | HydroModPy cible | `poetry` | `ruff` | `tox` |
|---|---|---|---|---|
| Fichier unique par projet | ✓ | ✓ (`pyproject.toml`) | ✓ | ✓ |
| Héritage (`extends`) | ✓ | partiel | ✓ | ✓ |
| Env vars (`${HOME}`) | ✓ | partiel | — | partiel |
| Profils (`user`/`dev`/`expert`) | ✓ | — | — | — |
| `config check` standalone | ✓ | ✓ | ✓ | ✓ |
| Messages d'erreur pointant à la colonne | ✓ | ✓ | ✓ | — |

---

## 11. Matrice de migration actuel → cible

### 11.1 API publique

| Élément actuel | Élément cible | Statut | Action |
|---|---|---|---|
| `hmp.open(ws)` | `hmp.open(ws)` | [C] | — |
| `hmp.Simulation` (`project.py`) | `hmp.Simulation` (`simulation/api.py`) | [R]+[F] | Déplacer, réécrire à ~150 l. |
| `hmp.SimulationResult` | `hmp.SimulationResult` | [C] | — (conserver alias pour API programmatique) |
| `hmp.SimulationCatalog` | `hmp.SimulationCatalog` | [C] | — |
| — | `hmp.SimulationGroup` | [N] | Expose la classe déjà écrite |
| — | `hmp.SimulationPlan` | [N] | Expose le plan immuable |
| `hmp.Workspace` | `hmp.Workspace` | [C] | — |
| `hmp.Geographic` | `hmp.Geographic` | [C] | — |
| — | `hmp.Domain` | [N] | Expose la classe existante |
| — | `hmp.HydroMesh` | [N] | Expose la classe existante |
| — | `hmp.Flow` | [N] | Expose la classe existante |
| — | `hmp.Transport` | [N] | Expose la classe existante |
| `hmp.Modflow` | `hmp.Modflow` | [C] | — (alias NWT) |
| — | `hmp.Modflow6` | [N] | Asymétrie résolue |
| `hmp.Modpath` | `hmp.Modpath7` | [R] | Renommé (c'est MODPATH 7) |
| `hmp.Mt3dms` | `hmp.Mt3dms` | [C] | — |
| — | `hmp.Boussinesq` | [N] | Exposé au top |
| — | `hmp.compare` | [N] | Fonction top-level |
| — | `hmp.doctor` | [N] | Fonction top-level |
| `hmp.Hydrometry` | `hmp.data.hydrometry.Hydrometry` | [D] | Sous-module |
| `hmp.Piezometry` | `hmp.data.piezometry.Piezometry` | [D] | Sous-module |
| `hmp.Subbasin` | `hmp.spatial.geographic.Subbasin` | [D] | Sous-module |
| `hmp.HydrographyConfig/Manager/Result` | `hmp.data.variables.hydrography.*` | [D] | Sous-module |
| `hmp.IntermittencyConfig/Manager` | `hmp.data.variables.intermittency.*` | [D] | Sous-module |
| `hmp.OceanicConfig/Manager` | `hmp.data.variables.oceanic.*` | [D] | Sous-module |
| `hmp.WorkspaceConfig`, `hmp.GeographicConfig` | `hmp.core.config.*` | [D] | Sous-module |

### 11.2 CLI

| Verbe actuel | Verbe cible | Statut | Action |
|---|---|---|---|
| `hmp init` | `hmp init` | [C] | Sortie rich-formatée |
| `hmp new` | `hmp new` | [F] | `--from TEMPLATE`, `--solver` |
| `hmp config` | `hmp config template` | [R] | Devient sous-verbe |
| — | `hmp config wizard` | [N] | Assistant interactif (questionary) |
| — | `hmp config check` | [N] | Validation sans exécution |
| `hmp run` | `hmp run` | [F] | `--override`, `--dry-run`, `--tag`, `--name` |
| `hmp display` | `hmp display` | [C] | — |
| `hmp list` | `hmp list` | [F] | `--project`, `--nse`, `--format`, scope argument |
| — | `hmp show <id>` | [N] | Dump détaillé |
| `hmp export <project>` | `hmp export <sim_id\|project>` | [F] | Un format à la fois |
| — | `hmp import <pkg>` | [N] | Symétrique de export |
| — | `hmp compare A B` | [N] | Comparaison pairwise |
| — | `hmp delete <id>` | [N] | Avec `--confirm` obligatoire |
| — | `hmp doctor` | [N] | Diagnostic environnement |
| — | `hmp completion <shell>` | [N] | Auto-completion |
| — | `hmp --version` | [N] | Standard manquant |
| `hmp test <suite>` | — | [K] | Supprimé (réinvention pytest) |

### 11.3 TOML

| Section actuelle | Section cible | Statut |
|---|---|---|
| `[geographic]` | `[geographic]` | [C] |
| `[mesh_catchment]` | `[mesh]` | [R] simplifié |
| `[mesh_input]` | `[mesh]` + `source = "external"` | [F] fusion |
| `[flow]` | `[flow]` | [C] |
| `[time]` | `[period]` | [R] sens clair |
| `[simulation]` | `[simulation]` | [C] |
| `[domain]` | `[domain]` | [C] (optionnel — auto-inféré si absent) |
| `[data]` | `[observations]` + `[recharge]` | [F] éclaté par rôle |
| `[postprocess]` | `[postprocess]` | [C] |
| `[display]` | `[display]` | [C] |
| — | `extends = "base.toml"` | [N] héritage |
| — | Variables `${ENV}` | [N] portabilité |

### 11.4 Messages d'erreur

| Actuel | Cible | Statut |
|---|---|---|
| `print(..., file=sys.stderr)` dispersés | `rich.console.Console(stderr=True)` centralisé | [F] |
| `try/except Exception: pass` | levée de `core.exceptions.*` avec code `HMPY.Exxx` | [F] |
| `ValueError("Embedded [mesh_catchment] and external [mesh_input]...")` | `ConfigError.mutually_exclusive([...], file=..., line=...)` | [F] |
| Pas de suggestion ("did you mean") | Levenshtein distance sur noms de section | [N] |

### 11.5 Comportements transverse

| Actuel | Cible | Statut |
|---|---|---|
| `LogManager()` à l'import de `hydromodpy` | LazyLogger via `core.logging.get_logger()` | [F] |
| PROJ_DATA muté à l'import (207 l.) | `core.io.crs.ensure_proj_data()` appelée par `Geographic.__init__` | [F] |
| Pas de `__fspath__` sur objets chemins | `Path`-compatibles partout | [N] |
| Pas de `__repr__` riche | `__repr__` + `_repr_html_` sur tous les publics | [N] |
| `Any` dans signatures publiques | Types complets (`Literal`, `Protocol`, `TypedDict`) | [F] |
| `py.typed` absent | `hydromodpy/py.typed` fichier vide | [N] |

---

## 12. Fin — critères d'acceptation UX

Un utilisateur novice doit pouvoir :

- [ ] Installer, lancer `hmp init` et obtenir un workspace valide en ≤ 30 s.
- [ ] Lancer `hmp config wizard` et obtenir un TOML valide en ≤ 5 min.
- [ ] Lancer `hmp run <toml>` et obtenir un résultat en ≤ 1 min (cas démo).
- [ ] Taper `hmp --help` et comprendre toutes les commandes sans lire la doc.
- [ ] Taper `hmp show <partial_id>` et voir les métadonnées complètes.
- [ ] Ouvrir Jupyter, taper `import hydromodpy as hmp; hmp.open("ws")` et
  accéder au catalogue en 2 lignes.
- [ ] Comparer deux simulations avec `hmp compare A B` sans lire la doc.
- [ ] Corriger un TOML invalide à partir de la seule sortie de
  `hmp config check`.
- [ ] Exécuter `hmp doctor` sur une machine neuve et savoir exactement quelles
  dépendances installer.
- [ ] Utiliser la complétion `hmp <TAB>` dans bash, zsh, et fish.

Chaque élément de cette liste correspond à UN test d'intégration automatisé
dans `tests/integration/test_ux_acceptance.py` (suggestion pour spec
`09_tests_ideaux.md`).

> **Mesure de succès** : le nombre de sessions hydrogéologue où
> l'utilisateur doit lire `CLAUDE.md` ou le code source pour progresser.
> Objectif : **zéro** pour les tâches standard (init → run → export).
