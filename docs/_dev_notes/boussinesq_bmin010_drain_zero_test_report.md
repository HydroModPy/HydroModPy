# Rapport des tests Boussinesq `b_min = 0.10 m` avec drainage nul

Date: 2026-05-14

Statut: rapport autonome fonde sur les matrices stationnaires ciblees lancees
dans le depot HydroModPy. Il ne change pas le comportement par defaut du solveur.
Il documente une piste de robustesse numerique: conserver une epaisseur saturee
minimale permanente de `0.10 m` dans le modele Boussinesq, puis tester le
stationnaire et un court passage transitoire avec la meme formulation.

## Resume executif

La strategie `b_min = 0.10 m` avec drainage nul est utile, mais elle n'est pas
universellement robuste.

Elle fonctionne clairement sur plusieurs cas:

- `site_01_k_low / drain_0`;
- `site_01_k_base / drain_0`;
- `site_01_k_high / drain_0`;
- `site_02_k_low / drain_0`;
- `site_02_network`, mais uniquement avec le chemin `TSPSEUDO -> VI`.

Elle echoue encore fortement sur:

- `site_02_k_base / drain_0`;
- `site_02_k_high / drain_0`;
- `site_01_k_base / maillage uniforme rivieres / drain_0`.

Les echecs `site_02_k_base` et `site_02_k_high` ne sont pas des echecs proches
de la convergence. Le solveur tombe dans un mauvais bassin domine par
l'obstacle inferieur: environ `12880` cellules sur `13200` sont actives au fond
ou sous le fond, avec des residus de l'ordre de `9` a `35`. Ajouter seulement
des pas ou augmenter les iterations ne semble donc pas etre une solution
prometteuse pour ces cas.

Le resultat le plus operationnel est:

1. `b_min=10 cm` stabilise plusieurs cas a drainage nul.
2. `TSPSEUDO -> VI` n'est pas toujours meilleur que le VI direct; sur plusieurs
   cas compacts, le VI direct converge alors que TSPSEUDO tombe dans le mauvais
   bassin.
3. Pour `site_02_network`, TSPSEUDO est indispensable et donne un champ
   stationnaire regularise coherent.
4. Pour `site_02_k_base` et `site_02_k_high`, le drainage nul reste trop dur.
   La variante avec drainage explicite faible `0.01 m2/s` est beaucoup plus
   robuste sur `site_02_k_base`.

## Protocole

Les tests ont utilise deux chemins seulement:

| methode | description |
|---|---|
| `bmin_floor_0p10_vi` | SNESVI stationnaire direct avec `b_eff = max(h - z_bottom, 0.10 m)` |
| `bmin_floor_0p10_tspseudo_then_vi` | TSPSEUDO avec le meme plancher, puis controle VI stationnaire avec le meme plancher |

Le critere pratique de succes est:

- convergence du solveur stationnaire regularise;
- residu stationnaire faible;
- probe transitoire court avec la meme formulation regularisee;
- absence de violation significative des bornes.

Important: ces solutions ne sont pas des solutions du VI strict sans plancher.
Elles correspondent a un modele Boussinesq regularise assume, qui doit etre
documente comme tel si on le promeut.

## Resultats synthese

| cas | VI direct | TSPSEUDO -> VI | meilleur residu | probe transitoire | actif fond meilleur | lecture |
|---|---:|---:|---:|---:|---:|---|
| `site_01_k_base__bouss_tri_irregular_drain_00` | OK | echec `1.75e-4` | `1.72e-7` | oui | 10 | robuste par VI direct |
| `site_01_k_base__bouss_tri_uniform_rivers_drain_00` | echec `6.71e-4` | echec `3.14e-4` | `3.14e-4` | non | 356 | proche mais non converge |
| `site_01_k_high__bouss_tri_irregular_drain_00` | OK | echec `1.97e-3` | `1.42e-8` | oui | 83 | robuste par VI direct |
| `site_01_k_low__bouss_tri_irregular_drain_00` | OK | OK | `2.88e-9` | oui | 0 | robuste |
| `site_02_k_base__bouss_tri_irregular_drain_00` | echec `9.28` | echec `9.30` | `9.28` | non | 12883 | echec massif |
| `site_02_k_high__bouss_tri_irregular_drain_00` | echec `33.7` | echec `35.5` | `33.7` | non | 12886 | echec massif |
| `site_02_k_low__bouss_tri_irregular_drain_00` | OK | OK | `1.62e-9` | oui | 20 | robuste |
| `site_02_network__bouss_unstructured_same_mesh` | echec `9.27` | OK | `6.65e-8` | oui | 120 | robuste via TSPSEUDO |

