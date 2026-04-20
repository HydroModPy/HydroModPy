# Audit critique — `hydromodpy/analysis/` (display + postprocess)

**Périmètre audité**
`hydromodpy/analysis/display/` (≈ 8 850 lignes Python) et `hydromodpy/analysis/postprocess/` (≈ 2 300 lignes Python), hors `calibration/`, `comparison/`, `batch/` (audités par ailleurs).

**Posture** : auditeur senior visualisation scientifique et post-traitement hydrogéologique.
**Référentiels comparés** : matplotlib (Figure/Axes/Artist), holoviews (Element/Layout/Overlay), xarray, FloPy, PyVista, conventions CF-1.8, UGRID-1.0, recommandations Crameri 2020 sur les colormaps.

---

## 1. Architecture display — monolithe ou composable ?

### 1.1 La façade `render_* / plot_*`

Le paquet expose, pour ~13 familles de figures, une paire systématique :

```python
def render_xxx(ax, *, payload...) -> None
def plot_xxx(*, payload..., options, save_path, figsize, dpi) -> tuple[fig, ax]
```

Cette séparation est un **bon principe** — c'est l'équivalent conceptuel de la dichotomie matplotlib `Axes.plot` (bas niveau, composable) vs `pyplot.plot` (haut niveau, stateful). Elle permet théoriquement la composition dans un `subplots` externe (multi-panel) et l'écriture de tests sans fenêtre.

**Mais** l'implémentation trahit le principe. Le boilerplate `plot_*` est recopié littéralement ~25 fois :

```python
fig, axs = make_figure(figsize=figsize, dpi=dpi)
ax = _single_axes(axs)
render_xxx(ax, ...)
fig.tight_layout()
if options is not None:
    finalize_figure(fig, options=options, save_path=save_path)
return fig, ax
```

Un décorateur `@as_figure(figsize=(12, 3.5))` appliqué aux `render_*` aurait tué les ~400 lignes de duplication.

### 1.2 Le pattern « suite »

`suites.py` / `orchestration.py` / `posthoc_orchestration.py` implémentent trois orchestrateurs pour les mêmes sorties (simulation en cours, post-hoc depuis catalog, post-hoc depuis FS legacy). Les fonctions `plot_flow_suite` (suites.py, l. 497-689) et `plot_posthoc_flow_suite` (posthoc_orchestration.py) dupliquent 80 % de leur logique.

Comparaison avec **holoviews** : chez holoviews, une `Layout` ou `Overlay` est un objet de données immuable séparé du backend de rendu. Le pipeline reste déclaratif : `Element * Element` → `Overlay`. Ici, `plot_flow_suite` est **impératif** et **couple fortement** : résolution de modèle (`_resolve_flow_model`), chargement timeseries (catalog ou CSV), I/O rasterio, reshape, plotting, toutes dans une même fonction de 200 lignes.

**Verdict** : **problématique**. Le pattern render/plot est correct en intention, raté en exécution. L'orchestration monolithique n'est pas testable sans mocks lourds (voir §7).

### 1.3 Testabilité headless

`tests/unit/display/test_figures.py`, `test_suites.py`, `test_posthoc_orchestration.py` existent (modifiés au merge), preuve que l'architecture _permet_ la mise à l'épreuve. Cependant :

- `plt.switch_backend("QtAgg")` dans `visualization_results.py:717` → casse tout test en CI.
- `matplotlib.use("Agg")` n'est forcé **qu'une fois** dans le package entier (`report/overview_report.py:27`). Ailleurs, `common.make_figure` délègue à l'utilisateur final. Si `HYDROMODPY_NO_DISPLAY=1` mais qu'un `import` matplotlib a lieu avant configuration, le backend GUI reste actif.
- `display_config.DisplayOptions.should_render()` (l. 327-335) court-circuite les suites quand `enabled=False` — bonne hygiène, mais ne protège pas des side-effects d'import (voir §7).

### 1.4 Tableau récapitulatif architecture

| Élément | Rôle | Verdict | Justification | Recommandation |
|---|---|---|---|---|
| `display_config.py` (350 l.) | Pydantic DisplayConfig + DisplayOptions (dataclass) | **conforme** | Séparation config validée / runtime dataclass, respecte `HYDROMODPY_NO_DISPLAY`/`NO_SAVE` | Garder |
| `orchestration.py` (18 l.) | Façade de compat ré-exportant suites.py | **acceptable** | Utile pendant migration, à supprimer ensuite | Supprimer après 1 cycle de release |
| `suites.py` (904 l.) | Orchestration live | **à améliorer** | Fonctions monolithes de 200+ l. | Split en `flow_suite/`, `particles_suite/`, `transport_suite/` + dispatcher table-driven |
| `posthoc.py` + `posthoc_orchestration.py` (1 244 l.) | Re-plot depuis catalog/FS | **problématique** | Duplication avec `suites.py` (>80 %), 4 blocs reshape 1D→2D recopiés | Unifier via un `PayloadSource` abstrait |
| `figures/` (12 fichiers, 2 900 l.) | Primitives `render_*/plot_*` | **acceptable** | Paire systématique = boilerplate × 25 | Décorateur `@as_figure` |
| `report/overview_report.py` (498 l.) | Carte d'identité bassin | **acceptable** | Bonne délégation aux primitives, seul module en mode Agg | Vérifier que `matplotlib.use('Agg')` est appliqué avant tout import mpl amont |
| `visualization_results.py` (914 l.) | Classe legacy `Visualization` | **problématique** | Monolithe, `plt.switch_backend` à chaud, `cmap='jet'` x3 | Supprimer après migration des 3 cas restants |
| `visualization_watershed.py` (469 l.) | Fonctions watershed legacy | **problématique** | `mpl.style.use` global à l'import, `except: pass` bares, side-effect d'écriture shapefile | Supprimer au profit de `figures/maps.py` |
| `export_vtuvtk.py` (1 258 l.) | Export VTU/VTK FloPy | **non-standard** | Pas à sa place dans `display/`, couplage `flopy` fort | Déplacer vers `spatial/mesh/io/` ou `results/exporters/vtu.py` |

