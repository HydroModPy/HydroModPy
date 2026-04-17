# Reprise Vire/Selune Linux et alignement solveurs au 2026-04-15

## Objet

Reprendre les exemples de solveurs `MODFLOW-NWT` et `MODFLOW 6` sur un bassin versant réel, en maillage régulier et irrégulier, en s'appuyant sur les réglages de convergence stabilisés sur les cas tests `hillslope`, puis documenter la proximité entre les cas synthétiques et le cas réel.

Le cas réel déjà engagé dans le dépôt est `examples/projects/vire_selune/`.

## Etat du dépôt au moment de la reprise

### Cas réel déjà engagé

Les éléments suivants existent déjà dans `examples/projects/vire_selune/` :

- sorties `Vire` et `Selune` en `MODFLOW-NWT` régulier transitoire ;
- sorties `Vire` et `Selune` en `MODFLOW 6` régulier transitoire ;
- sorties `Vire` et `Selune` en `MODFLOW 6` irrégulier transitoire ;
- sorties `Vire` et `Selune` en `MODFLOW 6` irrégulier stationnaire avec maillage conforme rivières + géologie.

Les fichiers de sortie présents montrent que ces runs ont déjà été exécutés avec succès côté Windows :

- `outputs/vire_nwt/.../_metrics.json` : succès, `9.02 s`
- `outputs/vire_mf6_regular/.../_metrics.json` : succès, `23.69 s`
- `outputs/vire_mf6_irregular/.../_metrics.json` : succès, `29.76 s`
- `outputs/vire_mf6_irregular_steady/.../_metrics.json` : succès, run présent
- `outputs/selune_nwt/.../_metrics.json` : succès, `7.47 s`
- `outputs/selune_mf6_regular/.../_metrics.json` : succès, `24.09 s`
- `outputs/selune_mf6_irregular/.../_metrics.json` : succès, `22.84 s`
- `outputs/selune_mf6_irregular_steady/.../_metrics.json` : succès, run présent

### Travail Linux déjà engagé

Le benchmark Linux `NWT` vs `Boussinesq` existe déjà dans :

- `tools/investigate_linux_nwt_boussinesq_transient.py`
- `out/linux_nwt_bouss_4m4m6m_r005_dt2_refined_20260414/summary.md`

Ce benchmark Linux a déjà servi à fixer un cas `hillslope` robuste :

- montée de recharge sur 4 mois, décrue sur 4 mois, puis 6 mois secs ;
- `dt = 2 jours` ;
- `K = 1e-5 m/s` ;
- conductance de drainage `2e-4 m2/s` ;
- maillage `80 x 6` ;
- rayon de régularisation de partition `0.005`.

Résumé Linux disponible :

- `MODFLOW-NWT` : pic de débit total `12.03 m3/j`, `30.46 s`
- `Boussinesq PETSc partition` : pic `15.70 m3/j`, `20.20 s`
- `Boussinesq PETSc complementarity` : pic `18.36 m3/j`, `8.92 s`

## Réglages de convergence repris depuis les cas hillslope / validation

### Profil `MODFLOW-NWT`

Le profil robuste déjà formalisé dans `validation_cases/shared/runtime.py` repose sur :

- `nwt_headtol = 1e-6`
- `nwt_fluxtol = 1e-4`
- `nwt_maxiterout = 500`
- `nwt_thickfact = 1e-5`
- `nwt_linmeth = 1`
- `nwt_ibotav = 1`
- `nwt_options = "SIMPLE"` pour les cas non les plus raides
- `nwt_stoptol = 1e-10`

Avant reprise, les fichiers `run_vire_nwt.toml` et `run_selune_nwt.toml` n'explicitaient pratiquement pas ces réglages.

### Profil `MODFLOW 6`

Le renforcement déjà utilisé sur les cas irréguliers stationnaires `vire_selune` est :

- `mf6_ims_complexity = "COMPLEX"`
- `mf6_outer_dvclose = 1e-4`
- `mf6_inner_dvclose = 1e-4`
- `mf6_outer_maximum = 1000`
- `mf6_inner_maximum = 1000`
- `mf6_enable_rewet = false`

Avant reprise :

- les cas réguliers `MF6` n'explicitaient pas de profil solveur ;
- les cas irréguliers transitoires restaient sur un profil plus souple :
  `SIMPLE`, `1e-3`, `800`.

## Modifications faites dans les configurations du cas réel

Les fichiers suivants ont été alignés sur des profils solveur plus robustes :

- `examples/projects/vire_selune/run_vire_nwt.toml`
- `examples/projects/vire_selune/run_selune_nwt.toml`
- `examples/projects/vire_selune/run_vire_mf6_regular.toml`
- `examples/projects/vire_selune/run_selune_mf6_regular.toml`
- `examples/projects/vire_selune/run_vire_mf6_irregular.toml`
- `examples/projects/vire_selune/run_selune_mf6_irregular.toml`

### Effet attendu

- rendre les runs régionaux plus proches des réglages qui ont servi à sécuriser les cas `hillslope` ;
- éviter de dépendre de valeurs implicites par défaut ;
- homogénéiser la robustesse numérique entre régulier et irrégulier ;
- préparer une relance Linux sans avoir à reconstituer le profil solveur à la main.

