# Audit critique — `hydromodpy/analysis/` (display + postprocess)

Portée auditée : 38 fichiers, ~13 560 lignes sous `hydromodpy/analysis/display/` et `hydromodpy/analysis/postprocess/`. L'audit se concentre sur la qualité des figures, l'architecture d'orchestration, les exports NetCDF, les séries temporelles, le mode headless, le module overview, et la classification des post-traitements.

---

## 1. Architecture du package `display`

### 1.1 Vue d'ensemble

Le package expose trois couches d'abstraction, dans cet ordre du plus générique au plus spécifique :

1. **`figures/*.py`** — fonctions `render_*(ax, ...)` dessinant sur un axe existant, et leurs duals `plot_*(...)` qui créent la figure, dessinent, puis délèguent à `finalize_figure()`. C'est le **pattern matplotlib classique** (Figure/Axes/Artist) et c'est la seule partie du package qui vieillit bien.
2. **`suites.py` + `posthoc_orchestration.py`** — orchestration par "suite" (famille d'écoulement, particules, transport). Deux copies presque parallèles : la première consomme un `WorkflowContext` runtime, la seconde consomme un `PosthocContext` lu depuis le disque/catalog.
3. **`visualization_results.py` / `visualization_watershed.py` / `export_vtuvtk.py`** — code patrimonial massif (~2 641 lignes), presque exclusivement appelé par `examples_legacy/`.

### 1.2 Verdict global du pattern "suite"

| Critère | Verdict | Justification |
|---|---|---|
| Séparation Figure/Axes | **conforme** | `render_* / plot_*` reproduit correctement l'idiome matplotlib |
| Testabilité sans display | **acceptable** | `HYDROMODPY_NO_DISPLAY=1` + `finalize_figure` ferment correctement les figures ; cependant le pattern n'est **pas** équivalent à `matplotlib.use("Agg")` (cf. §7) |
| Granularité des suites | **à améliorer** | `plot_flow_suite` (suites.py:497, 193 lignes) fait à la fois le chargement des timeseries, la reshape des rasters, l'appel des figures, le fallback vers copies de PNG solveur — c'est un **monolithe procédural** |
| Extensibilité | **problématique** | aucune façade pour enregistrer une nouvelle suite (ex. un plugin thermique) — il faut éditer `suites.py` + `posthoc_orchestration.py` + `display_config.py` + `common.py` |
| Comparaison à `holoviews` | **non-standard** | holoviews sépare Element (la donnée annotée) de Layout/Overlay (la composition). Ici, figures et données sont intimement couplées : `FlowSpatialFigurePayload` est un DTO honnête mais les suites le construisent *puis* dispatchent manuellement chaque sortie |

### 1.3 Redondance suites.py ↔ posthoc_orchestration.py

**C'est le problème structurel le plus grave du package.** Les deux fichiers totalisent **1 827 lignes**, dont une part considérable est fonctionnellement équivalente :

| Fonction suites.py | Équivalent posthoc_orchestration.py | État |
|---|---|---|
| `_copy_latest_native_mesh_figures` | `_copy_latest_native_mesh_figures` | **copie quasi-identique** (suites.py:92, posthoc_orchestration.py:106) |
| `_extract_cross_section_data` | `_plot_cross_section` (inline logic) | **duplication logique** de reshape/col-slicing |
| `plot_flow_suite` → watertable/seepage | `_plot_watertable_maps` + `_plot_composite_wtd_seepage` | **deux implémentations** du même rendu |
| `_load_flow_timeseries_from_store` | `_plot_timeseries_summary` (inline) | **deux paths** pour récupérer les séries du catalog |
| reshape flat→2D (lignes 464-466, 625-629, 294-304, etc.) | reshape flat→2D (lignes 228-239, 295-301, 313-321, 383-391) | **le même bloc répété 8 fois** au total |

Recommandation : fusionner les deux orchestrateurs en un seul module paramétré par une source de données abstraite (`DataSource`). Les deux flux chargent déjà depuis `SimulationCatalog`, seule l'entrée (runtime objet vs UUID) diffère.

### 1.4 Duplication intra-suite

Dans `posthoc_orchestration.py`, le bloc suivant est répété **4 fois** à quelques lignes près (228-239, 295-301, 313-321, 383-391) :

```python
if arr.ndim == 1 and dem_masked.ndim == 2:
    try:
        arr = arr.reshape(dem_masked.shape)
    except ValueError:
        arr = arr[: dem_masked.size].reshape(dem_masked.shape)
elif arr.ndim == 2:
    arr = arr[0]
    if arr.size == dem_masked.size:
        arr = arr.reshape(dem_masked.shape)
```

Ce code doit vivre dans **un seul helper** `_reshape_flat_field_to_grid(arr, grid_shape)` — soit dans `common.py`, soit idéalement dans `results/zarr_store.py` (où le flat array naît) pour que tout le display consomme une API 2D stable.

### 1.5 Wrappers `plot_*` — surcoût contestable

Chaque figure définit deux fonctions : `render_*(ax, ...)` et `plot_*(...)`. Le wrapper `plot_*` fait systématiquement les mêmes 4 lignes :

```python
fig, axs = make_figure(figsize=..., dpi=...)
ax = _single_axes(axs)
render_*(ax, ...)
fig.tight_layout()
if options: finalize_figure(fig, options=..., save_path=...)
return fig, ax
```

Pour ~10 fonctions `render_*`, il y a ~10 `plot_*` qui sont presque des copies. **Une seule fonction utilitaire** `build_single_panel_figure(render_fn, **render_kwargs)` dans `common.py` supprimerait ~150 lignes de code répété.

**Verdict** : over-engineering léger mais systématique. La convention render/plot est saine ; le wrapper explicite ne l'est pas.

---

## 2. Qualité des figures

### 2.1 Colormaps

| Carte | Colormap actuelle | Verdict | Justification |
|---|---|---|---|
| `watertable_elevation` | `viridis` (flow_synthesis.py:43) | **conforme** | perceptuellement uniforme |
| `watertable_depth` | `Blues` | **conforme** | séquentiel, sémantique eau |
| `seepage_areas` | `Reds` | **acceptable** | séquentiel ; `Oranges` pourrait être plus distinct du log-drain |
| `outflow_drain` | `magma` | **conforme** | perceptuellement uniforme |
| `accumulation_flux` | `plasma` | **conforme** | perceptuellement uniforme |
| `persistency_index` | **`jet`** (suites.py:685, posthoc_orchestration.py:855) | **problématique** | `jet` est activement découragé (Nuñez 2018, matplotlib>=3.9) — rainbow = non perceptuellement uniforme + barrières artificielles |
| composite seepage+WTD | **`jet`** (spatial.py:127) | **problématique** | même remarque |
| `pathlines` / résidence | **`jet`** (maps.py:478, 487, 490) | **problématique** | devrait utiliser `plasma`/`viridis` ou un log-cmap `cividis` ; le temps de résidence n'a pas de sens à "sauter" via jet |
| `drain_flow` legacy | `RdYlGn_r` (visualization_results.py:246) | **problématique** | divergent utilisé pour un séquentiel — à proscrire (Crameri 2020) |
| geology | palette hex ad-hoc | **acceptable** | catégoriel justifié |

**Recommandation** : appliquer une règle "pas de `jet`/`rainbow`" à l'échelle du package. `persistency_map`, qui représente une fraction [0,1], est typiquement rendu par `cividis` ou `cmo.turbid` dans la littérature hydrogéologique (e.g. Käser & Hunkeler 2016).

### 2.2 Unités, labels, échelles

Point positif : `FLOW_SPATIAL_FIELD_SPECS` (flow_synthesis.py:32) centralise les titres, labels de colorbar et unités ; c'est la bonne approche.

Problèmes :

- `render_discharge` utilise `ylabel="Discharge (m³/s)"` par défaut alors que `plot_flow_suite` lui passe `ylabel="Q / A [mm/month]"` — **l'unité par défaut est fausse** dans l'API publique. Un lecteur qui appelle `plot_discharge(observed_df=…)` sans forcer ylabel aura une mauvaise étiquette.
- `_reduce_qspe` (flow_timeseries.py:468) calcule `np.nansum(masked) / (cell * cell_area)` qui a les unités de `flux/surface`, mais le CSV est exporté sans indication d'unité. Le consommateur aval (`suites.py:483`) applique ensuite un facteur `* 30 * 1000` ad-hoc pour passer en `mm/month` : le pipeline unitaire n'est **pas documenté dans les données**, il est implicite dans le code d'affichage.
- Le triptyque `flow_state_triptych` gère correctement labels et colorbar compactes (flow_synthesis.py:146-180). **Bon travail** — c'est la qualité-cible du reste du package.
- `render_piezometry` (timeseries.py:216) fixe `axb.set_ylim(0, 100)` en dur pour la recharge, ce qui coupe les valeurs > 100 mm/mois sans avertissement.
- `render_cross_section` affiche "Elevation [m.a.s.l]" (cross_section.py:56) — bien — mais le `base_level` par défaut `y_min = min(wt) - 5.0` donne une coupe dont la base change d'une figure à l'autre ; une coupe géologique réelle fixe typiquement `base_level` au mur de l'aquifère.

### 2.3 Accessibilité visuelle

- Pas de mode "colorblind-safe" explicite ; `Blues_r`, `tab10` (timeseries.py:190) et `jet` sont tous sous-optimaux pour daltonisme.
- Aucune gestion de DPI adaptatif pour vectoriel (tout est en PNG 300 dpi, même quand SVG/PDF serait plus propre pour publication).
- Le mode `matplotlib_scalebar` est optionnel mais la classe *stub* (visualization_results.py:26-28, visualization_watershed.py:33-37) est **silencieusement dégradée** — la figure produite n'aura simplement pas de barre d'échelle.

### 2.4 Tableau récapitulatif figures

| Figure | Unités | Colormap | Échelles | Verdict |
|---|---|---|---|---|
| `flow_state_triptych` | m, m, m | terrain / viridis / Blues | robust quantiles 2%-98% | **conforme publication** |
| `cross_section` | m, m | fills saturé/non-saturé | auto | **acceptable** |
| `recharge_discharge_cumulative` | mm | couleurs palette tab | auto | **conforme** |
| `watertable_map` | m | viridis / Blues | auto | **conforme** |
| `seepage_areas` | m/day | Reds | 2%-98% | **acceptable** |
| `persistency_map` | [-] | **jet** | auto | **à améliorer** |
| `pathlines` | ans | **jet** + LogNorm | auto | **à améliorer** |
| `composite_seepage_wtd` | m | **jet** | 0-10 (hardcodé) | **problématique** |
| `concentration_map` | mg/L | turbo | LogNorm | **acceptable** |
| `boussinesq_state` | m | viridis | auto | **conforme** |
| `boussinesq_diagnostics` | m, mm/day | viridis/coolwarm/plasma/magma | auto | **conforme** |
| `drainage_density` | % | navy/dodgerblue fill | 0-100 | **conforme** |
| `intermittency` (ONDE) | catégoriel | palette 5 couleurs | 0.4-5.6 | **conforme** |

---

## 3. Types de figures manquants (standard hydrogéologique)

| Standard | Présent ? | Besoin | Priorité |
|---|---|---|---|
| Carte piézométrique avec **équipotentielles** (isolignes de h) | **non** — seul un raster `watertable_elevation` | la carte piézométrique canonique utilise des iso-potentielles + vecteurs `-K·∇h` | **haute** |
| Lignes de courant (streamlines, `matplotlib.pyplot.streamplot`) | **non** | interprétation de flux sortants | **haute** |
| Coupe géologique (stratigraphie par couche) | partielle — coupe colonne DEM / WT | manque multi-couche, aquitard/aquifère | **moyenne** |
| Hyétogramme (barres inversées en haut d'hydrogramme) | **non** | figure standard des hydrogrammes (Chow, Maidment, Mays 1988) | **moyenne** |
| Courbe de récession `log Q vs t` + Brutsaert-Nieber | **partielle** (dans `calibration/cases/recession_brutsaert/`) — pas dans display public | oui pour bilans basiques | **moyenne** |
| Diagramme de Piper | **non** | hydrogéochimie — mais hors scope écoulement | **faible** (hors scope) |
| Rose des vents / roseau directionnel | **non** | non applicable à ce toolkit | **n/a** |
| Courbe des débits classés (FDC) | **non** | indicateur standard signature hydrologique | **haute** |
| Profil de Ghyben-Herzberg / intrusion saline | **non** | hors scope flow d'eau douce | **n/a** |
| Diagramme de Hjulström / transport sédimentaire | **non** | n/a | **n/a** |
| Diagramme rose des lithologies | **non** | géologie — optionnel | **faible** |

Pour un **package d'hydrogéologie de bassin versant**, l'absence de FDC, d'équipotentielles et de hyétogramme est un manque significatif.

### 3.1 Cross-section

La coupe est **toujours une colonne N-S** (`_extract_cross_section_data` suites.py:468, `_plot_cross_section` posthoc_orchestration.py:394). Un toolbox moderne doit supporter :

- coupe obliquement orientée (deux points p₁, p₂) avec échantillonnage bilinéaire de la grille
- coupe multi-segments (polyligne)
- coupe avec multiples couches de conductivité coloriées en arrière-plan

L'infrastructure existe déjà (`HydroMesh.flatten_from_grid`) — il manque une fonction `sample_along_transect(mesh, field, p1, p2, n_samples)`.

---

## 4. Post-traitements : placement du code

### 4.1 `postprocess/flow/intermittency.py` (247 lignes)

**Verdict : mal placé.**

C'est un **calcul scientifique** qui transforme `accumulation_flux[t]` en indicateurs total/perennial/intermittent par fenêtre temporelle. Le pattern de fenêtrage (yearly/monthly/weekly/daily) est purement calculatoire et sans dépendance au moteur de visualisation.

Il devrait vivre dans :

- `hydromodpy/process/flow/diagnostics/intermittency.py` (où il pourrait être calculé au fil de l'exécution et écrit directement dans le catalog comme une timeseries dérivée), **ou**
- `hydromodpy/results/derived/intermittency.py` en suivant le pattern « derived variable » de xarray.

Le déplacer sortirait aussi une dépendance du `PostprocessConfig` (qui confond options de sortie et options de calcul).

### 4.2 `postprocess/flow/matching_streams.py` (329 lignes)

**Verdict : sérieusement mal placé.**

C'est une **pipeline spatiale** qui :
- clippe des rasters (`clip_tif`)
- convertit des pixels en points (`raster_to_vector_points`)
- trace des flowpaths (`trace_downslope_flowpaths`)
- calcule des distances downslope (`downslope_distance_to_stream`)

Toutes ces opérations relèvent de `spatial/` ou `process/flow/diagnostics/`. Aucune partie ne produit un artefact de visualisation. L'appel est d'ailleurs fait depuis `postprocess/runner.py:182` puis consommé par personne dans la phase "analysis" — les shapefiles `_matchingstreams/*.shp` ne sont même pas affichés par `plot_flow_suite`.

Par ailleurs, le constructeur lance **immédiatement** `prepare_files() → sim_to_obs() → obs_to_sim()` (matching_streams.py:120-122) — **anti-pattern « objet d'action »** : utilisez une fonction libre. Le code est d'ailleurs déjà enveloppé dans `run_matching_streams()` (ligne 306), preuve que la classe n'apporte rien.

### 4.3 NetCDF export

**Verdict : placement correct dans `analysis/`, mais ambiguïté sur la frontière avec `results/exporters/`.**

Le `CLAUDE.md` indique clairement : « Five export formats (NetCDF, CSV, VTU, GeoTIFF, Shapefile) in `results/exporters/` ». Or NetCDF ici est **dupliqué** : une implémentation dans `analysis/postprocess/netcdf/` (netcdf_writer.py, 288 lignes) et visiblement une autre route via `results/exporters/`. Il faut **choisir** :

- si l'export NetCDF est un *résultat canonique*, il va dans `results/exporters/` et `postprocess/` l'invoque via une fonction unique
- si c'est un *post-traitement optionnel*, `results/` n'en parle pas

Actuellement : les deux existent, tristement.

### 4.4 Timeseries

**Verdict : placement acceptable** mais la frontière avec `results/catalog.py` est floue. `FlowTimeseriesPostprocess` calcule des agrégats catchment et les écrit à la fois sur disque CSV **et** dans le catalog via `PostprocessRunner._write_timeseries_to_store`. Le CSV est **redondant** dès que le catalog existe.

---

## 5. Export NetCDF : conformité CF

### 5.1 Audit CF-1.8

`netcdf_writer.py` produit des fichiers `.nc` avec `xarray.Dataset.to_netcdf(...)`. Vérifié point par point contre le standard CF-1.8 (http://cfconventions.org/cf-conventions/cf-conventions.html) :

| Exigence CF | Présent ? | Commentaire |
|---|---|---|
| `Conventions = "CF-1.8"` global | **NON** | aucun attribut global n'est écrit ; `xarray` n'en ajoute pas par défaut |
| `title`, `institution`, `source`, `history`, `references` | **NON** | tous absents |
| `standard_name` sur variables de données | **NON** | seul `projection_x_coordinate`/`projection_y_coordinate` sont renseignés sur x/y (writer.py:187, 192) ; la variable principale n'a rien |
| `long_name`, `units` sur variables de données | **NON** | aucune annotation sur la variable principale (ex. `watertable_elevation`) |
| `grid_mapping` pointant vers un CRS variable | **partielle** | `dataset.rio.write_crs(...)` crée un `spatial_ref` variable mais ne pose pas `grid_mapping` sur la DataArray principale |
| Axe temps avec `units = "days since ..."` | **NON** | `times` est passé brut à xarray qui devine — acceptable mais non-portable |
| `_FillValue` correctement typé | **partiel** | writer.py:103 pose `_FillValue = -32768` en int16 — OK, mais la variable elle-même peut être NaN avant encodage, ce que `.max()`/`.min()` (writer.py:90-91) ne gère pas (voir §5.2) |
| `cell_methods` (ex. `time: mean`) | **NON** | absence totale — un hydrologue ne sait pas si `outflow_drain(t)` est moyen, instantané ou cumulé |
| `coordinates` sur data_vars non structurées | **partiel** | writer.py:250 passe `coords` mais sans annotation CF DSG (Discrete Sampling Geometries) pour le cas "cell" |

**Verdict : non-conforme CF-1.8.** Un utilisateur ouvrant le fichier avec `ncview` verra le champ mais sans titre ni unité ; Panoply l'affichera comme une grille anonyme. **C'est un problème d'interopérabilité sérieux** pour un toolkit qui produit des sorties destinées à être partagées dans la communauté hydro.

### 5.2 Bugs fonctionnels du writer

- **writer.py:90-91** : `float(dataset[variable_name].max())` / `.min()` retournent `nan` si une seule valeur est NaN ; ensuite `compute_scale_and_offset(nan, nan, 16)` produit `scale_factor = nan`, et la sortie `.nc` est corrompue. Il faut `np.nanmax` / `np.nanmin` et un garde si tout est NaN.
- **writer.py:138-153** : construction manuelle de `x_vals`/`y_vals` via `np.arange(min, min + step*width, step)` — risque d'erreur d'arrondi ; `np.linspace(min, min + step*(width-1), width)` est plus sûr.
- **writer.py:94-97** : pour un champ tout négatif, `bound_min *= 1.1` l'éloigne encore du zéro — comportement correct. Mais pour `bound_min == 0`, on a `bound_min = -0.01 * bound_max` — arbitraire, non documenté.

### 5.3 Pas de support UGRID pour les maillages non-structurés

Le mode unstructured (`export_cell_netcdf`) écrit `(time, cell)` avec un index entier, sans suivre **UGRID 1.0** (http://ugrid-conventions.github.io/ugrid-conventions/). Pour un maillage Boussinesq tétraédrique/triangulaire, UGRID est la convention de facto ; son absence rend les fichiers illisibles par Paraview/VisIt avec la détection automatique.

**Verdict export NetCDF : à améliorer sévèrement.** C'est un format « maison » qui se fait passer pour standard.

---

## 6. Timeseries : extraction et métriques

### 6.1 Extraction

`FlowTimeseriesPostprocess._append_column` (flow_timeseries.py:506) boucle sur `dataset.items()` (dict par stress period) et applique un reducer (mean/max/sum/percent/qspe). **Comportements problématiques** :

- **flow_timeseries.py:454-455** :
  ```python
  masked[masked < 0] = 0  # Keep legacy behavior
  masked[masked < -1] = np.nan
  ```
  La première ligne force toute valeur négative à zéro **avant** le calcul de la moyenne. Pour `watertable_depth`, qui peut être légèrement négatif près de sources artésiennes, c'est une *altération silencieuse des données*. Le commentaire « Keep legacy behavior » trahit la présence d'un bug porté depuis longtemps.
- **_reduce_percent** renvoie "% de cellules > 0", ce qui est bien défini, mais **_reduce_qspe** (ligne 468) fait deux choses différentes selon qu'on est structuré ou pas. Non documenté.
- Aucune gestion d'alignement temporel entre `recharge` et les sorties flow — si les grilles n'ont pas le même nombre de pas de temps, le code plante silencieusement dans `_append_column` (ligne 527 : `except Exception: pass`).

### 6.2 Métriques NSE/KGE/RMSE

**Bonne nouvelle** : les formules sont correctes et vivent dans `analysis/calibration/core/objective_function.py`.

- `nse` (ligne 81) : `1 - Σ(sim-obs)² / Σ(obs-mean_obs)²` — **formule Nash-Sutcliffe standard**, conforme Nash & Sutcliffe 1970.
- `kge` (ligne 109) : `1 - sqrt((r-1)² + (α-1)² + (β-1)²)` avec `α = σ_sim/σ_obs`, `β = μ_sim/μ_obs` — **formule Gupta et al. 2009** conforme.
- `rmse` (ligne 61) : `sqrt(mean((sim-obs)²))` — standard.
- `nse_log` (ligne 94) — implémenté.

Bémol : **ces fonctions ne sont pas utilisées par `display/`.** Aucune figure n'affiche NSE/KGE à côté d'un hydrogramme. Les métriques sont censées aller dans `SimulationCatalog.metrics` (via `simulation/results/extractors/`) mais l'intégration côté display n'est pas faite. Un `render_discharge` devrait afficher un cartouche `NSE=0.72 | KGE=0.68 | RMSE=12.3 m³/s`.

### 6.3 Pas d'interpolation/agrégation aux stations

Le code fait `ts.resample("MS").last()` / `.min()` / `.mean()` dans `posthoc_orchestration.py:685-698`. Choisir `.last()` pour outflow ou `.min()` pour well_pumping sans le documenter dans le fichier CSV de sortie est **une hypothèse cachée**. Les agrégations temporelles doivent être annotées (`cell_methods`) — cf. CF.

---

## 7. Mode headless

### 7.1 État des lieux

- `DisplayOptions.respect_env_no_display = True` + `HYDROMODPY_NO_DISPLAY=1` force `show=False` (display_config.py:254).
- `finalize_figure` (common.py:190) : si `show=False`, fait `plt.close(fig)` → pas de fuite de figures. **Correct**.
- **PROBLÈME** : `common.py:17` fait `import matplotlib.pyplot as plt` **au top-level**. Ce n'est en soi pas catastrophique (Agg est sélectionnée par matplotlib si aucun display n'est détecté), mais **ce n'est pas équivalent à `matplotlib.use("Agg")`**. Le backend sera celui résolu à l'import : Qt5Agg si DISPLAY est set sur Linux, TkAgg sinon. Un run CI headless sans `Xvfb` mais avec `$DISPLAY` défini (cas docker-in-docker) peut crasher.
- `overview_report.py:26-27` fait bien `matplotlib.use("Agg")` **à l'intérieur** de `generate_overview_report()`. C'est **trop tard** car `common.py` a déjà importé `pyplot` ; `matplotlib.use("Agg", force=True)` pourrait forcer mais le code ne passe pas `force=True`.

### 7.2 Side-effects globaux à l'import

**Le plus grave** : `visualization_watershed.py:55-96` mute l'état global matplotlib **au simple import du module** :

```python
mpl.style.use('classic')
mpl.rcParams["figure.facecolor"] = 'white'
mpl.rcParams['grid.color'] = 'darkgrey'
# ... 30 autres lignes de rcParams globaux
plt.rcParams["font.family"] = "serif"
```

Toute application tierce qui importe `hydromodpy.analysis` verra son style matplotlib *silencieusement altéré*. C'est une **violation de l'idiome « un module Python ne modifie pas l'état global sans être explicitement invité »**.

**Verdict headless** : acceptable pour l'API moderne (suites.py) mais **problématique** à cause du module patrimonial `visualization_watershed.py` et des imports top-level.

### 7.3 Comparaison à `matplotlib.use('Agg')`

Le pattern recommandé est :

```python
# au top de main(), avant tout import de plt
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
```

HydroModPy fait l'inverse : plt d'abord, `use()` après (et seulement dans le rapport overview). Il faudrait :

1. ne faire **aucun** import top-level de pyplot dans le package (les laisser dans les fonctions)
2. exposer une fonction `hmp.analysis.configure_headless()` qui force Agg
3. supprimer les `mpl.rcParams[...] = ...` globaux de `visualization_watershed.py`

---

## 8. Module `display/report/` (overview)

### 8.1 Utilité

C'est une **carte d'identité** du bassin versant : 9 panneaux PNG autonomes (DEM, géologie, hydrographie, hydrogramme, piézométrie, climatologie, intermittence, qualité d'eau, inventaire stations) + un stats card.

**Verdict : utile mais simpliste.**

### 8.2 Comparaison aux outils modernes de reporting

| Outil | HydroModPy `overview_report.py` | Jupyter-Book | Quarto | sphinx-gallery |
|---|---|---|---|---|
| Format de sortie | PNGs individuels | HTML/PDF interactif | HTML/PDF/Word | HTML + exemples exécutables |
| Templating | code Python procédural | Markdown + directives | Quarto MD + chunks | reStructuredText |
| Composition | aucune (juste des PNGs dispersés) | TOC + cross-ref | TOC + cross-ref | galerie + thumbnails |
| Reproductibilité | pas de metadata | environnement épinglé | environnement épinglé | métadonnées exec |
| Customisation | 9 toggles fixes | templates Jinja | templates Jinja | templates |

Pour une **carte d'identité de bassin**, produire des PNGs autonomes est **insuffisant**. Un utilisateur aval doit lui-même copier les fichiers dans un rapport Word/LaTeX. Une solution moderne :

- générer un `.qmd` (Quarto) ou `.ipynb` parameterisé (`papermill`) qui combine figures + texte
- OU produire un PDF unique (matplotlib PdfPages) avec tous les panneaux assemblés
- OU rendre en HTML unique avec templating Jinja + figures intégrées base64

**Verdict overview** : utilisabilité limitée, **à refactoriser** si le produit est sérieusement utilisé. Sinon, le déprécier et pointer vers des notebooks d'exemple.

### 8.3 Bloat identifié dans overview

- `overview_report.py:312-349` construit `station_points` comme `list[dict]` — mais `render_dem_map` (maps.py:137-154) refait presque la même chose via `defaultdict` par `(marker, color, group)`. Deux représentations équivalentes, aucune partagée.
- `_records_to_discharge_df` et `_records_to_piezometry_df` (overview_report.py:417, 430) sont des **copies exactes** modulo le nom.
- `_filter_discharge_records` est mort du fait que le hydrogramme prend toutes les stations (aucun filtrage de qualité).

---

## 9. Dead code et legacy

### 9.1 Fichiers majoritairement morts

| Fichier | Lignes | Appelé depuis | Verdict |
|---|---|---|---|
| `visualization_results.py` | 915 | `examples_legacy/` uniquement | **dead code dans le package**, à archiver |
| `visualization_watershed.py` | 469 | `examples_legacy/` uniquement | **dead code**, idem |
| `export_vtuvtk.py` | 1 258 | `examples_legacy/` uniquement | **dead code**, idem |
| **Total** | **2 642** | — | **~20 % du package `display/` est du code mort** |

La seule raison de garder ces fichiers est la compatibilité avec les notebooks d'exemple `examples_legacy/`. Mais le nom du dossier dit tout. Il faut :

1. soit migrer les exemples vers la nouvelle API
2. soit déplacer ces 3 fichiers sous `hydromodpy_annex/legacy_display/` pour clarifier leur statut

### 9.2 Code mort interne

- `compare.py` (`run_display_compare`) — utilisé par un entry point CLI sans test visible (cherché : aucune référence dans `tests/`).
- `transport_plots.py:300-309` — aliases `build_concentration_gif` et `plot_web_animation` explicitement annoncés comme deprecated. Dead code en attente.
- `capability_gallery.py:publish_run_to_capability_gallery` — utilité douteuse hors d'un cadre de gallery documentation versionnée. À évaluer.
- `transport_plots.py` lignes 284-287 : `if last_figure is not None: plt.close(last_figure); last_figure = fig` sert à montrer uniquement la dernière frame — logique sinueuse pour un cas pas très utile.

### 9.3 README.md obsolète

`display/README.md` (qu'on ignore pour l'audit mais qui est lu par un lecteur) **liste des fichiers qui n'existent plus** : `options.py`, `flow_plots.py`, `particles_plots.py`. Le README documente une architecture qui a été refactorée sans mise à jour. C'est un passif de documentation.

---

## 10. Bugs concrets repérés

| # | Fichier : ligne | Problème | Sévérité |
|---|---|---|---|
| 1 | `netcdf_writer.py:90-91` | `.max()/.min()` sur DataArray NaN → scale_factor=NaN → fichier corrompu | **critique** |
| 2 | `flow_timeseries.py:454` | `masked[masked < 0] = 0` altère les données avant réduction | **haut** |
| 3 | `visualization_watershed.py:55-96` | mutations `mpl.rcParams` globales à l'import | **haut** |
| 4 | `common.py:17` | `import matplotlib.pyplot` top-level | moyen |
| 5 | `compare.py:42-47` | `print(...)` + `sys.exit(1)` dans une fonction de module — devrait lever une exception | moyen |
| 6 | `flow_payloads.py:67` | `np.load(path, allow_pickle=True)` — **security smell** si le fichier vient d'ailleurs | moyen |
| 7 | `flow_timeseries.py:527` | `except Exception: pass` silencieux dans boucle de reduction | moyen |
| 8 | `maps.py:27` (code après return) | ligne morte `from hydromodpy.analysis.display.display_config import DisplayOptions` inatteignable | bas |
| 9 | `suites.py:281` | comparaison `array.shape[0] == n_steps + 1` sans broadcast pour 1D history | moyen |
| 10 | `visualization_results.py:130` | `if len(object_list) == len(color_scale):` avant `elif color_scale is None:` → TypeError si color_scale=None | moyen |
| 11 | `posthoc_orchestration.py:432,82` | `except (KeyError, Exception):` — catch chain redondant (Exception couvre KeyError) | bas |
| 12 | `transport_plots.py:61-66` | cascade de try/except 3 niveaux profonde pour charger UCN — impossible de log l'erreur finale | bas |
| 13 | `flow_synthesis.py:82-86` | `_cell_centroids` fait une **boucle Python** sur les cellules, vectorisable avec `np.mean(verts[conn], axis=1)` | perf |
| 14 | `intermittency.py:130-178` | double boucle imbriquée sur slices × cellules, **vectorisable** avec `np.sum(mask, axis=0)` | perf |
| 15 | `build_plotly_slider` (animation.py:107) | encode toutes les frames en base64 dans le HTML → pour 50 frames à 300dpi, HTML > 30 MB | perf |
| 16 | `_select_boussinesq_probe_indices` (suites.py:256) | boucle Python avec `np.argsort` à chaque itération, O(n_probes · n_cells · log n_cells) | perf |

---

## 11. Optimisations

### 11.1 Vectorisations manquées

- `_cell_centroids` (flow_synthesis.py:77) : boucle `for idx, node_ids in enumerate(conn)` → remplacer par `np.mean(verts[conn], axis=1)` (gain ~100× sur 10^5 cellules).
- `_compute_mode_rows` (intermittency.py:130) : double `for` sur les slices et les grids → tout est factorisable en `np.stack(slices).sum(axis=0)` puis un `where` global.
- `_streams_from_accumulation_array` (posthoc_orchestration.py:497) : triple boucle `for r, c in stream_set: for dr, dc in [...]:` — devrait utiliser `scipy.ndimage.label` + `shapely.ops.linemerge` en mode groupé.

### 11.2 Allocations / copies

- `FlowSpatialFigurePayload` construit avec `.copy()` systématique dans `_sanitize_cell_values` (flow_payloads.py:57) même pour les fields déjà sains. Utiliser un mask + vue plutôt qu'une copie.
- `load_field_dict_from_store` (common.py:137) charge en **boucle** pour chaque timestep au lieu de laisser le store retourner tout le cube — les stores Zarr permettent un `zarr_group[var][:]` qui récupère tout en une I/O.

### 11.3 I/O

- `plot_concentration_frames` ouvre le DEM une fois (bien), mais rouvre la shape `watershed` à chaque frame implicitement via `_plot_watertable_maps` dans les suites parallèles.
- `_copy_latest_native_mesh_figures` fait `shutil.copyfile` au lieu de créer un symlink — si la même figure est copiée 5 fois dans 5 runs, ça duplique inutilement.

---

## 12. Inventaire et verdict composant par composant

| Composant | Lignes | Rôle | Verdict | Justification |
|---|---:|---|---|---|
| `analysis/__init__.py` | 113 | lazy-loader | **conforme** | bon pattern pour coût d'import |
| `analysis/capability_gallery.py` | 135 | publie PNGs dans gallery versionnée | **acceptable** mais utilité douteuse | 135 lignes pour un `shutil.copy2` + manifest JSON — sur-ingénieré |
| `display/__init__.py` | 42 | ré-exports | **conforme** | |
| `display/adapters.py` | 124 | PointRecord → DataFrame | **conforme** | |
| `display/common.py` | 268 | helpers partagés | **acceptable** | mais `resolve_shared_figure_dir` mort ? à vérifier |
| `display/compare.py` | 110 | `hmp display compare` | **à améliorer** | `sys.exit` dans module, pas de tests |
| `display/display_config.py` | 351 | Pydantic config | **conforme** | bonne structure, mais 100+ toggles flow — à factoriser |
| `display/export_vtuvtk.py` | 1 258 | VTK legacy | **dead code** | à archiver |
| `display/flow_payloads.py` | 347 | DTO flow payload | **conforme** | |
| `display/orchestration.py` | 18 | façade | **acceptable** | pourrait disparaître au profit de `suites.py` direct |
| `display/posthoc.py` | 322 | PosthocContext | **conforme** | bonne dataclass |
| `display/posthoc_orchestration.py` | 923 | orchestration post-hoc | **problématique** | 4 blocs de reshape dupliqués + parallélisme avec suites.py |
| `display/posthoc_orchestration.py` : `_streams_from_accumulation_array` | — | dérive streams d'un raster | **mal placé** | relève de `spatial/` |
| `display/suites.py` | 904 | orchestration runtime | **à améliorer** | monolithe + duplications cross-file |
| `display/transport_plots.py` | 309 | frames animation | **acceptable** | logique propre mais dépend fortement de FloPy |
| `display/visualization_results.py` | 915 | viewer 2D/3D legacy | **dead code** | à archiver |
| `display/visualization_watershed.py` | 469 | watershed legacy | **dead code + side-effects graves** | à archiver ou au minimum supprimer les `rcParams` globaux |
| `display/figures/animation.py` | 179 | GIF/MP4/Plotly | **acceptable** | mais `build_plotly_slider` inefficient (base64) |
| `display/figures/boussinesq.py` | 556 | figures Boussinesq | **conforme** | |
| `display/figures/cross_section.py` | 88 | coupe | **acceptable** | mais trop simple (colonne N-S only) |
| `display/figures/flow_diagnostics.py` | 227 | mass balance + probes | **conforme** | |
| `display/figures/flow_synthesis.py` | 544 | triptyque + cumulative | **conforme publication** | **référence qualité** du package |
| `display/figures/maps.py` | 540 | cartes DEM/geol/hydro/pathlines | **acceptable** | mais `jet` pour pathlines |
| `display/figures/spatial.py` | 292 | raster + composite + concentration | **acceptable** | `jet` encore |
| `display/figures/tables.py` | 144 | stats card + inventory | **conforme** | |
| `display/figures/timeseries.py` | 824 | hydrogrammes, intermittence, WQ | **acceptable** | hardcodés magiques (widths, `axb.set_ylim(0,100)`) |
| `display/report/overview_config.py` | 69 | Pydantic overview | **conforme** | |
| `display/report/overview_data_loader.py` | 113 | proxy WorkflowContext | **à améliorer** | duck-typing via SimpleNamespace = fragile |
| `display/report/overview_report.py` | 499 | rendu overview | **à améliorer** | vs Jupyter-Book/Quarto, c'est du PNG-spraying |
| `display/report/summary.py` | 118 | OverviewSummary | **conforme** | |
| `postprocess/__init__.py` | 24 | ré-exports | **conforme** | |
| `postprocess/postprocess_config.py` | 179 | Pydantic postprocess | **conforme** | |
| `postprocess/runner.py` | 278 | PostprocessRunner | **acceptable** | `try/except Exception: logger.warning(...)` partout — masque des bugs |
| `postprocess/flow/intermittency.py` | 247 | calcul intermittence | **mal placé** | devrait être dans `process/flow/diagnostics/` |
| `postprocess/flow/matching_streams.py` | 329 | comparaison streams sim/obs | **mal placé** | devrait être dans `spatial/` ou `process/flow/diagnostics/` |
| `postprocess/netcdf/netcdf.py` | 14 | wrapper vide | **dead code** | retire les 14 lignes |
| `postprocess/netcdf/netcdf_writer.py` | 288 | writer CF | **problématique** | pas CF-1.8 compliant, bug nanmax |
| `postprocess/netcdf/flow_netcdf.py` | 157 | flow NetCDF | **acceptable** | |
| `postprocess/netcdf/transport_netcdf.py` | 224 | transport NetCDF | **acceptable** | |
| `postprocess/timeseries/timeseries.py` | 27 | alias legacy | **dead code** | 27 lignes pour un `class Timeseries(TransportTimeseriesPostprocess): pass` |
| `postprocess/timeseries/flow_timeseries.py` | 643 | export CSV flow | **à améliorer** | bug "< 0 → 0", reducers peu documentés |
| `postprocess/timeseries/transport_timeseries.py` | 178 | export CSV transport | **conforme** | |

---

## 13. Recommandations prioritaires

1. **Critique — corriger writer.py:90-91** : remplacer `.max()/.min()` par `np.nanmax`/`np.nanmin` pour éviter la corruption des fichiers NetCDF.
2. **Critique — CF-1.8 sur NetCDF** : ajouter `Conventions`, `title`, `source`, `history`, `standard_name`, `long_name`, `units`, `cell_methods` sur toutes les variables exportées. Sans cela le format est maison.
3. **Haut — supprimer les side-effects globaux** de `visualization_watershed.py` (rcParams + style classic). Utiliser un context manager `with plt.style.context('classic'):` localement.
4. **Haut — fusionner `suites.py` et `posthoc_orchestration.py`** en un seul orchestrateur paramétré par une `DataSource`. Économie estimée : ~500 lignes.
5. **Haut — supprimer le bloc `masked[masked < 0] = 0`** dans `flow_timeseries.py:454` et documenter la politique de gestion des valeurs négatives (soit NaN partout, soit conserver).
6. **Haut — éliminer `jet`** partout (persistency_map, pathlines, composite_seepage_wtd). Remplacer par `cividis`, `magma` ou `cmo.turbid`.
7. **Moyen — déplacer** `intermittency.py` et `matching_streams.py` hors de `analysis/postprocess/` vers `process/flow/diagnostics/` et `spatial/` respectivement.
8. **Moyen — archiver** `visualization_results.py`, `visualization_watershed.py`, `export_vtuvtk.py` sous `hydromodpy_annex/legacy_display/` (2 642 lignes hors du paquet principal).
9. **Moyen — ajouter des figures hydrogéologiques manquantes** : carte piézométrique avec iso-potentielles et vecteurs ∇h, FDC (flow duration curve), hyétogramme aligné sur hydrogramme.
10. **Moyen — intégrer NSE/KGE/RMSE dans les figures d'hydrogramme** (`render_discharge`) sous forme de cartouche.
11. **Moyen — réduire les wrappers `plot_*`** en une fonction `build_single_panel_figure(render_fn, **kwargs)` dans `common.py` (~150 lignes économisées).
12. **Moyen — cross-section oblique** : ajouter `sample_along_transect(mesh, field, p1, p2)`.
13. **Moyen — overview → Quarto/Jupyter-Book** : soit intégrer, soit déprécier.
14. **Bas — vectoriser** `_cell_centroids`, `_compute_mode_rows`, `_streams_from_accumulation_array`.
15. **Bas — supprimer les alias deprecated** (`build_concentration_gif`, `plot_web_animation`, `Netcdf`, `Timeseries`).
16. **Bas — mettre à jour le README.md** du module display (actuellement désynchronisé).

---

## 14. Tests

Je n'ai pas audité `tests/` en profondeur, mais les fichiers trouvés via grep (`tests/unit/postprocess/test_matching_streams.py`, `test_postprocess_runner.py`, `tests/unit/mesh/test_standalone_visualization.py`) suggèrent une **couverture partielle**. Points à vérifier en priorité :

- **tests sur le writer NetCDF** : aucun test ne vérifie que le fichier est lisible par `xarray.open_dataset` avec `decode_cf=True` — un test de round-trip avec conformité CF est indispensable.
- **tests visuels** : pytest-mpl ou `imagehash` permet de détecter les régressions visuelles sans comparer pixel à pixel.
- **tests mode headless** : existe-t-il un test qui importe `hydromodpy.analysis.display` avec `HYDROMODPY_NO_DISPLAY=1` et vérifie que **zéro** warning est émis ? Vu les imports top-level, j'en doute.

---

## 15. Synthèse

Le package `analysis/` a **deux visages** :

**Côté moderne (~6 000 lignes propres)** :
- `figures/*.py` : convention matplotlib render/plot propre, payloads typés, bons choix de colormaps pour flow_synthesis.
- Pydantic configs bien structurées.
- Lazy imports corrects.

**Côté legacy + duplications (~7 500 lignes)** :
- 2 642 lignes de dead code (viz_results/viz_watershed/export_vtuvtk).
- 1 827 lignes d'orchestration dupliquée (suites + posthoc_orchestration).
- 576 lignes mal placées (intermittency + matching_streams).
- NetCDF writer non-CF.
- Side-effects globaux matplotlib à l'import.

**Note globale : 5/10**. La fondation `figures/` est bonne. L'orchestration est **grosse et dupliquée**, le postprocess mélange calcul et export, et les exports NetCDF ne sont pas standards. Avec 1 à 2 sprints de nettoyage ciblé (recommandations 1-8), le package pourrait tomber à ~8 000 lignes avec la même fonctionnalité et une conformité CF-1.8 opérationnelle.
