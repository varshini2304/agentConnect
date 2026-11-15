"""Validated, reviewable fields returned by document based agent drafting."""
from pydantic import Field

from app.schemas.network import StrictModel


class AgentDocumentDraft(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=2000)
    role: str = Field(min_length=1, max_length=200)
    domain: str = Field(min_length=1, max_length=120)
    purpose: str = Field(min_length=1, max_length=2000)
    responsibilities: list[str] = Field(default_factory=list, max_length=20)
    helps_with: list[str] = Field(default_factory=list, max_length=20)
    must_not_do: list[str] = Field(default_factory=list, max_length=20)
    expected_outcomes: list[str] = Field(default_factory=list, max_length=20)
    categories: list[str] = Field(default_factory=list, max_length=20)
    topics: list[str] = Field(default_factory=list, max_length=20)
    keywords: list[str] = Field(default_factory=list, max_length=30)
    discussion_topics: list[str] = Field(default_factory=list, max_length=20)
    knowledge_text: str = Field(min_length=1, max_length=102400)
