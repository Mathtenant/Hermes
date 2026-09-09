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

## The project document is the HTML, not the Markdown

`HERMES_Local_Assistant_COMPLETE.html` in the repository root **is** the
project document: specification, POC runbook and the delivered-release history,
in one self-contained file. Document a change there.

There is no Markdown master any more. `docs/MASTER.md` was deleted once its
content was superseded: it was easy to mistake for the live document — it was
called MASTER, it was Markdown, and its own closing line said "extend the
relevant Part above" — and that mistake had already been made once. Its
history is in git if you need it.

The HTML is a generated bundle with no generator in the repo, so it is edited
in place. Three things to know before doing that:

- Sections are `<h2 class="secthead" id="…">N &middot; Title</h2><div class="doc">…</div>`,
  with a matching `<a class="top" href="#…">` in the `<nav>`.
- The `<script type="application/json" id="manifest">` at the end is the source
  bundle behind the download buttons. It is a **POC-era snapshot** and still
  names files that no longer exist under those paths; that is history, not rot.
- It is a raw text element, so its payload is plain JSON — not HTML-escaped —
  and it must sit *before* the `<script>` that reads it. Both were wrong
  originally, which left every download button in the bundle inert.

After editing, open the file in a browser and check for page errors: nothing
else tests it.