## Proximité entre cas tests et cas réel

### Points de proximité utiles

- Même famille physique : écoulement libre avec recharge et drainage topographique.
- Même enjeu numérique : convergence sur aquifère libre avec conditions top et forts contrastes de réponse.
- Même logique de robustification : réduire la sensibilité aux cellules sèches / fronts de saturation en durcissant tolérances et itérations.
- Même intérêt des maillages irréguliers : mieux suivre les structures physiques dominantes.

### Ecarts structurants

- `hillslope` est quasi minimaliste : géométrie 1D/2.5D synthétique, paramètres homogènes, une pente, une tête imposée.
- `Vire/Selune` sont des bassins réels 2D de grande taille avec recharge spatialisée, réseau hydrographique réel, emprise beaucoup plus grande, et maillages conformes.
- `hillslope` cible explicitement la comparaison `NWT` / `Boussinesq`.
- `Vire/Selune` cible aujourd'hui surtout `NWT` / `MF6`; le pendant `Boussinesq` n'est pas encore câblé pour ces deux bassins.

### Ce que montre le cas réel existant

#### Vire

- aire de bassin : `1258.25 km2`
- réseau : `680` segments, ordre de Strahler max `6`
- densité de drainage : `0.718 km/km2`
- maillage irrégulier transitoire rivières seules : `18887` noeuds, `37716` triangles
- maillage irrégulier stationnaire rivières + géologie : `15616` noeuds, `31182` triangles, `145` faces partitionnées

#### Selune

- aire de bassin : `366.94 km2`
- réseau : `211` segments, ordre de Strahler max `5`
- densité de drainage : `0.725 km/km2`
- maillage irrégulier transitoire rivières seules : `5715` noeuds, `11390` triangles
- maillage irrégulier stationnaire rivières + géologie : `4616` noeuds, `9198` triangles, `53` faces partitionnées

### Lecture d'ensemble

Le cas synthétique `hillslope` reste suffisamment proche pour transférer des choix de solveur, mais pas pour transférer directement des résultats hydrodynamiques. Il sert bien de banc d'essai de convergence ; il ne remplace pas la validation régionale.

## Statut Boussinesq sur cas réel

Je n'ai pas trouvé de run `Boussinesq` déjà engagé pour `Vire` ou `Selune`.

En revanche, le dépôt contient bien une amorce régionale réelle pour `Boussinesq` :

- `launchers/regional_lab/README.md` documente l'inspection de `mesh_bundle` pour la compatibilité Boussinesq ;
- `reporting/regional_lab_pilot_2026-04-12/.../regional_lab_site_inventory.csv` contient des sites réels marqués `boussinesq_steady_ready`.

Conclusion :

- `Boussinesq sur bassin réel` est engagé au niveau infrastructure régionale et compatibilité maillage ;
- `Boussinesq sur Vire/Selune` n'est pas encore implémenté comme exemple exécutable au même niveau que `NWT/MF6`.

## Statut Linux au moment de cette reprise

### Ce qui fonctionne

- `WSL2` est bien présent ;
- une commande Linux simple s'exécute correctement ;
- l'arborescence du dépôt est accessible depuis `/mnt/c/codes/HydroModPy-GH`.

### Blocage actuel

L'environnement Python Linux actif est `Python 3.10.12`, alors que le dépôt exige ici un environnement capable d'importer `tomllib`, donc `Python 3.11+` ou équivalent.

Le blocage actuel n'est donc pas sur les exemples `vire_selune`, mais sur l'environnement Linux local.

## Protocole de relance Linux recommandé

Quand un environnement Linux `Python 3.11+` sera prêt, lancer dans `WSL` :

```bash
cd /mnt/c/codes/HydroModPy-GH

python3.11 -m hydromodpy run examples/projects/vire_selune/run_vire_nwt.toml
python3.11 -m hydromodpy run examples/projects/vire_selune/run_selune_nwt.toml
python3.11 -m hydromodpy run examples/projects/vire_selune/run_vire_mf6_regular.toml
python3.11 -m hydromodpy run examples/projects/vire_selune/run_selune_mf6_regular.toml
python3.11 -m hydromodpy run examples/projects/vire_selune/run_vire_mf6_irregular.toml
python3.11 -m hydromodpy run examples/projects/vire_selune/run_selune_mf6_irregular.toml
python3.11 -m hydromodpy run examples/projects/vire_selune/run_vire_mf6_irregular_steady.toml
python3.11 -m hydromodpy run examples/projects/vire_selune/run_selune_mf6_irregular_steady.toml
```

## Conclusion opérationnelle

- La reprise sur bassin réel était déjà engagée dans `vire_selune`.
- Les profils solveur issus du travail de convergence `hillslope` ont maintenant été explicitement reportés sur les cas réels `NWT` et `MF6`.
- Les runs réels existants montrent déjà une faisabilité côté Windows.
- Le chaînon manquant pour terminer la demande "en Linux" est aujourd'hui l'environnement Python Linux local, pas le contenu des exemples.
- Le volet `Boussinesq` sur bassin réel n'est pas encore au niveau `Vire/Selune`, mais l'infrastructure régionale réelle est déjà amorcée pour des replays Boussinesq sur `mesh_bundle`.
