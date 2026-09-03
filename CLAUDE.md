# Working on HERMES

## Versioning — bump it, every time, without being asked

The dashboard shows the running version in its topbar chip. That chip exists to
answer one question: *am I looking at the build I just shipped?* A version that
never moves cannot answer it, and a stale one answers it wrongly.

**So: before any batch of work is merged, raise the version — unless the change
is purely cosmetic.** This is not a request that has to be made each time.

Cosmetic means the rendered result differs and nothing else does: wording,
spacing, colour, an icon, a comment, a docstring, a test that only got clearer.
Everything else — a new feature, a fixed bug, a changed route, an added field,
a migration, a dependency, anything that alters what the software *does* —
takes a bump.

Which component to raise:

| Change | Bump | Example |
|---|---|---|
| Features added, still backwards-compatible | minor (`0.2.0` → `0.3.0`) | delete with undo; model failover; merging two screens |
| Fixes and small corrections only | patch (`0.3.0` → `0.3.1`) | a wrong count; a broken link; a cache header |
| Breaking change to a stored schema, route, or CLI command | minor while pre-1.0; major after | renaming the `pendenz` node kind |

A patch release conventionally promises "backwards-compatible bug fixes only",
so shipping a feature batch as a patch tells the reader something untrue.

### How to bump

The number lives in exactly two files and they must agree:

- `src/hermes_assistant/__init__.py` — `__version__`, the single source the UI
  and `/api/health` read
- `pyproject.toml` — `[project] version`, for packaging

`tests/test_webapp_endpoints.py::test_version_matches_pyproject` fails loudly if
only one is edited. `setup.py` deliberately declares **no** version — it is a
package-discovery shim, and a third copy could drift unnoticed into wheel
metadata; `test_setup_py_declares_no_version` guards that absence.

Nothing else needs touching: the topbar chip reads `__version__` through
`/api/health`, and the served HTML stamps `?v=<version>` onto its asset URLs.

## Two things that bite, both learned the hard way

**Static assets go stale.** Starlette's `StaticFiles` sends `ETag` and
`Last-Modified` but no `Cache-Control`, so browsers fall back to *heuristic*
caching and can serve an old `app.js` for a long time without revalidating — a
shipped UI change simply does not appear, with no error to explain it. The
server now sends `Cache-Control: no-cache` on `/static/` and stamps asset URLs
with the version. If a change seems not to have landed, check that before
assuming the code is wrong.

**A browser test that skips is not a browser test that passed.** The e2e suite
skips silently unless a server is listening on `localhost:8000`, and needs
`pytest-playwright`, which is not in the `[dev]` extras. A run reporting
"skipped" is not green. Before pushing static-asset changes, also run
`node --check` over `webapp/static/*.js` — a syntax error there takes the whole
dashboard down and no Python test will notice.
