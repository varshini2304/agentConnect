"""Structured, validated model decisions."""
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AgentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    should_respond: bool
    reason: str = Field(min_length=5, max_length=300)
    comment: str | None = Field(default=None, max_length=400)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0, description="Model self-assessment, not a calibrated probability.")

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str | None) -> str | None:
        return None if value is None else " ".join(value.split())

    @model_validator(mode="after")
    def skipped_decisions_cannot_include_comment(self):
        if not self.should_respond and self.comment:
            raise ValueError("comment must be null or empty when should_respond is false")
        return self