---

## 2. Qualité des figures

### 2.1 Colormaps — conformité Crameri / perceptual uniformity

Scan `cmap=` / `cmap='` dans tout le package :

| Occurrence | Fichier:ligne | Verdict |
|---|---|---|
| `cmap='viridis'` (head, thickness) | `figures/flow_synthesis.py`, `figures/boussinesq.py` | **conforme** |
| `cmap='terrain'` (DEM) | `figures/maps.py`, `figures/flow_synthesis.py` | **acceptable** (non perceptuel, mais standard topographique) |
| `cmap='Blues'`, `cmap='Reds'`, `cmap='magma'`, `cmap='plasma'` | `figures/flow_synthesis.py` | **conforme** |
| `cmap='coolwarm'` (signed diff) | `figures/boussinesq.py` | **conforme** (divergent symétrique approprié pour diffs) |
| `cmap='jet'` pour persistency_index | `suites.py:685`, `posthoc_orchestration.py:855` | **problématique** |
| `cmap='jet'` pour WTD composite | `figures/spatial.py:127, 156` | **problématique** |
| `cmap='jet'` pour residence times | `figures/maps.py:478, 487, 491` (pathlines) | **problématique** |
| `cmap='jet'` pour surface_flow | `visualization_results.py:269, 278` | **problématique** (legacy) |
| `cmap='cool'` pour residence times | `visualization_results.py:348, 354` | **à améliorer** |
| `cmap='RdYlGn_r'` pour drain_flow | `visualization_results.py` | **à améliorer** (accessibilité daltoniens) |
| `cmap='jet'` pour calib_zones | `visualization_watershed.py:399, 401` | **problématique** (legacy) |
| `cmap='turbo'` pour concentration | `figures/spatial.py` | **acceptable** (turbo > jet mais reste non strictement perceptuel) |

**6 occurrences actives de `jet`** dans du code non-legacy. La recommandation de matplotlib 2.0 (2017), confirmée par Crameri, Shephard & Heron (2020, *Nat. Commun.*), est sans ambiguïté : `jet` crée des artefacts visuels (banding vert/jaune), fausse l'interprétation quantitative et est inaccessible aux daltoniens. **À remplacer partout.**

Correspondances recommandées :
- Persistency index [0, 1] → `cividis` ou `viridis` (séquentiel perceptuel).
- WTD [0, 10 m] → `viridis_r` ou `Blues` (inversée pour que "proche surface" = foncé).
- Residence times → `magma` ou `plasma`.
- Calibration zones → qualitatif : `tab10` ou `Paired`.

### 2.2 Unités

**Points positifs** :
- `flow_synthesis.py` utilise `FLOW_SPATIAL_FIELD_SPECS` (dict dataclass) avec `colorbar_label` explicite pour chaque variable (ex. `"Head [m]"`, `"Seepage [m/day]"`, `"Discharge [m/day]"`).
- `cross_section.py` : axes "Elevation [m a.s.l.]" / "Distance along profile [m]".
- `intermittency.py` (figure) : légende typée ONDE (Assec / Non visible / …).

**Points négatifs** :
- Labels écrits `m3/s`, `m2`, `L^3/T` au lieu des caractères Unicode `m³/s`, `m²`, `L³/T`. Cohérence chartée faible.
- `"Sum of pumping in wells [L$^3$/T]"` (timeseries.py:85) — mélange LaTeX (`L$^3$/T`) et ASCII (`m3/s`).
- `"Seepage [0/1]"` dans `posthoc_orchestration.py` annoté comme booléen alors que `seepage_areas` est en réalité `m/day` côté MODFLOW — **label faux** quand le champ est quantitatif.
- Facteurs unités magiques : `recharge * 30 * 1000` (m → mm/mois, suites.py:483) ; `runoff / cell_area` pour Q-specific. Pas de constante nommée, pas de reference à `hydromodpy/core/units/`.

**Verdict** : **à améliorer** — unités présentes mais non normalisées. Les labels devraient venir de `core/units/` + Unicode.

### 2.3 Conventions cartographiques

**Absent** :
- **Aucun usage de cartopy.** Zero. Les cartes DEM/hydrographie/WTD sont plottées en coordonnées métriques projetées (EPSG::2154/3857 suivant le projet) **sans jamais déclarer le CRS sur l'axe**. Aucun `GeoAxes`, aucun `ccrs.epsg()`, aucun `Transform`.
- **Aucune scalebar robuste.** `matplotlib-scalebar` est importé optionnellement avec fallback stub vide dans trois fichiers. Les figures `figures/maps.py` n'appellent pas la scalebar.
- **Aucun north arrow.**
- **Aucun graticule / coordinate labels** — `ax.set_axis_off()` est systématique.
- **Aucun `contextily`** pour tiles de fond, alors qu'il est importé conditionnellement dans le legacy.

