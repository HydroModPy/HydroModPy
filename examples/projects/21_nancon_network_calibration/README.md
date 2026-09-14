# Nançon, calibration par le réseau hydrographique puis par le débit

Bassin du Nançon à Fougères (station J001401001, 64,64 km² délimités,
Ille-et-Vilaine), calibré en deux étages selon la méthode d'Abherve et al.
(HESS 2023, WRR 2025) :

1. **`K/R` sur l'extension du réseau**, en régime permanent, par recherche du
   zéro de l'écart signé entre deux distances. **Aucune donnée de débit n'entre
   dans cet étage.**
2. **`Sy` sur l'hydrogramme observé**, en transitoire, `K` étant gelé à la
   valeur que l'étage 1 a trouvée.

MODFLOW 6, maillage DISV 25 m, 243 552 mailles, aquifère d'une couche de 30 m.

## Les quatre fichiers

| fichier | mode | ce qu'il fait |
|---|---|---|
| `project.toml` | simulation | La base : MNT 25 m, délimitation par exutoire, burn du linéaire, drain de Cauchy proportionnel à `K`, permanent d'un an. C'est aussi le **marqueur de racine** du projet, il ne se supprime pas. |
| `smoke.toml` | simulation | Contrôle permanent de deux minutes, SFR + DRN. La porte de sortie avant tout run long : `mesh_hash`, profil de lit, convergence. |
| `auto_drn_full.toml` | calibration | Les deux étages en drain pur, autonome, avec la galerie de figures. |
| `auto_sfr_drn.toml` | calibration | Les deux étages en SFR + DRN. L'étage 1 éteint les biefs par construction, l'étage 2 les rallume. |

Les deux `auto_*` sont **autonomes** : pas de `base_config`, pas de script
Python. C'est le montage à reprendre pour toute nouvelle variante.

## Lancer

```console
$ micromamba activate hmp_dev
$ cd examples/projects/21_nancon_network_calibration

$ hmp run smoke.toml                 # ~2 min, a lancer en premier
$ hmp calibrate auto_drn_full.toml   # drain pur
$ hmp calibrate auto_sfr_drn.toml    # SFR + drain

$ hmp calibrate auto_sfr_drn.toml --list-phases
$ hmp calibrate auto_sfr_drn.toml --phase steady_k
```

Le second étage ne peut pas être lancé seul : il dépend des valeurs que le
premier gèle, et le runner le refuse plutôt que de calibrer contre des
paramètres non gelés.

## Ce que le critère mesure

`D_so` est la distance moyenne, mesurée le long des chemins de descente du
maillage, du réseau de suintement **simulé** vers le linéaire **cartographié**.
`D_os` est la distance inverse. La calibration cherche le **zéro** de
`J = D_so - D_os`, pas le minimum d'une erreur : les deux ne sont pas au même
endroit.

## État au 8 septembre 2026

Le projet a été remis à zéro : 30 configs de développement supprimées, et les
76 runs, 31 sessions et 61 Go de résultats effacés. Ce qui reste est le montage
de référence, rien d'autre.

**Rien n'est calibré sur la géométrie corrigée.** La cote de lit SFR était lue
sur le MNT burné jusqu'au 6 septembre ; elle vient désormais du MNT du toit,
et le lit remonte de 3,755 m en médiane. Toutes les sessions précédentes
datent d'avant. Le premier travail à refaire est donc le calage lui-même.
Le détail du correctif et de ses mesures est dans `CORRECTION_LIT_SFR.md`, à
la racine du dépôt.

Trois écarts connus avec la méthode publiée, à traiter ensuite :

- `r_optim` vaut 3,93 à 12,01 pour une borne de 2 dans le papier, et la config
  pose `on_roptim_violation = "warn"` : l'étage 1 rend un nombre hors de son
  domaine de validité ;
- le modèle tourne à **une couche**, le papier en utilise six ;
- la cible de densité de drainage est 2,1 fois plus lâche que celle du papier
  (0,705 contre 1,5 km⁻¹), parce que le linéaire est filtré au permanent.
