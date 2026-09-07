from typing import Any, Optional

from pydantic import BaseModel, Field


class MasterSourceIngestRequest(BaseModel):
    sourceFileName: str = Field(min_length=1, max_length=255)
    sourceFormat: str = Field(min_length=1, max_length=16)
    sourceFileHash: Optional[str] = None
    sourceTextHash: Optional[str] = None
    rawText: str = Field(min_length=1, max_length=250_000)


class MasterChunkExtraction(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