**Présent** :
- Overlay du contour watershed (GeoDataFrame) : ✓.
- Overlay hydrographie Strahler via `_stream_order_colors` (Blues monochrome) : ✓.

**Verdict** : **problématique**. Une bibliothèque d'hydrogéologie distribuant des figures "cartographiques" sans CRS explicite produit des figures non republiables. Comparaison : `flopy.plot.PlotMapView` gère le CRS nativement ; `pygmt.Figure` force une projection déclarative.

### 2.4 Robustesse numérique

- Quantiles robustes `(0.02, 0.98)` pour colorbar dans `flow_synthesis.py` : **bonne pratique**.
- `vmin`/`vmax` hardcodés dans `figures/spatial.py` (`wtd_vmax=10.0`) : **à améliorer** (auto-scale avec fallback).
- Masquage nodata via `np.ma.masked_array(mask=data==nodata)` : ✓.

### 2.5 Tableau synthèse qualité figures

| Critère | Verdict | Justification |
|---|---|---|
| Colormaps perceptuelles | **à améliorer** | 6 `jet` dans du code actif ; `cool`, `RdYlGn` résiduels |
| Labels + unités | **à améliorer** | Unicode inconsistant, `[0/1]` pour du `m/day`, facteurs magiques |
| CRS / cartopy | **non-standard** | Pas de GeoAxes, pas de scalebar, pas de north arrow |
| Quantiles robustes | **conforme** | `(0.02, 0.98)` dans flow_synthesis |
| Colorbars | **acceptable** | Présentes sauf dans `visualization_results` legacy |
| Typographie / légendes | **acceptable** | `fontsize=7-12` cohérent, parfois trop petit (5.5 dans `water_quality`) |
| Multi-panel | **acceptable** | `make_figure(nrows, ncols)` + `_single_axes`, sans layout engine |

---

## 3. Types de figures hydrogéologiques : inventaire et lacunes

### 3.1 Présent

| Famille | Figures implémentées |
|---|---|
| **Cartes** | DEM, géologie, hydrographie (Strahler), WTD, WT elevation, seepage areas, pathlines, residence times, persistency index, accumulation flux, concentration, edge flux Boussinesq, triptych topo/head/depth |
| **Coupes** | 1 coupe verticale (DEM + watertable) avec fills bleu/marron |
| **Bilans** | Mass balance signée (components + net), budget bar chart, cumulative recharge/discharge |
| **Séries temporelles** | Discharge (obs/sim + recharge), piezometry (obs/sim + recharge), concentration panel, intermittency catégorielle (ONDE 5 états), water quality multi-paramètre, climatic summary (P/ETP mensuels moyens), drainage density stacked area, probe heads Boussinesq |
| **Tables** | Stats card, station inventory |
| **Animations** | GIF + MP4 + Plotly slider HTML |
| **3D** | Scène VTK/vedo (legacy `visualization_results.visual3D`) |
| **VTU** | Export ParaView-compatible |

### 3.2 Manquant (standards hydrogéologie)

| Figure standard | Domaine | Présence | Recommandation |
|---|---|---|---|
| **Flow duration curve / exceedance curve** | Hydrologie de base | ❌ | À ajouter : 1 fonction `render_duration_curve(ax, series)` en 20 lignes |
| **Recession curve / Maillet fit** | Analyse de tarissement | ❌ (sauf cas de calibration Brutsaert isolé) | À ajouter comme primitive `figures/recession.py` |
| **Storage-discharge S-Q** | Analyse non-linéaire récession | ❌ | À ajouter |
| **Diagramme de Piper** | Faciès hydrochimique | ❌ | À ajouter si ambition water quality |
| **Diagramme de Stiff / Schoeller** | Hydrochimie | ❌ | Idem |
| **Boxplot saisonnier piézo / Q** | Stationnarité, régime | ❌ | À ajouter |
| **Rose des directions d'écoulement** | Gradient hydraulique | ❌ | À ajouter |
| **Profondeur-fréquence piézo** | Régime aquifère | ❌ | À ajouter |
| **Semi-variogramme / covariance spatiale** | Géostat | ❌ | Probablement hors scope |
| **Coupe multicouche** (aquifer/aquitard stack, coloration K) | Coupe géologique | ❌ (cross_section mono-couche uniquement) | À ajouter |
| **Hydrogramme unitaire, analyse de fréquences de crues** | Hydrologie | ❌ | Probablement hors scope |
| **Heatmap climatologique** (année × mois) | Climat | ❌ | Trivial à ajouter |

**Verdict** : **à améliorer**. Le kit de visualisation est complet pour le spatial/mass-balance, **lacunaire pour l'analyse statistique hydrogéologique** (signature temporelle, récession, fréquence). Un utilisateur produisant une carte d'identité de bassin devra écrire ses propres duration curves.

### 3.3 Qualité de la coupe (cross_section.py)

La coupe 1D existante est **minimaliste** :
- Pas de gestion multi-couches (aquifer stack).
- Pas de coloration K / géologie le long de la coupe.
- Pas de vecteurs d'écoulement (quiver) — or c'est LA figure canonique en hydrogéologie.
- Pas de `head_contours` superposés.

Comparaison avec `flopy.plot.PlotCrossSection` : ce dernier trace automatiquement les couches, contourne les heads, affiche les BC types. Le module HydroModPy est ~10 ans en arrière sur ce point.

---

## 4. Postprocess : bon package ?

### 4.1 Positionnement actuel

