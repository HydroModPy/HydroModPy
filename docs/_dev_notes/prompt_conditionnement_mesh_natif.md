# Idée à approfondir : conditionnement hydrologique mesh-natif, agnostique du maillage

> **Nature de ce document.** Ce n'est PAS un cahier des charges à exécuter tel quel.
> C'est une **proposition d'idée** issue d'une discussion de conception. Le premier
> travail attendu est de **réfléchir au meilleur design** (options, compromis, packages,
> découpage), de le **proposer et le justifier**, puis seulement de l'implémenter de la
> façon la plus propre, optimisée et **agnostique** possible. Prends le temps de remettre
> en cause l'idée elle-même si tu trouves mieux.

## 1. Le problème, dans l'ordre

Chaîne actuelle (MODFLOW 6, backend Voronoi par défaut) :

1. On part d'un DEM brut, **traité en raster** par WhiteboxTools : D8, breach + depression
   fill, flux d'accumulation, extraction des cours d'eau par seuil d'accumulation,
   ordre de Strahler, délinéation du bassin, exutoire. À cette étape le réseau
   hydrographique est correct (résolution fine).
2. On **maille** (gmsh -> dual Voronoi/PEBI, ou triangles).
3. On **reprojette l'altitude** sur le mesh : échantillonnage bilinéaire du DEM au
   centroïde de chaque cellule (`discretization_spatial.py:174`).
4. On construit le modèle (LAK, SFR, HFB, WEL, DRN, RCH...).

**Le défaut est à l'étape 3.** Sur une grille **régulière**, la grille du modèle *est*
la grille du raster : le conditionnement hydro fait sur le raster est directement celui
du modèle, pas de reprojection, pas d'écart. En passant à un mesh **irrégulier**, la
reprojection au centroïde **casse la cohérence hydrologique** : elle recrée des
dépressions fermées que le fill raster avait supprimées, remonte des cellules de thalweg,
désolidarise des cellules qui portent un même cours d'eau. Bref, l'altitude « bouge
souvent dans le mauvais sens » et on obtient des artefacts (chenaux cassés, « rivières à
une case d'intervalle », faux points bas en fond de vallée qui polluent les cotes DRN).

Le mesh irrégulier a donc besoin d'une étape que la grille régulière obtenait
gratuitement : **rendre la surface `top` du mesh hydrologiquement cohérente, après
projection, dans la topologie propre du mesh.**

## 2. Ce qui existe déjà (point de départ, pas la solution finale)

Un premier correctif **volontairement simple** a été posé (à considérer comme un socle,
peut-être à englober ou remplacer par le design mesh-natif) :

- `hydromodpy/solver/modflow6/mesh_conditioning.py` : `condition_solver_mesh_top(...)`,
  un **priority-flood epsilon-fill** (Barnes 2014) sur le **graphe de faces** du mesh.
  Il ne relève que les cellules-pit jusqu'à leur seuil de débordement ; lacs et bord de
  domaine = niveaux de base fixes ; seul le `top` bouge, `botm` intact. Validé sur Chèze
  75 m : 61 -> 0 dépressions, +0.51 m de relevé moyen, MF6 Normal termination.
- `hydromodpy/spatial/mesh/cell_adjacency.py` : `build_planar_cell_adjacency(planar_mesh,
  n_cells, mesh_support)` — **déjà agnostique de l'arité** (triangles, quads, n-gones
  Voronoi) via `planar_mesh.flat_connectivity`. Partagé avec le postprocess.
- Config : `[modflow6.sgrid] condition_top` (bool, défaut `false`) + `condition_top_epsilon`.
- Deux pièges découverts et corrigés, à ne pas réintroduire :
  1. Il faut **protéger toutes les cellules-lac** (le réservoir marnage est actif +
     volontairement bas = une immense dépression légitime ; sans protection le flood le
     comble de +90 m).
  2. **`runtime_mesh_support` indexe la triangulation gmsh (~25 k), pas le dual Voronoi
     DISV (~12 k)** : un garde-fou par-arête est insuffisant, il faut rejeter l'incidence
     en bloc si un indice dépasse `n_cells` et retomber sur `planar_mesh.flat_connectivity`.
