# Legacy Remaining

Après le nettoyage v0.6 et les passes de suivi, la base de code ne porte
plus de shim mort ni d'alias redondant. Trois éléments subsistent de
façon légitime et sont documentés ici pour que les futurs contributeurs
sachent pourquoi.

## 1. Façade `CatchmentDelineation`

Objet runtime public exposé sous `hydromodpy.spatial.geographic.CatchmentDelineation`.

**Conservé parce que :**
- C'est l'API publique canonique : les utilisateurs appellent
  `from hydromodpy.spatial.geographic import CatchmentDelineation` puis
  `CatchmentDelineation(config, workspace)`.
- Les internes ont été migrés vers la disposition v0.6 : la classe délègue
  désormais à `build_geographic_runtime_context()` et hydrate ses attributs
  via `runtime_attributes()` (plus aucun symbole `legacy_*`).
- Retirer la façade casserait chaque script utilisateur en aval et chaque
  exemple.

**Statut :** c'est le design actuel, pas un shim.

## 2. `DataStore.workspace_root`

Paramètre constructeur de `hydromodpy.data.DataStore(workspace_root=...)`.

**Conservé parce que :**
- C'est un argument nommé public documenté dans toute la couche data.
- Renommer en `root` n'apporte aucune amélioration sémantique et casse
  chaque utilisateur de la façade data.
- L'attribut est descriptif (il *est* la racine du workspace que le store
  utilise pour le cache data partagé et les dossiers par variable) et
  distinct de `WorkspaceConfig.root` côté simulation.

**Statut :** API publique légitime, conservée telle quelle.

## 3. Docstrings « Ported from legacy X »

Docstrings de traçabilité dans :

- `hydromodpy/calibration/adapters/da_mh_gp_adapter.py`
- `hydromodpy/calibration/adapters/gp_mapping_adapter.py`
- `hydromodpy/calibration/cases/__init__.py`
- `hydromodpy/calibration/cases/recession_brutsaert.py`

**Conservées parce que :**
- Elles documentent l'origine scientifique de chaque algorithme porté
  (quelle implémentation de référence le comportement numérique reproduit,
  quel papier ou module legacy le code réplique).
- Critiques pour la reproductibilité : quand un golden de validation
  diverge, la première question est « qu'est-ce que la version pré-port
  faisait exactement ? », et les docstrings répondent.
- Elles sont descriptives, pas actionnables : pas de shim, pas d'alias,
  pas d'import mort.

**Statut :** documentation de provenance scientifique, conservée telle quelle.

## 4. Compatibilite `[method_comparison]`

Ancienne interface TOML de comparaison, conservee pendant la migration vers
l'interface canonique `[comparison]`.

**Conserve parce que :**
- Des pages de galerie historiques pointent encore explicitement vers
  `[method_comparison]` et vers des artefacts `examples_legacy_2/...`.
- L'interface `[comparison]` reprend progressivement ses capacites, notamment
  la reutilisation de dossiers de resultats existants via `run_folder`.
- Les classes internes canoniques portent maintenant des noms neutres
  (`ComparisonConfig`, `ComparisonVariant`, `ComparisonObservable`, etc.).
  Les noms `MethodComparison*` restent seulement comme imports de
  compatibilite.
- Le cas de validation boundary-step expose maintenant un point d'entree
  canonique `run_comparison.py`; `run_method_comparison.py` n'est plus qu'un
  relais de compatibilite.

**Statut :** compatibilite transitoire. Le batch/regional-lab sait utiliser
`launcher = "comparison"` et garde `launcher = "method-comparison"` pour les
anciennes recettes. A supprimer quand la galerie et les tests historiques auront
ete migres vers `[comparison]`.
