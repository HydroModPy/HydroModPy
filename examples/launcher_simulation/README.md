# `launcher_simulation` configs

- `config_extensive.toml` is the canonical default launcher config for example12.
  It is the git-tracked rename of the former `config_standard.toml`, with the
  same long-run NWT/MT3DMS baseline behavior. The launcher default and the
  extensive regression test both target this file.
- `config_normal_nwt.toml` is the reduced NWT/MT3DMS variant kept for shorter
  manual runs and solver-family comparisons against the historical baseline.
- `config_normal_6.toml` is the reduced normal-tier regression config for the
  MODFLOW 6 / GWT stack. It is intentionally minimal, and the fast normal
  regression test targets this file.
- `config_standard.toml` is intentionally removed. Update external scripts to
  `config_extensive.toml` instead of keeping a silent alias.
