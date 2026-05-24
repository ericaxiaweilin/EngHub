"""
Shared models for the manufacturing intelligence core.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from pydantic import BaseModel, Field


class DecisionSurface(BaseModel):
    name: str
    role: str
    entrypoint: str
    capabilities: List[str] = Field(default_factory=list)


class IntelligenceSubsystem(BaseModel):
    name: str
    role: str
    module: str
    status: str
    capabilities: List[str] = Field(default_factory=list)
    details: Dict[str, Any] = Field(default_factory=dict)


class IntelligenceOverview(BaseModel):
    system_name: str
    system_type: str
    focus: List[str] = Field(default_factory=list)
    orchestration_flow: List[str] = Field(default_factory=list)
    decision_surfaces: List[DecisionSurface] = Field(default_factory=list)
    subsystems: List[IntelligenceSubsystem] = Field(default_factory=list)


class IntelligenceHealth(BaseModel):
    status: str
    checked_at: datetime
    subsystems: List[IntelligenceSubsystem] = Field(default_factory=list)
