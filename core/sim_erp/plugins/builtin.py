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


class ISO7243HeatPlugin(SimulationPlugin):
    """按 WBGT 对照职业接触限值：30℃ 与 40℃ 的差别必须落在读数上。

    限值来自规则包（JSOH 2025-2026 按代谢强度档），WBGT 用 ISO 7243 室内形式
    0.7·自然湿球 + 0.3·干球（湿球按 Stull 2011 由温度+湿度估算，无黑球实测时 Tg≈Td）。
    标准给的是"超限就要改工作-恢复制度"，本厂把超限幅度折成休息比例与应变系数，
    换算系数也写在包里 —— 那是厂里的决定，不是标准原文，答复里要能分辨这两件事。
    """

    manifest = PluginManifest(
        plugin_name="ISO7243_Heat_TLV",
        plugin_version="1.0.0",
        rule_version="2025.01",
        priority=PolicyPriority.LEGAL,
        legislation_pack="iso7243_jsoh_heat",
    )

    def evaluate(self, snapshot, legislation_pack):
        from ..thermal import assess

        if not (legislation_pack or {}).get("metabolic_levels"):
            return []
        th = assess(temperature_c=snapshot.environment.temperature_c,
                    humidity_percent=snapshot.environment.humidity_percent,
                    task_type=snapshot.task_type, pack=legislation_pack)
        if not th.get("available"):
            return []
        exceed = float(th.get("exceedance_c") or 0.0)
        if exceed <= 0:
            return []

        evidence = [
            RuleEvidence(field="wbgt_c", observed_value=th["wbgt_c"],
                         expected=f"<={th['tlv_wbgt_c']}",
                         source=(th["basis"].get("wbgt") or "")[:180]),
            RuleEvidence(field="environment.humidity_percent",
                         observed_value=snapshot.environment.humidity_percent,
                         expected=f"湿球 {th['wet_bulb_c']}℃（Stull 2011 估算）",
                         source=(th["basis"].get("wet_bulb") or "")[:180]),
            RuleEvidence(field="work_context.task_type", observed_value=snapshot.task_type,
                         expected=f"强度档 {th['metabolic_level']}（{th['metabolic_kcal_per_hour']} kcal/h）",
                         source=(th["basis"].get("limit") or "")[:180]),
        ]
        rest_pct = round(float(th["required_rest_fraction"]) * 100)
        message = (f"WBGT {th['wbgt_c']:g}℃ 超过 {th['metabolic_level']} 强度档限值 "
                   f"{th['tlv_wbgt_c']:g}℃（超 {exceed:g}℃）→ 需约 {rest_pct}% 工休，"
                   f"每 60 分钟最多连续作业 {th['max_allowable_work_minutes_per_hour']:g} 分钟")
        blocking = bool(th.get("blocking"))
        return [
            RuleDecision(
                plugin_name=self.manifest.plugin_name,
                plugin_version=self.manifest.plugin_version,
                rule_code="ISO7243.WBGT.TLV",
                rule_version=self.manifest.rule_version,
                decision_type=DecisionType.VIOLATION if blocking else DecisionType.WARNING,
                priority=self.manifest.priority,
                message=message,
                blocking=blocking,
                penalty_score=int(round(exceed * 20)),
                # 摘要读的是 decision.required_break_minutes：只写在动作上会出现"正文要休 45 分钟、
                # 汇总说 0 分钟"这种自相矛盾
                required_break_minutes=int(round(float(th["required_rest_fraction"]) * 60)),
                evidence=evidence,
                required_actions=[RequiredAction(
                    action_code="SET_WORK_REST_CYCLE",
                    description=message,
                    break_minutes=int(round(float(th["required_rest_fraction"]) * 60))),],
                metadata={"wbgt_c": th["wbgt_c"], "tlv_wbgt_c": th["tlv_wbgt_c"],
                          "exceedance_c": exceed, "assumptions": th["assumptions"],
                          "strain_multiplier": th["strain_multiplier"],
                          "basis": th["basis"]},
            )
        ]
