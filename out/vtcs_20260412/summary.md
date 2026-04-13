# Simple Transient Cross-Solver Comparison

This report compares MODFLOW-NWT, MODFLOW 6, and Boussinesq on transient 1D analytical cases with minimal surface interaction.

## Linearized unconfined recharge step 1D

| Solver | Space-time RMSE [m] | Space-time max abs [m] | Final profile RMSE [m] | Final profile max abs [m] | Row spread [m] | Results dir |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| MODFLOW-NWT | 0.0061 | 0.0148 | 0.0048 | 0.0068 | 6.513e-06 | `C:\codes\HydroModPy-GH\out\vtcs_20260412\validation\validation_compar_b6d771bcc1\lu_recharge_step__372f174ac1_a1db34f5` |
| MODFLOW 6 | 0.0054 | 0.0120 | 0.0048 | 0.0068 | 1.017e-06 | `C:\codes\HydroModPy-GH\out\vtcs_20260412\validation\validation_compar_b6d771bcc1\lu_recharge_step_1d_modflow6_94672062` |
| Boussinesq | 0.0125 | 0.0156 | 0.0135 | 0.0155 | 4.015e-09 | `C:\codes\HydroModPy-GH\out\vtcs_20260412\validation\validation_compar_b6d771bcc1\lu_recharge_step__a908d17b20_8d39e57f` |

| Pair | Final profile RMSE [m] | Final profile max abs [m] | Monitor RMSE [m] | Monitor max abs [m] |
| --- | ---: | ---: | ---: | ---: |
| MODFLOW-NWT vs MODFLOW 6 | 0.0000 | 0.0000 | 0.0012 | 0.0035 |
| MODFLOW-NWT vs Boussinesq | 0.0182 | 0.0223 | 0.0218 | 0.0243 |
| MODFLOW 6 vs Boussinesq | 0.0181 | 0.0223 | 0.0212 | 0.0226 |

Figure: `C:\codes\HydroModPy-GH\out\vtcs_20260412\figures\lu_recharge_step_1d__transient.png`

## Linearized unconfined boundary step 1D

| Solver | Space-time RMSE [m] | Space-time max abs [m] | Final profile RMSE [m] | Final profile max abs [m] | Row spread [m] | Results dir |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| MODFLOW-NWT | 0.0018 | 0.0120 | 0.0001 | 0.0001 | 6.824e-06 | `C:\codes\HydroModPy-GH\out\vtcs_20260412\validation\validation_compar_b6d771bcc1\lu_boundary_step__b988715003_b5a7e8d5` |
| MODFLOW 6 | 0.0012 | 0.0116 | 0.0000 | 0.0001 | 1.593e-06 | `C:\codes\HydroModPy-GH\out\vtcs_20260412\validation\validation_compar_b6d771bcc1\lu_boundary_step_1d_modflow6_e2b79dd5` |
| Boussinesq | 0.0023 | 0.0167 | 0.0008 | 0.0014 | 4.754e-09 | `C:\codes\HydroModPy-GH\out\vtcs_20260412\validation\validation_compar_b6d771bcc1\lu_boundary_step__b20d12e0df_f1f2e742` |

| Pair | Final profile RMSE [m] | Final profile max abs [m] | Monitor RMSE [m] | Monitor max abs [m] |
| --- | ---: | ---: | ---: | ---: |
| MODFLOW-NWT vs MODFLOW 6 | 0.0000 | 0.0000 | 0.0010 | 0.0025 |
| MODFLOW-NWT vs Boussinesq | 0.0008 | 0.0014 | 0.0018 | 0.0048 |
| MODFLOW 6 vs Boussinesq | 0.0008 | 0.0014 | 0.0019 | 0.0058 |

Figure: `C:\codes\HydroModPy-GH\out\vtcs_20260412\figures\lu_boundary_step_1d__transient.png`

## Linearized unconfined recharge step deep 1D

| Solver | Space-time RMSE [m] | Space-time max abs [m] | Final profile RMSE [m] | Final profile max abs [m] | Row spread [m] | Results dir |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| MODFLOW-NWT | 0.0018 | 0.0103 | 0.0004 | 0.0006 | 1.035e-05 | `C:\codes\HydroModPy-GH\out\vtcs_20260412\validation\validation_compar_b6d771bcc1\lu_recharge_step__d42e326154_b4cb151b` |
| MODFLOW 6 | 0.0005 | 0.0030 | 0.0004 | 0.0006 | 1.521e-07 | `C:\codes\HydroModPy-GH\out\vtcs_20260412\validation\validation_compar_b6d771bcc1\lu_recharge_step__b3d788a943_a191bfee` |
| Boussinesq | 0.0014 | 0.0017 | 0.0014 | 0.0017 | 1.118e-09 | `C:\codes\HydroModPy-GH\out\vtcs_20260412\validation\validation_compar_b6d771bcc1\lu_recharge_step__448d48530b_c6b48a05` |

| Pair | Final profile RMSE [m] | Final profile max abs [m] | Monitor RMSE [m] | Monitor max abs [m] |
| --- | ---: | ---: | ---: | ---: |
| MODFLOW-NWT vs MODFLOW 6 | 0.0000 | 0.0000 | 0.0016 | 0.0073 |
| MODFLOW-NWT vs Boussinesq | 0.0018 | 0.0023 | 0.0034 | 0.0087 |
| MODFLOW 6 vs Boussinesq | 0.0018 | 0.0023 | 0.0023 | 0.0023 |

Figure: `C:\codes\HydroModPy-GH\out\vtcs_20260412\figures\lu_recharge_step_deep_1d__transient.png`
