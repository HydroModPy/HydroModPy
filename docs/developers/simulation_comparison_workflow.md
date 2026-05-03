# Workflow de comparaison de simulations

Cette note fixe le contrat de la surcouche `workflow = "comparison"`.
Objectif: comparer plusieurs simulations HydroModPy sans ajouter de logique
dans le workflow `simulation`.

## Positionnement

- La comparaison est une couche externe.
- Chaque candidat reste une vraie simulation HydroModPy lancee par `hmp run`.
- La couche de comparaison genere des TOML enfants, lance les simulations,
  lit les resultats persistes, puis produit audit, metriques, exports et
  figures.
- Le coeur `simulation` ne partage ni cache memoire, ni maillage Python, ni
  objets de forcing avec la comparaison.

Ce choix accepte un cout de recalcul ou de rechargement pour garder une
frontiere nette: les simulations sont autonomes et la comparaison est
post-hoc.

## Fichiers d'entree

Le cas recommande utilise deux niveaux de TOML:

- un TOML de comparaison, avec `workflow = "comparison"`;
- un TOML de simulation de base, pointe par
  `[comparison].base_simulation_config`.

Le TOML de comparaison declare les variantes a comparer:

```toml
workflow = "comparison"

[comparison]
comparison_id = "dupuit_mf6_vs_bouss"
base_simulation_config = "base_dupuit_shared_mesh.toml"
output_root = "outputs/dupuit_mf6_vs_bouss"
reference_simulation = "mf6_ref"

[[comparison.simulation]]
id = "mf6_ref"
solver = "modflow6"

[[comparison.simulation]]
id = "bouss_candidate"
solver = "boussinesq"

[[comparison.observable]]
name = "head_map_last"
variable = "watertable_elevation"
support = "map"
time = "last"
unit = "m"
```

La couche genere ensuite un TOML enfant par simulation dans:

```text
<output_root>/_generated_configs/<simulation_id>.toml
```

Ces TOML enfants sont self-contained: les chemins relatifs du TOML de base
sont resolus avant ecriture, pour eviter qu'un changement de dossier de sortie
modifie le sens des chemins.

## Overlays autorises

En V1, les overlays sont volontairement limites pour ne pas modifier la
physique du cas par accident. Les sections autorisees sont:

- `simulation`: nom, run id, collision, process;
- `solver`: parametres generiques solveur;
- `modflow6`: options propres MODFLOW 6;
- `modflownwt`: options propres MODFLOW-NWT;
- `flow`: `runtime_backend` uniquement;
- `display`: sortie graphique.

Les sections physiques comme domaine, recharge, proprietes hydrauliques ou
conditions aux limites ne doivent pas etre changees dans les variantes V1.
Si la physique doit changer, il faut creer un autre cas de simulation de base
ou etendre explicitement le contrat.

## Garde-fous V1

Le chargement du TOML de comparaison refuse maintenant les cas ambigus avant
de lancer les simulations:

- `base_simulation_config` doit exister;
- `comparison_id` ne doit pas contenir de separateur de chemin;
- chaque `comparison.simulation.id` doit etre unique et compatible avec un
  nom de fichier;
- au moins une simulation doit etre activee;
- `reference_simulation`, si renseigne, doit pointer vers une simulation
  activee;
- `observable.variants`, si renseigne, ne peut cibler que des simulations
  activees.

Ces controles restent dans la surcouche de comparaison. Ils n'ajoutent aucune
contrainte nouvelle au workflow `simulation`.

## Cycle d'execution

1. Charger le TOML de comparaison.
2. Charger le TOML de simulation de base.
3. Generer les TOML enfants avec les overlays solveur.
4. Lancer chaque enfant via l'entree publique:

```powershell
python -m hydromodpy run <child.toml>
```

5. Retrouver le `sim_id` et le catalogue de resultats.
6. Extraire les observables declarees.
7. Comparer les observables au candidat de reference.
8. Ecrire les exports et figures.
9. Auditer a posteriori les metadonnees persistantes.

## Sorties

Un run de comparaison produit notamment:

- `comparison_manifest.json`: index complet des sorties;
- `comparison_report.md`: rapport lisible;
- `comparison_audit.json` et `comparison_audit.md`: controle de coherence;
- `observables.csv`: valeurs extraites;
- `comparison_metrics.csv`: biais, MAE, RMSE, erreur max;
- `comparison_differences.csv`: differences elementaires;
- `hydrographic_network_metrics.csv`: comparaison geometrique `reference` vs
  `generated` quand les runs exposes stockent les deux reseaux hydrographiques
  canoniques;
- `comparison_figures/case_configuration.png`: figure d'orientation du cas
  compare, avec support spatial, conditions aux limites detectees, points
  observables et chronique de recharge quand elle existe;
- `comparison_figures/*.png`: cartes, differences, triptyques, budgets et
  temps calcul.

Par defaut, `hydrographic_network_metrics.csv` utilise une tolerance de
50 m et exporte notamment:

- longueurs totales reference/candidat;
- longueurs manquantes et surnumeraires;
- ratios de couverture / precision / F1 sur la longueur;
- distance de Hausdorff.

Les noms canoniques utilises par le code sont:

