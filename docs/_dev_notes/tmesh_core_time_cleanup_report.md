# TMesh core-time cleanup report

Date: 2026-05-28

## Objectif

Cloturer le deplacement des composants TMesh hors de `hydromodpy.core.time`.
Le contrat courant place la generation de maillage temporel dans
`hydromodpy.discretization.time`; `hydromodpy.core.time` ne garde que la
resolution de fenetre temporelle et les controles de couverture.

## Nettoyage applique

- Verification qu'aucun module source `hydromodpy/core/time/cases` n'existe
  dans le depot.
- Verification que les modules TMesh suivis sont les modules canoniques:
  `hydromodpy/discretization/time/tmesh_config.py`,
  `hydromodpy/discretization/time/tmesh_generation.py` et
  `hydromodpy/discretization/time/cases/*`.
- Suppression locale de l'index API ignore `hydromodpy.core.time.rst` et des
  pages generees pour les anciens modules `hydromodpy.core.time.tmesh_*` et
  `hydromodpy.core.time.cases.*`.
- Suppression locale des anciens bytecodes ignores
  `hydromodpy/core/time/__pycache__/tmesh_*.pyc`.

## Etat de cloture

Le chantier TMesh/core-time ne demande pas de changement de code suivi. Les
onglets IDE pointant vers `hydromodpy/core/time/cases/*` correspondent a un
ancien emplacement; le chemin maintenu est
`hydromodpy/discretization/time/cases/*`.

## Validations ciblees

- `rg "hydromodpy\\.core\\.time\\.tmesh|hydromodpy\\.core\\.time\\.cases|core/time/cases|core\\\\time\\\\cases" docs/source hydromodpy tests examples`
- `python -m pytest -q tests/unit/discretization/time tests/unit/solver/modflow_nwt/test_modflow_config.py tests/unit/solver/test_modflow6_time_grid_contract.py -o addopts=""`

Resultats 2026-05-28:

- grep actif hors `_dev_notes`: aucune occurrence restante.
- `python -m ruff check hydromodpy/discretization/time ...`: OK.
- `python -m pytest -q tests/unit/discretization/time/test_tmesh_config.py -o addopts=""`:
  9 passed.
- `python -m pytest -q tests/unit/discretization/time/test_tmesh_generation.py -o addopts=""`:
  18 passed.
- `python -m pytest -q tests/unit/discretization/time/cases/test_tmesh_cases.py -o addopts=""`:
  2 passed.
- `python -m pytest -q tests/unit/solver/modflow_nwt/test_modflow_config.py -o addopts=""`:
  10 passed, avec un avertissement non bloquant d'ecriture `.pytest_cache`
  refusee par le systeme de fichiers local.
- `python -m pytest -q tests/unit/solver/test_modflow6_time_grid_contract.py -o addopts=""`:
  2 passed.
