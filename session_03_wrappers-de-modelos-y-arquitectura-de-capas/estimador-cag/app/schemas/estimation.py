"""Request and response schemas for the estimate endpoint."""

from pydantic import BaseModel, field_validator


class EstimationRequest(BaseModel):
    """Request schema for the estimate endpoint."""

    transcription: str

    @field_validator("transcription")
    @classmethod
    def transcription_min_length(cls, v: str) -> str:
        if len(v) < 10:
            raise ValueError("transcription must have at least 10 characters")
        return v


class EstimationResponse(BaseModel):
    """Response schema for the estimate endpoint."""

    estimation: str
    model: str
    provider: str
