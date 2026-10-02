"""API-safe models for the manufacturing intelligence composition layer."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from pydantic import BaseModel, Field


class IntelligenceSubsystem(BaseModel):
    """One independently probed runtime capability."""

    name: str
    status: str
    capabilities: List[str] = Field(default_factory=list)
    details: Dict[str, Any] = Field(default_factory=dict)


class IntelligenceSignal(BaseModel):
    """A deterministic, evidence-backed operational signal."""

    code: str
    severity: str
    message: str
    action: str
    evidence: Dict[str, Any] = Field(default_factory=dict)


class IntelligenceOverview(BaseModel):
    factory_id: str
    status: str
    generated_at: datetime
    subsystems: List[IntelligenceSubsystem] = Field(default_factory=list)
    signals: List[IntelligenceSignal] = Field(default_factory=list)


class IntelligenceHealth(BaseModel):
    factory_id: str
    status: str
    checked_at: datetime
    subsystems: List[IntelligenceSubsystem] = Field(default_factory=list)
