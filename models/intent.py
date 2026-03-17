"""BundleFabric — Intent and execution models (Pydantic v2)"""
from __future__ import annotations
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class Intent(BaseModel):
    """Structured representation of a human intention."""
    raw_text: str = Field(..., min_length=1, description="Original human text")
    goal: str = Field(..., min_length=1, description="Extracted goal/objective")
    domains: List[str] = Field(default_factory=list,
                               description="Relevant domains (linux, gtm, devops, ...)")
    keywords: List[str] = Field(default_factory=list)
    complexity: str = Field("medium", description="simple / medium / complex")
    extraction_method: str = Field("keyword",
                                   description="keyword | ollama — how intent was extracted")
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BundleMatch(BaseModel):
    """A bundle matched to an intent with scoring."""
    bundle_id: str
    bundle_name: str = ""
    score: float = Field(..., ge=0.0, le=1.0,
                         description="Composite relevance score")
    tps_score: float = Field(0.0, ge=0.0, le=1.0)
    keyword_overlap: float = Field(0.0, ge=0.0, le=1.0)
    recency_score: float = Field(0.5, ge=0.0, le=1.0)
    matched_keywords: List[str] = Field(default_factory=list)
    explanation: str = ""


class ExecutionResult(BaseModel):
    """Result of executing a bundle via DeerFlow."""
    status: str = Field(..., description="success | error | pending | timeout")
    bundle_id: str
    intent_goal: str = ""
    output: str = ""
    deerflow_thread_id: Optional[str] = None
    deerflow_run_id: Optional[str] = None
    execution_time_ms: Optional[int] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
