# 03 - Groundwater 1D (cas analytique)

Cas analytique purement Python : aquifère Dupuit-Forchheimer 1D
calibré sur une chronique de têtes synthétique bruitée. Pas de
MODFLOW, pas de filesystem, pas de réseau.

## État courant

Le fichier `project.toml` n'existe pas : il a été mis en quarantaine
sous `project.toml.draft` car ce projet **n'est pas dispatché par
`hmp run`** dans v1. Les cas analytiques vivent sous
`hydromodpy.calibration.cases` et sont chargés directement depuis
Python.

## Utilisation Python

```python
from hydromodpy.calibration.cases.groundwater_1d import (
    build_noisy_groundwater_chronicle,
    calibrate_groundwater,
)

chronicle = build_noisy_groundwater_chronicle({
    # voir [chronicle] dans project.toml.draft
})
result = calibrate_groundwater(
    method="optuna",
    chronicle=chronicle,
    max_iter=50,
    seed=42,
    bounds={"Kam": [1.0, 10.0]},   # voir [calibration.parameters]
)
```

Les sections TOML du draft documentent les kwargs attendus par les
deux helpers. Voir `docs/developers/calibration_guide.md` pour le
walkthrough complet.

## Réactiver le TOML

Pour transformer le draft en projet runnable, il faudra :

1. Câbler `groundwater_1d` dans le dispatcher de `hmp run`
   (`hydromodpy/cli/commands/run.py`).
2. Définir un schéma Pydantic dédié (ou réutiliser le sous-set
   `[calibration]` de `HydroModPyConfig`).
3. Renommer `project.toml.draft` -> `project.toml` et valider via
   `hmp config check`.
