# Diagnostic Nancon : Boussinesq PETSc complementarity

Liens :
[boussinesq_solver_architecture.md](boussinesq_solver_architecture.md),
[boussinesq_petsc_vs_marcais_2017.md](boussinesq_petsc_vs_marcais_2017.md),
[boussinesq_petsc_headwater_100km2_diagnostic.md](boussinesq_petsc_headwater_100km2_diagnostic.md),
[simulation_comparison_workflow.md](simulation_comparison_workflow.md).

## Portee

Cette note documente le diagnostic realise sur le cas Nancon mensuel
MODFLOW 6 DISV versus Boussinesq PETSc avec fermeture par complementarite.

Objectifs :

- rendre explicites les modifications faites dans le runtime PETSc,
- separer la reparation numerique de l'interpretation hydrologique,
- garder une trace des echecs rencontres,
- fournir des mots-cles pour une recherche bibliographique ou PETSc externe.

Conclusion courte :

- le calcul PETSc complementarity tourne maintenant sur les 12 mois du cas
  Nancon,
- les tests PETSc cibles passent,
- les differences de cartes de suintement avec MODFLOW restent fortes,
- le resultat ne doit donc pas etre lu comme une validation scientifique de la
  fermeture actuelle.

## Cas lance

Configuration ajoutee :

```text
examples/projects/09_comparison_workflow/compare_nancon_transient_monthly_mf6_bouss_comparable_petsc_complementarity.toml
```

Sorties principales :

```text
examples/projects/09_comparison_workflow/outputs/nancon_transient_monthly_mf6_bouss_comparable_petsc_complementarity/web/index.html
examples/projects/09_comparison_workflow/outputs/nancon_transient_monthly_mf6_bouss_comparable_petsc_complementarity/comparison_report.md
examples/projects/09_comparison_workflow/outputs/nancon_transient_monthly_mf6_bouss_comparable_petsc_complementarity/comparison_manifest.json
```

Le temoin MODFLOW 6 reutilise le workspace du cas comparable existant. Le
candidat Boussinesq utilise un workspace dedie au run PETSc complementarity.

Le bloc de configuration important est :

```toml
[comparison.simulation.overlay.flow]
runtime_backend = "petsc"
```

Le workflow de comparaison ne permet pas aujourd'hui de surcharger
`surface_interaction_model` dans `comparison.simulation.overlay.flow`. Ce n'est
pas bloquant ici, car `runtime_backend = "petsc"` et
`surface_interaction_model = "auto"` resolvent deja vers la fermeture
`complementarity`.

## Formulation numerique visee

Le runtime PETSc mixte resout un systeme non lineaire par pas de temps. Les
inconnues physiques par cellule sont :

- `h`, charge hydraulique en metres,
- `q_ex`, debit surfacique d'exces de saturation en `m/s`,
- `q_dry`, debit correctif de deficit sec en `m/s`.

Le residu de bilan contient, sous forme schematique :

```text
R_h =
  stockage implicite
  + flux lateraux
  + flux de conditions aux limites
  + drainage
  + A q_ex
  - A q_dry
  - A recharge
  - puits
```

avec `A` la surface de cellule.

La contrainte de surface est ecrite comme une complementarite :

```text
0 <= q_ex  perpendicular  z_top - h >= 0
```

Interpretation :

- si `h < z_top`, la cellule n'est pas contrainte par la surface et
  `q_ex = 0`,
- si `q_ex > 0`, la charge est collee a la surface `h = z_top`.

La contrainte de fond utilise le meme principe :

```text
0 <= q_dry  perpendicular  h - z_bottom >= 0
```

Interpretation :

- si `h > z_bottom`, pas de correction seche,
- si la cellule veut passer sous le fond, `q_dry` agit comme une reaction qui
  garde `h` au fond.

Numeriquement, les deux complementarites sont transformees en residus de type
Fischer-Burmeister :

```text
phi(a, b) = sqrt(a^2 + b^2) - a - b
```

avec des variables adimensionnees :

```text
a = q / q_scale
b = gap / h_scale
```

Le solveur PETSc SNES cherche donc :

```text
F(h, q_ex, q_dry) = 0
```

## Difference avec la loi de repartition regularisee

Le mode `regularized_partition` n'a pas la meme logique.

Dans la loi de repartition regularisee, le flux de surface est calcule par une
loi locale du type :

