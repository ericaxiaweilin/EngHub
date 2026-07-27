"""
组织节点模型 (Organization Node Model)
=======================================

每个管理角色 = 一个信号处理器(Transducer)：
- ParameterDef: 可调参数（该角色权限内的旋钮）
- CapabilityDef: 能力（该角色能影响什么信号）
- Constraint: 硬边界（不可被参数绕过的物理限制）
- OrgNode: 组织节点（参数+能力+输入+输出+约束+传导函数）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .signals import SignalType


@dataclass
class ParameterDef:
    """可调参数定义（该角色的'旋钮'）
    
    每个参数有物理边界（min/max），超出边界的值会被截断。
    """
    key: str
    label: str              # 显示名
    value: float            # 当前值
    min_val: float          # 物理下限
    max_val: float          # 物理上限
    step: float             # 调节步长
    unit: str               # 单位
    description: str = ""   # 物理含义

    def clamp(self, val: float) -> float:
        """截断到合法范围"""
        return max(self.min_val, min(self.max_val, val))

    def set(self, val: float) -> float:
        """设值（自动截断），返回实际生效值"""
        self.value = self.clamp(val)
        return self.value

    @property
    def normalized(self) -> float:
        """归一化到 0-1"""
        span = self.max_val - self.min_val
        if span <= 0:
            return 0.0
        return (self.value - self.min_val) / span


@dataclass
class CapabilityDef:
    """能力定义（该角色'能做什么'）
    
    能力 = 对某种信号的影响力。
    gain > 1 表示放大，< 1 表示衰减。
    latency_hours > 0 表示不是调了立刻见效（如培训需要时间）。
    """
    name: str               # 能力名
    signal_type: SignalType  # 影响哪种信号
    gain: float = 1.0       # 放大/衰减系数
    latency_hours: float = 0.0  # 生效延迟
    description: str = ""


@dataclass
class Constraint:
    """硬边界约束（不可被参数绕过）
    
    当 signal_type 的值触发 condition 时，执行 action。
    例：良率 < 0.55 → 强制停线（throughput 归零）
    """
    name: str
    signal_type: SignalType     # 监控哪个信号
    operator: str               # 比较运算符: "<", ">", "<=", ">="
    threshold: float            # 阈值
    action: str                 # 触发动作: "clamp_output", "shutdown", "escalate"
    action_target: Optional[SignalType] = None  # 动作作用于哪个信号
    action_value: float = 0.0   # 强制设为什么值
    description: str = ""

    def check(self, value: float) -> bool:
        """检查是否触发"""
        ops = {
            "<": lambda v, t: v < t,
            ">": lambda v, t: v > t,
            "<=": lambda v, t: v <= t,
            ">=": lambda v, t: v >= t,
        }
        fn = ops.get(self.operator)
        if fn is None:
            return False
        return fn(value, self.threshold)


# 传导函数类型：(输入信号字典, 参数字典) → 输出信号字典
TransferFn = Callable[[Dict[SignalType, float], Dict[str, float]], Dict[SignalType, float]]


class OrgNode:
    """组织节点 = 一个管理角色
    
    核心职责：
    1. 持有可调参数（该角色权限内的旋钮）
    2. 接收上游输入信号
    3. 通过 transfer_fn 确定性计算输出信号
    4. 检查约束（硬边界不可绕过）
    5. 向下游发出输出信号
    """

    def __init__(
        self,
        node_id: str,
        name: str,
        level: int,
        scope: str,
        transfer_fn: TransferFn,
        parameters: Optional[List[ParameterDef]] = None,
        capabilities: Optional[List[CapabilityDef]] = None,
        constraints: Optional[List[Constraint]] = None,
    ):
        self.node_id = node_id
        self.name = name
        self.level = level          # 1=现场 2=主管 3=经理 4=总监 5=高层
        self.scope = scope          # 职责范围描述
        self.transfer_fn = transfer_fn

        self.parameters: Dict[str, ParameterDef] = {}
        if parameters:
            for p in parameters:
                self.parameters[p.key] = p

        self.capabilities: List[CapabilityDef] = capabilities or []
        self.constraints: List[Constraint] = constraints or []

        # 信号状态
        self.input_signals: Dict[SignalType, float] = {}
        self.output_signals: Dict[SignalType, float] = {}

        # 约束违反记录
        self.violations: List[str] = []
        self.warnings: List[str] = []

    def set_parameter(self, key: str, value: float) -> float:
        """设置参数（自动截断到合法范围）"""
        if key not in self.parameters:
            raise KeyError(f"节点 '{self.name}' 没有参数 '{key}'")
        return self.parameters[key].set(value)

    def get_param_dict(self) -> Dict[str, float]:
        """获取所有参数的当前值字典"""
        return {k: p.value for k, p in self.parameters.items()}

    def compute(self) -> Dict[SignalType, float]:
        """执行传导函数：inputs + params → outputs
        
        确定性：相同输入永远产生相同输出。
        """
        self.violations = []
        self.warnings = []

        # 1. 调用传导函数
        params = self.get_param_dict()
        raw_outputs = self.transfer_fn(self.input_signals, params)

        # 2. 检查约束（硬边界）
        for c in self.constraints:
            # 检查输入信号
            if c.signal_type in self.input_signals:
                if c.check(self.input_signals[c.signal_type]):
                    self._apply_constraint(c)
            # 检查输出信号
            if c.signal_type in raw_outputs:
                if c.check(raw_outputs[c.signal_type]):
                    self._apply_constraint(c, raw_outputs)

        # 3. 存储输出
        self.output_signals = raw_outputs
        return raw_outputs

    def _apply_constraint(self, c: Constraint, outputs: Optional[Dict[SignalType, float]] = None):
        """应用约束动作"""
        self.violations.append(
            f"[{c.name}] {c.signal_type.label} 触发 {c.operator} {c.threshold} → {c.action}"
        )
        if c.action == "shutdown" and outputs is not None:
            # 强制停线：产出归零
            target = c.action_target or SignalType.THROUGHPUT
            outputs[target] = c.action_value
        elif c.action == "clamp_output" and outputs is not None:
            target = c.action_target or c.signal_type
            outputs[target] = c.action_value
        elif c.action == "escalate":
            self.output_signals[SignalType.ESCALATION_LEVEL] = max(
                self.output_signals.get(SignalType.ESCALATION_LEVEL, 0), 2.0
            )

    def receive_signal(self, signal_type: SignalType, value: float):
        """接收一个输入信号"""
        self.input_signals[signal_type] = value

    def snapshot(self) -> dict:
        """生成该节点的微观数据快照"""
        return {
            "node_id": self.node_id,
            "name": self.name,
            "level": self.level,
            "scope": self.scope,
            "parameters": {
                k: {
                    "label": p.label,
                    "value": p.value,
                    "min": p.min_val,
                    "max": p.max_val,
                    "step": p.step,
                    "unit": p.unit,
                    "description": p.description,
                }
                for k, p in self.parameters.items()
            },
            "capabilities": [
                {
                    "name": cap.name,
                    "signal": cap.signal_type.label,
                    "gain": cap.gain,
                    "latency_h": cap.latency_hours,
                    "description": cap.description,
                }
                for cap in self.capabilities
            ],
            "inputs": {
                st.label: {"value": v, "unit": st.unit}
                for st, v in self.input_signals.items()
            },
            "outputs": {
                st.label: {"value": v, "unit": st.unit}
                for st, v in self.output_signals.items()
            },
            "violations": self.violations,
            "warnings": self.warnings,
        }

    def __repr__(self) -> str:
        return f"OrgNode({self.node_id}, '{self.name}', L{self.level})"
