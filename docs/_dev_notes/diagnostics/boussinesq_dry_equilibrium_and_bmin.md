# Boussinesq dry equilibrium and minimum saturated thickness

Date: 2026-05-15

Statut: investigation locale et tests unitaires sur l'equilibre sec
Boussinesq. Cette passe ajoute des helpers et diagnostics experimentaux, et un
court-circuit stationnaire uniquement pour les cas secs evidents sans entree
positive. Elle ne change pas le comportement des cas naturels forces.

## Executive summary

L'etat `h = z_bottom` est bien interpretable comme une solution VI sur la borne
inferieure lorsque la recharge est nulle et qu'aucune entree externe ne peut
injecter de l'eau. La condition n'est pas `R(h) = 0` partout, mais:

```text
h_i = z_bottom_i
R_i(h) >= 0
```

avec la convention de signe deja utilisee par le runtime PETSc VI de
HydroModPy: sur la borne inferieure, un residu positif est admissible, un
residu negatif ne l'est pas.

Le nouveau helper `detect_dry_equilibrium(...)` reconnait cet etat dans les cas
secs simples. Le runtime stationnaire `petsc_vi_obstacle` l'utilise maintenant
avant SNESVI pour ces cas evidents, ce qui evite d'appeler PETSc quand le champ
sec est deja admissible. Il refuse explicitement le raccourci si une recharge
positive, un puits injectant, une charge imposee au-dessus du fond ou une
condition de charge de bord est presente.

La distinction importante est:

- `physical_saturated_thickness`: epaisseur hydrologique reelle,
  `clip(h - z_bottom, 0, z_top - z_bottom)`;
- `effective_saturated_thickness`: epaisseur utilisee par une regularisation
  numerique de transmissivite, `max(physical_saturated_thickness, b_min)`.

Sur fond plat, `b_min = 0.10 m` ne cree pas de flux si `h = z_bottom` est
constant. Sur fond incline, `b_min > 0` cree un flux de film le long du fond,
meme si l'epaisseur physique reste nulle. Avec les parametres synthetiques du
probe (`K = 1e-5 m/s`, longueur/distance = 1), le flux vaut environ
`K * b_min * pente_h`. Pour `b_min = 0.10 m`, cela donne `1e-7 m3/s` pour une
pente de charge de `0.1 m/m`, et `1e-6 m3/s` pour `1 m/m`.

Conclusion: `b_min = 0.10 m` est une piste de robustesse numerique assumee, mais
elle n'est pas hydrologiquement neutre dans les zones seches a fond incline. Les
diagnostics doivent donc toujours separer epaisseur physique et epaisseur
effective.

## Mathematical interpretation

Le probleme obstacle inferieur n'est pas une equation classique dans les cellules
seches. Si une cellule est sur la borne `h = z_bottom`, le solveur VI accepte un
residu oriente vers l'exterieur du domaine admissible. Dans la convention locale:

```text
borne basse active: R >= 0
borne haute active: R <= 0
cellule libre:      R = 0
```

Un domaine completement sec sans entree externe peut donc etre correct meme si
la reaction de fond n'est pas nulle. A l'inverse, un champ quasi sec n'est pas
necessairement admissible: si des cellules au fond ont `R < 0`, le residu pousse
vers une charge plus elevee et l'etat sec doit etre refuse.

`b_min` modifie la transmissivite effective, pas l'etat physique:

```text
physical_saturated_thickness = clip(h - z_bottom, 0, z_top - z_bottom)
effective_saturated_thickness = max(physical_saturated_thickness, b_min)
```

Une cellule avec `h = z_bottom` et `b_min = 0.10 m` reste physiquement seche:
`physical_saturated_thickness = 0`. Elle garde seulement une transmissivite
residuelle numerique.

## Implementation

Nouveau module:

- `hydromodpy/solver/boussinesq/runtimes/dry_equilibrium.py`

Fonctions principales:

- `physical_saturated_thickness(...)`;
- `effective_saturated_thickness(...)`;
- `saturated_thickness_diagnostics(...)`;
- `assemble_effective_steady_balance(...)`;
- `detect_dry_equilibrium(...)`.

Les diagnostics d'echec stationnaire ont ete enrichis dans:

- `hydromodpy/solver/boussinesq/runtimes/stationary_failure_diagnostics.py`.

Le runtime suivant appelle aussi le preflight sec avant SNESVI:

- `hydromodpy/solver/boussinesq/runtimes/petsc_vi_obstacle.py`.