```text
q_ex = G_r(theta) max(balance, 0)
```

Cette loi peut produire de petits flux positifs sur beaucoup de cellules, car
`G_r(theta)` peut etre petit mais non nul pres de la saturation.

Dans la formulation de complementarite :

- `q_ex` n'est pas impose par une loi locale de repartition,
- `q_ex` est une inconnue de reaction,
- le flux n'apparait que pour imposer la contrainte `h <= z_top`.

Cette distinction est centrale pour l'interpretation des cartes :

- la repartition regularisee donne une activation lisse et anticipee,
- la complementarite donne une activation de contrainte,
- les masques binaires `seepage_areas` peuvent diverger fortement selon qu'ils
  representent `h proche de z_top`, `h >= z_top`, ou `q_ex > seuil`.

## Problemes rencontres

### 1. Cle de configuration refusee par le workflow de comparaison

Une premiere configuration explicite contenait :

```toml
surface_interaction_model = "complementarity"
```

dans l'overlay `flow`.

Le workflow de comparaison refuse cette cle dans l'overlay enfant. La solution
retenue a ete de ne garder que :

```toml
runtime_backend = "petsc"
```

car le catalogage des methodes resout automatiquement PETSc vers
`complementarity`.

### 2. Regression dans les tests de complementarite

Un test single-cell de sechage construisait `NonlinearRuntimeOptions` sans
`regularization_radius`, alors que ce champ est requis par le contrat runtime.

Correction :

- ajout explicite de `regularization_radius = 0.05` dans le test.

Ce point est surtout une correction de contrat de test.

### 3. Residu PETSc incomplet pour les contraintes runtime

Le runtime mixte utilisait `residual_m3_s` pour le bloc de bilan PETSc et pour
le residu final.

Probleme :

- `residual_m3_s` est le residu physique brut,
- `solver_residual` est le residu que le solveur doit effectivement annuler,
  apres application des contraintes de solveur.

Correction :

- remplacer le bloc de bilan PETSc par `solver_residual`,
- remplacer le residu final par `solver_residual`.

Fichier :

```text
hydromodpy/solver/boussinesq/runtimes/petsc_mixed.py
```

### 4. Correction seche appliquee a un seul canal de residu

La correction `q_dry` etait soustraite seulement a `residual_m3_s`.

Probleme :

- les diagnostics et le solveur ne regardent pas toujours le meme canal,
- `flow_residual_m3_s` et `solver_residual` restaient incoherents avec
  `residual_m3_s`.

Correction :

- appliquer la correction `A q_dry` aux trois champs :
  `residual_m3_s`, `flow_residual_m3_s`, `solver_residual`.

Test ajoute :

```text
tests/unit/solver/test_petsc_mixed_double_obstacle.py
```

### 5. Divergence Nancon au troisieme mois

Symptome initial :

```text
SNES_DIVERGED_LINEAR_SOLVE
```

Le run direct avec moniteurs PETSc a montre :

```text
month 1: SNES converged
month 2: SNES converged
month 3: KSP DIVERGED_ITS at 1000 iterations
```

Un essai `preonly + lu` sans decalage a montre :

```text
DIVERGED_PC_FAILED
FACTOR_NUMERIC_ZEROPIVOT
```

Interpretation numerique :

- au troisieme mois, beaucoup de cellules sont proches de la contrainte de
  surface ou du fond,
- le systeme mixte a un comportement d'ensemble actif,
- la matrice lineaire devient mal conditionnee ou numeriquement singuliere,
- GMRES/ILU ne suffit pas,
- LU sans decalage rencontre des pivots nuls.

### 6. Conditionnement des inconnues de debit

Les inconnues `q_ex` et `q_dry` sont physiquement en `m/s`, donc souvent de
l'ordre de `1e-8` a `1e-6`.

Le residu Fischer-Burmeister travaille avec :

```text
q / q_scale
```

mais le vecteur PETSc stockait auparavant directement `q` en `m/s`. Cela
melangeait des inconnues de taille tres differente :

- `h` en metres,
- `q` en `m/s`.

Correction :

- stocker dans PETSc les inconnues adimensionnees `q_scaled = q / q_scale`,
- reconvertir vers `m/s` avant l'assemblage physique,
- multiplier les colonnes jacobiennes associees a `q_scaled` par `q_scale`.

Ce changement ne modifie pas les sorties physiques. Il modifie seulement le
conditionnement du systeme vu par SNES/KSP.

