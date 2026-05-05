Évolution du schéma
===================

Statut : prospectif. Ce document décrit les principes d'évolution du
schéma de stockage HydroModPy à appliquer aux futures migrations. Le
versioning n'est pas encore implémenté dans le codebase ; les principes
ci-dessous s'appliqueront dès que les premières migrations seront
introduites.

Liens :
:doc:`simulation_catalog_architecture <storage>`,
:doc:`parquet_lakehouse_architecture <storage>`.

Portée
------

Le périmètre couvert :

- Fichiers DuckDB : ``hydromodpy.duckdb`` (catalogue workspace) et
  ``data/cache.duckdb`` (cache d'entrée).
- Stores Zarr : ``simulations/<basename>.zarr/`` ou ``.zarr.zip``, avec fallback
  legacy sur ``sim_id`` quand ``simulations.storage_basename`` est absent.
- Packages ``.hmp`` portables produits par
  ``SimulationCatalog.export_package``.

Hors périmètre : les TOML utilisateur, dont le versioning est assuré
côté Pydantic via ``ConfigDict(extra="forbid")``.

Principes
---------

1. **Un seul champ de version.** Chaque DuckDB porte une table
   ``_schema_version`` avec une ligne unique
   ``(version INTEGER, applied_at TIMESTAMP, notes TEXT)``. Les Zarr
   portent la même information dans leur ``.zattrs`` racine sous la clé
   ``hmp_schema_version``. La bibliothèque détient la version courante
   comme constante de module.

2. **Migrations additives d'abord.** Privilégier
   ``ALTER TABLE ... ADD COLUMN`` avec valeur par défaut plutôt que des
   suppressions ou renommages. Les champs spatiaux Zarr ne font que
   grandir (nouveaux datasets) ; ceux existants conservent leur shape
   et leur dtype.

3. **Numérotation monotone.** Les versions sont des entiers incrémentés
   de un par migration. Pas de saut. Les rétrogradations ne sont pas
   supportées ; une migration est une porte à sens unique.

4. **Organisation des modules.** Chaque migration vit dans
   ``hydromodpy/results/migrations/v{n:03d}_{slug}.py`` et expose une
   fonction ``apply(connection_or_store)``. La docstring du module
   explique la motivation et la nature du changement. Le registre
   ``hydromodpy/results/migrations/__init__.py`` mappe version à module.

5. **Tests round-trip obligatoires.** Pour chaque migration
   ``v(n) -> v(n+1)``, un test
   ``tests/unit/results/migrations/test_v{n:03d}.py`` doit couvrir :

   - une fixture minimale ``v(n)`` créée à la main (pas via le writer
     courant qui ne connaît que la dernière version) ;
   - l'application de la migration produit un store ``v(n+1)`` lisible
     par le reader courant ;
   - la migration est **idempotente** : l'appliquer deux fois est un
     no-op.

6. **Changement brisant du reader.** Toute modification de shape, dtype,
   ordre de colonnes ou sémantique d'un champ existant déclenche une
   incrémentation de version et une migration. Les refactorings internes
   purs (renommages sans impact disque) n'incrémentent pas.

7. **Frontière export/import.** Les packages ``.hmp`` embarquent la
   version dans leur manifest. L'import refuse les packages plus récents
   que la bibliothèque courante et migre silencieusement les plus
   anciens via le registre.

Anti-patterns
-------------

- **Ne pas** accepter silencieusement des tables ou colonnes inconnues.
  Le reader refuse les stores dont la version dépasse le maximum connu.
- **Ne pas** injecter de données depuis l'extérieur de la migration. La
  fonction opère uniquement sur le store qui lui est passé.
- **Ne pas** coupler les numéros de version DuckDB et Zarr. Chacun évolue
  indépendamment avec son propre ``_schema_version``.

Plan d'introduction
-------------------

- Introduction du champ ``_schema_version`` simultanée sur DuckDB et Zarr
  au moment de la première migration effective.
- Puis alimentation continue du registre ``migrations/`` au fil des
  évolutions de schéma.
