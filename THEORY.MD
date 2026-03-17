# Theory: Safe Internal Refactor for qbo-cli

## Problem

`qbo_cli/cli.py` is still the center of the application, but before this pass it
mixed parser construction, command dispatch, repeated command glue, and output
normalization in ways that made small changes noisier than necessary. The risk
was not a broken CLI; the risk was that future edits would keep paying a
complexity tax in the least interesting parts of the file.

## Operating Theory

The project is safest to improve at its seams. Unit tests already protect the
public behavior of common command handlers, parser aliases, output formatting,
client pagination/retry behavior, and many pure report helpers. The less-tested
surfaces are OAuth callback handling, token persistence internals, and the
orchestration-heavy parts of `cmd_gl_report()`. That makes the correct lever a
local refactor of parser/dispatch and command plumbing, not a large module
split.

## Strategy

Keep behavior stable while reducing repetition:

- shrink `main()` into orchestration only
- move parser building and dispatch decisions into dedicated helpers
- centralize repeated command concerns: client creation, output emission, stdin
  JSON loading, report param building
- centralize output normalization shared by text and TSV rendering
- document the logical architecture so the file can stay understandable even
  before a future module split

The aim is structural clarity with minimal movement of risky code.

## Key Discoveries

The earlier readonly pass was useful because it separated environment gaps from
real quality issues. Once the local toolchain was installed, the important fact
was that `pytest` was already green, `ruff` problems were isolated to tests,
and `mypy` failures in `qbo_cli/cli.py` were small enough to eliminate as part
of the refactor. That turned the work from "safe cleanup only" into "safe
cleanup plus static-check hardening" without widening the risk surface.

The current shape now matches the intended strategy: `main()` delegates to
`_build_parser()`, `_build_runtime()`, and `_dispatch_command()`, command
handlers share helper glue, and output normalization is centralized. The code
is still a single-file CLI, but with cleaner internal boundaries.

## Open Questions

The next meaningful architectural step is still blocked on test depth, not on
mechanical extraction work. Before splitting `cli.py` into separate modules, the
project should add stronger tests around `TokenManager`, OAuth callback state
handling, and `cmd_gl_report()` output modes. Without that, larger movement
would trade readability gains for regression risk.
