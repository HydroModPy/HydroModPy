# MODFLOW Discretization Contract (`TemporalDiscretizationResult`, `SpatialDiscretizationResult`)

This note defines the contract used by HydroModPy before creating the MODFLOW-NWT DIS package.

## Scope

The contract is implemented in:

- `hydromodpy/solver/modflow_nwt/modflow/discretization.py`

It covers two typed payloads:

1. `TemporalDiscretizationResult`
2. `SpatialDiscretizationResult`

## Temporal Contract

`TemporalDiscretizationResult` fields:

1. `itmuni` (`int`): MODFLOW time-unit code forwarded to DIS.
2. `nper` (`int`): number of stress periods (`> 0`).
3. `perlen` (`np.ndarray`, 1D float): period lengths in `itmuni` units.
4. `nstp` (`np.ndarray`, 1D int): number of time steps per period.
5. `steady` (`np.ndarray`, 1D bool): steady/transient flags per period.
6. `start_datetime` (`object | None`): optional absolute start datetime metadata.

Required consistency:

1. `nper == perlen.size`
2. `nstp.size == nper`
3. `steady.size == nper`
4. `nper > 0`

Conversion to FLOPY DIS kwargs is centralized in:

- `TemporalDiscretizationResult.as_dis_kwargs()`

Returned keys:

- `itmuni`, `nper`, `perlen`, `nstp`, `steady`, `start_datetime`

## Spatial Contract

`SpatialDiscretizationResult` fields:

1. `sgrid`: structured grid object returned by `StructuredGridBuilder`.
2. `dem` (`np.ndarray`, 2D float): validated top support.
3. `nlay` (`int`): number of layers.
4. `nrow` (`int`): number of rows.
5. `ncol` (`int`): number of columns.
6. `zbot` (`np.ndarray`, 3D float): full bottom elevations with shape `(nlay, nrow, ncol)`.
7. `bottom_layer` (`np.ndarray`, 2D float): `zbot[-1]`, deepest-layer bottom.

Required consistency:

1. `zbot.shape == (nlay, nrow, ncol)`
2. `bottom_layer.shape == (nrow, ncol)`
3. domain `surface_topo` and `substratum` exist, are `Surface`, and match DEM shape

## Upstream Inputs

Temporal builder uses:

- `tgrid_config.to_builder_kwargs()`
- `flow_regime`
- `default_itmuni`

Spatial builder uses:

- runtime `domain` with `surface_topo` and `substratum`
- active DEM shape
- `vertical_config`

## Why this contract exists

1. Keep DIS payload assembly explicit and testable.
2. Prevent shape/unit drift between runtime objects and solver setup.
3. Avoid scattering DIS argument conventions across orchestration code.

## Related Notes

- `docs/developers/modflow_bas_contract.md` (BAS contract for `ibound`/`strt`)
