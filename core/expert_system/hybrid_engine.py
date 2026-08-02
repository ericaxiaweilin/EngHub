

"""
v2.5 - Expert System Hybrid Inference Engine

混合推理模式：
1. 规则优先：模具/电子行业的硬编码参数（转速、温度）优先匹配
2. LLM兜底：未知问题自动调用大模型生成建议
3. 前端集成：支持切换纯规则/AI优先策略

设计原则：
- 不依赖外部 LLM 网关也能运行（纯规则降级）
- 所有规则可配置、可维护
- 前端可通过 expert_mode 开关切换策略
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# ==================== 行业规则库 ====================

class IndustryRules:
    """行业 Know-how 硬编码参数"""

    MOLD_FACTORY = {
        "cnc_spindle_speed": {"min_rpm": 8000, "max_rpm": 24000, "default_rpm": 15000, "unit": "rpm"},
        "edm_gap_voltage": {"min_v": 60, "max_v": 220, "default_v": 120, "unit": "V"},
        "wire_cut_tension": {"min_kgf": 5, "max_kgf": 15, "default_kgf": 10, "unit": "kgf"},
        "assembly_tolerance": {"value": 0.01, "unit": "mm", "description": "装配间隙公差"},
        "surface_roughness": {"max_ra": 0.8, "unit": "μm", "description": "镜面加工Ra上限"},
    }

    ELECTRONICS_FACTORY = {
        "smt_reflow_profile": {
            "preheat_start": 120, "preheat_end": 180,
            "soak_start": 180, "soak_end": 217,
            "reflow_peak": 245, "reflow_time": 30,
            "cool_down_rate_max": 6, "unit": "°C/s"
        },
        "aoi_inspection_sensitivity": {"value": 85, "unit": "%", "min_acceptable": 80},
        "dip_wave_solder_temp": {"value": 260, "unit": "°C", "tolerance": 5},
        "func_test_pass_criteria": {"min_voltage": 3.3, "max_voltage": 3.6, "unit": "V"},
    }

    SPORTING_GOODS_FACTORY = {
        "leather_cutting_pressure": {"min_bar": 2, "max_bar": 8, "default_bar": 5, "unit": "bar"},
        "sewing_stitch_length": {"min_mm": 2.0, "max_mm": 4.0, "default_mm": 3.0, "unit": "mm"},
        "lasting_temp": {"value": 80, "unit": "°C", "tolerance": 10},
        "painting_coating_weight": {"min_g_m2": 40, "max_g_m2": 80, "default_g_m2": 60, "unit": "g/m²"},
    }


# ==================== 规则引擎 ====================

class RuleEngine:
    """生产规则推理引擎 — 硬编码参数优先匹配"""

    def __init__(self):
        self.rules = IndustryRules()

    async def check_mold_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """检查模具厂工艺参数合规性"""
        findings = []

        spindle_rpm = params.get("spindle_rpm")
        if spindle_rpm is not None:
            cfg = self.rules.MOLD_FACTORY["cnc_spindle_speed"]
            if spindle_rpm < cfg["min_rpm"]:
                findings.append({
                    "rule_id": "MOLD-CNC-RPM-LOW",
                    "severity": "warning",
                    "message": f"主轴转速 {spindle_rpm} rpm 低于最小值 {cfg['min_rpm']} rpm",
                    "suggestion": f"建议调整为 {cfg['default_rpm']} rpm 附近",
                })
            elif spindle_rpm > cfg["max_rpm"]:
                findings.append({
                    "rule_id": "MOLD-CNC-RPM-HIGH",
                    "severity": "critical",
                    "message": f"主轴转速 {spindle_rpm} rpm 超过最大值 {cfg['max_rpm']} rpm",
                    "suggestion": "立即停机检查，可能损坏刀具或工件",
                })
            else:
                findings.append({"rule_id": "MOLD-CNC-RPM-OK", "severity": "info", "message": f"主轴转速 {spindle_rpm} rpm 在正常范围"})

        gap_voltage = params.get("edm_gap_voltage")
        if gap_voltage is not None:
            cfg = self.rules.MOLD_FACTORY["edm_gap_voltage"]
            if gap_voltage < cfg["min_v"] or gap_voltage > cfg["max_v"]:
                findings.append({
                    "rule_id": "MOLD-EDM-VOLTAGE",
                    "severity": "warning",
                    "message": f"EDM 间隙电压 {gap_voltage} V 超出范围 [{cfg['min_v']}-{cfg['max_v']}]",
                    "suggestion": f"建议设置为 {cfg['default_v']} V",
                })

        return {
            "check_type": "mold_params",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "findings": findings,
            "overall_status": "failed" if any(f["severity"] == "critical" for f in findings) else "ok",
        }

    async def check_electronics_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """检查电子厂 SMT/ DIP 工艺参数合规性"""
        findings = []

        reflow_peak = params.get("reflow_peak_temperature")
        if reflow_peak is not None:
            cfg = self.rules.ELECTRONICS_FACTORY["smt_reflow_profile"]
            peak = cfg["reflow_peak"]
            tolerance = 5
            if reflow_peak < peak - tolerance:
                findings.append({
                    "rule_id": "ELEC-REFLOW-LOW",
                    "severity": "warning",
                    "message": f"回流焊峰值温度 {reflow_peak}°C 低于标准 {peak}°C",
                    "suggestion": f"建议调整至 {peak} ± {tolerance} °C",
                })
            elif reflow_peak > peak + tolerance:
                findings.append({
                    "rule_id": "ELEC-REFLOW-HIGH",
                    "severity": "critical",
                    "message": f"回流焊峰值温度 {reflow_peak}°C 超过标准 {peak}°C",
                    "suggestion": "可能导致锡膏氧化或元件损伤，需立即排查",
                })
            else:
                findings.append({"rule_id": "ELEC-REFLOW-OK", "severity": "info", "message": f"回流焊峰值温度 {reflow_peak}°C 符合标准"})

        dip_temp = params.get("dip_wave_solder_temperature")
        if dip_temp is not None:
            cfg = self.rules.ELECTRONICS_FACTORY["dip_wave_solder_temp"]
            deviation = abs(dip_temp - cfg["value"])
            if deviation > cfg["tolerance"]:
                findings.append({
                    "rule_id": "ELEC-DIP-TEMP",
                    "severity": "warning",
                    "message": f"DIP 波峰焊温度偏差 {deviation}°C，超出容差 {cfg['tolerance']}°C",
                    "suggestion": f"建议设置至 {cfg['value']} ± {cfg['tolerance']} °C",
                })
            else:
                findings.append({"rule_id": "ELEC-DIP-OK", "severity": "info", "message": f"DIP 波峰焊温度 {dip_temp}°C 在容差范围内"})

        aoi_sens = params.get("aoi_sensitivity")
        if aoi_sens is not None:
            cfg = self.rules.ELECTRONICS_FACTORY["aoi_inspection_sensitivity"]
            if aoi_sens < cfg["min_acceptable"]:
                findings.append({
                    "rule_id": "ELEC-AOI-SENS",
                    "severity": "warning",
                    "message": f"AOI 灵敏度 {aoi_sens}% 低于最低要求 {cfg['min_acceptable']}%",
                    "suggestion": f"建议调整至 {cfg['min_acceptable']}% 以上",
                })

        return {
            "check_type": "electronics_params",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "findings": findings,
            "overall_status": "failed" if any(f["severity"] == "critical" for f in findings) else "ok",
        }

    async def check_sporting_goods_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """检查运动器材厂裁断/针车/涂装参数合规性"""
        findings = []

        cut_pressure = params.get("cutting_pressure_bar")
        if cut_pressure is not None:
            cfg = self.rules.SPORTING_GOODS_FACTORY["leather_cutting_pressure"]
            if cut_pressure < cfg["min_bar"] or cut_pressure > cfg["max_bar"]:
                findings.append({
                    "rule_id": "SPRT-CUT-PRESSURE",
                    "severity": "warning",
                    "message": f"裁断压力 {cut_pressure} bar 超出范围 [{cfg['min_bar']}-{cfg['max_bar']}]",
                    "suggestion": f"建议设置为 {cfg['default_bar']} bar",
                })

        stitch_len = params.get("stitch_length_mm")
        if stitch_len is not None:
            cfg = self.rules.SPORTING_GOODS_FACTORY["sewing_stitch_length"]
            if stitch_len < cfg["min_mm"] or stitch_len > cfg["max_mm"]:
                findings.append({
                    "rule_id": "SPRT-STITCH-LEN",
                    "severity": "warning",
                    "message": f"针车线距 {stitch_len} mm 超出范围 [{cfg['min_mm']}-{cfg['max_mm']}]",
                    "suggestion": f"建议设置为 {cfg['default_mm']} mm",
                })

        paint_weight = params.get("painting_coating_weight_gm2")
        if paint_weight is not None:
            cfg = self.rules.SPORTING_GOODS_FACTORY["painting_coating_weight"]
            if paint_weight < cfg["min_g_m2"] or paint_weight > cfg["max_g_m2"]:
                findings.append({
                    "rule_id": "SPRT-PAINT-WEIGHT",
                    "severity": "warning",
                    "message": f"涂装重量 {paint_weight} g/m² 超出范围 [{cfg['min_g_m2']}-{cfg['max_g_m2']}]",
                    "suggestion": f"建议设置为 {cfg['default_g_m2']} g/m²",
                })

        return {
            "check_type": "sporting_goods_params",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "findings": findings,
            "overall_status": "ok",
        }

    async def evaluate(self, industry: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """按行业执行规则检查"""
        if industry == "mold":
            return await self.check_mold_params(params)
        elif industry == "electronics":
            return await self.check_electronics_params(params)
        elif industry == "sporting_goods":
            return await self.check_sporting_goods_params(params)
        else:
            return {
                "check_type": "unknown_industry",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "findings": [],
                "overall_status": "ok",
                "note": f"不支持的行业: {industry}。请使用 mold/electronics/sporting_goods",
            }


# ==================== LLM 兜底客户端 ====================

class LLMAgent:
    """LLM 兜底回答客户端 — 当前仅封装结构，实际接入需配置 LLM_GATEWAY_URL"""

    async def fallback_answer(self, query: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        LLM 兜底回答

        当前实现为占位逻辑：
        - 如果 LLM 网关未配置，返回友好提示
        - 生产环境接入时替换为实际 HTTP 调用

        TODO: 当 LLM_GATEWAY_URL 环境变量可用时，替换此处为 httpx 异步调用
        """
        gateway_url = __import__("os").environ.get("LLM_GATEWAY_URL", "")

        if not gateway_url:
            return {
                "source": "llm_fallback",
                "fallback": True,
                "response": (
                    "🔧 目前 AI 专家网关未配置。\n\n"
                    "请将环境变量 `LLM_GATEWAY_URL` 和 `LLM_API_KEY` 指向可用的 litellm 网关。\n\n"
                    "已收集到的信息：\n"
                    f"- 问题: {query}\n"
                    f"- 上下文: {json.dumps(context, ensure_ascii=False) if context else '无'}\n"
                    "\n请补充配置后重试。"
                ),
                "message": "AI Gateway not configured. Please set LLM_GATEWAY_URL environment variable.",
            }

        # 未来接入 LLM 网关的代码预留位置
        return {
            "source": "llm_gateway",
            "fallback": False,
            "message": "LLM Gateway configured but not yet connected. Placeholder response.",
            "query": query,
        }