```
analysis/postprocess/
├── netcdf/           (NetcdfWriter, FlowNetcdfPostprocess, TransportNetcdfPostprocess)
├── timeseries/       (FlowTimeseriesPostprocess, TransportTimeseriesPostprocess)
├── flow/             (matching_streams, intermittency)
├── postprocess_config.py
└── runner.py
```

### 4.2 Analyse par sous-module

**`flow/intermittency.py` (247 l.)**
Calcul de `total_areas`, `perenn_areas`, `intermit_areas` à partir de `accumulation_flux` agrégé par fenêtre temporelle. **C'est de la physique dérivée**, pas du post-traitement d'affichage. La formule "une cellule est pérenne si `days_flux == window_size`" est un choix de modélisation hydrologique (état hydrique des têtes de bassin) qui mériterait d'être dans `process/flow/` avec les autres dérivations, et exposé comme `ProcessContract`.

**Verdict** : mauvais emplacement. **Devrait être `process/flow/intermittency.py`** et produire un `FieldRecord` / `TimeseriesRecord` consommable par display comme n'importe quel autre champ. Actuellement c'est enfoui dans un `apply_intermittency_columns(frame, ...)` qui mute un DataFrame en place.

**`flow/matching_streams.py` (328 l.)**
Diagnostics bidirectionnels de distance obs↔sim via WhiteboxTools (downslope flowpaths, raster-to-vector, distance-to-stream). C'est un **algorithme de géomorphologie**, pas un post-traitement de sortie.

**Verdict** : **non-standard**. Devrait vivre dans `spatial/hydrography/` ou `analysis/comparison/streams/`. Le constructeur exécute **tout le pipeline à l'instanciation** (`prepare_files() → sim_to_obs() → obs_to_sim()` forcés dans `__init__`), antipattern Python confirmé (cf. "calling constructor for side effects"). `run_matching_streams()` est une fonction wrapper qui ré-appelle le constructeur, preuve que l'API est maladroite.

**`timeseries/flow_timeseries.py` (642 l.)**
La classe `FlowTimeseriesPostprocess` charge les `FieldRecord` de champs spatiaux depuis le catalogue, applique des **reducers par zone** (`_reduce_mean`, `_reduce_qspe`, `_reduce_percent`, `_reduce_sum`, `_reduce_max`), et écrit un CSV `_simulated_timeseries.csv`. **Fonction légitime** mais mal découpée :
- `__init__` exécute tout (193 lignes de constructeur à side-effect I/O).
- `_reduce_mean` écrase les valeurs négatives à zéro "Keep legacy behavior" (l. 454) — heuristique silencieuse.
- `_reduce_qspe` calcule un débit spécifique `Q / A` — physique qui devrait venir de `core/units/` ou `process/flow/derived/`.
- Conversion `m/day → mm/month` (recharge×30×1000) : ne devrait pas vivre ici.

**Verdict** : Le **concept** (aggregation field → timeseries) est correct, l'**emplacement** discutable. Les reducers sont des opérations génériques qui devraient vivre dans `results/reducers/` (module transverse consommé par display et postprocess). L'écriture CSV est redondante avec le catalog (`write_timeseries`) : deux sources de vérité concurrentes.

**`netcdf/` — voir §5.**

**`runner.py` (277 l.)**
Orchestrateur. Qualité correcte. Couplage fort avec `display` via import direct (l. 16-21) : couche postprocess ↔ display non séparables.

### 4.3 Tableau synthèse postprocess

| Module | Verdict | Emplacement correct |
|---|---|---|
| `flow/intermittency.py` | **à déplacer** | `process/flow/derived/intermittency.py` |
| `flow/matching_streams.py` | **à déplacer** | `analysis/comparison/streams/` ou `spatial/hydrography/diagnostics/` |
| `timeseries/flow_timeseries.py` | **à refactorer** | Reducers vers `results/reducers/`, CSV via catalog |
| `netcdf/*.py` | **acceptable** | OK dans `analysis/postprocess/netcdf/` mais voir §5 pour CF |
| `postprocess_config.py` | **conforme** | Pydantic propre, profils "standard/solver_only" |
| `runner.py` | **acceptable** | Orchestrateur propre |

---

## 5. Export NetCDF — conformité CF-1.8

### 5.1 Analyse de `NetcdfWriter` (netcdf_writer.py)

**Ce qui est fait correctement** :
- `x`, `y` : attribut `standard_name="projection_x_coordinate"` / `"projection_y_coordinate"` ✓.
- `long_name` présent ✓.
- Encoding int16 avec `scale_factor`/`add_offset`/`_FillValue` ✓ — conformité CF packing section 8.1.
- `dataset.rio.write_crs` pour attacher le CRS ✓ (via rioxarray → respecte `grid_mapping_name`).

**Ce qui n'est PAS conforme CF-1.8** :

