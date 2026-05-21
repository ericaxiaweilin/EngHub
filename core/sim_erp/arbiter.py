"""
Decision arbitration for plugin outputs.
"""

from __future__ import annotations

from typing import Iterable, List

from .models import ArbiterResult, DecisionType, PluginExecutionRecord, PolicyPriority, RequiredAction


class DecisionArbiter:
    VERSION = "2.0.0"

    def resolve(self, plugin_records: Iterable[PluginExecutionRecord]) -> ArbiterResult:
        decisions = [
            decision
            for record in plugin_records
            if record.status == "ok"
            for decision in record.decisions
        ]

        blocking_decisions = [
            decision
            for decision in decisions
            if decision.priority == PolicyPriority.LEGAL and decision.decision_type == DecisionType.VIOLATION
        ]
        warnings = [decision for decision in decisions if decision.decision_type == DecisionType.WARNING]
        applied_actions = self._collect_actions(decisions)
        max_break = max((decision.required_break_minutes for decision in decisions), default=0)
        total_cost = sum(decision.cost_delta for decision in decisions)
        total_penalty = sum(decision.penalty_score for decision in decisions)

        legal_blocked = bool(blocking_decisions)
        accepted = not legal_blocked
        final_status = "rejected" if legal_blocked else "accepted"
        winning_priority = min((decision.priority for decision in decisions), default=None, key=self._priority_rank)

        return ArbiterResult(
            legal_blocked=legal_blocked,
            accepted=accepted,
            final_status=final_status,
            max_required_break_minutes=max_break,
            total_cost_delta=total_cost,
            total_penalty_score=total_penalty,
            winning_priority=winning_priority,
            decisions=decisions,
            applied_actions=applied_actions,
            blocking_decisions=blocking_decisions,
            warnings=warnings,
        )

    @staticmethod
    def _priority_rank(priority: PolicyPriority) -> int:
        return {
            PolicyPriority.LEGAL: 0,
            PolicyPriority.CUSTOMER_CODE: 1,
            PolicyPriority.FACTORY_POLICY: 2,
            PolicyPriority.OPTIMIZATION_GOAL: 3,
        }[priority]

    @staticmethod
    def _collect_actions(decisions) -> List[RequiredAction]:
        merged: List[RequiredAction] = []
        seen = set()
        for decision in decisions:
            for action in decision.required_actions:
                key = (action.action_code, action.break_minutes, action.description)
                if key in seen:
                    continue
                seen.add(key)
                merged.append(action)
        return merged
