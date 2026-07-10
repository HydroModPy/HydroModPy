# Conditionnement de surface hydrologique : mesure décisive + design agnostique du solveur (2026-07-10)

Réponse au document d'idée `prompt_conditionnement_mesh_natif.md`. Conformément à sa
section 7.4 (« ne rien figer sans preuve »), la mesure qui tranche a été faite AVANT le
design. Méthode : cartographie du code, mesure QC sur le mesh Chèze 75 m conditionné
(vérifiée par recomputation indépendante intégrale, verdict *sound*), panel de 4 designs
concurrents + scout bibliothèques jugés sous 3 angles, puis une passe de généralisation
sur TOUS les solveurs (6 lecteurs + synthèse). Ce document est la synthèse arbitrée.

**Portée.** Le conditionnement est un opérateur de SURFACE agnostique du solveur, pas un
détail MF6-Voronoi. Il s'applique à :

- **MODFLOW 6 DISV** (Voronoi / triangle, mesh gmsh runtime) : le cas problématique, seul
  câblé aujourd'hui, cible du MVP. C'est là que la mesure décisive a été faite.
- **MODFLOW 6 structuré** (SolverMesh structuré exporté en DISV) : no-op quand la grille =
  résolution du DEM et que le clip brut est déjà sans pit ; nécessaire dès qu'on rééchantillonne (coarsening).
- **MODFLOW-NWT** (DIS structuré) : même besoin que MF6 (DRN sur toutes les cellules, EVT,
  strt, CHD océan lisent le top), mais NON câblé aujourd'hui ; gate sur la décision de sunset.