| Attribut CF requis | Présence | Statut |
|---|---|---|
| `Conventions = "CF-1.8"` | ❌ | Jamais écrit. Attribut global obligatoire. |
| `title`, `institution`, `source`, `history` | ❌ | Absents. |
| `cell_methods` sur variables (ex. `"time: mean"`) | ❌ | Absent. |
| `standard_name` sur variable principale | ❌ | Présent uniquement sur x/y. La variable de sortie (head, seepage, …) n'a aucun standard_name. `groundwater_potential` existe dans CF Standard Name Table ; `land_ice_basal_melt_flux` n'est pas applicable. |
| Unité de `time` ISO-8601 (`days since 1970-01-01`) | ❌ | Les times sont écrits comme `DatetimeIndex` pandas → xarray les encode automatiquement, mais ça dépend de la version xarray. Pas de contrôle explicite. |
| Coordinate bounds (`time_bnds`) | ❌ | Absents. |
| `units="Meter"` majuscule non-conforme | ❌ | UDUnits attend `"m"` ou `"meter"` (minuscule). `"Meter"` n'est pas reconnu par ncview/Panoply strictement. |
| `units="m2"` au lieu de `"m**2"` ou `"m2"` (UDUnits accepte les deux) | ⚠️ | Acceptable. |
| `grid_mapping` pointant vers variable CRS | partiel | `rioxarray.write_crs` crée bien la variable `spatial_ref`, mais les variables data n'ont pas l'attribut `grid_mapping="spatial_ref"`. |

**Variable principale nommée par basename de fichier** (l. 179) :
```python
main_var = os.path.splitext(os.path.split(out_path)[-1])[0]
```
Si `out_path = ".../watertable_elevation.nc"`, la variable s'appelle `watertable_elevation`. **Fragile** : dépend du chemin. Un renommage de fichier casse le NetCDF. Devrait être un argument explicite.

**Bug potentiel** dans `_apply_common_encoding` (l. 82-104) :
```python
if bound_min < 0:
    bound_min *= 1.1
elif bound_min > 0:
    bound_min /= 1.1
```
Expansion asymétrique du domaine. Pour une variable positive quasi-constante (ex. head ≈ 100 m partout), `bound_min /= 1.1 = 90.9`, la plage utile [100, 100] devient [90.9, 100] → perte de précision à l'encoding int16. Préférable : `np.quantile(data, [0.001, 0.999])` + marge symétrique.

**Export cell-based** (`export_cell_netcdf`, l. 203-282) : crée une dimension `cell` avec `cell_x`, `cell_y`, `cell_area`. **Non-conforme UGRID-1.0** qui est LA convention CF pour maillages non structurés. UGRID exige :
- Variable "dummy" `mesh` avec `cf_role="mesh_topology"`, `topology_dimension=2`.
- Références `node_coordinates`, `face_node_connectivity`.
- Les variables data pointent `mesh="mesh"` + `location="face"`.

L'export actuel est **maison** : interopérable seulement avec du code HydroModPy. Un lecteur UGRID standard (Panoply, xugrid) ne reconnaît pas le maillage.

### 5.2 Interopérabilité

- **ncview** : ouvrable, affichera variable principale + x/y comme attendus sur grille structurée.
- **Panoply** : ouvrable, mais le manque de `Conventions="CF-1.8"` affiche un warning "no CF conventions detected".
- **xarray.open_dataset** : fonctionne (xarray est permissif).
- **CDO / NCO** : `cdo info` passera ; `cdo sellonlatbox` échouera si CRS projeté (pas de lat/lon).
- **xugrid** (UGRID) : **ne reconnaîtra pas le maillage cell-based**.

### 5.3 Tableau NetCDF

| Exigence CF-1.8 | Statut | Verdict |
|---|---|---|
| `Conventions=CF-1.8` global | ❌ | **problématique** |
| `standard_name` sur variables data | ❌ | **problématique** |
| `units` UDUnits valides | Partiel (`Meter` majuscule invalide) | **à améliorer** |
| `cell_methods` | ❌ | **à améliorer** |
| `grid_mapping` sur variables data | ❌ | **à améliorer** |
| Time axis CF-compliant | Indirect via xarray | **acceptable** |
| Unstructured mesh (UGRID-1.0) | ❌ (format maison) | **non-standard** |
| Encoding packing int16 | ✓ (avec bug marge asymétrique) | **acceptable** |
| Global metadata (title, source, history) | ❌ | **à améliorer** |

**Verdict global NetCDF** : **non-standard**. Les fichiers sont lisibles par xarray/ncview mais ne peuvent pas être revendiqués CF-1.8-compliant. La non-conformité UGRID pour les maillages irréguliers est particulièrement problématique vu que HydroModPy mise sur MODFLOW 6 DISV.

---

## 6. Timeseries : extraction et métriques

### 6.1 Extraction

`FlowTimeseriesPostprocess.extract_results` (l. 533-642) agrège des `FieldRecord` 3D (time, cell) vers un CSV 2D (time, variable) via des reducers.

**Reducers disponibles** :
- `_reduce_mean` (mean spatial, weighted si unstructured)
- `_reduce_sum` (nansum)
- `_reduce_max` (nanmax)
- `_reduce_percent` (% cellules avec valeur > 0)
- `_reduce_qspe` (débit spécifique = Q/A)

**Problèmes** :
- Pas d'interpolation spatiale aux stations — les "timeseries aux stations" viennent de `simulation/results/extractors/` ailleurs (observation_points). Le double pipeline crée du confusion : le display consomme parfois le catalog (timeseries aux stations) et parfois le CSV (catchment-aggregated).
- **Agrégation temporelle** : aucune. Les séries sont exportées stress-period par stress-period. Si l'utilisateur veut une moyenne mensuelle, il doit resample en aval (c'est ce que fait `suites.py` avec `factor=30`). Devrait être exposé comme option Pydantic.
- `_reduce_mean` applique silencieusement `masked[masked < 0] = 0` (l. 454) — filtrage physique hardcodé "Keep legacy behavior". **Bug** : masque les valeurs légitimement négatives (ex. WTD < 0 signifierait "au-dessus de la surface" — cas possible en zone de seepage).

