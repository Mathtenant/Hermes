"""Deterministic scheduling and ICS export for HERMES project plans (Phase 3.5).

Derives dated milestone/task schedules from a ``ProjectPlan`` using a pure-Python
topological sort + working-day arithmetic (Zürich calendar by default); exports
the result as RFC-5545 ``.ics`` files for import into Outlook or any calendar app.

No LLM is involved — all date math is deterministic and fully testable offline.
"""