### 7. Choix du solveur lineaire PETSc

Le runtime mixte utilise maintenant :

```text
KSP preonly
PC lu
factor shift nonzero, amount 1e-10
```

Raison :

- GMRES/ILU passe les cas tests mais echoue sur Nancon au troisieme mois,
- LU sans shift rencontre des pivots nuls,
- LU avec shift non nul permet au cas Nancon complet de converger.

Point de prudence :

- ce choix est plus robuste mais plus couteux,
- il n'est pas une preuve que la formulation scientifique est bonne,
- il est acceptable comme stabilisation numerique temporaire pour le runtime
  mixte, mais il faudra surveiller la scalabilite.

## Validation effectuee

Environnement :

```text
WSL, conda env hydromodpy-wsl
Python 3.13.12
petsc4py available
```

Tests cibles :

```text
python -m pytest \
  tests/unit/solver/test_boussinesq_method_catalog.py \
  tests/unit/solver/test_petsc_mixed_double_obstacle.py \
  tests/validation/analytical/steady/test_dupuit_fixed_head_petsc_1d.py \
  tests/validation/numerical/transient/test_boussinesq_hillslope_recharge_pulse_overflow_petsc.py \
  tests/validation/numerical/transient/test_boussinesq_drying_petsc.py \
  -q --tb=short
```

Resultat :

```text
17 passed
```

Smoke PETSc plus large :

```text
python -m pytest \
  tests/unit/solver/test_boussinesq_method_catalog.py \
  tests/unit/validation/test_dupuit_fixed_head_petsc_alias.py \
  tests/validation/analytical/steady/test_dupuit_fixed_head_petsc_1d.py \
  tests/validation/numerical/transient/test_boussinesq_hillslope_recharge_pulse_overflow_petsc.py \
  tests/validation/numerical/transient/test_boussinesq_headwater_100km2_petsc_transient.py \
  tests/validation/numerical/transient/test_boussinesq_drying_petsc.py \
  -q --tb=short
```

Resultat :

```text
16 passed, 4 skipped
```

Les skips viennent de fixtures headwater 100 km2 absentes.

Run Nancon :

```text
python examples/projects/09_comparison_workflow/run_comparison_example.py \
  examples/projects/09_comparison_workflow/compare_nancon_transient_monthly_mf6_bouss_comparable_petsc_complementarity.toml
```

Resultat :

```text
completed simulations: 2 / 2
audit status: warn
```

L'audit `warn` n'est pas une erreur de solveur. Les warnings portent sur :

- budget recharge non comparable dans l'export,
- politique d'etat initial differente sur les series de charge,
- metriques de reseau actif non disponibles cote Boussinesq.

## Resultats Nancon a ne pas sur-interpreter

Les differences de cartes de suintement sont fortes.

Nombre de cellules actives dans `seepage_areas` :

```text
wet period:
  Boussinesq PETSc: 2173 / 6194, 35.1 %
  MODFLOW 6:         422 / 6194,  6.8 %

dry period:
  Boussinesq PETSc:  702 / 6194, 11.3 %
  MODFLOW 6:         791 / 6194, 12.8 %

last:
  Boussinesq PETSc: 2997 / 6194, 48.4 %
  MODFLOW 6:         926 / 6194, 14.9 %
```

Metriques comparatives principales :

```text
head_map_last:
  MAE  = 1.007 m
  RMSE = 1.552 m
  max_abs_error = 23.060 m

outlet_flux_series:
  MAE  = 1.15e-4 m3/s
  RMSE = 1.21e-4 m3/s

seepage_map_wet_period:
  MAE  = 0.318
  RMSE = 0.564

seepage_map_dry_period:
  MAE  = 0.121
  RMSE = 0.348

seepage_map_last:
  MAE  = 0.428
  RMSE = 0.654
```

Lecture recommandee :

- la correction numerique rend le solveur utilisable sur ce cas,
- elle ne rend pas les cartes de suintement equivalentes a MODFLOW,
- les differences de masque sont assez grandes pour exiger un chantier separe
  sur la semantique de `seepage_areas`.

## Hypotheses sur l'origine des differences

### Semantique du masque `seepage_areas`

Le masque binaire peut representer plusieurs choses :

- charge exactement a la surface,
- charge au-dessus d'un seuil proche de la surface,
- flux `q_ex` strictement positif,
- flux `q_ex` superieur a un seuil physique,
- drainage MODFLOW positif,
- drainage MODFLOW plus surface excess.

