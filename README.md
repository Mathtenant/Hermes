# HERMES Local Assistant

A fully-local AI assistant that helps junior consultants operate at senior level under HERMES 2022 Swiss project management method.

- **Fully local:** Ollama-only, no cloud reasoning, no confidential data leaves the box
- **Structured:** Rubric-driven quality review, grammar-constrained JSON, explicit acceptance criteria
- **Hardware-aware:** Designed for i7-1265U + 64GB RAM (MoE models, Q4 quantization, async job queue)
- **Asynchronous:** Heavy passes run overnight via SQLite job queue

## Quick Start

```bash
bash scripts/bootstrap.sh        # Install deps, pull models
python -m hermes_assistant.cli --help   # See available commands
```

## Documentation

- **Full spec:** see `docs/HERMES_Local_Assistant_PROJECT.md`
- **Project structure & phase backlog:** §15–16 in the spec
- **Quality-review system (rubrics):** §4D–4J

## Building

Phases are in order (Phase 0 → Phase 5). Keep `ruff check`, `mypy src`, `pytest -q` green at each step.

```bash
# Phase 0: Skeleton & guardrails (in progress)
pytest -q          # mocked Ollama tests green
ruff check .       # lint clean
mypy src           # types clean
```

## Security

HERMES processes sensitive project data locally. Five guardrail layers
protect confidential information from leaking:

1. **External data directory** — runtime SQLite databases are stored in
   `~/.hermes/data/` (macOS/Linux) or `%LOCALAPPDATA%\hermes-data\`
   (Windows), not inside the repository. Override with `HERMES_DATA_DIR`.

2. **Pre-commit hook** — blocks `.db`, `.env`, `.log`, and files matching
   PII terms before a commit is written to history. Activate once with:
   ```bash
   git config core.hooksPath scripts/hooks
   ```

3. **PII terms dictionary** — add organisation-specific sensitive terms to
   `.hermes/pii_terms.txt` to extend the pre-commit check without code
   changes.

4. **API response validation** — every JSON endpoint is scanned for
   forbidden field names, filesystem paths, and email addresses before the
   response is delivered to the browser.

5. **HTTP security headers** — `Content-Security-Policy`, `X-Frame-Options`,
   and friends are applied to every server response.

See `docs/SECURITY.md` for the full security model.

## License

MIT