- `hydrographic_network_reference` pour le reseau charge depuis
  `data.hydrography`;
- `hydrographic_network_generated` pour le reseau derive du DEM via
  `geographic.river_network`.

Les noms historiques restent lisibles pour compatibilite, mais doivent etre
consideres comme des alias legacy:

- `river_network` pour l'ancienne feature du reseau genere;
- `streams.shp` pour le fichier vecteur de reference exporte par le manager;
- `hydrography_streams` pour le raster de forcing du masque hydrographique.

Si un run n'expose qu'un seul des deux reseaux canoniques:

- `hydrographic_network_metrics.csv` n'est pas produit pour ce run;
- les figures de comparaison hydrographique ne doivent pas etre demandees;
- l'API `Run` permet de verifier ce cas via
  `available_hydrographic_network_roles()` et `has_hydrographic_network(...)`.

Lire d'abord `case_configuration.png` pour comprendre le cas teste, puis les
figures `*triptych*.png` pour valider rapidement les champs: champ de
reference, champ candidat, puis difference candidat moins reference.

## Nettoyage disque

Les simulations enfants persistent leurs propres sorties, comme tout run
HydroModPy. La couche de comparaison peut seulement nettoyer les TOML generes:

```toml
[comparison.execution]
keep_generated_configs = false
```

Par defaut, ils sont gardes pour faciliter le debug et la reproductibilite.
Les resultats lourds restent dans les dossiers de run des simulations, car la
surcouche n'a pas vocation a detruire des sorties de simulation.

## Exemples disponibles

Le dossier `examples/projects/09_comparison_workflow/` contient:

- `compare_dupuit_mf6_bouss.toml`: cas synthetique, MODFLOW 6 contre
  Boussinesq, maillage triangulaire partage;
- `compare_vire_natural_mf6_nwt.toml`: bassin naturel Vire, MODFLOW 6 contre
  MODFLOW-NWT, grille structuree 40 x 40;
- `compare_10km2_natural_mesh_mf6_bouss.toml`: maillage naturel pre-calcule
  10 km2, physique steady simplifiee, MODFLOW 6 contre Boussinesq sur le meme
  maillage triangulaire;
- `compare_10km2_natural_mesh_recharge_mf6_bouss.toml`: meme maillage naturel
  10 km2, avec recharge synthetique uniforme faible, MODFLOW 6 contre
  Boussinesq;
- `compare_10km2_natural_mesh_transient_pulse_mf6_bouss.toml`: meme maillage
  naturel 10 km2, recharge journaliere impulsionnelle et stockage Sy/Ss,
  MODFLOW 6 contre Boussinesq.
- `compare_nancon_transient_seasonal_mf6_bouss.toml`: bassin Nancon, support
  regenere depuis le meme TOML de base, recharge hebdomadaire synthetique avec
  saisonnalite et episodes humides/secs, MODFLOW 6 contre Boussinesq.

Commandes:

```powershell
python examples/projects/09_comparison_workflow/run_comparison_example.py --case synthetic --show
python examples/projects/09_comparison_workflow/run_comparison_example.py --case natural --show
python examples/projects/09_comparison_workflow/run_comparison_example.py --case natural-bouss --show
python examples/projects/09_comparison_workflow/run_comparison_example.py --case natural-bouss-recharge --show
python examples/projects/09_comparison_workflow/run_comparison_example.py --case natural-bouss-transient-pulse --show
python examples/projects/09_comparison_workflow/run_comparison_example.py --case nancon-seasonal --show
python examples/projects/09_comparison_workflow/run_comparison_example.py --case all --show
```

## Limites actuelles

- Execution sequentielle uniquement: `max_parallel_runs = 1`.
- Audit strict base sur les metadonnees persistees, pas sur un partage
  d'objets en memoire.
- Les comparaisons sur maillages differents passent par les observables et
  les rasters fins, pas par une correspondance cell-to-cell generale.
- Le cas naturel Boussinesq historique reste volontairement reduit: il utilise
  un maillage naturel mais une topographie analytique et des charges imposees
  laterales. La variante recharge ajoute un forcage diffus synthetique, mais
  pas encore une physique bassin complete avec drainage et reseau
  hydrographique. La variante transitoire ajoute Sy/Ss et un pulse de recharge,
  mais reste courte et controlee pour garder les ecarts interpretables.
- Le cas `nancon-seasonal` pousse la difficulte: topographie de bassin naturel,
  drainage de surface, maillage/support regenere par chaque run, et recharge
  transitoire non triviale. Il sert de test de robustesse plus que de benchmark
  analytique.

## Prochain developpement naturel

Le prochain increment utile est d'etendre le cas naturel reduit MODFLOW 6
contre Boussinesq vers une physique bassin:

- comparer explicitement les flux de bord et les budgets quand les deux
  solveurs les exposent de maniere compatible;
- ajouter une variante saisonniere multi-mois ou multi-annees sur le meme
  maillage;
- tester un cas bassin naturel complet avec drainage/reseau hydrographique;
- documenter les criteres de convergence et les ecarts attendus par famille de
  cas.

Ce developpement doit rester dans `examples/projects/09_comparison_workflow/`
ou dans un dossier `validation_cases/`, sans modifier `simulation`.
