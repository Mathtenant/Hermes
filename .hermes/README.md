# .hermes/ — HERMES Runtime Configuration

This directory holds operator-level configuration files that customise
HERMES guardrail behaviour without touching source code.

## Files

### `pii_terms.txt`

A plain-text dictionary of terms that must never appear in a git commit.
The pre-commit hook (`scripts/hooks/pre-commit`) scans every staged diff
against this list and blocks the commit if any term is found
(case-insensitive).

**Format:**
- One term per line.
- Blank lines are ignored.
- Lines beginning with `#` are treated as comments.

**When to extend this list:**
Add customer names, project code names, internal system names, and any
other strings that would indicate confidential data is being committed.

## How the pre-commit hook uses this directory

```
.hermes/pii_terms.txt  →  read line-by-line  →  grep against staged diff
```

If a match is found the commit is aborted and the offending term is printed.

## Activating the hook

```bash
git config core.hooksPath scripts/hooks
```

This is a one-time command per working copy and takes effect immediately.
