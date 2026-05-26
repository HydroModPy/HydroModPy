# Site selection - rapport de suppression legacy, lot 1

Date: 2026-05-27

## Perimetre

Ce lot traite uniquement la legacy `site_selection`, hors source DEM
`ign_bdalti`. Le but est de supprimer les anciens chemins de rapport, les
aliases de domaine sans logique propre et le doublon de sortie
`selection_decisions.jsonl`.

## Changements appliques

- Suppression finalisee de `reports/legacy_review.py` et retrait de l'export
  public `render_selection_report`.
- Suppression des aliases de domaine `domain/candidates.py` et
  `domain/catchments.py`; les imports canoniques sont respectivement
  `candidates.outlets.CandidateOutlet` et
  `hydrology.delineation.DelineatedCatchment`.
- Renommage de `decisions/adapters.py` en `decisions/records.py`.
  Le module de decisions ne parle plus de modele legacy: il construit des
  `DecisionRecord` normalises a partir du resultat de selection courant.
- Suppression de l'ecriture de `selection_decisions.jsonl`.
  La sortie canonique est maintenant `site_selection_decisions.jsonl`, completee
  par `site_selection_decisions.csv` pour la synthese par bassin.
- Mise a jour du manifest: `site_selection_decisions_jsonl` devient une sortie
  requise a la place de `selection_decisions_jsonl`.
- Mise a jour du rapport HTML: il lit les decisions normalisees et retrouve la
  decision finale via les enregistrements `criterion_id = "final_selection"`.
- Mise a jour des tests et de la documentation de contrat.

## Validation

Commandes executees:

```powershell
python -m pytest -q tests/unit/site_selection -m fast -o addopts=""
python -m pytest -q tests/unit/site_selection/test_exports.py tests/unit/site_selection/test_manifest_report.py tests/unit/site_selection/test_decision_records.py -m fast -o addopts=""
python -m ruff check hydromodpy/spatial/site_selection hydromodpy/schema/site_selection_manifest.py tests/unit/site_selection
```

Resultats:

- `142 passed` sur les tests rapides `site_selection`;
- `23 passed` sur les tests de contrat export/manifest/decision;
- `ruff`: aucun probleme.

## Etat apres lot 1

Le contrat `site_selection` n'expose plus:

- `reports/legacy_review.py`;
- `render_selection_report`;
- `decisions.adapters`;
- `selection_decisions.jsonl`;
- `selection_decisions_jsonl`.

Le coeur d'audit canonique est:

- `site_selection_manifest.json`;
- `criteria_components.jsonl`;
- `site_selection_decisions.jsonl`;
- `site_selection_decisions.csv`;
- `site_selection_evidence.jsonl` quand des preuves normalisees existent.

## Suite proposee

1. Lancer le lot 2 DEM: remplacer les exemples restants `ign_bdalti` par
   `ign_geoplateforme_dem`, puis retirer la branche runtime `ign_bdalti`.
2. Regenerer les references de documentation/API si le chantier inclut les
   artefacts ignores sous `docs/source/api/generated/`.
3. Faire une passe globale hors `site_selection` sur les autres compatibilites
   declarees comme legacy (`workflow_dispatch`, aliases CLI, colonnes de
   heartbeat historiques), a traiter dans un chantier separe car le risque de
   casse publique est plus large.
