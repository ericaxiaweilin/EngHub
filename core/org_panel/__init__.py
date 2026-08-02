"""
全组织层级参数驱动仿真面板 (Organization Panel)
================================================

将公司每个可量化管理角色建模为信号处理节点(Transducer)，
通过类型安全的确定性逻辑链传导参数变化。

核心概念：
- Signal: 类型化信号（生产/质量/设备/人员/物料/成本/管理）
- OrgNode: 组织节点 = 一个管理角色（有参数/能力/输入/输出/约束）
- LogicChain: 确定性传导链（类型安全，只有因果相关的才能串联）
- OrgSimEngine: 图仿真引擎（参数注入→拓扑传播→全节点快照）
"""

from .signals import SignalType, Signal
from .node import OrgNode, ParameterDef, CapabilityDef, Constraint
from .chains import ChainLink, LogicChain
from .engine import OrgSimEngine

__all__ = [
    "SignalType",
    "Signal",
    "OrgNode",
    "ParameterDef",
    "CapabilityDef",
    "Constraint",
    "ChainLink",
    "LogicChain",
    "OrgSimEngine",
]
