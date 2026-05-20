# Validity Frame

Service transverse indépendant du solveur, du workflow et de l'orchestrateur.

## Objectif

Capturer automatiquement les informations d'exécution, associer des métriques métier, permettre une validation experte, puis constituer une base de connaissance d'exécutions.

## Arborescence proposée

- `auto_capture/` : collecte automatique du contexte et des métriques runtime.
- `probes/` : sondes spécialisées pour le système, le runtime, le solveur et le matériel.
- `semantic_model/` : modèle sémantique défini par l'utilisateur.
- `objectives/` : objectifs simples, composites et règles d'acceptation.
- `extraction/` : extraction des résultats, scores, erreurs et convergence.
- `validation/` : validation experte, rejet, justification et annotations.
- `provenance/` : traçabilité scientifique, versions, environnement et paramètres.
- `storage/` : organisation des supports de stockage et des formats.
- `adapters/` : connecteurs pour boucles Python, Airflow, Prefect, Ray et HPC.
- `records/` : structure logique des Execution Knowledge Records.
- `analytics/` : exploitation, exploration et visualisation des expériences.
- `plugins/` : extensions optionnelles.
- `configs/` : fichiers de configuration du service.
- `schemas/` : schémas de validation des données.
- `docs/` : documentation locale du service.
- `tests/` : tests dédiés au service.

## Stockage logique conseillé

- `raw/` : exécutions capturées brutes.
- `validated/` : exécutions validées.
- `rejected/` : exécutions rejetées avec explication.
- `provenance/` : artefacts de traçabilité.
- `index/` : index et catalogues.
- `archives/` : conservation historique.

## Principe d'architecture

Le service doit rester indépendant du calcul et n'utiliser que :
- les objets de contexte d'exécution,
- les probes,
- les adapters,
- le modèle sémantique.

## Intégration future

Cette base peut ensuite recevoir les modules fonctionnels sans modifier l'organisation globale.