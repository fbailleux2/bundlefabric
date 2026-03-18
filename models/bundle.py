"""BundleFabric — Bundle models (Pydantic v2)"""
from __future__ import annotations
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


class BundleStatus(str, Enum):
    active = "active"
    stable = "stable"
    legacy = "legacy"
    archival = "archival"
    experimental = "experimental"


class TemporalScore(BaseModel):
    """Temporal Pertinence Score: measures bundle relevance over time."""
    status: BundleStatus = BundleStatus.active
    freshness_score: float = Field(..., ge=0.0, le=1.0,
                                   description="How fresh/current the bundle content is")
    usage_frequency: float = Field(0.5, ge=0.0, le=1.0,
                                   description="How often the bundle is used")
    ecosystem_alignment: float = Field(0.5, ge=0.0, le=1.0,
                                       description="Alignment with current ecosystem trends")
    last_updated: Optional[str] = None  # ISO date string
    usage_count: int = Field(0, ge=0, description="Cumulative execution count for this bundle")

    @property
    def tps_score(self) -> float:
        """TPS = freshness×0.4 + usage_frequency×0.3 + ecosystem_alignment×0.3"""
        return round(
            self.freshness_score * 0.4
            + self.usage_frequency * 0.3
            + self.ecosystem_alignment * 0.3,
            4
        )


class BundleManifest(BaseModel):
    """Core bundle definition — the portable cognitive program spec."""
    id: str = Field(..., min_length=1, description="Unique bundle identifier")
    version: str = Field(..., description="Semver version string e.g. 1.0.0")
    name: str = Field(..., min_length=1)
    description: str = ""
    capabilities: List[str] = Field(..., min_length=1,
                                    description="List of capabilities this bundle provides")
    domains: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    temporal: TemporalScore
    author: str = "unknown"
    license: str = "MIT"
    deerflow_workflow: Optional[str] = None
    rag_collection: Optional[str] = None

    @field_validator("version")
    @classmethod
    def validate_semver(cls, v: str) -> str:
        parts = v.split(".")
        if len(parts) < 2:
            raise ValueError(f"version must be semver format (e.g. 1.0.0), got: {v}")
        return v

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities_non_empty(cls, v: list) -> list:
        if not v:
            raise ValueError("capabilities must contain at least one item")
        return v

    def to_summary(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "tps_score": self.temporal.tps_score,
            "status": self.temporal.status.value,
            "capabilities": self.capabilities,
            "description": self.description,
            "usage_count": self.temporal.usage_count,
        }