### 6.2 Métriques (statistics.py)

`rmse_manual`, `nse_manual`, `mare_manual`, `kge_manual`, `efficiency_criteria` — vérification des formules vs littérature :

| Métrique | Formule HydroModPy | Formule canonique | Verdict |
|---|---|---|---|
| **RMSE** | `np.sqrt(np.mean((sim - obs) ** 2))` | Identique | ✓ |
| **NSE** (Nash-Sutcliffe, 1970) | `1 - sum((obs-sim)²) / sum((obs - mean(obs))²)` | `1 - sum((sim-obs)²) / sum((obs-mean(obs))²)` | ✓ (`(obs-sim)²` = `(sim-obs)²`) |
| **MARE** | `mean(abs(sim-obs)/obs)` | `mean(abs((sim-obs)/obs))` | ⚠️ explode si `obs=0`, pas de garde |
| **KGE** (Gupta et al. 2009) | `1 - sqrt((r-1)² + (alpha-1)² + (beta-1)²)` avec `alpha = std(sim)/std(obs)`, `beta = sum(sim)/sum(obs)` | **Correct pour la forme 2009**. Kling (2012) révision : `beta = mean(sim)/mean(obs)` et non `sum/sum` | ✓ **si l'on assume KGE 2009**. Si KGE 2012 voulu → bug |

**Problèmes** :
- Pas de gestion `NaN` dans `obs` dans `kge_manual` / `nse_manual` individuellement (seulement dans `efficiency_criteria`).
- `np.corrcoef` renvoie `NaN` si `std=0` — pas géré.
- `nrmse = rmse / np.mean(obs)` : NaN si `mean(obs)=0`, pas standard (habituellement `rmse / (max(obs)-min(obs))` ou `rmse / std(obs)`).
- **Pas de KGE' (Kling 2012)** exposée. À fournir pour la modélisation hydro moderne.
- **Pas de PBIAS** exposé (biais % standard USGS).
- `nse_manual(sim, obs, transform='log')` ajoute `eps=1e-6` — fragile si `obs` contient de vrais zéros négatifs (débit sec → `log(-x)`).