## Resultats detailles

| cas | methode | converge | probe | residu | fond actif | toit actif | violation basse max m | violation haute max m | q01 epaisseur m | q50 epaisseur m |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `site_01_k_base / drain_0` | VI direct | oui | oui | `1.72e-7` | 10 | 67 | `0` | `0` | `0.185` | `10.9` |
| `site_01_k_base / drain_0` | TSPSEUDO -> VI | non | non | `1.75e-4` | 820 | 0 | `49.2` | `0` | `0.10` | `0.10` |
| `site_01_k_base uniform / drain_0` | VI direct | non | non | `6.71e-4` | 356 | 0 | `49.8` | `0` | `0.10` | `0.10` |
| `site_01_k_base uniform / drain_0` | TSPSEUDO -> VI | non | non | `3.14e-4` | 356 | 0 | `49.8` | `0` | `0.10` | `0.10` |
| `site_01_k_high / drain_0` | VI direct | oui | oui | `1.42e-8` | 83 | 32 | `0` | `0` | `0.10` | `7.25` |
| `site_01_k_high / drain_0` | TSPSEUDO -> VI | non | non | `1.97e-3` | 820 | 0 | `49.2` | `0` | `0.10` | `0.10` |
| `site_01_k_low / drain_0` | VI direct | oui | oui | `2.88e-9` | 0 | 109 | `0` | `0` | `5.28` | `18.2` |
| `site_01_k_low / drain_0` | TSPSEUDO -> VI | oui | oui | `3.86e-7` | 0 | 109 | `0` | `0` | `5.28` | `18.2` |
| `site_02_k_low / drain_0` | VI direct | oui | oui | `1.62e-9` | 20 | 1599 | `0` | `0` | `5.93` | `26.4` |
| `site_02_k_low / drain_0` | TSPSEUDO -> VI | oui | oui | `2.92e-8` | 20 | 1599 | `0` | `0` | `5.93` | `26.4` |
| `site_02_network` | VI direct | non | non | `9.27` | 12865 | 2 | `69.6` | `13.8` | `0.10` | `0.10` |
| `site_02_network` | TSPSEUDO -> VI | oui | oui | `6.65e-8` | 120 | 542 | `0` | `0` | `0.126` | `19.6` |
| `site_02_k_base / drain_0` | VI direct | non | non | `9.28` | 12883 | 2 | `69.6` | `13.8` | `0.10` | `0.10` |
| `site_02_k_base / drain_0` | TSPSEUDO -> VI | non | non | `9.30` | 12883 | 2 | `69.6` | `13.9` | `0.10` | `0.10` |
| `site_02_k_high / drain_0` | VI direct | non | non | `33.7` | 12886 | 2 | `69.6` | `12.6` | `0.10` | `0.10` |
| `site_02_k_high / drain_0` | TSPSEUDO -> VI | non | non | `35.5` | 12885 | 2 | `69.6` | `13.2` | `0.10` | `0.10` |

## Comparaison des champs de charge

Lorsque les deux chemins convergent sur le meme cas, les champs sont quasiment
identiques:

| cas | paire | RMSE | p95 abs | max abs |
|---|---|---:|---:|---:|
| `site_01_k_low / drain_0` | TSPSEUDO -> VI vs VI direct | `1.0e-5 m` | `4.1e-6 m` | `3.3e-4 m` |
| `site_02_k_low / drain_0` | TSPSEUDO -> VI vs VI direct | `2.6e-7 m` | `1.7e-8 m` | `2.5e-5 m` |

Lorsque l'un des deux chemins echoue, la comparaison de champs sert surtout a
identifier le bassin numerique:

- `site_01_k_base` et `site_01_k_high`: VI direct donne un champ coherent,
  TSPSEUDO tombe dans un mauvais bassin domine par le fond.
- `site_02_k_base` et `site_02_k_high`: les deux chemins donnent des champs
  proches entre eux, mais tous deux mauvais. Cela confirme un echec structurel
  du couple `site_02 + K base/high + drain_0`.