Les champs ajoutes au resume d'echec incluent:

- `dry_equilibrium_candidate_checked`;
- `dry_equilibrium_detected`;
- `dry_equilibrium_rejected_reason`;
- `dry_equilibrium_min_R`;
- `dry_equilibrium_projected_residual_inf`;
- `dry_equilibrium_vi_violations_count`;
- `minimum_saturated_thickness_m`;
- statistiques d'epaisseur physique et effective;
- `cells_physically_dry_count`;
- `cells_at_effective_floor_count`.

Ce point est critique pour relire les echecs `site_02`: beaucoup de cellules au
fond peut etre normal si l'etat sec est admissible; c'est un mauvais bassin si
le residu VI reste fortement negatif dans certaines cellules.

## Tests added

Nouveau fichier:

- `tests/unit/solver/test_boussinesq_dry_equilibrium.py`

Tests couverts:

| test | scenario | resultat attendu |
|---|---|---|
| cellule unique | recharge nulle, `b_min=0` | equilibre sec accepte |
| cellule unique | recharge nulle, `b_min=0.10` | sec physique, epaisseur effective `0.10 m` |
| deux cellules | fond plat, `b_min=0.10` | flux nul, equilibre sec accepte |
| deux cellules | fond incline, `b_min=0` | transmissivite nulle, flux nul, equilibre accepte |
| deux cellules | fond incline, `b_min=0.10` | flux de film mesure, equilibre sec strict refuse |
| cellule unique | recharge positive faible | equilibre sec refuse |
| cellule unique | charge imposee au-dessus du fond | equilibre sec refuse |
| runtime stationnaire | recharge nulle, fond plat | retour sec sans appel PETSc, 0 iteration |

## Probe results

Script ajoute:

- `examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_dry_equilibrium_probe.py`

Sorties:

- `docs/_dev_notes/diagnostics/boussinesq_dry_equilibrium_probe/dry_equilibrium_probe.csv`;
- `docs/_dev_notes/diagnostics/boussinesq_dry_equilibrium_probe/dry_equilibrium_probe.md`.

Parametres du probe:

- `K = 1e-5 m/s`;
- cellules de surface `1 m2`;
- longueur d'arete `1 m`;
- distance centre-centre `1 m`;
- recharge nulle;
- aucune condition de charge imposee.

| scenario | b_min | dry equilibrium accepted | max flux m3/s | residual inf | interpretation |
|---|---:|---:|---:|---:|---|
| fond plat 2 cellules | 0.00 | oui | `0.0` | `0.0` | sec admissible |
| fond plat 2 cellules | 0.10 | oui | `0.0` | `0.0` | `b_min` sans gradient de charge ne cree pas de flux |
| pente faible 2 cellules | 0.00 | oui | `0.0` | `0.0` | sec admissible sans transmissivite |
| pente faible 2 cellules | 0.10 | non | `1.0e-7` | `1.0e-7` | flux de film residuel |
| pente forte 2 cellules | 0.00 | oui | `0.0` | `0.0` | sec admissible sans transmissivite |
| pente forte 2 cellules | 0.10 | non | `1.0e-6` | `1.0e-6` | flux de film residuel plus fort |
| pente faible 4 cellules | 0.10 | non | `1.0e-7` | `1.0e-7` | flux par arete, total absolu `3.0e-7` |

Les flux sont lineaires en `b_min` dans ce probe. Pour `b_min = 0.01 m`, les
flux sont dix fois plus faibles; pour `b_min = 0.50 m`, ils sont cinq fois plus
forts que pour `0.10 m`.

## Impact on natural failures

Les echecs naturels precedents ne doivent pas etre lus uniquement avec le nombre
de cellules au fond. Il faut separer deux cas:

1. Equilibre sec admissible: beaucoup de cellules sont a `z_bottom`, mais
   `R >= 0` sur ces cellules et il n'y a pas d'entree externe positive.
2. Mauvais bassin quasi sec: beaucoup de cellules sont a `z_bottom`, mais des
   residus VI restent negatifs ou enormes.

Les echecs `site_02_k_base / drain_0` et `site_02_k_high / drain_0` appartiennent
au deuxieme groupe dans les tests precedents: environ `12880` cellules sont au
fond, mais le residu reste de l'ordre de `9` a `35`. Ce n'est pas un aquifere
sec admissible; c'est un etat quasi sec non convergent.