**Verdict métriques** : **acceptable**. Formules de base correctes, mais le kit est incomplet (KGE', PBIAS absents) et non robuste aux cas limites.

---

## 7. Headless mode : `HYDROMODPY_NO_DISPLAY` / `NO_SAVE`

### 7.1 Pattern implémenté

```python
# display_config.py:254-259
if self.respect_env_no_display and os.environ.get("HYDROMODPY_NO_DISPLAY") == "1":
    show = False
if self.respect_env_no_save and os.environ.get("HYDROMODPY_NO_SAVE") == "1":
    save = False
```

Puis `DisplayOptions.should_render()` court-circuite les suites.

**C'est un bon pattern de contrôle de flux** mais il ne protège pas les effets de bord d'import. Comparaison avec `matplotlib.use('Agg')` :

| Mécanisme | Effet | Moment |
|---|---|---|
| `matplotlib.use('Agg')` | Force un backend non-interactif au niveau process | **Avant** tout import pyplot |
| `HYDROMODPY_NO_DISPLAY=1` + `should_render()=False` | Saute les fonctions plot | Runtime, **après** potentiellement déjà un import interactif |

### 7.2 Problèmes détectés

**Import top-level matplotlib.pyplot** :
```
hydromodpy/analysis/display/common.py:17  — import matplotlib.pyplot as plt
hydromodpy/analysis/display/visualization_results.py:19-42
hydromodpy/analysis/display/visualization_watershed.py:~35
hydromodpy/analysis/display/export_vtuvtk.py  (fallback stub)
hydromodpy/analysis/display/report/overview_report.py:27 — matplotlib.use("Agg") avant les imports matplotlib
```

Seul `report/overview_report.py` force `Agg` **avant** d'importer pyplot (ordre correct). `common.py` importe directement `matplotlib.pyplot as plt` au top-level ligne 17 — si un process tourne sans `DISPLAY`, matplotlib essaie de choisir automatiquement un backend compatible : OK sur CI Linux (Agg par défaut), fragile sur macOS/Windows en headless.

**Side-effect global à l'import** :
```python
# visualization_watershed.py lignes ~55-96
plt.style.use("classic")
matplotlib.rcParams['font.family'] = 'serif'
# ...
```
Modifier `rcParams` au simple import casse les figures d'utilisateurs qui ont leur propre style. **Anti-pattern bibliothèque** absolu.

**Changement de backend à chaud** :
```python
# visualization_results.py:717
plt.switch_backend("QtAgg")
```
Pour `interactive_cross_section`. Casse CI, casse Jupyter headless. À supprimer ou déclencher uniquement sur condition explicite.

### 7.3 Tableau headless

| Mécanisme | Verdict |
|---|---|
| `HYDROMODPY_NO_DISPLAY` runtime | **conforme** (bien pensé côté config) |
| `HYDROMODPY_NO_SAVE` runtime | **conforme** |
| `matplotlib.use('Agg')` amont | **à améliorer** (seul `report/` le force) |
| Absence de side-effects d'import | **problématique** (watershed.py casse le pattern) |
| Backend switch dynamique | **problématique** (visualization_results.py) |

---

## 8. Report / Overview — utilité vs bloat

### 8.1 Ce qui est implémenté

`hydromodpy/analysis/display/report/` produit une **carte d'identité de bassin** :
- Cartes (DEM, géologie, hydrographie).
- Séries temporelles observées (discharge, piezometry, intermittency, water quality).
- Résumé climatique (P/ETP mensuels).
- Stats card (aire, élévation, nombre de stations).
- Station inventory table.

Sortie : une grande figure matplotlib compositée multi-subplots + JSON summary.

### 8.2 Comparaison avec les standards

| Outil | Positionnement | HydroModPy vs |
|---|---|---|
| **jupyter-book** | HTML multi-page + exécution notebooks | HydroModPy = une figure PNG uniquement — pas de navigation, pas de texte explicatif. ≠ |
| **quarto** | Idem jupyter-book + multi-format (PDF/HTML/docx) | ≠ |
| **sphinx-gallery** | Auto-génération à partir de scripts Python | Les `.rst` `capability_gallery/` font ça, mais **ailleurs** (docs/) |
| **papermill + nbconvert** | Exécute un notebook paramétré | ≠ |
| **datapane / dash** | App web interactive | ≠ |

**Ce qui est fourni est une seule figure compositée**. Le `OverviewSummary` JSON est un résumé numérique, non rendu visuellement. C'est utile — les utilisateurs veulent une vue synthétique — mais **ce n'est pas un vrai "report"**.

### 8.3 Bloat ou valeur ?

- **Valeur réelle** : oui, la carte d'identité est consommée par `examples/projects/Nancon_data_overview/` et produit une figure PNG utilisable en rapport de projet.
- **Bug latent détecté** : `_render_intermittency_panel` utilise `sharex=3` et `loc="bottom"` (syntaxe ultraplot) dans du matplotlib standard — ces arguments ne sont pas valides en matplotlib. À corriger ou à clarifier la dépendance à ultraplot.

**Verdict** : **acceptable**. Utile mais surdimensionné : 498 lignes dans `overview_report.py` pour une figure composée qui pourrait être 200 lignes en déléguant à `figures/`. L'existence de 4 fichiers dans `report/` (config, data_loader, summary, report) pour une fonctionnalité unique traduit un découpage excessif. **Le "report" ne mérite pas son sous-package** — devrait être un module unique `display/overview.py`.

---

## 9. Tableau récapitulatif par composant display

| Composant | Lignes | Rôle | Verdict | Action recommandée |
|---|---|---|---|---|
| `display/__init__.py` | 41 | Façade publique | **conforme** | — |
| `display/adapters.py` | 123 | Bridge PointRecord→DataFrame | **conforme** | — |
| `display/common.py` | 267 | Helpers lifecycle figures + catalog | **acceptable** | Supprimer `_extract_recharge_series_m_per_day` si orphelin |
| `display/compare.py` | 109 | CLI hmp display compare | **conforme** | — |
| `display/display_config.py` | 350 | Pydantic + runtime | **conforme** | — |
| `display/export_vtuvtk.py` | 1 258 | Export VTU/VTK FloPy | **non-standard** | Déplacer vers `spatial/mesh/io/` ou `results/exporters/` |
| `display/flow_payloads.py` | 470 | Dataclasses payload + builders | **acceptable** | Retirer deprecation aliases après release |
| `display/orchestration.py` | 18 | Façade compat suites | **acceptable** | Supprimer à terme |
| `display/posthoc.py` | 321 | Dataclasses PosthocContext | **acceptable** | Éliminer double entrée `from_store`/`from_result_store` |
| `display/posthoc_orchestration.py` | 923 | Ré-plot depuis catalog/FS | **problématique** | Factoriser avec `suites.py`, éradiquer duplication reshape |
| `display/suites.py` | 904 | Orchestration live | **à améliorer** | Splitter par famille + table-driven dispatch |
| `display/transport_plots.py` | 309 | Frames concentration transport | **acceptable** | Retirer deprecation aliases |
| `display/visualization_results.py` | 914 | Classe monolithe legacy | **problématique** | Supprimer après migration cas restants |
| `display/visualization_watershed.py` | 469 | Fonctions watershed legacy | **problématique** | Supprimer, migrer vers `figures/maps.py` |
| `display/figures/__init__.py` | 137 | Ré-exports | **acceptable** | — |
| `display/figures/animation.py` | 178 | GIF, MP4, Plotly slider | **conforme** | — |
| `display/figures/boussinesq.py` | 555 | Figures solveur Boussinesq | **acceptable** | Unifier avec stack triangulaire `HydroMesh` |
| `display/figures/cross_section.py` | 88 | Coupe 1D terrain/nappe | **acceptable** | Enrichir multi-couches + vecteurs |
| `display/figures/flow_diagnostics.py` | 226 | Mass balance + probes | **conforme** | — |
| `display/figures/flow_synthesis.py` | 552 | Triptych + spatial field + cumul | **conforme** | Référence qualité du package |
| `display/figures/maps.py` | 539 | DEM, géologie, hydro, pathlines | **à améliorer** | Éradiquer `jet`, ajouter cartopy, fixer fuite `_open_dem` |
| `display/figures/spatial.py` | 291 | Raster + seepage + concentration | **à améliorer** | Remplacer `jet` + `turbo`, paramétrer vmin/vmax |
| `display/figures/tables.py` | 143 | Stats card + station inventory | **conforme** | — |
| `display/figures/timeseries.py` | 829 | Discharge, piezo, intermittency, WQ, climatic, drainage | **acceptable** | Ajouter duration curve, recession curve |
| `display/report/overview_config.py` | 68 | Pydantic overview | **conforme** | — |
| `display/report/overview_data_loader.py` | 112 | Adapter data overview | **acceptable** | Contractualiser duck-type |
| `display/report/overview_report.py` | 498 | Orchestrateur overview | **acceptable** | Fusionner le sous-package dans 1 fichier |
| `display/report/summary.py` | 117 | Dataclass `OverviewSummary` | **conforme** | — |
| **TOTAL display** | **~10 300** | | | ~2 600 l. supprimables (legacy) + ~400 l. factorisables (render/plot) |

---

## 10. Synthèse et recommandations priorisées

### 10.1 Forces

- `display_config.py` : Pydantic + runtime séparés, respect env vars, bonne couche de validation.
- `figures/flow_synthesis.py` : référence de qualité (specs dataclass, quantiles robustes, labels unités corrects, colormaps perceptuelles).
- Pattern `render_*/plot_*` : conceptuellement bon.
- `postprocess_config.py` : profils `solver_only`/`standard` bien faits.
- Métriques de base correctes (NSE, RMSE, KGE-2009).

### 10.2 Dettes critiques

1. **`jet` dans 6+ lieux actifs**. Bug scientifique mineur mais embarrassant pour une lib moderne.
2. **Absence totale de cartopy / CRS explicite** sur les cartes hydrogéologiques.
3. **NetCDF non CF-1.8** (no Conventions, no standard_name, `Meter` vs `m`), **non UGRID** pour maillages irréguliers.
4. **Side-effects globaux à l'import** dans `visualization_watershed.py` (rcParams, `plt.style.use`).
5. **Backend switch à chaud** dans `visualization_results.py` (`QtAgg`).
6. **~2 640 lignes legacy** (`visualization_results`, `visualization_watershed`, `export_vtuvtk`) redondantes.
7. **Duplication `render_*/plot_*`** → ~400 l. factorisables via décorateur.
8. **Duplication `suites.py` ↔ `posthoc_orchestration.py`** → 80 % de logique doublée.
9. **Intermittency et matching_streams mal placés** : physique/géomorpho dans postprocess.
10. **Figures hydrogéologiques standards absentes** : duration curve, recession curve, storage-discharge, Piper, Stiff, coupes multicouches.

### 10.3 Actions prioritaires (ordre)

| # | Action | Effort | Impact |
|---|---|---|---|
| 1 | Remplacer tous les `cmap='jet'`/`'cool'`/`'RdYlGn'` par `viridis`/`cividis`/`plasma`/`tab10` | XS | Moyen |
| 2 | Ajouter `Conventions="CF-1.8"` + `standard_name` + corriger `Meter`→`m` dans `NetcdfWriter` | S | Élevé |
| 3 | Supprimer `plt.style.use`/`rcParams` au top-level de `visualization_watershed.py` | XS | Élevé |
| 4 | Supprimer `plt.switch_backend("QtAgg")` de `visualization_results.py` | XS | Élevé |
| 5 | Fixer bug `loc="bottom"`/`sharex=3` dans `report/overview_report.py` | XS | Bug latent |
| 6 | Factoriser pattern `render_*/plot_*` via décorateur | S | Moyen |
| 7 | Consolider `suites.py` + `posthoc_orchestration.py` derrière un `PayloadSource` abstrait | M | Élevé |
| 8 | Déplacer `intermittency.py` → `process/flow/derived/` | S | Architectural |
| 9 | Déplacer `matching_streams.py` → `analysis/comparison/streams/` | S | Architectural |
| 10 | Supprimer `visualization_results.py` + `visualization_watershed.py` après migration | M | 1 400 l. retirées |
| 11 | Déplacer `export_vtuvtk.py` → `results/exporters/vtu.py` | M | 1 258 l. relocalisées |
| 12 | Ajouter figures manquantes : duration curve, recession curve, coupe multicouches | M | Valeur produit |
| 13 | Adopter cartopy pour les cartes (au moins scalebar + north arrow) | M | Qualité publication |
| 14 | Adopter UGRID-1.0 pour export NetCDF cell-based | L | Interopérabilité |
| 15 | Exposer KGE' (Kling 2012) + PBIAS dans `statistics.py` | XS | Complétude |

### 10.4 Code à supprimer sans remplacement

- `hydromodpy/analysis/display/orchestration.py` (18 lignes de façade une fois `suites.py` migré en entrée publique).
- `_extract_recharge_series_m_per_day` dans `common.py` si confirmé orphelin.
- Deprecation aliases `run_id`/`artifact_id` dans `flow_payloads.py` après 1 release.
- Deprecation aliases `build_concentration_gif`, `plot_web_animation` dans `transport_plots.py`.
- Deprecation aliases `from_store`/`from_result_store` dans `posthoc.py`.
- `netcdf/netcdf.py` (13 lignes) : fichier placeholder vide, supprimer si non utilisé.

### 10.5 Verdict global

Le package `analysis/` est **fonctionnellement riche mais architecturalement fragmenté**. Il porte encore ~30 % de code legacy qui contredit les patterns établis par le refactor (`figures/`, `display_config.py`). La qualité scientifique des figures est **inégale** : excellente dans `figures/flow_synthesis.py`, médiocre ailleurs (colormaps `jet`, absence de CRS, NetCDF non conforme). Le post-traitement mélange responsabilités (physique, export, diagnostic) dans un même package.

**Priorité absolue** : éradiquer les 3 points toxiques (side-effects globaux, `jet`, NetCDF non CF), puis décommissionner les 2 640 lignes legacy. Après nettoyage, le package devrait peser ~7 500 lignes, plus cohérentes et testables.
