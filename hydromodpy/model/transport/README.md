# model/transport

The configuration of the transport process. Its runtime objects are gone: a
transport solver receives the frozen `Model` of its flow, its own options and
the run slot through the adapter contract, and builds from them.

## Modules

| module | answers |
|---|---|
| `transport_config.py` | `TransportConfig`, the `[transport]` table of a run: one free table per transport solver, under its registry name, without a parameters level |

The solvers themselves live in the folders of the flow backends they follow,
and the runner reads the table of a run with `options_of(name)`. The file of a
2.0.0 project still reads, at the table paths it was written with.