`b_min = 0.10 m` aide certains cas car il evite une transmissivite exactement
nulle. Mais sur fond incline, il introduit aussi une conductance residuelle. Si
la robustesse prime sur l'exactitude, cela peut etre acceptable, mais seulement
si le modele regularise est declare explicitement et si les flux de film restent
petits devant les flux hydrologiques d'interet.

## Recommendation

1. Garder `detect_dry_equilibrium(...)` comme preflight experimental pour les
   cas stationnaires sans entree positive.
2. Ne pas masquer les echecs SNESVI: si l'equilibre sec est refuse, le solveur
   doit continuer normalement et conserver les diagnostics d'echec.
3. Si `minimum_saturated_thickness_m` est promu en option de production, le
   documenter comme epaisseur effective numerique, pas comme stockage d'eau
   physique.
4. Ajouter systematiquement aux rapports les statistiques d'epaisseur physique
   et effective.
5. Pour les cas naturels avec fond incline, comparer les flux de film induits
   par `b_min` aux flux de recharge/drainage avant de conclure que `0.10 m` est
   marginal.

## Commands executed

```powershell
python -m pytest -o addopts='' tests/unit/solver/test_boussinesq_dry_equilibrium.py -q
python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_dry_equilibrium_probe.py --output-dir docs/_dev_notes/diagnostics/boussinesq_dry_equilibrium_probe
python -m pytest -o addopts='' tests/unit/solver/test_boussinesq_stationary_failure_diagnostics.py -q
python -m pytest -o addopts='' tests/unit/solver/test_petsc_vi_obstacle.py -q
python -m pytest -o addopts='' tests/unit/solver/test_petsc_ts_vi_obstacle.py -q
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python -m pytest -o addopts='' tests/unit/solver/test_petsc_vi_obstacle.py -q"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python -m pytest -o addopts='' tests/unit/solver/test_petsc_ts_vi_obstacle.py -q"
python -m py_compile hydromodpy/solver/boussinesq/runtimes/dry_equilibrium.py hydromodpy/solver/boussinesq/runtimes/stationary_failure_diagnostics.py tests/unit/solver/test_boussinesq_dry_equilibrium.py examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_dry_equilibrium_probe.py
python -m ruff format hydromodpy/solver/boussinesq/runtimes/dry_equilibrium.py hydromodpy/solver/boussinesq/runtimes/stationary_failure_diagnostics.py tests/unit/solver/test_boussinesq_dry_equilibrium.py examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_dry_equilibrium_probe.py
python -m ruff check hydromodpy/solver/boussinesq/runtimes/dry_equilibrium.py hydromodpy/solver/boussinesq/runtimes/stationary_failure_diagnostics.py tests/unit/solver/test_boussinesq_dry_equilibrium.py examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_dry_equilibrium_probe.py
python -m ruff format --check hydromodpy/solver/boussinesq/runtimes/dry_equilibrium.py hydromodpy/solver/boussinesq/runtimes/stationary_failure_diagnostics.py tests/unit/solver/test_boussinesq_dry_equilibrium.py examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_dry_equilibrium_probe.py
git diff --check
```

## Files produced

- `hydromodpy/solver/boussinesq/runtimes/dry_equilibrium.py`;
- `hydromodpy/solver/boussinesq/runtimes/petsc_vi_obstacle.py`;
- `hydromodpy/solver/boussinesq/runtimes/stationary_failure_diagnostics.py`;
- `tests/unit/solver/test_boussinesq_dry_equilibrium.py`;
- `examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_dry_equilibrium_probe.py`;
- `docs/_dev_notes/diagnostics/boussinesq_dry_equilibrium_probe/dry_equilibrium_probe.csv`;
- `docs/_dev_notes/diagnostics/boussinesq_dry_equilibrium_probe/dry_equilibrium_probe.md`;
- `docs/_dev_notes/boussinesq_dry_equilibrium_and_bmin.md`.

## Remaining open questions

- Sur les maillages naturels, les flux de film `b_min=0.10 m` sont-ils petits
  devant les flux de recharge et de drainage?
- Faut-il utiliser une tolerance VI separee pour accepter des flux de film tres
  faibles dans les zones physiquement seches?
- Le plancher doit-il porter uniquement la transmissivite laterale, ou aussi
  certains termes de jacobienne/stockage?
- Pour `site_02_k_base/high`, l'echec avec drainage nul vient-il surtout du
  chemin numerique, du modele sans sortie explicite, ou d'une incompatibilite de
  parametrage?
