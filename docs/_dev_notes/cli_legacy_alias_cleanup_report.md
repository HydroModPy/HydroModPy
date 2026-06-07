# CLI legacy alias cleanup report

Date: 2026-05-27

## Lot: suppression de l'alias top-level `hmp init`

Objectif: retirer l'ancien raccourci de compatibilite `hmp init` pour garder
une surface CLI unique et explicite: `hmp workspace init`.

Changements:

- Suppression de `hydromodpy/cli/commands/init.py`.
- Retrait du module `init` de `hydromodpy/cli/commands/__init__.py`.
- Migration des messages et de la documentation vers `hmp workspace init`.
- Ajout d'une garde anti-retour: `hmp init --help` doit echouer comme commande
  top-level invalide.
- Ajustement du test de completion pour verifier des commandes top-level
  actuelles (`run`, `workspace`, `doctor`) sans dependance au mot `init`.

Validation:

- `python -m ruff check hydromodpy/cli hydromodpy/core/workspace hydromodpy/data/store.py hydromodpy/data/scaffold.py hydromodpy/data/adapters/csv_to_parquet.py tests/unit/test_cli_help.py tests/integration/test_cli_subcommands.py tests/unit/data_managers/test_scaffold.py tests/unit/data_managers/test_data_scaffold.py`
- `python -m pytest tests/unit/test_cli_help.py tests/integration/test_cli_subcommands.py tests/unit/cli/test_workspace_family.py tests/unit/cli/test_workspace_index.py tests/unit/data_managers/test_scaffold.py tests/unit/data_managers/test_data_scaffold.py -q`

Resultat: 80 tests passes.

## Lot: suppression des alias historiques d'exit codes CLI

Objectif: retirer les alias de compatibilite qui masquaient les constantes
typees actuelles.

Changements:

- Suppression de `EXIT_RUN_FAILED`, `EXIT_USER_ABORT` et `EXIT_DATA_ERROR`
  dans `hydromodpy/cli/helpers.py`.
- Migration des commandes CLI vers les constantes explicites:
  `EXIT_GENERIC`, `EXIT_SIGINT`, `EXIT_VALIDATION`.
- Ajout d'une garde anti-retour dans `tests/unit/test_cli_exit_codes.py`.

Validation:

- `python -m ruff check hydromodpy/cli tests/unit/test_cli_exit_codes.py tests/unit/test_cli_help.py tests/integration/test_cli_subcommands.py`
- `python -m pytest tests/unit/test_cli_exit_codes.py tests/unit/test_cli_help.py tests/integration/test_cli_subcommands.py tests/unit/cli/test_workspace_family.py tests/unit/cli/test_workspace_index.py -q`

Resultat: 70 tests passes.

## Lot suivant traite

Les compatibilites historiques du runtime workflow ont ete traitees dans
`docs/_dev_notes/workflow_legacy_cleanup_report.md`:

- `hydromodpy/workflow/events.py`
- `hydromodpy/workflow/heartbeat.py`

La suppression propre est passee par deux migrations catalogue et les tests de
schema, heartbeat, GC, bootstrap testbed et dispatch CLI.
