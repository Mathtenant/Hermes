"""Microsoft 365 Copilot API client — proof of concept.

HERMES is otherwise fully local: no Graph access, no credentials, nothing
leaves the machine (spec §Calendar, "Why ICS, not Graph/Outlook API"). This
package is the one deliberate exception, and it stays **off by default**.
Nothing here runs unless ``m365_enabled`` is set and a user signs in.

Two APIs, with different jobs:

``retrieval``
    Send a natural-language query, get back permission-trimmed text extracts
    from SharePoint / OneDrive. Microsoft does the chunking and the ranking,
    so this replaces the plan to download files through Graph and parse them
    locally — no vector index of our own, and no copy of tenant content on
    disk unless we choose to keep one.

``chat``
    Multi-turn conversation with Copilot, grounded in tenant content and
    trimmed to the signed-in user's permissions. Text answers only: no file
    creation, no mail, no code interpreter, no long-running tasks. That makes
    it right for *state capture* — running the export prompts without
    copy-paste — and still wrong for document generation, which stays in the
    interactive Copilot UI.
"""

from hermes_assistant.m365.client import CopilotClient
from hermes_assistant.m365.models import (
    ChatAnswer,
    ChatAttribution,
    RetrievalExtract,
    RetrievalHit,
    RetrievalResult,
)

__all__ = [
    "ChatAnswer",
    "ChatAttribution",
    "CopilotClient",
    "RetrievalExtract",
    "RetrievalHit",
    "RetrievalResult",
]
