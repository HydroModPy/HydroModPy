# Rapport de conformité architecture — HydroModPy v0.4

**Date :** 2026-04-21
**Branche :** `dev-refact_v2` au commit `31b90697` (HEAD, avant F08)
**Base :** `run_migration.sh` (P01-P13) + `run_finalization.sh` (F01-F07), phase F08 en cours
**Méthodologie :** vérification directe du code, indépendante de `migration_report_dev_refact_v2.md` (obsolète).
**Fichier de référence pour chaque spec :** `architecture_cible/XX_*.md`.

Ce rapport atteste la conformité du codebase v0.4 aux 14 spécifications
d'architecture cible, en inventoriant pour chaque spec un ensemble de
_checkpoints_ concrets (fichier/classe/CLI/table DuckDB/import). Chaque
checkpoint est noté :

- **OK**       — conforme, avec une preuve (file:line ou commande).
- **ÉCART**    — divergence assumée/documentée ailleurs (F02, OVERRIDE spec, etc.).
- **MANQUANT** — divergence résiduelle. Une tâche de suivi est proposée.

---

## Executive summary

| Spec | OK | Écart | Manquant | Verdict global |
|------|----|-------|----------|----------------|
| 01_structure_packages.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 02_config_pydantic.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 03_data_contracts.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 04_storage_ideal.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 05_solver_contracts.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 06_pipeline_execution.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 07_calibration.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 08_postprocess_display.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 09_tests_ideaux.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 10_ux_cli_api.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 11_frontend_ready.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 12_input_data_rethink.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 13_coherence_globale.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 14_plan_migration.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| **TOTAL** | _TBD_ | _TBD_ | _TBD_ | _TBD_ |

---

## Détail par spécification

_Les sections ci-dessous seront remplies au fil de la vérification (F08)._

---

## Écarts globaux assumés (décisions architecture)

_À compiler après les 14 vérifications._

---

## Manquants résiduels (à traiter post-v0.4)

_À compiler après les 14 vérifications._

---

## Conclusion

_À renseigner après synthèse._