- `site_02_network`: VI direct tombe dans le mauvais bassin, TSPSEUDO sort du
  bassin et converge vers un champ stationnaire regularise coherent.

## Pourquoi `site_02_k_high / drain_0` echoue

Le cas combine plusieurs facteurs defavorables:

1. `site_02` est un grand domaine naturel avec environ `13260` cellules.
2. `K high` rend les flux internes tres raides.
3. `drain_0` supprime la sortie explicite par drainage de surface.
4. L'obstacle inferieur reste dur, meme avec `b_min=10 cm`.
5. Le solveur tombe dans un etat ou presque tout le domaine est colle au fond.

Diagnostic principal:

| methode | residu | fond actif | toit actif | raison PETSc |
|---|---:|---:|---:|---|
| VI direct | `33.7` | 12886 | 2 | `SNES_DIVERGED_LINE_SEARCH` |
| TSPSEUDO -> VI | `35.5` | 12885 | 2 | `SNES_DIVERGED_LINE_SEARCH` |

Le plancher `b_min=10 cm` evite une transmissivite nulle, mais il ne supprime
pas la difficulte d'ensemble actif. Le seuil du fond reste brutal. Le probleme
n'est donc pas seulement une degenerescence de transmissivite; c'est aussi une
difficulte de chemin de solution avec obstacle inferieur, drainage nul et K fort.

## Role du drainage faible

Les tests precedents montrent que `site_02_k_base` devient robuste des que l'on
garde un drainage explicite faible:

| cas | methode | residu | probe transitoire |
|---|---|---:|---:|
| `site_02_k_base / drain_0` | meilleur chemin `b_min=10 cm` | `9.28` | non |
| `site_02_k_base / drain_0.01` | VI direct `b_min=10 cm` | `4.75e-7` | oui |
| `site_02_k_base / drain_0.1` | VI direct `b_min=10 cm` | `1.35e-7` | oui |

Cela indique que le drainage nul est un stress test utile, mais pas
necessairement la meilleure fermeture numerique pour une production robuste. Le
couple `b_min=10 cm + drainage explicite faible` est actuellement plus solide
que `b_min=10 cm + drain_0` sur les cas `site_02` difficiles.

## Proposition de testbed elargi

Un testbed elargi est faisable, mais il faut le separer en deux niveaux.

### Niveau 1: screening stationnaire leger

Objectif: classer beaucoup de cas sans relancer toute la chaine physique.

Approche:

- reutiliser les configurations et bundles de maillage existants;
- lancer seulement `bmin_floor_0p10_vi` puis `bmin_floor_0p10_tspseudo_then_vi`;
- ecrire CSV/JSON et champs `head_field.npz`;
- produire un resume Markdown/HTML;
- classer les cas en quatre categories:
  - robuste par VI direct;
  - robuste seulement via TSPSEUDO;
  - proche mais non converge;
  - echec massif.

Ce niveau convient pour les cas deja materialises:

- matrice drainage/K/maillage;
- candidats reseau;
- quelques N1/N2 si les bundles existent.

### Niveau 2: testbed physique/transitoire complet

Objectif: tester si le modele regularise reste acceptable dans les rapports
comparatifs Boussinesq/MODFLOW 6.

Il faut d'abord ajouter une option explicite de configuration, par exemple:

```toml
[flow.numerics]
minimum_saturated_thickness_m = 0.10
```

Cette option doit etre appliquee de facon coherente:

- stationnaire;
- transitoire;
- jacobienne;
- diagnostics;
- bilans;
- rapports HTML.

Variantes recommandees:

| variante | role |
|---|---|
| `bmin010_drain00` | stress test drainage nul |
| `bmin010_drain001` | variante robuste probable pour `site_02` |
| `bmin010_drain01` | comparaison avec drainage fort deja proche de MF6/DRN |

Campagne recommandee:

1. matrice drainage/K existante: `site_01` et `site_02`, K low/base/high;
2. candidats reseau: `site_01`, `site_02`, `site_03`, `site_05`,
   `site_02_low_k`, `site_03_low_k`;
3. N1 10 km2: sites deja termines plus un ou deux sites en echec;
4. seulement ensuite quelques 100 km2.

## Interpretation finale

La strategie `b_min=10 cm` est une vraie piste de robustesse. Elle resout
plusieurs echecs stationnaires et permet un passage transitoire coherent lorsque
le meme modele regularise est conserve.

