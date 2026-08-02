"""
Base plugin contract for Sim-ERP compliance rules.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List

from ..models import PhysicalSnapshot, PluginManifest, RuleDecision


class SimulationPlugin(ABC):
    manifest: PluginManifest

    @abstractmethod
    def evaluate(
        self,
        snapshot: PhysicalSnapshot,
        legislation_pack: Dict[str, Any],
    ) -> List[RuleDecision]:
        raise NotImplementedError