- Outils de diagnostic interactifs (HTML autonome, pas de Streamlit) :
  `tools/diagnostics/cheze_interactive_mesh.py` (carte des dépressions du top, polygones +
  flèches d'écoulement + pits classés) et `cheze_interactive_d8.py` (D8 raster).

Le fill actuel **enlève les pits** mais reste brutal : il relève uniformément sans notion
de chenal, et ne répare pas un segment de cours d'eau déjà inversé par la reprojection.
C'est le point de départ de la réflexion, pas la fin.

## 3. L'idée à creuser

Traiter le mesh comme un « raster grossier irrégulier » et **reconditionner sa surface
après projection**, mais **contraint par le réseau fin déjà connu** (raster), pas en
redécouvrant le réseau. La distinction est centrale :

- **NE PAS re-délinéer sur le mesh grossier.** La précision d'une délinéation croît avec
  la résolution ; re-extraire les cours d'eau par seuil d'accumulation *sur* des grosses
  cellules irrégulières donnerait un réseau strictement pire (c'est même là que
  naîtraient les « rivières à une case »). Le réseau raster fin reste l'autorité.
- **Reconditionner l'altitude du mesh** pour qu'elle draine proprement vers ce réseau et
  ses exutoires : chenaux monotones, pas de cuvette, versants qui drainent dans les
  chenaux/lacs.

Signaux à utiliser (à évaluer, ne rien prendre pour acquis) :

- **Le flux d'accumulation** semble le bon driver : il définit les cellules-chenal
  (`acc > seuil`, le même seuil que la délinéation) et donne une « force » pour pondérer
  une correction. Il sert aussi de **QC** : recalculer l'accumulation sur le graphe du
  mesh reconditionné pour *détecter* un chenal cassé ou une cuvette résiduelle.
- **Strahler : probablement PAS nécessaire** au conditionnement (c'est une hiérarchie
  d'affichage/priorisation, pas une contrainte de cohérence). À écarter sauf si tu
  démontres un usage concret (ex : arbitrage de confluence).

Deux régimes de correction à considérer :

- **Cellules-chenal** : forcer un **thalweg monotone descendant** le long de la topologie
  aval du réseau raster (breach/carve vers le bas, garder le fond bas et continu), plutôt
  que de le remonter. Il existe déjà une monotonisation de profil côté délinéation
  (`sfr_network.py`) et côté SFR mesh (`sfr.py`) : à **réutiliser**, pas réinventer.
- **Cellules-versant** : simple fill résiduel (le priority-flood existant), avec
  chenaux + lacs + structures + bord comme niveaux de base, pour qu'elles drainent *dans*
  le chenal.

Le problème « rivières à une case d'intervalle » n'est pas qu'un problème de
conditionnement : c'est **résolution + mapping** (un chenal fin projeté sur des cellules
non adjacentes). Levier amont : **raffiner le mesh le long du réseau d'accumulation**
(même seuil) pour que le chenal soit résolu et connexe, puis conditionner. Réfléchis à
l'interaction génération-du-mesh <-> conditionnement.

## 4. Exigence centrale : agnostique du maillage

**Le conditionnement ne doit rien supposer du type de mesh.** Triangle, Voronoi/PEBI,
quad, et demain un vrai DISU non prismatique doivent tous passer par le **même** code.
La bonne abstraction existe déjà en partie :

- Tout doit s'exprimer sur : (a) le **graphe d'adjacence de cellules** (faces partagées,
  déjà agnostique via `build_planar_cell_adjacency` / `flat_connectivity`), (b) le `top`
  par cellule, (c) des grandeurs **zonales par cellule** (accumulation max, appartenance
  à un chenal) mappées depuis le raster sur le polygone de chaque cellule — indépendamment
  de la forme de la cellule.
- Aucune hypothèse « une cellule = un carré » ou « = un hexagone Voronoi ». Le moteur
  zonal `hydromodpy/spatial/lake_bed/regrid.py` (`cell_bed_from_surface`, ray-cast des
  pixels dans le polygone de cellule) est déjà générique et est le template pour mapper
  accumulation/réseau -> cellules, quelle que soit l'arité.
- L'étape doit aussi être **indépendante du reste du pipeline** autant que possible :
  entrée = un `SolverMesh` (top/botm/inactive + planar_mesh) + les produits raster
  hydro + les jeux de cellules structurelles (lacs, carve barrage) ; sortie = un
  `SolverMesh` reconditionné. Pas de couplage caché à SFR/DRN/backend ; garde-fou propre
  si un produit manque (ex : SFR désactivé -> repli sur le fill nu).

Réfléchis à **où** ça vit dans l'architecture en couches (voir `CLAUDE.md`) pour rester
réutilisable par n'importe quel backend/mesh sans violer le DAG : le cœur « conditionner
une surface sur un graphe de cellules contraint par un réseau » est-il un utilitaire
`spatial/mesh` (agnostique solveur) plutôt qu'un détail `solver/modflow6/` ?

## 5. Prise en compte de l'ensemble (contraintes systémiques)

- **Lacs (réflexion à part entière, pas un simple « niveau de base »)** : traiter un lac
  comme un blob plat protégé est probablement **trop grossier**. Un lac (surtout avec
  **bathymétrie fournie**) est une **ancienne vallée** : son lit a un thalweg, et
  l'écoulement doit continuer à s'y faire *normalement* (entrée amont -> fond du lac ->
  exutoire/seuil), il ne faut pas « aplatir » la vallée noyée. Points à concevoir :
  - Si bathymétrie disponible : conditionner **aussi le lit du lac** pour qu'il draine
    (thalweg monotone du fond de vallée), tout en le gardant sous le niveau d'eau. Sans
    bathymétrie : niveau de base plat reste acceptable.
  - **Pré-retenue et seuil/déversoir entre deux lacs** (cas Chèze : réservoir + pré-retenue
    reliés par un WEIR réciproque) : l'écoulement inter-lacs doit être cohérent — le seuil
    est un point de contrôle, pas une cuvette à combler ni une barrière à ignorer. Le
    conditionnement du top autour du seuil doit respecter la cote de déversement.
  - **Vérifier la géométrie** : cohérence lit/rive/seuil, cellules partagées entre deux
    lacs (rappel : MF6 interdit qu'une cellule appartienne vraiment à deux lacs), et
    continuité entrée-stream -> lac -> sortie. Ne jamais combler un lac ; mais ne pas non
    plus le figer plat s'il porte une vallée réelle.
  - Interaction avec le mover SFR->LAK (un stream s'arrête à la rive) et avec LAK
    (marnage/dynamic_area : cellules actives et basses).
- **HFB / voile (cutoff wall)** : barrière **verticale sub-surface** entre cellules ;
  l'eau de surface passe au-dessus -> **transparente** au conditionnement du `top`. En
  revanche le **dam-carve** (déversoir creusé dans le top) doit être respecté comme
  *chemin de chenal*, jamais comblé.
- **Wells** : ponctuels, sub-surface, aucun effet topographique -> hors sujet pour le top.
- **DRN** : leur cote = le `top`. Conditionner le top améliore directement les DRN.
- **Raffinement des cours d'eau par seuil d'accumulation** : input de **génération du
  mesh**, à câbler sur le même seuil que la définition des streams.

Question ouverte à trancher : la surface `top` du modèle et le lit SFR (`rtp`) sont
aujourd'hui indépendants ; ce conditionnement doit-il les rendre **cohérents** là où ils
coïncident (même `min_slope`, pas de croisement top/streambed) ?

## 6. Ordonnancement du workflow : la boucle mesh <-> altitude (à trancher)

C'est le point le plus délicat et il faut le concevoir explicitement. La tension
ressentie : « il faut bien une nouvelle grille, mais si on retravaille son altitude pour
corriger les écoulements, alors en refaisant/raffinant le mesh ce n'est plus le même. »

Piste de résolution (à valider ou réfuter) : **il n'y a de boucle que si on fait
dépendre la géométrie du mesh de l'altitude conditionnée. Ne le fais pas.**

- La **géométrie du mesh** doit être déterminée par les **produits raster** (réseau
  d'accumulation, rives de lac, zones de structures), qui sont **indépendants du mesh** et
  de l'altitude projetée. Le mesh est donc construit **une fois**.
- La **projection d'altitude** puis le **conditionnement** sont une étape **terminale,
  altitude seulement**, qui **ne touche jamais la géométrie** du mesh. Donc conditionner
  ne force pas à re-mailler : pas de boucle.

La vraie question restante : **que faire si le QC (accumulation recalculée sur le mesh)
révèle une sous-résolution** (chenal cassé, rivière à une case) que le conditionnement ne
peut pas réparer proprement, parce qu'il manque des cellules le long du chenal ? Options à
comparer, avec une recommandation motivée :

1. **Passe unique, raffinement généreux en amont** : raffiner suffisamment le long du
   réseau (seuil d'accumulation) dès la génération, conditionner une fois, accepter. Si le
   QC échoue, c'est un réglage de raffinement à corriger, pas une boucle runtime.
2. **Un seul re-mesh piloté par le QC (borné)** : conditionner, faire le QC, si chenaux
   cassés -> ajouter des zones de raffinement *à ces endroits* (dérivées du réseau raster,
   pas de l'altitude), re-mailler **une fois**, re-conditionner. Bornée à une itération,
   pas infinie, et le driver de raffinement reste raster (pas d'altitude -> pas de boucle).
3. **Itératif jusqu'à convergence** : à éviter sauf preuve de nécessité (coût, non-garantie
   de convergence).

Principe directeur à défendre ou amender : **aucun feedback runtime altitude-conditionnée
-> géométrie du mesh.** Le raffinement se pilote sur des invariants raster ; le
conditionnement est en aval et terminal. Explique noir sur blanc l'ordre des étapes que
tu retiens et pourquoi il ne boucle pas.

## 7. Ce qu'on attend concrètement de toi (dans cet ordre)

1. **Réfléchir et proposer** : évalue les options (fill nu + protection chenal ; carve
   monotone contraint par le réseau ; échantillonnage zonal « min sur pixels de chenal »
   dès la projection ; combinaison). Donne les compromis, les risques (sur-carve aux
   confluences, mauvaise classification d'une cellule grossière, croisement top/botm),
   le coût, et une **recommandation motivée** avec un chemin par phases (MVP le plus
   léger d'abord, qui capte l'essentiel du bénéfice pour un risque quasi nul).
2. **Choisir les bons outils** : est-ce que WhiteboxTools (ou `whitebox_workflows`,
   `pysheds`, `richdem`, `landlab`... à comparer honnêtement) apporte quelque chose sur un
   **graphe irrégulier**, ou est-ce que la plupart de ces libs sont raster-only et il vaut
   mieux un priority-flood / accumulation **sur le graphe de cellules** en interne ?
   Justifie le choix (perf, dépendances, maintenance, licence).
3. **Rester propre et optimisé** : Pydantic v2, couches respectées, pas de god-class,
   agnostique du mesh, testé (unitaire + un end-to-end Chèze), et **objectivé** :
   mesurer accumulation-sur-mesh avant/après et le delta sur un run validé (KGE Chèze).
4. **Ne rien figer sans preuve** : commence par la mesure qui tranche (recalcul de
   l'accumulation sur le mesh conditionné actuel : reste-t-il des chenaux cassés /
   rivières à une case ? le fill + protection chenal suffit-il, ou le carve monotone
   est-il nécessaire ?), puis conçois en conséquence.

## 8. Ancrages code (points d'entrée, à vérifier avant de t'appuyer dessus)

- Projection du top : `hydromodpy/solver/modflow_grid/discretization_spatial.py:~174`
  (`PreparedSurfaceSampler`, échantillonnage au centroïde ; DEM = model-top brut
  dam-carvé, PAS le DEM rempli).
- Seam de conditionnement actuel : `hydromodpy/solver/modflow6/build.py` (après carve
  lac + masque idomain, avant la construction du DISV).
- Fill existant : `hydromodpy/solver/modflow6/mesh_conditioning.py`.
- Adjacence agnostique : `hydromodpy/spatial/mesh/cell_adjacency.py`.
- Moteur zonal (template mapping raster->cellules) : `hydromodpy/spatial/lake_bed/regrid.py`.
- Monotonisation de réseau existante à réutiliser : `hydromodpy/spatial/geographic/core/
  sfr_network.py` et `hydromodpy/solver/modflow6/builders/sfr.py`.
- Produits hydro WBT persistés et lisibles in-process : accumulation
  (`dem_acc_cells.tif` / `_flow_products.acc`), Strahler
  (`stream_order_strahler_full_tif`), liens (`stream_link_id_full_tif`), D8
  (`watershed_direc` / `_flow_products.direc`) ; cf. `geographic_paths.py`,
  `spatial/geographic/core/river_network.py`, `flow_products.py`. Attention : le mapping
  tronçon->cellules (`resolve_sfr_networks`) tourne APRÈS le seam de conditionnement -> au
  seam il faut une passe zonale raster->cellules autonome.
- Contexte mémoire pertinent : `lakeres-mesh-top-conditioning`,
  `lakeres-mesh-refinement-redesign`, `lakeres-sfr-drn-routing-fix`,
  `lakeres-dem-hydro-conditioning`, `lakeres-lake-enforcement-pipeline`,
  `mesh-elevation-design`, `grid-abstraction-disv-disu`, `no-streamlit`.

## 9. Garde-fous du projet (rappel)

Conda `hmp_refact` ; `ruff check --fix .` puis `ruff format .` avant tout commit ;
Pydantic v2 `extra="forbid"` ; pas de code legacy / shim / alias ; DAG en couches strict ;
tolérances dans `tests/TOLERANCES.md` ; `examples/projects/` non éditable (lecture seule) ;
zéro Streamlit ; réponses à l'utilisateur en français, code/commentaires en anglais.
