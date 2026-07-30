"""
确定性逻辑链 (Deterministic Logic Chains)
==========================================

逻辑链 = 有向信号传导路径。
每一环(ChainLink)定义：从 source 节点的某输出信号 → target 节点的某输入信号，
经过一个确定性传导函数(propagation_fn)。

类型安全：
- 只有 signals_compatible(source_signal, target_signal) == True 才能建链
- 不能串的（无因果关系的信号对）不存在传导函数，自然不串

传导函数要求：
- 纯函数：相同输入永远相同输出
- 单参数：f(float) → float
- 可含衰减/放大/阈值/非线性，但不可有随机
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from .signals import SignalType, signals_compatible


# 传导函数类型：f(输入值) → 输出值
PropagationFn = Callable[[float], float]


@dataclass
class ChainLink:
    """链的一环：从 source 的某输出 → target 的某输入
    
    propagation_fn 是确定性传导函数：
    - 线性：lambda x: x * gain
    - 非线性：lambda x: 0.98 - 0.15 * (x - 1) ** 2
    - 阈值：lambda x: 0 if x < threshold else (x - threshold) / (max - threshold)
    """
    source_node_id: str
    source_signal: SignalType
    target_node_id: str
    target_signal: SignalType
    propagation_fn: PropagationFn
    latency_hours: float = 0.0  # 传导延迟（不是调了立刻到）
    label: str = ""             # 这一环的描述

    def propagate(self, value: float) -> float:
        """执行传导"""
        return self.propagation_fn(value)

    def validate(self) -> Tuple[bool, str]:
        """类型安全检查"""
        if not signals_compatible(self.source_signal, self.target_signal):
            return False, (
                f"类型不兼容: {self.source_signal.label}({self.source_signal.domain.value}) "
                f"→ {self.target_signal.label}({self.target_signal.domain.value}) "
                f"无因果关系，不能串联"
            )
        return True, "OK"

    def __repr__(self) -> str:
        desc = self.label or f"{self.source_signal.label}→{self.target_signal.label}"
        return f"Link({self.source_node_id}.{desc}→{self.target_node_id})"


class LogicChain:
    """确定性逻辑链：由多个 ChainLink 组成的有向传导路径
    
    一条链描述一个完整的因果传导路径，如：
    "速度-质量链"：线长.speed → 质量.yield → 返工量 → 产能损失
    """

    def __init__(self, chain_id: str, name: str, links: Optional[List[ChainLink]] = None):
        self.chain_id = chain_id
        self.name = name
        self.links: List[ChainLink] = links or []

    def add_link(self, link: ChainLink) -> "LogicChain":
        """添加一环（自动做类型安全检查）"""
        valid, msg = link.validate()
        if not valid:
            raise TypeError(f"逻辑链 '{self.name}' 添加失败: {msg}")
        self.links.append(link)
        return self

    def validate_all(self) -> List[str]:
        """验证整条链的类型安全"""
        errors = []
        for i, link in enumerate(self.links):
            valid, msg = link.validate()
            if not valid:
                errors.append(f"  环[{i}]: {msg}")
        return errors

    def get_involved_nodes(self) -> List[str]:
        """获取链涉及的所有节点ID"""
        nodes = set()
        for link in self.links:
            nodes.add(link.source_node_id)
            nodes.add(link.target_node_id)
        return sorted(nodes)

    def describe(self) -> str:
        """人类可读的链描述"""
        parts = [f"逻辑链 [{self.name}]"]
        for i, link in enumerate(self.links):
            desc = link.label or f"{link.source_signal.label}→{link.target_signal.label}"
            parts.append(f"  {i+1}. {link.source_node_id} ──{desc}──→ {link.target_node_id}")
            if link.latency_hours > 0:
                parts.append(f"     (延迟 {link.latency_hours}h)")
        return "\n".join(parts)

    def __repr__(self) -> str:
        return f"LogicChain({self.chain_id}, '{self.name}', {len(self.links)} links)"


# ==================== 常用传导函数工厂 ====================

def linear(gain: float = 1.0, offset: float = 0.0) -> PropagationFn:
    """线性传导：y = gain * x + offset"""
    def fn(x: float) -> float:
        return gain * x + offset
    return fn


def quadratic_degrade(base: float = 0.98, coeff: float = 0.15, threshold: float = 1.0) -> PropagationFn:
    """二次退化：speed ≤ threshold 时保持 base，超过后二次下降
    y = base - coeff * (x - threshold)^2
    """
    def fn(x: float) -> float:
        if x <= threshold:
            return base
        return max(0.1, base - coeff * (x - threshold) ** 2)
    return fn


def power_stress(exponent: float = 1.5, normalize_max: float = 3.0) -> PropagationFn:
    """幂次应力：y = (x / max) ^ exponent，归一化到 0-1"""
    def fn(x: float) -> float:
        return min(1.0, (x / normalize_max) ** exponent)
    return fn


def threshold_linear(threshold: float, collapse: float) -> PropagationFn:
    """阈值后线性：x ≤ threshold → 0，之后线性到 collapse 时 = 1.0"""
    def fn(x: float) -> float:
        if x <= threshold:
            return 0.0
        return min(1.0, (x - threshold) / (collapse - threshold))
    return fn


def exponential_decay(base_rate: float = 0.02, exponent: float = 2.5, hours: float = 24.0) -> PropagationFn:
    """指数衰减（故障概率）：P = 1 - exp(-rate * x^exponent * hours)"""
    import math
    def fn(x: float) -> float:
        rate = base_rate * (x ** exponent)
        return 1.0 - math.exp(-rate * hours)
    return fn


def inverse_proportional(numerator: float = 100.0, floor: float = 0.01) -> PropagationFn:
    """反比：y = numerator / max(x, floor)"""
    def fn(x: float) -> float:
        return numerator / max(x, floor)
    return fn


def clamp_propagation(min_val: float = 0.0, max_val: float = 1.0) -> PropagationFn:
    """截断传导：将值限制在范围内"""
    def fn(x: float) -> float:
        return max(min_val, min(max_val, x))
    return fn
