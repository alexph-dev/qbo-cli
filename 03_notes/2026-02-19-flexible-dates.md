# Session: Flexible Date Parsing + `-e` Shorthand

**Date:** 2026-02-19

## Changes

- Added `_parse_date()` helper — accepts `YYYY-MM-DD`, `DD.MM.YYYY`, `DD/MM/YYYY`
- Added `-e` shorthand for `--end` on `gl-report` subparser
- Applied `_parse_date()` to both `gl-report` and `report` date args
- Dropped `-s` shorthand for `--start` (conflicts with existing `--sort`)
