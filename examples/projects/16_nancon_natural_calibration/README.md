# Calibration Nancon naturelle: flux et reseau hydrographique

Ce dossier documente le passage du prototype B0 synthetique vers une cible
Nancon naturelle: comparer un reseau hydrographique observe avec le drainage
permanent simule, et comparer une chronique de debit observe avec un flux
transitoire simule.

Le livrable actuel est volontairement limite:

```text
observations naturelles -> package d'observation -> score naturel -> rapport HTML compatible B0
```

Il ne lance pas encore une calibration Nancon complete avec generation de
candidats, simulations permanent/transitoire et optimiseur.

## Ce qui est developpe

### Module de scoring naturel

Le module `hydromodpy.calibration.natural_observations` ajoute les briques
suivantes:

- `write_natural_observation_package(...)` ecrit un package d'observation
  naturel compatible avec les rapports B0 existants.
- `natural_network_cost(...)` compare le support de drainage permanent simule
  a une hydrographie observee projetee sur les cellules du maillage.
- `discharge_log_nse_cost(...)` calcule le cout de debit `1 - NSElog`.
- `score_natural_network_transient_candidate(...)` combine le cout reseau et le
  cout debit dans un score scalaire.

Le "package naturel" est le paquet d'observations figees qui sert de frontiere
entre les donnees observees, le scorer et le rapport. Il contient notamment:

```text
observed_network_active_mask.npz
observed_network_distance_by_cell.npz
steady_network_active_mask.npz
steady_network_drain_by_cell.npz
cell_geometry.npz
observed_q_total_release.csv
transient_q_total_release.csv
metadata.json
normalization.json
```

Les aliases `steady_network_drain_by_cell.npz` et
`transient_q_total_release.csv` sont conserves pour reutiliser le rapport HTML
B0. Dans ce cas naturel, `steady_network_drain_by_cell.npz` est un pseudo-champ
de reference issu du masque hydrographique observe; il ne doit pas etre
interprete comme un flux observe par cellule.

Cette ecriture ne duplique pas la logique B0. Elle fait seulement l'adaptation
de contrat:

- les observations naturelles sont stockees une fois dans un format explicite;
- les noms de fichiers attendus par le rapport B0 sont fournis comme aliases;
- le renderer HTML, les figures de comparaison, le manifeste et la lecture des
  tables de score sont reutilises sans fork naturel;
- le score naturel reste dans `natural_observations.py`, donc la difference
  scientifique est isolee au niveau metrique, pas dupliquee dans le reporting.

L'ecriture disque est donc optionnelle pour le calcul pur: les fonctions
`natural_network_cost(...)` et `discharge_log_nse_cost(...)` peuvent etre
appelees directement avec des arrays en memoire. Elle est en revanche le chemin
necessaire pour le workflow actuel `score_natural_network_transient_candidate`
et pour le rapport HTML, parce que ces deux briques relisent un package
persistant qui fige les observations, les normalisations et les chemins
d'artefacts. Pour une future boucle d'optimisation, on pourra scorer en memoire
pendant les iterations, puis ecrire le package et les tables seulement pour
l'audit/reproductibilite.

### Score reseau

Le score reseau naturel ne compare pas un faux flux observe a un flux simule.
Il compare:

- les cellules ou le drainage permanent candidat est actif;
- le masque d'hydrographie observee projetee sur le maillage;
- la distance de chaque cellule au reseau observe.

La forme actuelle est:

```text
C_reseau_naturel = C_dist
C_dist = abs(D_sim_to_obs / D_obs_to_obs - 1)
```

Si le reseau observe tombe exactement sur les cellules observees,
`D_obs_to_obs` peut etre nul. Le code gere ce cas avec une penalite basee sur
`d_tol` lorsque le ratio n'est pas defini.

La longueur equivalente `L_obs` / `L_sim` peut rester affichee comme diagnostic
descriptif, mais elle ne participe plus au cout. Le choix est volontaire:
ajouter une penalisation d'extension du reseau melangeait ce diagnostic avec la
question principale de localisation vis-a-vis de l'hydrographie observee, et
risquait de compter deux fois une meme erreur de support.

