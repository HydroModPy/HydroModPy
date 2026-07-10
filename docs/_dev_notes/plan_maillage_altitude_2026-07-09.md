# Maillage adaptatif + projection d'altitude + délinéation — plan de conception (2026-07-09)

Objectif utilisateur: un maillage "le plus intelligent possible" qui suive les délimitations
géologie / rivière / barrage / lac, grossier là où ça ne compte pas et fin avec un bon gradient
là où ça compte, une bonne délinéation du BV, et surtout une **logique d'altitude propre sur la
projection sur la grille** pour que le flux ne fasse pas n'importe quoi. Contrainte: garder
l'orthogonalité Voronoi (XT3D-free).

## 0. Le constat central du bake-off

Bake-off sur la Chèze 5 m (`figures/cheze_5m_voile/mesh_bakeoff.png`), même domaine, 3 maillages:

| maillage | cellules | med côté | near-lac | far | conformité feature | solve |
|---|---|---|---|---|---|---|
| Voronoi défaut | 8832 | 83 m | 38 m | 105 m | cellules chevauchent le contour | **Normal** |
| Voronoi tuné (√2) | 11115 | 62 m | 44 m | 87 m | chevauchent, densité+gradient meilleurs | Abnormal |
| Triangle | 17416 | 58 m | 28 m | 82 m | **arêtes SUR le contour (exact)** | Abnormal |

Lectures:
- Le triangle a ~2x les cellules du Voronoi (le dual halve le compte) et **conforme exactement**
  au contour du lac (arêtes = la ligne), gradient lisse. C'est ce que l'utilisateur admire.
- Le Voronoi met la feature au **centre** des cellules; le raffinage est une "bande de petites
  cellules" qui chevauchent la ligne, pas une conformité. Tuner (√2) améliore densité + gradient
  (med 83→62, far 105→87) mais **pas** la conformité.
- **Seul le Voronoi défaut (grossier) converge.** Le Voronoi fin ET le triangle finissent en
  Abnormal termination. Donc sur ce modèle, **le solveur est la contrainte limitante, pas le
  maillage**. Raffiner n'est pas gratuit: ça tape le mur Newton (marnage + DRN + LAK).

Corollaire décisif: on ne peut pas se contenter de "mailler plus fin/mieux". La cause probable de
l'instabilité au raffinage est la **projection d'altitude bruitée** (top échantillonné ponctuellement
au centroïde → pics mono-pixel → géométrie sale → Newton galère). Donc **la projection d'altitude
doit être réglée AVANT de raffiner**.

## 1. Verdict mf6Voronoi (hatarilabs)

Point-first (seeds à densité graduée, pas de gmsh). MIT. MAIS: il met AUSSI la feature au centre
(pas meilleur sur la conformité), écrit le **centroïde** comme centre DISV (pas le générateur) et
n'a **aucun validateur d'orthogonalité** → il régresse la propriété XT3D-free que HMP tient mieux
(générateur exact = centre, `voronoi.py:150`, + `mesh_orthogonality.py`). Immature (pas de release,
shapefile-only). **À écarter comme dépendance.** L'idée à emprunter (anneaux gradués) se
réimplémente en interne (~40 lignes) dans B2.

## 2. Méthodes maillage, classées

L'invariant partout: **générateur = centre de cellule reste intact**, donc l'orthogonalité CVFD
exacte (XT3D-free) est préservée par TOUTES ces méthodes. Le dual (`voronoi.py:81-151`) n'est jamais
touché.

1. **A — tuner le dual** (LOW). Diviser les tailles GMSH par un facteur ~√2 calibré (le dual donne
   des cellules √2 plus grosses que l'arête de triangle visée) seulement si `grid_dual=voronoi`,
   remplacer la rampe linéaire par un smoothstep, rendre `min_size` obligatoire sur le chemin
   Voronoi (sinon `MeshSizeMin=global_size` plancher le raffinage, `_gmsh_occ.py:191-193`). Corrige
   taille + gradient, PAS la conformité. Le bake-off confirme l'effet taille (med 83→62).
2. **C — géologie en contrainte de raffinage** (LOW-MED). Les polygones géologie sont DÉJÀ une
   partition OCC + famille de raffinage (`geology_interface`, prio 200) mais `refine_interfaces`
   défaut False (`config.py:298`) et l'interface passe au centre des cellules. Défaut True sur
   Voronoi + router les courbes `interface::*` dans la liste FACE de B1.
3. **B1 — control points en paires miroir** (MED, le vrai fix de conformité). Injecter des paires
   de seeds symétriques à ±δ/2 de part et d'autre de chaque ligne-contrainte dans la triangulation
   (`_conformal_gmsh_stages.py:104-143`, là où les lignes sont déjà re-nodées): leur bissectrice
   perpendiculaire EST la ligne → une cellule Voronoi de chaque côté → **arête sur la feature**
   (conformité triangle) AVEC l'orthogonalité Voronoi. FACE = rive lac, divide BV, interface
   géologie, tracé voile, seuil lac-lac. CELL = polyligne SFR, points déversoir. Réutilise tout
   l'aval inchangé.
4. **B2 — générateur point-first PEBI complet** (HIGH). `spatial/mesh/pebi_seeds.py`: paires miroir
   + seeds SFR sur la ligne + remplissage intérieur à gradient borné (blue-noise/anneaux + CVT),
   puis appeler `voronoi_planar_mesh` directement (nouveau `grid_dual="pebi_seeds"`, bypass GMSH).
   Gradient band-limité que ni GMSH Threshold ni le vertex-dual ne garantissent. Plus tard.
5. **D — coarsening gradué sûr** (LOW, gated). Grossir seulement le buffer passif loin des features
   sous un cap de croissance + cap d'aspect, gated sur un check 1-trial de convergence (le coarsening
   naïf casse le Newton, déjà constaté).