- **Boussinesq** (triangle) : projection zonale OUI (anti-alias de la géographie de seepage) ;
  fill priority-flood N/A et physiquement faux (une EDP diffusive n'a pas de graphe de routage).
- **GR4J** : N/A par construction (lumped, aucune surface à conditionner).
- **futur DISU** (non prismatique) : affaire d'ADAPTER, kernel inchangé.

La mesure décisive ci-dessous est la preuve du chemin **MF6-DISV** ; elle n'est pas
transposée aux autres solveurs (Boussinesq notamment : argument dérivé du code, pas mesuré).

## 0. La mesure qui tranche (MF6-DISV, Chèze 75 m, Voronoi v7 conditionné, 9407 cellules)

Outil : `tools/diagnostics/mesh_flow_qc.py` (nouveau, ~1200 lignes, sans import
hydromodpy). Il recharge le dossier solveur, reconstruit l'adjacence par faces, route en
steepest-descent, accumule les aires, mappe le réseau vecteur sur les cellules et compare
au raster. Baseline persistée : `docs/_dev_notes/figures/qc_mesh_flow_cheze75m_v7.{json,html}`.

| Question | Résultat |
|---|---|
| Q1 chenaux cassés (« rivières à une case ») | **ZÉRO**. 12 chaînes, 304 cellules-chenal, 300/300 paires consécutives face-adjacentes. |
| Q2 inversions le long des chaînes | Pré-fill 65 ; après fill **12** (max 4.48 m, moyenne 1.18 m). Le fill en a **créé 0**, retiré 53. Les 12 survivantes = artefacts d'échantillonnage au centroïde ; 7/12 dans la gorge sous-barrage. |
| Q3 concordance accumulation mesh / réseau | 88.8 % des cellules-chenal routent vers chenal ou lac ; 46 faux thalwegs dont 38 collés au réseau (jitter d'une cellule) ; brin principal (~9.7 km²) longe le chenal et ré-entre après 6 cellules ; 23/75 cellules-chenal sous 0.5x leur accumulation raster. Bilan de masse **exact** (30.06 lacs + 1.44 bord = 31.49 km², 0 stranded, 0 pit). |
| Q4 comportement anti-chenal du fill | **CONFIRMÉ** : 35.5 % des cellules-chenal relevées de plus de 1 cm (moyenne 0.80 m, max 4.19 m) contre 1.3 % des versants. Le fill enterre le thalweg là où le flux jitte. |
| Méthode | Top pré-fill == bilinéaire(watershed_dem = DEM brut + dam-carve + masque BV) au bruit float32 près ; 51 pits pré-fill, 0 après. |

**Verdict** : à 75 m, le fill nu + protection des lacs SUFFIT à l'intégrité du drainage.
Tous les défauts résiduels sont des artefacts de **projection** (échantillon ponctuel
bilinéaire au centroïde), pas de fill ni de maillage. Le régime 5 m n'est PAS mesuré :
c'est la première action du plan.

## 1. Décisions de design (arbitrées)

### Ce qu'on construit

1. **Corriger l'échantillonneur, pas ajouter un moteur** (colonne vertébrale). Projection
   zonale par classe : min/p10 sur les pixels-chenal, moyenne surfacique sur les versants,
   garde anti-pic, clamp d'épaisseur minimale, substratum réduit avec le MÊME réducteur.
   Le fill priority-flood reste tel quel comme filet terminal (il ne crée aucune inversion).
2. **Mesurer le 5 m avant de figer quoi que ce soit** (Phase 0). Triggers chiffrés dans TOLERANCES.md.
3. **Filet réseau GATED, pas dans le MVP** : seeding des cellules-chenal + sweep lower-only cappé, seulement sur trigger.
4. **QC permanent, une seule implémentation** partagée par le kernel et l'outil.
5. **Fix isolé du bug d'ordre du 3e clamp SFR** (`sfr.py:1063` re-casse la monotonie après le freeze).
6. **Raffinement rivière EN DERNIER, Newton-gated, annulable.**

### Ce qu'on ne construit pas (et pourquoi)

- **Pas de carve lourd d'emblée** (cible = 12 inversions moyenne 1.18 m dont la cause est l'échantillonnage).
- **Pas de re-mesh runtime (options 2/3 §6)** : le défaut gardé a mesuré ZÉRO ; démoté en artefact advisory GeoJSON.
- **Pas de re-délinéation sur le mesh grossier** (origine théorique des rivières à une case).
- **Pas de monotonisation du lit de lac bathymétrique** : l'abaque est un contrat de volume EXACT.
- **Pas de pin/plafond du seuil à l'invert 86.93** : l'invert WEIR n'est jamais lu dans le top du mesh. QC-only.
- **Pas de fusion top/rtp** : doctrine deux-surfaces porteuse. Cohérence par INÉGALITÉS `botm + rbth + 0.1 <= rtp <= top`.
- **Pas de rupture de config** : `condition_top` reste intact ; le renommer ferait échouer au chargement l'exemple validé read-only.
- **Zéro dépendance externe** : landlab reconstruit sa propre Delaunay + tire GPL-3 ; le kernel interne fait 0.24 s à 1e5.

### Doctrine gravée (réponse à la section 6 : option 1, durcie)

Frontière de responsabilité : **la projection corrige des VALEURS, le raffinement corrige
la TOPOLOGIE, le QC discrimine**. Invariants d'acyclicité :

- I1 : la géométrie du mesh ne consomme que {vecteurs dérivés du raster, config}.
- I2 : les opérations d'altitude (projection, carve lac, conditionnement) ne mutent jamais géométrie ni topologie.
- I3 : les entrées du conditionnement = géométrie gelée + surfaces + chaînes vecteur + ensembles structurels, jamais une sortie des builders aval.
- I4 : le QC est en lecture seule au runtime.
- I5 : l'autorité chenal = délinéation raster fine ; jamais de re-délinéation sur mesh.
- I6 : tout driver de raffinement est raster-positionnel, jamais dérivé d'une altitude conditionnée.
- **I7 (nouveau, cross-solveur)** : le conditionnement tourne APRÈS la projection/rééchantillonnage
  vers la géométrie FINALE des cellules, jamais avant. Un fill ne garantit le drainage qu'au
  support sur lequel il est calculé ; rééchantillonner vers une grille plus grossière (Voronoi
  OU structuré coarsened) ré-introduit des pits. Corollaire : « grille = DEM donc gratuit » est
  FAUX par défaut car le top modèle est le DEM brut clippé (`domain_geographic_pipeline.py:285-293`),
  pas le DEM rempli de routage.

Nuance honnête sur le « théorème Q1 » : une polyligne continue mappée par GridIntersect sort
d'une cellule par une face (chaînes connexes par construction), MAIS `resolve_reach_line_cells`
droppe les segments sub-millimétriques : quasi-théorème avec un trou de coin, mesuré 0 à 75 m.

## 2. Architecture cible : un kernel agnostique + un adapter mince par solveur

Le kernel de conditionnement est une fonction PURE de la couche `spatial`, qui n'opère que
sur des primitives (zéro type solveur, zéro flopy). Chaque solveur fournit un ADAPTER mince
qui extrait ces primitives de sa discrétisation native et réécrit le top retourné. Vérifié
DAG-légal : `spatial/` n'a aucun import flopy ; `SolverMesh` reste dans `solver/modflow_grid/`
(couche solveur, solver -> spatial autorisé, jamais l'inverse) ; le kernel ne peut PAS vivre
dans `discretization/` (qui n'importe que core/schema/discretization).

Placement : `hydromodpy/spatial/mesh/surface_conditioning/` (ou `spatial/mesh/conditioning.py`).
Deux étapes opt-in indépendamment :

- **Stage A = projection zonale par classe** (`spatial/mesh/zonal_stats.py`, NET-NEW, pas un
  refactor : aucune agrégation pixels-par-cellule n'existe aujourd'hui) : `rasterize_cell_ids`
  + `grouped_reduce` (rasterio.features.rasterize + np.bincount/np.minimum.at, deps cœur).
  Produit un `zonal_top`.
- **Stage B = fill priority-flood epsilon** : le corps actuel de `condition_solver_mesh_top`
  (`solver/modflow6/mesh_conditioning.py:24-95`) déplacé pour opérer sur primitives.

Contrat (zéro type solveur) :

```python
@dataclass(frozen=True)
class SurfaceConditioningInput:
    top: np.ndarray                       # (n_cells,) élévation de surface par cellule
    active: np.ndarray                    # (n_cells,) bool
    adjacency: list[set[int]]             # cellule -> voisins par arête partagée
    floor: np.ndarray | None = None       # (n_cells,) botm0 + min_thickness ; top >= floor
    control_cells: dict[int, float] = {}  # cellule -> cote fixe (lit lac, thalweg SFR, invert weir) ; niveaux de base, jamais relevés
    centroids: np.ndarray | None = None   # (n_cells,2) pour pente/accumulation QC
    areas: np.ndarray | None = None       # (n_cells,) pour accumulation QC
    zonal_top: np.ndarray | None = None   # (n_cells,) surface issue du Stage A

@dataclass(frozen=True)
class SurfaceConditioningResult:
    top: np.ndarray
    raised: np.ndarray                    # (n_cells,) bool
    info: dict[str, float]                # cells_raised, max_raise_m, mean_raise_m, unreached_active

def condition_surface_top(inp, *, epsilon: float = 1e-3) -> SurfaceConditioningResult
```

Invariant dur : `control_cells >= floor` (une cote de contrôle sous le plancher min-thickness
est contradictoire) ; c'est l'ADAPTER qui le garantit. NPF `icelltype=1` / STO `iconvert=1`
(couches convertibles) exigent `top >= botm + min_thickness` après conditionnement, donc le
`floor` est requis, pas optionnel. Le kernel ne fait aucun `dataclasses.replace`, aucun
SolverMesh : l'adapter fait le write-back.

Primitives QC partagées (même package, donc l'outil `mesh_flow_qc.py` et le pipeline ne peuvent
pas diverger) : `build_surface_adjacency` (renommage de `build_planar_cell_adjacency`, déjà dans
`spatial/mesh/cell_adjacency.py`, ragged-safe, rejet en bloc de l'incidence triangulation quand
un id dépasse n_cells), `classify_depressions`, `steepest_descent_accumulation`, `channel_monotonicity`.
L'outil garde seulement un chemin de re-lecture flopy pour obtenir le mesh on-disk.

Le tout est NET-NEW comme code (le kernel nommé, les dataclasses, le floor-clamp, le zonal
n'existent pas aujourd'hui) ; seuls les ingrédients (adjacence, fill, PreparedSurfaceSampler)
sont présents et vérifiés layer-légaux.

### Config

`[modflow6.sgrid.top_sampling]` (additive, Pydantic v2, `extra="forbid"`) : `mode`
(centroid défaut byte-identique / zonal), `hillslope_stat`, `channel_stat` (figé après la
mesure 5 m), `channel_source`, `spike_guard_tol_m`, `min_pixels`, `min_thickness_m`.
`condition_top` / `condition_top_epsilon` inchangés (interrupteurs du fill terminal,
orthogonaux à l'échantillonneur). Chaque champ opt-in documente l'invalidation du cache
params_hash (footgun code-blind).

Piège de namespace à trancher : ce bloc est sous `[modflow6.sgrid]`, MF6-only. La docstring
de `condition_top` (`sgrid_config.py:210-222`) dit à tort « MODFLOW 6 runtime-mesh only » ;
le mettre sur un run NWT est un no-op silencieux (seul `build.py:588` le lit). Pour servir
NWT/Boussinesq il faudra soit élargir la sémantique, soit un flag de conditionnement
solveur-neutre (question ouverte §7).

## 3. Taxonomie des conditions aux limites vis-à-vis du top

Remplace le cadrage « lacs + structures ». Chaque package se rattache au top d'exactement
une des quatre façons. C'est ce qui dissout l'objection « pourquoi les lacs / pourquoi les
wells hors sujet » : le job du conditionnement est de rendre le top correct pour que TOUS
les consommateurs (bucket 2/3) en profitent, et d'honorer TOUTES les cotes de contrôle (bucket 1).

**Bucket 1 — cote de contrôle (contrainte / driver du top)** : impose une cote fixe/bornée
que le top conditionné doit honorer.
- LAK : `carve_lake_bed` réécrit top/botm au lit bathymétrique (`lake.py:161-312`) = le plus
  fort driver ; invert d'outlet WEIR/MANNING (`lake.py:1253`). *MF6-only.*
- SFR : streambed `rtp` = cote de thalweg (depuis le DEM routage), clampé contre le botm de
  cellule (`sfr.py:1063`). *MF6-only.* C'est exactement ce que le min/p10 zonal doit préserver.
- Nuance : les CHD côté/stream sont des heads imposés sur des cellules géométriques
  (effectivement bucket 1) que HMP ne réinjecte PAS dans le conditionnement aujourd'hui.

**Bucket 2 — consommateur d'élévation** : lit le top conditionné pour poser sa propre cote.
- DRN : cote = top par cellule (`boundary_conditions.py:409`) ; posé sur TOUTES les cellules
  actives (« enables seepage on the top layer ») ; NWT `adapter.dem` (`_well_drainage_payloads.py:85`).
  Le « free win » le plus fort : chaque amélioration du top est une amélioration DRN, et le
  compte de pits QC = compte de faux bas DRN. (NWT `sink_fill` zère seulement la conductance
  DRN aux pits, ce n'est PAS un fill.)
- EVT : surface d'extraction = top (`recharge.py:667-691`) ; NWT `top - surf_offset`.
- IC (`strt`) : `ic='top'` -> `strt = top` via un helper partagé (`initial_conditions.py:74-75`).
- RCHA : recharge sur la topmost active cell ; couplage top = masque lac obligatoire (`recharge.py:498-519`).
- CHD océan : empreinte `dem <= sea_threshold` (`boundary_conditions.py:248-250`).
- Boussinesq : fermeture de seepage `conductance * max(head - z_top, 0)` (`fluxes.py:185`) +
  obstacle VI `head <= z_top`. *Boussinesq-only, l'analogue du DRN.*

**Bucket 3 — consommateur de couche/géométrie** : lit top+botm pour le placement cellule/couche
ou la transmissivité.
- **WELS** (réponse corrigée à ta question) : un well n'est PAS un driver et n'impose AUCUNE
  cote de contrôle, mais « hors sujet » était imprécis. Placement (x,y)->cellule uniquement,
  couche donnée par config (défaut 0, pas de résolveur depth->layer) : `FlowWellLocationAbsoluteXY.layer`
  et `RelativeXY.layer` défaut 0 (`wells.py:311-314, 340-343`) ; le builder émet seulement
  `[lay, cell_id, flux]` (`solver/modflow6/builders/wells.py`), un débit spécifié, jamais un
  head. DONC un well ne peut jamais imposer de cote au top -> l'adapter well contribue un
  ensemble de control_cells VIDE. MAIS le couplage est réel et aval : le top/botm de la cellule
  du well vient du top conditionné, et comme les wells sont en couche 0 par défaut = la couche
  dont le top est conditionné, conditionner sa cellule change son épaisseur saturée donc sa
  réponse Newton (AUTO_FLOW_REDUCE) et le rabattement calculé. Verdict : driver ? Non.
  Contrainte ? Non. Consommateur géométrie/couche ? Oui, comme n'importe quelle cellule active
  de couche 0. MAW/GHB/RIV n'existent pas (aucun builder). Le seul vrai gap wells (résolveur
  depth->layer, indépendant du conditionnement) LIRAIT justement le top conditionné s'il était ajouté.
- NPF (UPW pour NWT) : `icelltype=1` = couches convertibles, transmissivité plafonnée au top (`build.py:670-682`).
- STO : `iconvert=1` = stockage Sy non confiné entre botm et top (`build.py:686-693`).
- DIS/DISV : le porteur du top conditionné lui-même. MF6 exporte toujours en DISV même pour
  un SolverMesh structuré (`build.py:646`) ; `to_dis_kwargs` est NWT-only. Boussinesq : `mesh.z_top_m`.

**Bucket 4 — transparent** : sub-surface, n'affecte pas et n'est pas affecté par le top.
- HFB : barrière verticale ; lit le top seulement comme crête par défaut quand `crest_elevation=None`
  (`flow_barrier.py:92`). Nuance honnête : « lit le top pour la géométrie de bande », mais n'impose
  aucune cote de surface -> bucket 4 correct ; si le kernel bouge le top, une HFB à crête None bouge
  avec, signaler le delta au QC. *MF6-only.*
- MVR (`build.py:937`), OC (`build.py:946`) : aucun couplage top.
- GHB / MAW / RIV : ABSENTS du codebase (seulement des enums / de la prose). S'ils étaient
  câblés un jour, GHB/RIV/MAW-screen seraient bucket 1/2 (référencent un head/une cote), pas
  bucket 4 comme WEL.

Note importante : les cotes de contrôle bucket 1 (lit LAK, rtp SFR, invert weir) sont
aujourd'hui dérivées du DEM routage + abaque dans la couche solveur APRÈS la projection, puis
clampées contre le botm, package par package. « Le top doit les honorer » est donc une cible du
nouveau kernel, pas l'état actuel : aujourd'hui elles sont ré-imposées par package plutôt que
cuites dans un top conditionné unique.

## 4. Couverture par solveur

| Solveur (grille) | Besoin | Seam | Adapter | Notes |
|---|---|---|---|---|
| **MF6 DISV** (Voronoi/triangle) | Oui (cause mesurée) | (A) `discretization_spatial.py:170-175` zonal ; (B) `build.py:588` fill | `mesh_conditioning.py` devient l'adapter mince ; control_cells = lit LAK + thalweg SFR | Seul chemin câblé. **MVP.** |
| **MF6 structuré** (DISV depuis SolverMesh structuré) | No-op si `keep_native` ET clip brut sans pit ; NÉCESSAIRE sous `resample_to_shape` (coarsening) | même flag `build.py:588` (déjà flag-only, il fire déjà) + seam zonal | adapter MF6 inchangé ; `mesh_support=None` -> adjacence rook 4-connexe via `flat_connectivity` ; control_cells vide | Dégénéré (LAK/SFR exigent runtime_mesh_support -> raise) ; non testé E2E ; corriger la docstring « MF6 runtime-mesh only ». |
| **MODFLOW-NWT** (DIS structuré) | Oui (DRN partout, EVT, strt, CHD océan lisent le top ; top = DEM brut) mais NON câblé | après `nwt_solver._build_spatial_discretization` (`:269-290`), propager à `top_elevation:280` + `adapter.dem` | net-new, PETIT : SolverMesh structuré partagé -> kernel inchangé, `mesh_support=None` | Sur plan de sunset (`nwt_sunset_plan.md`). Zonal EXACT ici (réductions block axis-aligned). Gate sur décision utilisateur. |
| **Boussinesq** (triangle, mono-couche) | Partiel : zonal OUI (anti-alias seepage) ; fill N/A et physiquement FAUX | `_mesh_builders.py:75-81` (remplacer le point-sample de `z_top_m`) | net-new triangle : top=`z_top_m`, floor=`z_bottom_m+min_thickness`, adjacence `edge_cell_a/b`, control_cells = cellules rivière ; Stage A SEULEMENT | Argument dérivé du code, PAS mesuré. `constant_thickness` : substratum auto-track ; `flat_substratum` : re-dériver. Auditer aussi le chemin bundle-export. |
| **GR4J** (lumped) | N/A par construction | aucun | aucun | Aucune surface. Ne rien inventer ici. |
| **futur DISU** (non prismatique) | Oui en principe, affaire d'adapter | adapter réduit le set 3D à la couche de surface | net-new : surface cell = cellule top-exposée de chaque colonne, adjacence latérale des top-exposées, floor = botm de cette cellule | Kernel INCHANGÉ (ne référence jamais couches/prismes). Free/additif quand DISU atterrit. |

Le kernel « un top par cellule top-exposée + adjacence des cellules top-exposées + floor
optionnel » est suffisant pour les six lignes ; seule la façon d'extraire ces primitives
diffère. C'est ça, l'agnosticisme réel.

## 5. Plan par phases (payoff-first, MVP = MF6-DISV, adapters gated)

| Phase | Contenu | Effort | Gate |
|---|---|---|---|
| **0. Mesure + QC produit** | Sortie JSON du QC (fait), baseline 75 m (fait), PREMIÈRE mesure 5 m, 3 métriques dimensionnantes, compteur 3e clamp, bande top-rtp. Triggers dans TOLERANCES.md. | 1-2 j | Aucun paramètre figé avant ces chiffres. |
| **1. Kernel spatial + projection par classe** (MF6-DISV) | `spatial/mesh/surface_conditioning/` (contrat primitive + fill déplacé, relocation = colonne vertébrale PAS bullet différé) + `zonal_stats.py` + config additive + câblage seam + primitives QC partagées + test régression SolverMesh byte-identique en centroid + tests unitaires (tri/quad/Voronoi ragged, NaN/nodata). Chenal = link raster UNION delta dam-carve. Substratum même réducteur. | 4-6 j | Recette 75 m : inversions <= 3 (vs 12), créées == 0, chenal-relevé <= 5 % (vs 35.5 %), sous-porteuses < 10/75, bilan exact. |
| **2. Campagne 5 m + recette** | Run Chèze 5 m zonal+fill : QC complet, check Newton 1-trial, non-régression KGE chronique pré-retenue (params_hash invalidé), go/no-go filet + raffinement. | 2-3 j | KGE dans la bande TOLERANCES ; verdict trigger. |
| **3. Fix ordre du 3e clamp SFR** (isolée) | `sfr.py:1063` : clamp plancher/plafond PUIS re-sweep monotone final. Jamais bundlé avec les opt-ins. | 1-2 j | Re-validation Chèze explicite. |
| **4. Filet réseau** (GATED) | Seulement si trigger : hoist `resolve_sfr_networks` + test d'équivalence + seeding chenal (terminus lac/bord) + sweep lower-only cappé (corridor-segment, `max_lowering_m`, min aux confluences). | 3-4 j | Trigger atteint + inversions créées == 0. |
| **5. Adapter NWT** (GATED sunset) | Appel du kernel après `_build_spatial_discretization`, propagation à `top_elevation` + `adapter.dem` ; flag solveur-neutre ; test de pit synthétique sur SolverMesh structuré. | 1-2 j | Décision utilisateur sur le sunset NWT. |
| **6. Adapter Boussinesq** (GATED mesure) | Stage A seulement au seam `_mesh_builders.py:75-81` ; re-dérivation substratum ; audit bundle-export. | 2-3 j | Check de sensibilité seepage par cellule sur un site Boussinesq réel. |
| **7. Coarsening MF6 structuré** (GATED besoin) | Valider/documenter le chemin structuré coarsened (aujourd'hui dégénéré) ; test de pit synthétique. | 1-2 j | Un run coarsened qui en a besoin apparaît. |
| **8. Famille raffinement rivière** (GATED, dernière) | Champs de COURBES filtre Strahler>=3, check 1-trial obligatoire. Prédiction falsifiable : seeding chenal seul -> capture Q3 88.8 % -> > 95 % sans cellule ajoutée. | 2-3 j | Prédiction Q3 échouée + Newton vert. |
| **9. Consolidation regrid.py** (optionnelle) | `lake_bed/regrid.py` délègue à `zonal_stats` ; gate égalité STRICTE des beds. | 1-2 j | Beds identiques au bit près. |

Ordre impératif : 0 -> 1 -> 2, puis 3 (indépendante). Phases 4-9 sur preuve/décision.
**GR4J : aucune phase (N/A).** MVP (0-2) : ~7-11 jours.

## 6. Risques transverses

- **Cache params_hash code-blind** : tout opt-in = changement de modèle -> NULL params_hash ou bump avant re-calibration.
- **KGE 0.769 protégé** : défaut byte-identique verrouillé par test.
- **Newton** : l'hypothèse « top propre débloque les meshes fins » reste une hypothèse ; zonal-mean versant et raffinement chacun derrière un gate 1-trial.
- **Aliases périmés** : `model.top_elevation`/`model.dem` (`build.py:462,471`) ; le placement au seam les rend justes pour la projection, audit dû si le filet gated (build seam) atterrit.
- **Rasters éphémères** : link raster et acc vivent seulement pendant le run ; conditionnement build-time OK, dégradation propre au re-run catalogue.
- **Boussinesq non mesuré** : le besoin de zonal est dérivé du code (fermeture seepage, obstacle VI), pas d'un run avant/après. Opt-out par défaut, mesure avant câblage.
- **Housekeeping env** : pysheds 0.5 (GPLv3+) orphelin dans hmp_refact ; à retirer.

## 7. Questions ouvertes (utilisateur ou mesure)

1. **NWT sous sunset** : câbler le conditionnement dans NWT (coût quasi nul via SolverMesh
   partagé) malgré le plan de sunset, ou le laisser en no-op silencieux jusqu'au retrait ?
2. **Boussinesq** : le chemin Boussinesq a-t-il vraiment besoin du zonal en pratique ?
   Argument code-dérivé, sans mesure d'artefact Boussinesq. Et min/p10 est-il le bon
   statistique pour une EDP diffusive (où la nappe intersecte la surface) vs le choix DRN de MF6 ?
3. **Namespace config solveur-neutre** : sortir `condition_top`/`top_sampling` de `[modflow6.sgrid]`
   (MF6-only) vers une section neutre ? Churn vs gain fonctionnel.
4. **MF6 structuré coarsened** : le valider E2E (dégénéré aujourd'hui : LAK/SFR raise) ou le documenter non supporté ?
5. **Seam bundle-export Boussinesq** : un projet live tourne-t-il `resolve_runtime_solver_mesh`
   vs le chemin historique `CatchmentMeshBundle` (`from_bundle`) ? Si les bundles sont pré-exportés
   d'un DEM déjà conditionné, le seam doit aussi vivre dans l'export bundle.
6. **CHD côté/stream comme contraintes** : les faire entrer comme control_cells du kernel (pour
   que le top les honore) ou rester des heads imposés indépendants ?
7. `channel_stat` min vs p10, buffer, epsilon : figés par les distributions Phase 0 à 5 m.
8. Persistance du masque chenal par cellule (ou QC JSON) dans le zarr pour les re-runs catalogue ?
9. Retrait de pysheds de l'env conda (orphelin GPL) : ok ?

## 8. Artefacts produits par cette session

- `tools/diagnostics/mesh_flow_qc.py` : outil QC générique (non commité), ruff-clean.
- `docs/_dev_notes/figures/qc_mesh_flow_cheze75m_v7.{json,html}` : baseline 75 m.
- Ce plan. Les 4 propositions complètes, le scout bibliothèques, les 3 verdicts de juges et
  la passe de généralisation cross-solveur (6 lecteurs + synthèse) sont dans le scratchpad
  de session (`design_prop_*.md`, `design_scout.md`, `design_judge_*.md`).
