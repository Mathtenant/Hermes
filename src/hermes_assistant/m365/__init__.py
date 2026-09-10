"""Microsoft 365 Copilot API client — proof of concept.

HERMES is otherwise fully local: no Graph access, no credentials, nothing
leaves the machine (spec §Calendar, "Why ICS, not Graph/Outlook API"). This
package is the one deliberate exception, and it stays **off by default**.
Nothing here runs unless ``m365_enabled`` is set and a user signs in.

One API, and one direction.

``retrieve``
    Send a natural-language query, get back permission-trimmed text extracts
    from SharePoint / OneDrive. Microsoft does the chunking and the ranking,
    so this replaces the plan to download files through Graph and parse them
    locally — no vector index of our own, and no copy of tenant content on
    disk unless we choose to keep one.

The Chat API was implemented here and then **deliberately removed**. Pulling
content in is allowed; sending project data out is not, and a chat turn is a
push by construction — its whole purpose is to carry context outward. What
remains can ask a question and read an answer, and cannot be made to upload a
plan, a risk register or a meeting note. That is a property of the code now,
not a rule someone has to remember.

The query string is the one thing that still travels outward, and it is
irreducible: there is no way to pull anything without saying what you want.
Keep it a question, not a payload.
"""

from hermes_assistant.m365.client import CopilotClient
from hermes_assistant.m365.models import (
    RetrievalExtract,
    RetrievalHit,
    RetrievalResult,
)

__all__ = [
    "CopilotClient",
    "RetrievalExtract",
    "RetrievalHit",
    "RetrievalResult",
]
