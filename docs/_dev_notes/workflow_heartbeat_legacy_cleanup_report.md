# Workflow heartbeat legacy cleanup report

Date: 2026-05-27

## Lot: suppression du heartbeat legacy dans `simulations`

Objectif: faire de `workflow_events` l'unique source runtime de liveness et
supprimer la dependance a `simulations.last_heartbeat`.

Changements:

- `HeartbeatPulse` n'ecrit plus dans `simulations.last_heartbeat`.
- `HeartbeatPulse` emet uniquement des evenements `heartbeat` dans
  `workflow_events`.
- `Pipeline` aligne le heartbeat runtime sur le `sim_id`, qui est la cle lue
  par `v_workflow_heartbeats` pour GC/doctor.
- Suppression de `WorkflowJournal.update_heartbeat`.
- Ajout d'une migration en deux temps:
  - `0005_drop_simulation_heartbeat.sql`: suppression temporaire des index
    `simulations`, necessaire avant modification de table DuckDB.
  - `0006_drop_simulation_heartbeat_column.sql`: suppression de la colonne,
    puis recreation des index conserves.
- Les tests workflow/GC utilisent maintenant `v_workflow_heartbeats`.
- La documentation `pipeline_resume.rst` parle des evenements heartbeat, plus
  de la colonne `simulations.last_heartbeat`.

Validation:

- `python -m ruff check hydromodpy/workflow hydromodpy/results/catalog/migrations tests/unit/workflow/test_heartbeat.py tests/unit/workflow/test_journal.py tests/integration/workflow/test_resume_e2e.py tests/unit/cli/test_gc.py tests/unit/results/test_schema_v2.py tests/unit/results/test_schema_migrations.py`
- `python -m pytest tests/regression/migration/test_workflow_events.py tests/unit/results/test_schema_v2.py tests/unit/results/test_schema_migrations.py -q`
- `python -m pytest tests/unit/workflow/test_heartbeat.py tests/unit/workflow/test_journal.py tests/integration/workflow/test_resume_e2e.py tests/unit/cli/test_gc.py tests/unit/architecture/test_storage_boundary.py tests/regression/migration/test_workflow_events.py tests/unit/results/test_schema_v2.py tests/unit/results/test_schema_migrations.py -q`

Resultat: 72 tests passes sur le lot complet.

## Proposition du lot suivant

Nettoyer les remappings de configuration legacy encore acceptes au chargement
TOML, en commencant par `hydromodpy/config/toml_section_loader.py`.

But: remplacer les conversions silencieuses d'anciens noms de sections par des
erreurs explicites et des tests anti-retour, comme deja fait pour plusieurs
schemas site-selection et DEM.
