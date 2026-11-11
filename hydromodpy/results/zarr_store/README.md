# results/zarr_store

This folder answers how the arrays of one run are stored. The store is Zarr 3, one per run, in `fields.zarr/`.
It follows CF-1.11, ACDD-1.3 and UGRID-1.0 for its metadata. The class `SimulationZarr` is the door. It holds the
store, its root group and its write lock.

## How the work flows

1. `zarr_schema.py` opens the root group and writes the layout and the schema version (`initialise_root`).
2. A writer takes the store first and writes one thing. The writes of the mesh, the descent, the topography,
   the time, the CRS and the geographic raster are functions of `geometry_writer.py` (`write_mesh`, `write_time`,
   `write_crs` and so on), and the writes of fields and forcing are functions of `zarr_writer.py` (`write_field`,
   `write_forcing_timeseries`, and `write_array`, which both read).
3. `SimulationZarr` binds each function of the two writers and each function of `zarr_reader.py` as its methods.
   A signature is written once, in the module, and the method is the same function.
4. `chunks.py` picks balanced chunk sizes and, for large arrays, shard sizes. The constants are in `constants.py`.
5. `acdd.py` composes the root attributes, and `cf_validation.py` checks a standard name against the bundled CF list.
6. `zarr_finalizer.py` gives the lock address and consolidates the metadata when the writes are done.
7. A reader calls `read_field`, `read_time` and the other functions of `zarr_reader.py`. Nothing here opens the index.

## The folder map

```text
zarr_store/
├── simulation_zarr.py   SimulationZarr, the class that binds writer and reader functions
├── zarr_writer.py       the writes of fields and forcing, as functions of the store
├── geometry_writer.py   the writes of mesh, descent, topography, time, CRS and geographic raster
├── zarr_reader.py       every read, as a function of the store
├── zarr_schema.py       local store, root group, schema version, attributes
├── zarr_finalizer.py    write-lock path, metadata consolidation
├── mesh_layout.py       what the store keeps of the cell mesh and its line families
├── chunks.py            balanced chunks and shards
├── constants.py         chunk targets, codec, CF conventions, schema version
├── acdd.py              ACDD root attributes
├── cf_validation.py     CF standard names
└── data/                cf_standard_names_v85.txt
```

The table that maps a field name to its place in the store and to its CF metadata is `results/field_registry.py`.

## Where to add what

| To add | Where |
|--------|-------|
| a stored field | an entry in `results/field_registry.py`, then its write in `zarr_writer.py` |
| a read of a stored field | a function in `zarr_reader.py`, bound in `simulation_zarr.py` |
| a new write | a function in `zarr_writer.py`, or `geometry_writer.py` for the geometry, bound in `simulation_zarr.py` |
| a change of chunk or shard size | `chunks.py` and the targets in `constants.py` |
| a root attribute | `acdd.py` |
| something the mesh must keep | `mesh_layout.py` |