### Score debit

Le debit est score avec:

```text
C_debit_obs = 1 - NSElog(Q_sim, Q_obs)
```

Ce choix rend les erreurs relatives sur basses et moyennes eaux plus visibles
qu'un RMSE lineaire domine par les pics.

### Composition de l'objectif

Le code courant garde encore des poids de package par defaut pour que le smoke
test soit executable:

```text
J = 0.3 * C_reseau_naturel + 0.7 * C_debit_obs
```

Ces coefficients ne doivent pas devenir une regle fixe pour le Nancon naturel.
Le bon choix d'implementation est de garder les composantes explicites
(`C_reseau_naturel`, `C_debit_obs`, diagnostics de distance, `NSElog`) et de
rendre la scalarisation configurable/adaptative. La suite devrait permettre au
minimum:

- une composition declaree en configuration plutot que codee dans le package;
- une normalisation robuste estimee sur un plan d'experience initial;
- une lecture Pareto reseau/debit avant de figer une somme ponderee;
- eventuellement un mode contrainte, par exemple minimiser le debit avec une
  erreur reseau maximale acceptable, ou l'inverse.

Dans l'etat actuel, `J` est donc seulement un score de classement pour le smoke
test et pour les premiers diagnostics, pas une fonction objectif definitive.

### Smoke test synthetique

Le script `run_synthetic_natural_smoke.py` cree un petit maillage ligne,
ecrit un package d'observation naturel, score quatre candidats et genere un
rapport HTML via le renderer B0 existant.

Candidats generes:

- `truth_identity`: reseau et debit identiques a l'observation;
- `shifted_network`: debit correct, reseau decale;
- `high_discharge`: reseau correct, debit trop eleve;
- `combined_error`: erreur reseau et erreur debit.

Sorties principales:

```text
outputs/synthetic_smoke/natural_observation_package/
outputs/synthetic_smoke/candidates/
outputs/synthetic_smoke/synthetic_natural_smoke_candidate_scores.csv
outputs/synthetic_smoke/synthetic_natural_smoke_candidate_scores.json
outputs/synthetic_smoke/web/index.html
outputs/synthetic_smoke/b0_reference_manifest.json
```

Le rapport HTML sait maintenant lire un package naturel, utiliser le
`mesh_bundle` du package quand aucun run de reference n'est disponible, et
ecrire un manifeste avec le contrat
`natural_network_steady_discharge_transient.v1`.

### Builder de package Nancon reel

Le script `build_observation_package.py` prepare un package naturel a partir
de donnees deja projetees sur le maillage:

```powershell
python examples/projects/16_nancon_natural_calibration/build_observation_package.py `
  --network-mask-npz path/to/observed_network_active_mask.npz `
  --network-distance-npz path/to/observed_network_distance_by_cell.npz `
  --geometry-npz path/to/cell_geometry.npz `
  --mesh-bundle path/to/mesh_bundle
```

Par defaut, la chronique observee est lue depuis:

```text
examples/projects/15_nancon_gauged_context/outputs/context/observed_discharge_daily.csv
```

Elle est filtree sur `2000-01-01 -> 2002-12-31`, puis agregee au pas mensuel
`ME`. La fenetre, la frequence et la periode de warmup sont configurables par
arguments CLI.

## Ce qui reste a developper

1. Projeter automatiquement l'hydrographie observee sur le maillage naturel.
   Aujourd'hui, `build_observation_package.py` consomme
   `observed_network_active_mask.npz` et
   `observed_network_distance_by_cell.npz`, mais ne les fabrique pas.

2. Brancher le package naturel sur de vrais runs candidats Nancon. Il manque
   le driver qui lance, pour chaque `{mK, Sy}` ou autre vecteur de parametres,
   un permanent pour le reseau et un transitoire pour le debit, puis appelle
   `score_natural_network_transient_candidate(...)`.

3. Promouvoir le contrat dans l'API de calibration generale. Le schema global
   ne declare pas encore proprement une observable `support = "network"` ou
   une calibration multi-scenario `steady + transient` pour un meme candidat.

