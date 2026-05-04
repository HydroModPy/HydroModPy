# Comparison Audit: pass

- Reference simulation: `modflow6`
- Mode: `strict_same_case`
- Issues: 0
- Physical config sections: 13

## Issues
- No equivalence issue detected.

## Physical Config Checks
- No physical config section mismatch detected.

## Recharge Budget Checks
- `modflownwt` / `recharge_total_m3_s`: status=`pass`, pairs=40, max_abs_diff=0.0, max_abs_rel_diff=0.0

## Initial-State Policy
- No mixed initial-state policy was detected.

## Head Bounds
- No head/top-bottom diagnostic was produced.

## Head-Recharge Response
- `modflow6` / `head_east_response`: head_range_m=0.00745826725699672, corr_delta_recharge_delta_head=None, same_sign_delta_fraction=None
- `modflow6` / `head_mid_response`: head_range_m=0.04000062140961447, corr_delta_recharge_delta_head=None, same_sign_delta_fraction=None
- `modflow6` / `head_west_response`: head_range_m=0.027881448319027058, corr_delta_recharge_delta_head=None, same_sign_delta_fraction=None
- `modflownwt` / `head_east_response`: head_range_m=0.00745826725699672, corr_delta_recharge_delta_head=None, same_sign_delta_fraction=None
- `modflownwt` / `head_mid_response`: head_range_m=0.04000062140961447, corr_delta_recharge_delta_head=None, same_sign_delta_fraction=None
- `modflownwt` / `head_west_response`: head_range_m=0.027881448319027058, corr_delta_recharge_delta_head=None, same_sign_delta_fraction=None
