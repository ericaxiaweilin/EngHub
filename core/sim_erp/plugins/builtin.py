"""
Built-in legal, customer, and factory plugins for bootstrap scenarios.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..models import (
    DecisionType,
    PhysicalSnapshot,
    PluginManifest,
    PolicyPriority,
    RequiredAction,
    RuleDecision,
    RuleEvidence,
)
from .base import SimulationPlugin


class VNLabor2024Plugin(SimulationPlugin):
    manifest = PluginManifest(
        plugin_name="VN_Legal_2024",
        plugin_version="1.0.0",
        rule_version="2024.01",
        priority=PolicyPriority.LEGAL,
        legislation_pack="vn_labor_2024",
    )

    def evaluate(
        self,
        snapshot: PhysicalSnapshot,
        legislation_pack: Dict[str, Any],
    ) -> List[RuleDecision]:
        decisions: List[RuleDecision] = []
        heat_rule = legislation_pack["heat_allowance"]
        max_continuous_minutes = legislation_pack["continuous_work_limit"]["max_minutes"]

        if snapshot.environment.temperature_c > heat_rule["temperature_c_gt"]:
            decisions.append(
                RuleDecision(
                    plugin_name=self.manifest.plugin_name,
                    plugin_version=self.manifest.plugin_version,
                    rule_code="VN.HEAT.ALLOWANCE",
                    rule_version=self.manifest.rule_version,
                    decision_type=DecisionType.COST_MODIFIER,
                    priority=self.manifest.priority,
                    message="High-temperature allowance required.",
                    cost_delta=heat_rule["allowance_vnd"],
                    evidence=[
                        RuleEvidence(
                            field="environment.temperature_c",
                            observed_value=snapshot.environment.temperature_c,
                            expected=f">{heat_rule['temperature_c_gt']}",
                            source="VN Labor 2024 heat allowance",
                        )
                    ],
                )
            )

        if snapshot.continuous_work_minutes > max_continuous_minutes:
            decisions.append(
                RuleDecision(
                    plugin_name=self.manifest.plugin_name,
                    plugin_version=self.manifest.plugin_version,
                    rule_code="VN.CONTINUOUS.WORK",
                    rule_version=self.manifest.rule_version,
                    decision_type=DecisionType.VIOLATION,
                    priority=self.manifest.priority,
                    message="Continuous work limit exceeded.",
                    blocking=True,
                    penalty_score=100,
                    required_break_minutes=legislation_pack["continuous_work_limit"]["required_break_minutes"],
                    evidence=[
                        RuleEvidence(
                            field="continuous_work_minutes",
                            observed_value=snapshot.continuous_work_minutes,
                            expected=f"<={max_continuous_minutes}",
                            source="VN Labor 2024 continuous work limit",
                        )
                    ],
                    required_actions=[
                        RequiredAction(
                            action_code="INSERT_BREAK",
                            description="Insert mandatory legal recovery break.",
                            break_minutes=legislation_pack["continuous_work_limit"]["required_break_minutes"],
                        )
                    ],
                )
            )

        return decisions


class JohnsonGlobalStandardPlugin(SimulationPlugin):
    manifest = PluginManifest(
        plugin_name="Johnson_Global_Standard",
        plugin_version="1.0.0",
        rule_version="2024.01",
        priority=PolicyPriority.CUSTOMER_CODE,
        legislation_pack="johnson_global_standard",
    )

    def evaluate(
        self,
        snapshot: PhysicalSnapshot,
        legislation_pack: Dict[str, Any],
    ) -> List[RuleDecision]:
        threshold = legislation_pack["fatigue_warning"]["step_count_gt"]
        if snapshot.step_count <= threshold:
            return []

        return [
            RuleDecision(
                plugin_name=self.manifest.plugin_name,
                plugin_version=self.manifest.plugin_version,
                rule_code="JOHNSON.FATIGUE.WARNING",
                rule_version=self.manifest.rule_version,
                decision_type=DecisionType.WARNING,
                priority=self.manifest.priority,
                message="Worker fatigue risk exceeds customer threshold.",
                penalty_score=20,
                evidence=[
                    RuleEvidence(
                        field="step_count",
                        observed_value=snapshot.step_count,
                        expected=f"<={threshold}",
                        source="Johnson Global Standard fatigue threshold",
                    )
                ],
            )
        ]


class FactoryBreakPolicyPlugin(SimulationPlugin):
    manifest = PluginManifest(
        plugin_name="Factory_Policy_Default",
        plugin_version="1.0.0",
        rule_version="2024.01",
        priority=PolicyPriority.FACTORY_POLICY,
        legislation_pack="factory_policy_default",
    )

    def evaluate(
        self,
        snapshot: PhysicalSnapshot,
        legislation_pack: Dict[str, Any],
    ) -> List[RuleDecision]:
        threshold = legislation_pack["break_policy"]["continuous_work_minutes_gte"]
        if snapshot.continuous_work_minutes < threshold:
            return []

        break_minutes = legislation_pack["break_policy"]["break_minutes"]
        return [
            RuleDecision(
                plugin_name=self.manifest.plugin_name,
                plugin_version=self.manifest.plugin_version,
                rule_code="FACTORY.REQUIRED.BREAK",
                rule_version=self.manifest.rule_version,
                decision_type=DecisionType.REQUIRED_ACTION,
                priority=self.manifest.priority,
                message="Factory policy requires a recovery break.",
                required_break_minutes=break_minutes,
                evidence=[
                    RuleEvidence(
                        field="continuous_work_minutes",
                        observed_value=snapshot.continuous_work_minutes,
                        expected=f">={threshold}",
                        source="Factory policy default break rule",
                    )
                ],
                required_actions=[
                    RequiredAction(
                        action_code="INSERT_BREAK",
                        description="Insert factory-mandated break.",
                        break_minutes=break_minutes,
                    )
                ],
            )
        ]
