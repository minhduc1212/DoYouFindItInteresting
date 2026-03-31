"""
Pydantic schemas for request/response validation.
These define the exact JSON shape the frontend receives.
"""

from pydantic import BaseModel
from typing import Literal, Optional


class ContentSegment(BaseModel):
    """
    A single segment of article content.
    - type="text"  → plain text, render as-is.
    - type="term"  → highlighted word, render with tooltip trigger.
    """
    type: Literal["text", "term"]
    text: str
    term_id: Optional[int] = None
    definition: Optional[str] = None


class KnowledgeResponse(BaseModel):
    """Full response returned by /api/random-knowledge"""
    id: int
    title: str
    source_url: Optional[str]
    source_type: str
    segments: list[ContentSegment]
    term_count: int

    class Config:
        from_attributes = True