Mais le drainage nul reste trop dur pour certaines combinaisons naturelles,
notamment:

`site_02 + K base/high + drain_0`.

Le meilleur chemin pratique n'est donc pas:

`toujours drain_0 + toujours TSPSEUDO`.

Le chemin le plus defensible actuellement est:

1. declarer explicitement le modele regularise `b_min=0.10 m`;
2. essayer VI direct;
3. si VI direct echoue, essayer `TSPSEUDO -> VI`;
4. si `drain_0` echoue massivement, tester `drain_0.01`;
5. conserver les echecs comme tels dans les rapports.

## Commandes executees

Matrice drain `0` sur les cas disponibles:

```powershell
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_best_candidate_matrix.py --case site_01_k_base__bouss_tri_irregular_drain_00 --case site_01_k_base__bouss_tri_uniform_rivers_drain_00 --case site_01_k_low__bouss_tri_irregular_drain_00 --case site_01_k_high__bouss_tri_irregular_drain_00 --case site_02_k_low__bouss_tri_irregular_drain_00 --case site_02_k_base__bouss_tri_irregular_drain_00 --case site_02_k_high__bouss_tri_irregular_drain_00 --method bmin_floor_0p10_vi --method bmin_floor_0p10_tspseudo_then_vi --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_best_candidate_matrix_bmin010_drain00_all_cases --probe-dt-days 30"
```

Relance testbed pour regenerer le bundle manquant `site_01_k_low`:

```powershell
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_natural_drainage_k_mesh_matrix_chain.py --cases site_01_k_low --continue-on-error"
```

Relances complementaires:

```powershell
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_best_candidate_matrix.py --case site_01_k_low__bouss_tri_irregular_drain_00 --method bmin_floor_0p10_vi --method bmin_floor_0p10_tspseudo_then_vi --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_best_candidate_matrix_bmin010_drain00_site01_low --probe-dt-days 30"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_best_candidate_matrix.py --case site_02_k_high__bouss_tri_irregular_drain_00 --method bmin_floor_0p10_vi --method bmin_floor_0p10_tspseudo_then_vi --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_best_candidate_matrix_bmin010_drain00_site02_high --probe-dt-days 30"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_best_candidate_matrix.py --case site_02_network__bouss_unstructured_same_mesh --method bmin_floor_0p10_vi --method bmin_floor_0p10_tspseudo_then_vi --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_best_candidate_matrix_bmin010_drain00_network_reference --probe-dt-days 30"
```

Verification:

```powershell
python -m py_compile examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_robust_solver_matrix.py examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_best_candidate_matrix.py
python -m ruff check examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_robust_solver_matrix.py examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_best_candidate_matrix.py
python -m pytest -o addopts='' tests/unit/solver/test_boussinesq_stationary_robust_solver_matrix.py -q
```

## Artefacts

Rapport principal:

- `docs/_dev_notes/boussinesq_bmin010_drain_zero_test_report.md`

Synthese combinee:

- `docs/_dev_notes/diagnostics/boussinesq_stationary_best_candidate_matrix_bmin010_drain00_combined/stationary_best_candidate_matrix_combined.md`
- `docs/_dev_notes/diagnostics/boussinesq_stationary_best_candidate_matrix_bmin010_drain00_combined/stationary_best_candidate_matrix_combined.csv`

Matrices:

- `docs/_dev_notes/diagnostics/boussinesq_stationary_best_candidate_matrix_bmin010_drain00_all_cases/stationary_best_candidate_matrix.csv`
- `docs/_dev_notes/diagnostics/boussinesq_stationary_best_candidate_matrix_bmin010_drain00_site01_low/stationary_best_candidate_matrix.csv`
- `docs/_dev_notes/diagnostics/boussinesq_stationary_best_candidate_matrix_bmin010_drain00_site02_high/stationary_best_candidate_matrix.csv`
- `docs/_dev_notes/diagnostics/boussinesq_stationary_best_candidate_matrix_bmin010_drain00_network_reference/stationary_best_candidate_matrix.csv`

HTML testbed actualise par la relance `site_01_k_low`:

- `examples/projects/10_testbed_workflow/outputs/boussinesq_natural_drainage_k_mesh_matrix_testbed/web_synthesis/index.html`
