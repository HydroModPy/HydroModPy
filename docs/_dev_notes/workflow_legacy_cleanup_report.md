# Workflow legacy cleanup report

Date: 2026-05-27

## Objectif

Retirer les compatibilites workflow restantes identifiees apres les lots
`site_selection`, DEM IGN, validation cases et CLI:

- colonne historique `simulations.last_heartbeat`;
- shim d'import racine `hydromodpy.workflow_dispatch`;
- hooks de compatibilite `hydromodpy.workflow.testbed`.

## Changements appliques

- Ajout des migrations catalogues:
  - `0005_drop_simulation_heartbeat.sql`: retire les index de `simulations`
    avant modification de table;
  - `0006_drop_simulation_heartbeat_column.sql`: supprime
    `simulations.last_heartbeat` et recree les index conserves.
- `HeartbeatPulse` et les tests ne s'appuient plus que sur
  `workflow_events` et `v_workflow_heartbeats`.
- Suppression du shim public `hydromodpy/workflow_dispatch.py`.
  L'import canonique est `hydromodpy.project.dispatch.workflow`.
- Suppression de `hydromodpy/workflow/testbed.py`.
  Le bootstrap enregistre directement `ProjectTestbedRunnerProvider` via
  `hydromodpy.analysis.testbed.contracts.register_testbed_runner_provider`.
- Mise a jour des tests, docs API generees et commentaires d'exemples.

## Validation

Commandes executees:

```powershell
python -m pytest -q tests/unit/results/test_schema_v2.py tests/unit/workflow/test_heartbeat.py tests/unit/workflow/test_journal.py tests/unit/cli/test_gc.py tests/unit/architecture/test_storage_boundary.py -o addopts=""
python -m pytest -q tests/unit/workflow/test_testbed_bootstrap.py tests/unit/site_selection/test_workflow_dispatch.py tests/unit/launchers/test_hmp_simulation_cli.py -o addopts=""
python -m ruff check hydromodpy/workflow hydromodpy/results/catalog/migrations tests/unit/results/test_schema_v2.py tests/unit/workflow/test_heartbeat.py tests/unit/workflow/test_journal.py tests/unit/cli/test_gc.py tests/integration/workflow/test_resume_e2e.py
python -m ruff check hydromodpy/_bootstrap.py tests/unit/workflow/test_testbed_bootstrap.py tests/unit/site_selection/test_workflow_dispatch.py tests/unit/launchers/test_hmp_simulation_cli.py
```

Resultats:

- `54 passed` pour schema, heartbeat, journal, GC et garde architecture;
- `26 passed` pour bootstrap testbed, dispatch site-selection et CLI run;
- Ruff passe sur les fichiers touches.

## Etat apres lot

Le code actif ne contient plus:

- `hydromodpy.workflow_dispatch`;
- `hydromodpy.workflow.testbed`;
- lecture/ecriture directe de `simulations.last_heartbeat`.

Les occurrences restantes de `last_heartbeat` sont:

- le nom de colonne expose par la vue courante `v_workflow_heartbeats`;
- les migrations historiques 0001/0004 et la migration de suppression 0006;
- les tests de garde anti-retour.

## Suite

La dette legacy restante n'est plus un shim workflow actif. Les prochains lots
possibles sont plus larges:

1. migration du vocabulaire de fixtures/regression `launcher_simulation`;
2. nettoyage des artefacts locaux non suivis dans
   `examples/projects/17_site_selection_workflow/outputs`;
3. decision long terme sur les chemins transport historiques MT3DMS/MODPATH.
