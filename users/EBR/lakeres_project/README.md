# LakeRes EBR Project

Refonte modulaire de `users/EBR/app_EBR_commun.py` et `users/EBR/app_EBR_simplex.py`.

## Profils disponibles

- `common`: exécution standard (équivalent `app_EBR_commun.py`)
- `simplex`: calibration Nelder-Mead + run final (équivalent `app_EBR_simplex.py`)

## Lancement

Depuis la racine du dépôt:

```bash
python -m users.EBR.lakeres_project.main --profile common
python -m users.EBR.lakeres_project.main --profile simplex
```

Ou via wrappers:

```bash
python -m users.EBR.lakeres_project.run_common
python -m users.EBR.lakeres_project.run_simplex
```
