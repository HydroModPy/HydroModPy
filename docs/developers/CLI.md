# CLI

Après `pip install -e .`, deux commandes équivalentes sont disponibles :
`hmp` et `hydromodpy`. Le dispatch principal est dans
`hydromodpy/_cli/main.py`, les sous-commandes dans
`hydromodpy/_cli/commands/`.

Liens : [glossary.md](glossary.md),
[frontend_hooks.md](frontend_hooks.md),
[calibration_guide.md](calibration_guide.md).

## Exécution d'un workflow

Point d'entrée unique :

```bash
hmp run chemin/vers/project.toml
```

Le TOML doit déclarer un champ `workflow = "..."` au premier niveau.
Valeurs reconnues (voir `hydromodpy/_cli/workflows.py`, constante
`KNOWN_WORKFLOWS`) :

| Valeur | Rôle |
|---|---|
| `"simulation"` | Exécute une simulation : setup, data, mesh, solveur, extraction, export |
| `"calibration"` | Boucle d'optimisation, exécute N simulations, choisit la meilleure |
| `"batch"` | Campagne régionale multi-sites, expansion sites × recettes |
| `"overview"` | Fiche d'identité du bassin (data et géographie, sans solveur) |
| `"mesh"` | Génération du maillage de bassin uniquement |
| `"comparison"` | Comparaison post-hoc de simulations enfants issues d'un cas de base |
| `"testbed"` | Banc d'essai méthodologique, variantes enfants et preuves de robustesse |

Exemple minimal de TOML :

```toml
workflow = "simulation"

[workspace]
root = "/chemin/vers/workspace"
project_root = "."

[geographic]
# ...
```

Si `workflow` est absent ou prend une valeur inconnue, la commande
échoue au chargement avec un message explicite. La même contrainte est
appliquée côté Pydantic (`HydroModPyConfig`) afin que les frontaux
(Angular, React) voient le champ comme un enum requis.

Les scripts Python peuvent aussi être passés à `hmp run`, ils sont
exécutés comme sous-processus :

```bash
hmp run prototype_script.py
```

## Génération d'un fichier de configuration

```bash
hmp config mon_config.toml
hmp config mon_config.toml --profile user
hmp config --list-modules
hmp config --modules flow transport
```

`--profile` contrôle la verbosité du TOML produit :

- `user` : défauts sûrs, champs minimaux.
- `dev` : intermédiaire.
- `expert` : tous les champs (défaut).

Voir `Profile` dans [glossary.md](glossary.md).

## Tests

### Unitaires

```bash
hmp test unit
```

### Régression

Tous les tests :

```bash
hmp test regression
```

Filtres par vitesse ou famille de solveur :

```bash
hmp test regression --fast
hmp test regression --extensive
hmp test regression --slow
hmp test regression --nwt
hmp test regression --mf6
```

Un test spécifique :

```bash
hmp test regression launcher_simulation_fast_nwt --fast --nwt
hmp test regression launcher_simulation_fast_mf6 --fast --mf6
hmp test regression launcher_simulation_extensive_nwt --extensive --nwt
hmp test regression launcher_simulation_extensive_mf6 --extensive --mf6
```

Liste les tests disponibles :

```bash
hmp test regression --list
```

Parallélisation (requiert `pytest-xdist`) :

```bash
hmp test regression -j auto
hmp test regression --fast -j 4
hmp test unit -j auto
hmp test regression launcher_simulation_extensive_nwt -j 1
```

Mise à jour des goldens :

```bash
hmp test regression --update-goldens
hmp test regression launcher_simulation_fast_mf6 --update-goldens
```

### Validation

```bash
hmp test validation
hmp test validation --fast
hmp test validation --steady
hmp test validation --transient
hmp test validation --analytical
hmp test validation --mf6
hmp test validation --nwt
```

La cible `validation` ajoute automatiquement le marqueur pytest
`validation`, puis les filtres supplémentaires.

## Autres commandes

| Commande | Rôle |
|---|---|
| `hmp init [chemin]` | Scaffold d'un workspace |
| `hmp new <projet>` | Créer un nouveau projet dans le workspace |
| `hmp doctor` | Diagnostic environnement et workspace |
| `hmp list` | Liste les projets et runs |
| `hmp show <sim_id>` | Affiche les métadonnées d'un run |
| `hmp inspect <sim_id>` | Inspection détaillée d'un run |
| `hmp best` / `hmp worst` | Meilleur ou pire run selon métrique |
| `hmp compare <sim_a> <sim_b>` | Comparaison de deux runs |
| `hmp display <config.toml>` | Production des figures |
| `hmp export <sim_id>` | Export vers un format externe ou un `.hmp` |
| `hmp import <package.hmp>` | Import d'un `.hmp` dans le workspace |
| `hmp delete <sim_id>` | Suppression d'un run |
| `hmp migrate` | Migration v0.5 vers v0.6 (voir [parquet_lakehouse_migration_guide.md](parquet_lakehouse_migration_guide.md)) |
| `hmp schema export` | Export JSON Schema (voir [frontend_hooks.md](frontend_hooks.md)) |
| `hmp schema validate-field` | Validation partielle d'un champ |
| `hmp lock` | Verrou workspace |
| `hmp data` | Gestion du cache d'entrée |
| `hmp completion` | Génération d'un script de complétion shell |

Notes :

- `--fast` et `--extensive` sélectionnent les tiers de régression,
  `--slow` est un filtre par marqueur pytest.
- `--nwt` et `--mf6` filtrent par famille de solveur.
- `-j` est mappé sur `pytest-xdist -n`. Sans flag, exécution séquentielle.
- `--normal` est un alias déprécié de `--fast`.
- La commande imprime sur stderr l'invocation `pytest` réelle avant de
  la lancer.