## 3. Pipeline de projection d'altitude (le cœur de correction, LE point clé du user)

Principe: **deux surfaces, deux usages.** Topo de routage (D8) = préserve crêtes/thalwegs fins.
Topo aquifère (top modèle) = surface représentative de cellule, pics mono-pixel noyés, structures
béton ramenées à leur fondation. HMP a déjà ce split pour les LACS (`lake_enforcement.py`); on
l'étend aux structures + on change l'échantillonneur du top.

Aujourd'hui: top = **échantillon bilinéaire ponctuel au centroïde** (`discretization_spatial.py:174`),
botm proportionnel, `constant_thickness` → base = top − ep (suit la topo), **aucun lissage / sink-fill
/ clamp d'épaisseur min** sur le top modèle. Bug barrage: centroïde sur crête béton 87 m → colonne
aquifère suspendue 30 m au-dessus du thalweg, HFB ancré sur 87 (`flow_barrier.py:92`).

Pipeline recommandé (dans `_build_extruded_solver_mesh_from_runtime_planar` puis `build.py:454-582`):

1. **Échantillonnage zonal du top par classe de cellule** (remplace le point-sample), nouveau
   `project_top_to_cells(...)` réutilisant `_zonal_mean`/`cell_bed_from_surface` (`regrid.py:24-121`,
   déjà utilisé par `carve_lake_bed`):
   - cellule versant ordinaire: **moyenne surfacique** des pixels DEM (noie les pics mono-pixel);
   - cellule SFR: **thalweg-min** (ou p10) → le lit dans le vrai point bas, rtp/DRN cohérents;
   - garde anti-pic: si `|top − médiane des voisins| > tol` (~3-5 m), remplacer par la médiane.
   - Le générateur (centre Voronoi) ne bouge pas; seule la VALEUR d'altitude change → 0 impact CVFD.
2. **Clamp d'épaisseur minimale global** (généraliser celui qui n'existe que pour les lacs,
   `carve_math.py:48-55`), réutiliser `_regrade_segment`.
3. **Structure carve du top** (le fix barrage): sous-config `structure_carve` sur le voile, abaisser
   `top[cid]` des cellules de l'axe barrage à l'altitude **fondation/vallée**, re-grader avec
   `regrade_column_active_top` (`carve_math.py:73-105`). Tourner AVANT `carve_lake_bed`. HFB prend
   alors `barrier_top` = fondation (correct).
4. **SFR/LAK/HFB cohérents**: re-sampler rtp SFR sur le `model_top` thalweg-min (pas le DEM routage);
   le clamp `max(rtp, botm+rbth+0.1)` devient un garde-fou, pas une correction porteuse. Test
   invariant deux-surfaces (unit + régression Chèze).

C'est CE pipeline qui, en plus de corriger la physique, devrait **stabiliser le Newton** et donc
débloquer les maillages plus fins (voir §0).

## 4. Délinéation / cache (Stage 0, débloque la vitesse)

Cause des "3 min par itération de mesh": deux points d'entrée dupliquent la délinéation, un seul
cache. `build_geographic_runtime_context` (`pipeline.py:409`) A un cache manifest+fingerprint;
`build_geographic_derived_features` (`domain_geographic_pipeline.py:192`, le chemin mesh) n'en a
PAS. Ordre: P1 cacher le chemin mesh (3 min → 0), P2 borner le breach least-cost (`max_dist`,
`flow.py:23` sans borne sur 16.6M cellules), P4 unifier le retry breach→fill, P5 signer le contenu
des fichiers lac/voile dans le fingerprint (footgun cache-code-blind connu), P6/P7 snap sur le
réseau extrait + `flat_increment`.

## 5. Plan étagé (payoff-first, chaque étape shippable, arbre vert)

- **Stage 0 — vitesse + correction délinéation** (~2-4 j): P1 cache chemin mesh, P2 breach borné,
  P4/P5. Débloque toutes les itérations suivantes (3 min → 0). Gate: watershed byte-égal pré/post.
- **Stage 1 — projection d'altitude** (~1-1.5 sem): §3 (top zonal/thalweg, clamp min-thickness,
  structure carve barrage, rtp re-sample, test invariant + figure QC). **LE cœur**: corrige le bug
  physique ET devrait stabiliser le Newton.
- **Stage 2 — taille maillage** (Méthode A): compensation √2 calibrée + smoothstep + min_size garde.
- **Stage 3 — conformité maillage** (B1 paires miroir + C géologie): rives/divides/interfaces/voile
  deviennent des ARÊTES de cellules (conformité triangle) tout en gardant l'orthogonalité.
- **Stage 4-5 — optionnel/gated**: D coarsening sûr, B2 PEBI point-first, base géologie-conformable.

Recommandation: **Stage 0 → Stage 1 d'abord** (vitesse + physique propre), puis Stage 2, puis
Stage 3 (B1 = le vrai fix de conformité, la chose que le triangle fait et que l'utilisateur veut,
sans perdre XT3D-free). mf6Voronoi écarté. Triangle gardé seulement comme run de comparaison.

Synthèse brute complète: `scratchpad/design_synthesis_full.md` (session).