Ces definitions ne sont pas equivalentes.

Une cellule peut etre active au sens complementarity parce que `h` est bloque a
`z_top`, tout en produisant un flux tres faible. A l'inverse, un masque MODFLOW
peut etre pilote par la logique DRN ou par une variable derivee differente.

### Difference de fermeture surface

MODFLOW 6 DISV avec drainage et Boussinesq complementarity ne representent pas
la surface par le meme operateur.

Questions ouvertes :

- le comparatif doit-il comparer `q_ex > seuil` ou `h proche de z_top` ?
- faut-il integrer le drainage dans le meme indicateur que le suintement ?
- faut-il comparer des flux continus plutot qu'un masque binaire ?
- faut-il definir un seuil en `m/day` ou en volume par cellule ?

### Difference de discretisation verticale

Boussinesq est un modele Dupuit 2D avec epaisseur saturee reconstruite. MODFLOW
6 DISV reste une discretisation groundwater differente, meme en couche unique.

Sur des zones proches de la surface, de faibles differences de charge peuvent
changer un masque binaire sur de nombreuses cellules.

## Pistes de recherche bibliographique

Mots-cles anglais utiles :

```text
groundwater seepage face complementarity problem
unconfined aquifer obstacle problem
variational inequality groundwater free surface seepage
mixed complementarity problem seepage face
Fischer Burmeister semismooth Newton complementarity
PETSc SNESVI variable bounds complementarity
PETSc PCFactorSetShiftType zero pivot
active set method seepage face groundwater
Dupuit Boussinesq saturation excess runoff
dynamic coupling subsurface seepage flows Marcais 2017
```

Mots-cles francais utiles :

```text
probleme d'obstacle aquifere libre
inequation variationnelle nappe libre suintement
condition de complementarite face de suintement
ruissellement par exces de saturation Boussinesq
```

Familles de methodes a comparer :

- formulation complementarity avec Fischer-Burmeister,
- formulation variational inequality avec active set,
- PETSc SNESVI avec bornes explicites,
- methodes MCP type PATH ou semismooth Newton,
- regularized partition law type Marcais 2017,
- formulations seepage face dans MODFLOW ou codes elements finis.

## Prochaines actions recommandees

Priorite 1 : clarifier les variables comparees.

- Documenter exactement comment `seepage_areas` est derive pour MODFLOW et pour
  Boussinesq.
- Produire trois cartes separees :
  `h_near_surface`, `q_ex_positive`, `q_ex_above_threshold`.
- Ne plus juger la qualite avec un masque binaire unique tant que la semantique
  n'est pas stabilisee.

Priorite 2 : ajouter un diagnostic de flux.

- Comparer les cartes continues `surface_excess_rate` en `m/day`.
- Ajouter des seuils physiques, par exemple `1e-9`, `1e-8`, `1e-7 m/s`.
- Comparer des volumes agreges par bassin, pas seulement des cellules actives.

Priorite 3 : ajouter un test Nancon reduit.

- Extraire un sous-cas ou une duree courte qui reproduit l'activation forte du
  troisieme mois.
- Le verrouiller dans les tests PETSc Linux.
- Eviter de ne tester que les bandes 1D simples.

Priorite 4 : evaluer une vraie formulation active-set.

- Tester une formulation VI ou active-set plutot qu'une simple equation
  Fischer-Burmeister non bornee.
- Ne pas activer `SNESVI` sans reformuler le residu, l'essai direct avec bornes
  a casse les validations existantes.

## Niveau de confiance

Confiance dans le diagnostic de panne numerique : moyenne a bonne.

Raisons :

- les echecs PETSc ont ete reproduits,
- les raisons KSP/SNES ont ete identifiees,
- LU avec shift permet de passer Nancon,
- les tests PETSc existants restent verts.

Confiance dans la validite hydrologique des cartes de suintement : faible a
moyenne.

Raisons :

- les differences de masque restent fortes,
- la semantique de `seepage_areas` n'est pas assez explicite,
- les formulations MODFLOW drainage et Boussinesq complementarity ne sont pas
  strictement equivalentes,
- le critere binaire amplifie les differences pres de la surface.

Cette note doit donc etre lue comme un point d'appui pour poursuivre le
diagnostic, pas comme une validation finale du modele.
