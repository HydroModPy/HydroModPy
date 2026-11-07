# model/transport

The transport process.

## Modules

| module | answers |
|---|---|
| `transport.py` | The runtime `Transport` |
| `transport_config.py` | `TransportConfig`, the `[transport]` table, with one parameter block per engine |

`transport.py` copies the parameters of each engine from the config, in one loop over the four engines
(`modpath`, `mt3dms`, `modflow6gwt` and `modflow6prt`), and keeps the transport initial conditions.
