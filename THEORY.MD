# Theory: Safe CLI Refactor With Format Contract Verification

## Problem

`qbo_cli/cli.py` still carries the whole CLI surface, so small refactors can
silently change behavior in places where parser defaults, command glue, and
output selection interact. The structural cleanup already improved the file, but
that kind of cleanup is only safe if the format contract stays consistent across
commands. `gl-report` was the highest-risk spot because it has custom output
modes and heavier orchestration than the basic CRUD/report commands.

## Operating Theory

The right way to stabilize this codebase is to keep changes at the seams and
verify the public contract aggressively. The refactor reduced duplication by
centralizing parser construction, runtime creation, dispatch, stdin handling,
report param building, and output emission. That increases maintainability, but
it also means one mismatch in format resolution can affect an entire command
surface. The leverage point is therefore not more extraction; it is making sure
every command follows the same format-selection rules unless it has an explicit
reason not to.

## Strategy

Treat the refactor as successful only if the CLI contract is demonstrably
preserved:

- review local commits and uncommitted fixes against `origin/main`
- verify parser behavior directly, not only through handler unit tests
- patch only the format-resolution gap at the source
- add tests that lock the contract in place for both command-level and parser-level flows
- validate with unit tests, live tests, and static checks that matter for the touched surface

The intent is still minimal movement. One root fix in the parser/output path is
better than special-casing downstream rendering.

## Key Discoveries

The critical discovery from review was not inside report generation itself but
at the CLI boundary: `gl-report` emitted JSON correctly when `args.output` was
set to `json`, but it did not actually honor the shared format contract. Global
`-f json` left `args.output` at `"text"`, and `gl-report --format json` was not
accepted at all. That meant the refactor had made the common `_resolve_fmt()`
path feel shared while `gl-report` still behaved like a special case.

The fix is small and structural. `gl-report` now resolves output through the
same format selector as other commands, accepts `--format` as an alias, and
fails explicitly for `tsv`, which remains unsupported for that command. The
tests now cover both direct handler behavior and parser wiring for `gl-report`,
which was the missing safety net.

Verification stayed strong after the fix. Full non-live `pytest`, full
`@pytest.mark.live` smoke tests, and `mypy` all passed. Ruff also passes for the
touched surface. Repo-wide Ruff failures still exist on `origin/main`, but they
are pre-existing test-file issues unrelated to this refactor.

## Open Questions

The main remaining uncertainty is still test depth around the most stateful
paths: `TokenManager`, OAuth callback handling, and the more exotic
`cmd_gl_report()` modes such as `txns`, `expanded`, and explicit unsupported
format cases. Future extraction work should wait until those contracts are
covered more directly, otherwise readability gains will come with regression
risk.
