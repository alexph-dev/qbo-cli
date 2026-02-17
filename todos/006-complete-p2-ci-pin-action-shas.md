---
status: pending
priority: p2
issue_id: "006"
tags: [code-review, security, ci]
dependencies: []
---

# CI workflow actions pinned to mutable tags, not SHAs

## Problem Statement

GitHub Actions in `lint.yml` and `publish.yml` use mutable tags (`@v4`, `@v5`, `@release/v1`). A compromised upstream action could inject code into the build/publish pipeline. Especially sensitive for `publish.yml` which has `id-token: write` for trusted PyPI publishing.

## Findings

- **Source:** security-sentinel agent
- **Location:** `.github/workflows/publish.yml`, `.github/workflows/lint.yml`

## Proposed Solutions

### Option A: Pin to commit SHAs with tag comments
```yaml
- uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683  # v4
- uses: actions/setup-python@0b93645e9fea7318ecaed2b359559ac225c90a2b  # v5
```
- **Effort:** Small (look up current SHAs, update 3 lines per file)
- **Risk:** None — SHAs are immutable

## Acceptance Criteria

- [ ] All `uses:` entries in both workflow files pinned to full commit SHAs
- [ ] Tag version kept as inline comment for readability

## Work Log

- 2026-02-17: Identified during code review
