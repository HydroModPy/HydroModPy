# Simple Validation Cross-Solver Comparison

This report compares MODFLOW-NWT, MODFLOW 6, and Boussinesq on simple analytical cases with minimal surface interaction.

## Dupuit fixed-head 1D

| Solver | RMSE vs analytical [m] | Max abs error [m] | Cross-row spread [m] | Results dir |
| --- | ---: | ---: | ---: | --- |
| MODFLOW-NWT | 0.0054 | 0.0077 | 4.672e-07 | `C:\codes\HydroModPy-GH\out\vscs_20260412\validation\validation_compar_00a0d08034\dupuit_fixed_head_cb0dd6cf67` |
| MODFLOW 6 | 0.0001 | 0.0001 | 3.969e-06 | `C:\codes\HydroModPy-GH\out\vscs_20260412\validation\validation_compar_00a0d08034\dupuit_fixed_head_ec0532fa37` |
| Boussinesq | 0.0430 | 0.0994 | 2.089e-08 | `C:\codes\HydroModPy-GH\out\vscs_20260412\validation\validation_compar_00a0d08034\dupuit_fixed_head_305dd88560` |

| Pair | Pairwise RMSE [m] | Pairwise max abs error [m] | Pairwise mean abs error [m] |
| --- | ---: | ---: | ---: |
| MODFLOW-NWT vs MODFLOW 6 | 0.0054 | 0.0078 | 0.0048 |
| MODFLOW-NWT vs Boussinesq | 0.0449 | 0.0994 | 0.0370 |
| MODFLOW 6 vs Boussinesq | 0.0429 | 0.0994 | 0.0354 |

Figure: `C:\codes\HydroModPy-GH\out\vscs_20260412\figures\dupuit_fixed_head_1d__profiles.png`

## Dupuit uniform recharge 1D

| Solver | RMSE vs analytical [m] | Max abs error [m] | Cross-row spread [m] | Results dir |
| --- | ---: | ---: | ---: | --- |
| MODFLOW-NWT | 0.0476 | 0.0632 | 2.336e-07 | `C:\codes\HydroModPy-GH\out\vscs_20260412\validation\validation_compar_00a0d08034\dupuit_uniform_re_dbb1539744` |
| MODFLOW 6 | 0.0406 | 0.0547 | 1.743e-06 | `C:\codes\HydroModPy-GH\out\vscs_20260412\validation\validation_compar_00a0d08034\dupuit_uniform_re_7c5e734951` |
| Boussinesq | 0.0340 | 0.0735 | 2.056e-10 | `C:\codes\HydroModPy-GH\out\vscs_20260412\validation\validation_compar_00a0d08034\dupuit_uniform_re_b78dcda21d` |

| Pair | Pairwise RMSE [m] | Pairwise max abs error [m] | Pairwise mean abs error [m] |
| --- | ---: | ---: | ---: |
| MODFLOW-NWT vs MODFLOW 6 | 0.0070 | 0.0085 | 0.0066 |
| MODFLOW-NWT vs Boussinesq | 0.0702 | 0.0735 | 0.0702 |
| MODFLOW 6 vs Boussinesq | 0.0637 | 0.0735 | 0.0636 |

Figure: `C:\codes\HydroModPy-GH\out\vscs_20260412\figures\dupuit_uniform_recharge_1d__profiles.png`

## Boussinesq fixed-head piecewise-K 1D

| Solver | RMSE vs analytical [m] | Max abs error [m] | Cross-row spread [m] | Results dir |
| --- | ---: | ---: | ---: | --- |
| MODFLOW-NWT | 0.0107 | 0.0231 | 3.815e-07 | `C:\codes\HydroModPy-GH\out\vscs_20260412\validation\validation_compar_00a0d08034\boussinesq_fixed__fbbaa3520c` |
| MODFLOW 6 | 0.0082 | 0.0190 | 2.379e-06 | `C:\codes\HydroModPy-GH\out\vscs_20260412\validation\validation_compar_00a0d08034\boussinesq_fixed__f333091e42` |
| Boussinesq | 0.0289 | 0.0714 | 5.222e-02 | `C:\codes\HydroModPy-GH\out\vscs_20260412\validation\validation_compar_00a0d08034\boussinesq_fixed__703c935c81` |

| Pair | Pairwise RMSE [m] | Pairwise max abs error [m] | Pairwise mean abs error [m] |
| --- | ---: | ---: | ---: |
| MODFLOW-NWT vs MODFLOW 6 | 0.0035 | 0.0059 | 0.0029 |
| MODFLOW-NWT vs Boussinesq | 0.0318 | 0.0714 | 0.0254 |
| MODFLOW 6 vs Boussinesq | 0.0307 | 0.0714 | 0.0243 |

Figure: `C:\codes\HydroModPy-GH\out\vscs_20260412\figures\boussinesq_fixed_head_piecewise_k_1d__profiles.png`
