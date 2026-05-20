# Golden tests

This directory hosts golden fixtures (frozen artefacts) and their smoke
harness. It complements `tests/regression/golden_utils.py`, which builds
statistical signatures: here we compare exact bytes or normalized DOM.

## Layout

| Subdir    | Content                                  | Helper                          |
|-----------|------------------------------------------|---------------------------------|
| `parquet/`| Parquet tables                           | `assert_parquet_equal` (SHA256) |
| `json/`   | Canonical JSON for DuckDB / dict outputs | `assert_duckdb_query_equal`     |
| `html/`   | HTML reports                             | `assert_html_dom_equal` (lxml)  |
| `zarr/`   | Zarr stores (directory trees)            | `assert_zarr_array_equal`       |

All helpers live in `tests/_helpers/golden.py`. Each golden test must:

1. produce an `actual` artefact (Parquet file, dict, HTML string, Zarr dir),
2. call the matching `assert_X_equal(actual, golden_path)` from
   `tests/_helpers/golden.py`,
3. carry the `@pytest.mark.golden` marker.

## Regeneration

When a golden needs to be refreshed (legitimate output change):

```bash
HMP_REGENERATE_GOLDEN=1 pytest -m golden
```

The helper overwrites the golden then **fails the test on purpose** so the
diff goes through manual review before the new fixture is committed.

Never bypass this: regenerate, review `git diff tests/golden/`, then commit
the fixture together with the code change that justified it.

## Large fixtures and LFS

Fixtures larger than ~1 MB should land in Git LFS. The repository already
ships `.gitattributes`. Extend it with explicit patterns before adding heavy
fixtures, for example:

```
tests/golden/parquet/**/*.parquet filter=lfs diff=lfs merge=lfs -text
tests/golden/zarr/** filter=lfs diff=lfs merge=lfs -text
```

LFS is not enabled in this pass: keep demo fixtures small and binary-stable.

## Tolerance policy

Byte-equal comparisons (`assert_parquet_equal`, `assert_zarr_array_equal`)
have no tolerance: they fail on any change, including writer-version bumps.
Use the data-level helpers (`assert_parquet_data_equal`, statistical
signatures in `tests/regression/golden_utils.py`) when floating-point
jitter is expected. Numerical tolerances are documented in
`tests/TOLERANCES.md`.
