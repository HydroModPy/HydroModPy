# physics/transport

The transport process.

## Modules

1. `transport_config.py` is `TransportConfig`, the `[transport]` table, with one parameter block per engine: `modpath`, `mt3dms`, `modflow6gwt` and `modflow6prt`.
2. `transport.py` is the runtime `Transport`. It copies the parameters of each engine from the config, in one loop over the four engines, and keeps the transport initial conditions.
