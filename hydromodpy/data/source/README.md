# Data source port

A data source answers one question about one provider: what may it be asked for, and what does it hand back. Every provider of this tree is a class of the port, from BD Topage to Hub'Eau and SIM2, so one form covers all of them. The port has no cache: a source receives its request, owns its `out_dir`, and asks nothing about the catalog, the workspace, a lock or a run. `port.py` holds the Protocol and its value types, and `registry.py` holds `data_sources`.

## What a source receives

A `FetchRequest` carries an `out_dir`, an `Extent` (a box and its CRS), `station_ids`, a `Period` and `bounds`. A request with neither an extent nor stations is accepted only from a source that declares `selectors = ()`, and `require_selectors` holds that rule. `extent_for`, `require_period` and `require_declared_variables` read the request the way the source declared it.

## What a source returns

A `FetchResult` carries the one payload its `kind` names: `points` and `fields` records, `features` (one GeoDataFrame, the river networks), or `files` as `FileRecord` entries with `path`, `sha256`, `state` (`"raw"`, `"conditioned"` or `None`), `nodata` and `origin`. A files answer that cached an empty file declares `records = 0`, and `is_empty` then says the provider held nothing. Values stay in the unit their record carries, because `core/units` converts to SI at the entry of the `Model`. The port converts no value.

## What a source declares

On the class, `section` (the one `[data.<section>]` it serves) and `source_id` (the word written in `source =`), both `ClassVar`, then `payload_kind` (`points`, `fields`, `features` or `files`), `extent_crs`, `selectors` (`extent`, `station_ids`, or an empty tuple), `period_need`, `writes_out_dir` and the method `fetch`. On the instance, `variables`, because a source configured one way may serve fewer variables than its class, and `hosts`, every host it contacts. A shipped source reads its hosts from `hydromodpy.schema.sources` through `shipped_hosts`, so no host is named twice.

## How a source registers

`data_sources` keys a class on its section and its id, as in `data_sources.get("hydrometry", "hubeau")`. The shipped classes are dotted paths in `_BUILTIN_PATHS`, imported on first lookup. A third-party source publishes an entry point named `<section>_<source_id>` in the `hydromodpy.data.source` group, and the `installed` member of a data request resolves it by its id. `build_from_section` binds the fields of a section to the constructor of the class it names.

## What is refused

`names(section)` answers what one section accepts, and `check_registered_name` refuses any other `source =` with the names this installation serves and the entry-point group. An installed id that two sections share is refused with both keys, and an unknown key at lookup raises `DataRequestError`.

## What tests it

`tests/ports/test_data_source.py` runs on every source the registry serves, an installed one too, with a `SourceCase` for what reaches the provider.