4. Remplacer les poids fixes par une composition d'objectif adaptable. La
   strategie recommandee est de lancer un plan d'experience, regarder les
   echelles empiriques de `C_dist` et `C_debit_obs`, inspecter le front de
   Pareto, puis choisir une scalarisation configuree ou un mode contrainte.

5. Nettoyer les libelles du rapport HTML. Le rapport B0 est reutilise tel quel
   et certains libelles restent orientes "cible", `outflow_drain` ou B0. Le
   contrat naturel est correct, mais la presentation n'est pas encore finale.

6. Ajouter une validation Nancon reelle. Le smoke test actuel valide le contrat
   logiciel, pas la pertinence hydrologique du score sur le bassin naturel.

## Cas tests developpes

### Tests unitaires du module naturel

Commande:

```powershell
python -m pytest -o addopts="" tests/unit/calibration/test_natural_observations.py -q
```

Ce que ces tests verifient:

- un candidat avec le meme support reseau que l'observe obtient
  `C_reseau_naturel = 0`;
- un support reseau decale est penalise;
- l'ecriture d'un package naturel produit les fichiers attendus;
- le candidat identite obtient `J = 0`;
- un candidat avec reseau et debit errones obtient un score positif;
- `1 - NSElog` vaut zero pour une chronique parfaite et penalise les erreurs
  relatives sur les faibles debits.

Resultat attendu:

```text
6 passed
```

### Test du rapport HTML avec package naturel

Commande:

```powershell
python -m pytest -o addopts="" tests/unit/calibration/test_network_transient_html_reporting.py::test_network_transient_html_uses_truth_mesh_when_reference_run_is_empty -q
```

Ce que le test verifie:

- le rapport peut fonctionner sans run HydroModPy de reference;
- le maillage est reconstruit depuis le `mesh_bundle` du package naturel;
- les figures `dem_context_map.png` et `outflow_drain_maps.png` sont produites;
- le manifeste indique le contrat
  `natural_network_steady_discharge_transient.v1`;
- l'objectif affiche est `0.3*C_reseau_naturel + 0.7*C_debit_obs`.

Resultat attendu:

```text
1 passed
```

### Smoke test executable

Commande rapide dans le dossier du depot:

```powershell
python examples/projects/16_nancon_natural_calibration/run_synthetic_natural_smoke.py
```

Pour eviter d'ecraser les sorties suivies dans le depot, utiliser plutot un
dossier temporaire:

```powershell
python examples/projects/16_nancon_natural_calibration/run_synthetic_natural_smoke.py `
  --output-dir $env:TEMP\hmp_nancon_natural_smoke
```

Ce qu'il faut attendre:

- la commande affiche le chemin du rapport `web/index.html`;
- `truth_identity` est classe premier avec un objectif nul ou quasi nul;
- `shifted_network` degrade surtout `C_reseau_naturel`;
- `high_discharge` degrade surtout `C_debit_obs`;
- `combined_error` degrade les deux termes;
- le rapport HTML montre les cartes de drainage/support, les chroniques de
  debit et le manifeste de reference.

### Tests B0 voisins utiles

Les tests suivants ne sont pas specifiques au package naturel, mais ils
protegent les briques reutilisees:

```powershell
python -m pytest -o addopts="" tests/unit/calibration/test_network_metrics.py -q
python -m pytest -o addopts="" tests/unit/calibration/test_network_transient_truth.py -q
python -m pytest -o addopts="" tests/unit/calibration/test_b0_synthetic_smoke.py -q
python -m pytest -o addopts="" tests/unit/calibration/test_b0_score_candidate_table.py -q
```

Ils valident les metriques de reseau B0, le package verite reseau/debit,
le smoke synthetique historique et le classement de tables de candidats.

Le `-o addopts=""` neutralise l'option `--dist=loadgroup` du `pytest.ini` pour
les environnements ou `pytest-xdist` n'est pas installe. Dans un environnement
de developpement complet avec `pytest-xdist`, il peut etre retire.
