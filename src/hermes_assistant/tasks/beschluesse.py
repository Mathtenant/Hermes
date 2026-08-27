"""Beschluss model — decisions from a "Pendenzen- und Beschlussliste".

That document, standard in Swiss/German project practice, holds two different
kinds of row that must not be conflated:

* a **Beschluss** is a decision that has already been taken — past tense,
  settled, and identified by *when* and *by whom* it was decided;
* a **Pendenz** is an open action, often one that a Beschluss set in motion.

``Pendenz.source_ref`` has always been documented as "id of the review/
decision/meeting that raised it", so the link direction was anticipated here
long before anything populated it. A Beschluss is a ``Task`` with
``node_kind="decision"``, which keeps it in the same tree and the same store
as everything else rather than adding a parallel one.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from hermes_assistant.tasks.model import Task

# beschlossen — taken, not yet visibly implemented
# umgesetzt   — taken and carried out
# aufgehoben  — later reversed; kept because the trail matters
# vertagt     — deferred to a later session
BeschlussStatus = Literal["beschlossen", "umgesetzt", "aufgehoben", "vertagt"]


# A Beschluss keeps the inherited open/closed/blocked ``status`` and carries
# its own vocabulary alongside it. Overriding ``status`` outright is not an
# option: ``TaskStore._row_to_task`` validates every row as a plain ``Task``,
# so a stored "beschlossen" would raise on the next read of that row and take
# every list_all() with it.
_LIFECYCLE: dict[str, str] = {
    "beschlossen": "open",    # taken, not yet visibly carried out
    "umgesetzt": "closed",    # taken and carried out
    "aufgehoben": "closed",   # later reversed — kept, because the trail matters
    "vertagt": "open",        # deferred to a later session
}


class Beschluss(Task):
    """A decision node in the task tree (node_kind = "decision")."""

    node_kind: Literal["decision"] = "decision"

    # A decision without a date is not a decision, it is a proposal. The
    # importer rejects rows that lack this, which is what keeps "soll noch
    # entschieden werden" rows out of the decision list.
    decided_on: date | None = None
    decided_by: str | None = None      # deciding body or role, e.g. "Steuerungsausschuss"
    decision_status: BeschlussStatus = "beschlossen"
    rationale: str = ""                # why, in a sentence or two
    affects: str = ""                  # area or sub-project the decision bears on
    source_hint: str | None = None     # originating file name, never a path

    @staticmethod
    def lifecycle_for(decision_status: str) -> str:
        """Map a decision vocabulary value onto the shared task lifecycle."""
        return _LIFECYCLE.get(decision_status, "open")
