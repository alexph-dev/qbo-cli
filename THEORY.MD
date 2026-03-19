# Theory: Safe CLI Refactor With Remote Gate Verification

## Problem

`qbo_cli/cli.py` still carries the whole CLI surface, so small refactors can
silently change behavior in places where parser defaults, command glue, output
selection, and report sub-modes interact. The earlier refactor improved
structure, but the real acceptance bar is not local green alone. This repo also
has remote gates with different checks, so a change is not actually done until
the command contract and the CI/quality contract both hold.

## Operating Theory

The right way to stabilize this codebase is to keep changes at the seams and
verify the public contract aggressively. The refactor reduced duplication by
centralizing parser construction, runtime creation, dispatch, stdin handling,
report param building, and output emission. That increases maintainability, but
it also means one mismatch in format resolution can affect an entire command
surface. The leverage point is therefore not more extraction; it is making sure
every `gl-report` branch follows the same format-selection rules unless it has
an explicit reason not to, and making sure local verification matches the remote
gates that will judge the change.

## Strategy

Treat the work as successful only if both the CLI behavior and the remote gates
are demonstrably satisfied:

- review local commits and uncommitted fixes against `origin/main`
- verify parser behavior directly, not only through handler unit tests
- patch format-resolution gaps at the source, not in downstream renderers
- add tests that lock the contract in place for both command-level and parser-level flows
- validate with unit tests, live tests, Ruff format/lint, mypy, and then remote GitHub checks

The intent is still minimal movement. One root fix in the parser/output path is
better than special-casing downstream rendering.

## Key Discoveries

The first important discovery was that the initial remote failure was not a
failing runtime test. GitHub `Tests` passed. The real blockers were `ruff
format --check qbo_cli/` and SonarCloud's quality gate on new code. That
shifted the problem from "the feature is still broken" to "the feature works,
but the repo's remote acceptance rules were not fully matched locally."

The second discovery was that the original format bug had a sibling branch.
`gl-report` report rendering had been fixed to respect shared format
resolution, but `gl-report --list-accounts` still bypassed that contract and
always rendered text. That meant the right fix was to resolve format once at
the top of `cmd_gl_report()` and apply it consistently across both report and
account-listing modes.

The final shape is small and structural. `gl-report` now honors shared format
resolution across its main branches, `--list-accounts` supports `text` and
`json`, unsupported format combinations fail explicitly, `qbo_cli/cli.py`
matches Ruff formatting, and the new test assertions use `pytest.approx` so
SonarCloud no longer sees new float-equality bugs in the touched tests.

Verification stayed strong after the fixes. Full non-live `pytest`, full
`@pytest.mark.live` smoke tests, Ruff lint, Ruff format checks, and `mypy` all
passed locally.

## Open Questions

The main remaining uncertainty is still test depth around the most stateful
paths: `TokenManager`, OAuth callback handling, and the more exotic
`cmd_gl_report()` combinations outside the covered text/json flows. Future
extraction work should wait until those contracts are covered more directly,
otherwise readability gains will come with regression risk.
