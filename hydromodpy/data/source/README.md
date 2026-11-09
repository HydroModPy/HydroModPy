# `data/source`

This folder holds the `DataSource` port (`port.py`) and its registry
(`registry.py`). A source answers one question about one provider: what may it
be asked for, and what does it hand back. Every provider of this tree is a
class of the port, from BD Topage to Hub'Eau and SIM2, so one form covers all
of them. The port has no registry inside it and no cache: a source receives
its request and owns its `out_dir`, and asks nothing about the catalog, the
workspace, a lock or a run.

## The declaration

A source class declares `section` (the `[data.<section>]` it serves, one
only) and `source_id` (the word written in `source =`), both `ClassVar`. It
declares `payload_kind` (`points`, `fields`, `features` or `files`),
`extent_crs`, `selectors` (`extent`, `station_ids`, or an empty tuple),
`period_need` and `writes_out_dir` on the class. Two members belong to the
instance: `variables`, because a source configured one way may serve fewer
variables than the class can, and `hosts`, every host the source contacts. A
shipped source reads its hosts from `hydromodpy.schema.sources` through
`shipped_hosts` instead of writing them, so no host is named twice.

## The request and the result

A `FetchRequest` carries an `out_dir`, an `Extent` (a box and the CRS it is
expressed in), `station_ids`, a `Period` and `bounds`. A request with neither
an extent nor stations is accepted only from a source that declares
`selectors = ()`, and `require_selectors` enforces that: a content of plain
files has no extent to ask for. The helpers `extent_for`, `require_period` and
`require_declared_variables` read the request the way the source declared it.

The generic sources `file` and `url` both declare `payload_kind = "files"` and
`selectors = ()`, asking for no extent and no station. A `file` source reads
local files already on disk without caching, whereas an `url` source downloads
a remote file to fill the data cache, verified by a pinned sha256 or remote
headers and recorded in a sidecar.

A `FetchResult` carries the one payload its `kind` names: `points` and
`fields` records, `features` (one GeoDataFrame, the river networks), or
`files` as `FileRecord` entries: `path`, `sha256`, `state`, `nodata` and
`origin`, built by `FileRecord.of`, which hashes with
`schema.job.digest.sha256_file`. `state` is `"raw"` or `"conditioned"`, the
vocabulary of `schema/job/inputset.py`, or `None`. A files answer that cached
an empty file alongside (the sources that write one) declares `records = 0`,
and `is_empty` then answers that the provider held nothing. Points and fields
are written in the unit their record carries, and the SI is reached at the
entry of the Model, where `core/units` converts and refuses a unit it cannot
read. The port converts no value.

## The registry

`data_sources` keys a class on its section and its name:
`data_sources.get("hydrometry", "hubeau")`. The shipped classes are dotted
paths in `_BUILTIN_PATHS`, 26 today, imported on the first lookup. A
third-party source publishes an entry point named `<section>_<source_id>` on
the `hydromodpy.data.source` group; under the `installed` member of a data
request, a source resolves by its name, and a name two sections share is
refused with both. `names(section)` answers what one section accepts and the
config validates `source =` against it, so the list is written once.
`build_from_section(source_cls, section, **resolved)` binds the fields of a
section to the constructor of the class that section names.

A source is held to all of this by
`tests/contract/test_data_source_contract.py`, one `SourceCase` per shipped
source, with a real or recorded fetch.