# ==================== 混合推理引擎入口 ====================

class HybridExpertEngine:
    """混合推理引擎 — 规则优先 + LLM 兜底"""

    def __init__(self):
        self.rule_engine = RuleEngine()
        self.llm_agent = LLMAgent()

    async def answer(
        self,
        query: str,
        industry: str = "mold",
        params: Optional[Dict[str, Any]] = None,
        expert_mode: str = "hybrid",  # hybrid / rules_only / ai_first
    ) -> Dict[str, Any]:
        """
        主入口：根据专家模式返回回答

        Args:
            query: 用户问题
            industry: 行业 (mold/electronics/sporting_goods)
            params: 工艺参数（可选）
            expert_mode: 推理策略
                - hybrid: 规则优先，结果不足时LLM兜底
                - rules_only: 纯规则推理
                - ai_first: AI优先，仅在AI失败时用规则
        """
        context = {"industry": industry, "params": params or {}, "expert_mode": expert_mode}

        # 路径1: 规则优先 (hybrid 或 rules_only)
        if expert_mode in ("hybrid", "rules_only"):
            rule_result = await self.rule_engine.evaluate(industry, params or {})

            if rule_result["overall_status"] != "ok":
                return {
                    "source": "hybrid_engine",
                    "strategy": expert_mode,
                    "phase": "rules",
                    "result": rule_result,
                    "has_ai_fallback": expert_mode == "hybrid",
                }

            if expert_mode == "ai_first":
                pass  # 走到下面 AI 优先路径

        # 路径2: AI优先 或 hybrid 兜底
        if expert_mode == "hybrid" or expert_mode == "ai_first":
            llm_result = await self.llm_agent.fallback_answer(query, context)
            return {
                "source": "hybrid_engine",
                "strategy": expert_mode,
                "phase": "llm_fallback" if expert_mode == "hybrid" else "ai_primary",
                "result": llm_result,
            }

        return {
            "error": f"未知专家模式: {expert_mode}",
            "supported_modes": ["hybrid", "rules_only", "ai_first"],
        }


# 全局实例
expert_engine = HybridExpertEngine()

__all__ = ["HybridExpertEngine", "RuleEngine", "IndustryRules", "LLMAgent", "expert_engine"]


