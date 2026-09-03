"""Typed views of the Copilot Retrieval and Chat payloads.

``extra="ignore"`` throughout, deliberately. These are preview APIs on
Microsoft's release cadence, not ours: a field appearing in a response should
not break a running dashboard, and a field disappearing should surface as a
missing optional rather than a validation error. What we depend on is named
here; everything else is allowed to drift.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# Documented service limits. Enforced client-side (see client.py) so a caller
# gets a precise error before a round trip, rather than a 400 after one.
MAX_QUERY_CHARS = 1500
MAX_RESULTS = 25

# The API takes one data source per call — there is no "search everything".
DATA_SOURCES = ("sharePoint", "oneDriveBusiness", "externalItem")


class SensitivityLabel(BaseModel):
    """The tenant's own classification of a hit.

    Carried through rather than dropped: a "Streng vertraulich" extract is
    exactly the thing a user needs to see labelled before pasting it anywhere,
    and the label is the tenant's judgement, not ours to discard.
    """

    model_config = ConfigDict(extra="ignore")

    sensitivity_label_id: str | None = Field(default=None, alias="sensitivityLabelId")
    display_name: str | None = Field(default=None, alias="displayName")
    tool_tip: str | None = Field(default=None, alias="toolTip")
    priority: int | None = None
    color: str | None = None


class RetrievalExtract(BaseModel):
    """One passage Microsoft chose out of a document."""

    model_config = ConfigDict(extra="ignore")

    text: str = ""
    relevance_score: float | None = Field(default=None, alias="relevanceScore")
    page_numbers: list[int] = Field(default_factory=list, alias="pageNumbers")


class RetrievalHit(BaseModel):
    """One document, plus the passages within it that matched."""

    model_config = ConfigDict(extra="ignore")

    web_url: str = Field(default="", alias="webUrl")
    extracts: list[RetrievalExtract] = Field(default_factory=list)
    resource_type: str | None = Field(default=None, alias="resourceType")
    resource_metadata: dict = Field(default_factory=dict, alias="resourceMetadata")
    sensitivity_label: SensitivityLabel | None = Field(
        default=None, alias="sensitivityLabel"
    )

    @property
    def title(self) -> str:
        """Best available human name for the hit.

        ``resourceMetadata`` only carries the fields that were *asked* for, so
        title can be legitimately absent; the file name from the URL beats
        showing an empty cell.
        """
        title = self.resource_metadata.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
        tail = self.web_url.rstrip("/").rsplit("/", 1)[-1]
        return tail or self.web_url or "(ohne Titel)"


class RetrievalResult(BaseModel):
    """A whole retrieval response."""

    model_config = ConfigDict(extra="ignore")

    retrieval_hits: list[RetrievalHit] = Field(
        default_factory=list, alias="retrievalHits"
    )

    @property
    def extract_count(self) -> int:
        return sum(len(h.extracts) for h in self.retrieval_hits)


class ChatAttribution(BaseModel):
    """Where Copilot says an answer came from.

    The reason the Chat API is usable for state capture at all: an unsourced
    summary of a project is not evidence, and these are what make a claim
    checkable against the document it came from.
    """

    model_config = ConfigDict(extra="ignore")

    attribution_type: str | None = Field(default=None, alias="attributionType")
    provider_display_name: str | None = Field(
        default=None, alias="providerDisplayName"
    )
    see_more_web_url: str | None = Field(default=None, alias="seeMoreWebUrl")


class ChatAnswer(BaseModel):
    """One assistant turn, flattened out of the conversation envelope."""

    model_config = ConfigDict(extra="ignore")

    conversation_id: str = ""
    text: str = ""
    attributions: list[ChatAttribution] = Field(default_factory=list)
    turn_count: int | None = None
