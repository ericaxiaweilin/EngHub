"""
组织图仿真引擎 (Organization Simulation Engine)
================================================

核心算法：参数注入 → 拓扑排序传播 → 全节点快照

传播流程：
1. 参数变化 → 重新计算该节点的 transfer_fn → 输出信号变化
2. 沿 DAG 拓扑序传播：对每条 ChainLink，用 propagation_fn 传导
3. 下游节点收到新输入 → 重新计算自己的输出 → 继续传播
4. 遇到约束违反 → 截断 + 标记
5. 反馈环通过迭代收敛处理（最多 N 轮，epsilon 收敛）
6. 全部收敛后返回快照

确定性保证：相同参数 → 永远相同结果（可复现）
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .signals import SignalType
from .node import OrgNode
from .chains import ChainLink, LogicChain


# ==================== 数据模型 ====================

@dataclass
class NodeSnapshot:
    """节点快照：某角色视角看到的一切微观数据"""
    node_id: str
    name: str
    level: int
    scope: str
    parameters: Dict[str, dict]
    inputs: Dict[str, dict]
    outputs: Dict[str, dict]
    capabilities: List[dict]
    violations: List[str]
    warnings: List[str]


@dataclass
class ImpactEntry:
    """影响追踪中的一条记录"""
    node_id: str
    node_name: str
    signal_label: str
    before: float
    after: float
    delta: float
    delta_pct: float  # 变化百分比


@dataclass
class ImpactReport:
    """影响追踪报告：某参数调整后全链的确定性影响"""
    source_node_id: str
    param_key: str
    param_before: float
    param_after: float
    impacts: List[ImpactEntry] = field(default_factory=list)
    violations: List[str] = field(default_factory=list)
    chain_path: List[str] = field(default_factory=list)  # 传导路径描述


# ==================== 引擎 ====================

class OrgSimEngine:
    """组织仿真引擎
    
    管理所有组织节点和逻辑链，执行确定性信号传播。
    """

    MAX_ITERATIONS = 20       # 反馈环最大迭代次数
    CONVERGENCE_EPS = 1e-6    # 收敛精度

    def __init__(self):
        self.nodes: Dict[str, OrgNode] = {}
        self.chains: List[LogicChain] = []
        # 邻接表：source_node_id → [(link, target_node_id)]
        self._outgoing: Dict[str, List[ChainLink]] = defaultdict(list)
        # 反向：target_node_id → [source_node_id]
        self._incoming: Dict[str, List[str]] = defaultdict(list)

    # ── 构建 ──

    def add_node(self, node: OrgNode) -> None:
        """注册一个组织节点"""
        self.nodes[node.node_id] = node

    def connect(self, chain: LogicChain) -> None:
        """注册一条逻辑链（自动做类型安全检查）"""
        errors = chain.validate_all()
        if errors:
            raise TypeError(
                f"逻辑链 '{chain.name}' 类型校验失败:\n" + "\n".join(errors)
            )
        # 检查节点存在性
        for link in chain.links:
            if link.source_node_id not in self.nodes:
                raise KeyError(f"源节点 '{link.source_node_id}' 未注册")
            if link.target_node_id not in self.nodes:
                raise KeyError(f"目标节点 '{link.target_node_id}' 未注册")
            self._outgoing[link.source_node_id].append(link)
            self._incoming[link.target_node_id].append(link.source_node_id)

        self.chains.append(chain)

    # ── 参数操作 ──

    def set_parameter(self, node_id: str, param_key: str, value: float) -> float:
        """设置某节点的某参数，返回实际生效值"""
        if node_id not in self.nodes:
            raise KeyError(f"节点 '{node_id}' 不存在")
        return self.nodes[node_id].set_parameter(param_key, value)

    # ── 传播 ──

    def propagate(self) -> Dict[str, Dict[SignalType, float]]:
        """执行全图传播
        
        算法：
        1. 计算所有节点的初始输出（基于当前输入+参数）
        2. 拓扑排序确定传播顺序
        3. 按序传播信号
        4. 对有反馈环的，迭代直到收敛
        
        返回：{node_id: {SignalType: value}} 所有节点的最终输出
        """
        # 拓扑排序（Kahn's algorithm）
        order = self._topological_sort()

        # 迭代传播（处理反馈环）
        for iteration in range(self.MAX_ITERATIONS):
            prev_outputs = {
                nid: dict(node.output_signals) for nid, node in self.nodes.items()
            }

            # 按拓扑序逐节点计算
            for node_id in order:
                node = self.nodes[node_id]
                # 收集来自上游的信号
                self._gather_inputs(node_id)
                # 执行传导函数
                node.compute()

            # 检查收敛
            if self._converged(prev_outputs):
                break

        return {nid: dict(node.output_signals) for nid, node in self.nodes.items()}

    def _gather_inputs(self, node_id: str):
        """收集所有指向该节点的链传导信号"""
        for link in self._outgoing.get(node_id, []):
            # 这里是 node_id 作为 source 的情况，不需要 gather
            pass

        # 找所有以 node_id 为 target 的 link
        for source_id, links in self._outgoing.items():
            for link in links:
                if link.target_node_id == node_id:
                    source_node = self.nodes.get(link.source_node_id)
                    if source_node and link.source_signal in source_node.output_signals:
                        raw_value = source_node.output_signals[link.source_signal]
                        propagated = link.propagate(raw_value)
                        self.nodes[node_id].receive_signal(link.target_signal, propagated)

    def _topological_sort(self) -> List[str]:
        """Kahn 拓扑排序（有环时退化为全节点遍历）"""
        in_degree: Dict[str, int] = {nid: 0 for nid in self.nodes}
        adj: Dict[str, List[str]] = defaultdict(list)

        for source_id, links in self._outgoing.items():
            for link in links:
                target = link.target_node_id
                if target in in_degree:
                    adj[source_id].append(target)
                    in_degree[target] = in_degree.get(target, 0) + 1

        queue = deque([nid for nid, deg in in_degree.items() if deg == 0])
        order = []

        while queue:
            nid = queue.popleft()
            order.append(nid)
            for neighbor in adj.get(nid, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # 有环：把剩余节点追加（迭代收敛处理）
        remaining = [nid for nid in self.nodes if nid not in set(order)]
        order.extend(remaining)
        return order

    def _converged(self, prev_outputs: Dict[str, Dict[SignalType, float]]) -> bool:
        """检查是否收敛（所有节点输出变化 < epsilon）"""
        for nid, node in self.nodes.items():
            prev = prev_outputs.get(nid, {})
            curr = node.output_signals
            all_keys = set(prev.keys()) | set(curr.keys())
            for k in all_keys:
                if abs(curr.get(k, 0.0) - prev.get(k, 0.0)) > self.CONVERGENCE_EPS:
                    return False
        return True

    # ── 查询 ──

    def snapshot(self, node_id: str) -> NodeSnapshot:
        """获取某节点的微观数据快照"""
        if node_id not in self.nodes:
            raise KeyError(f"节点 '{node_id}' 不存在")
        node = self.nodes[node_id]
        data = node.snapshot()
        return NodeSnapshot(
            node_id=data["node_id"],
            name=data["name"],
            level=data["level"],
            scope=data["scope"],
            parameters=data["parameters"],
            inputs=data["inputs"],
            outputs=data["outputs"],
            capabilities=data["capabilities"],
            violations=data["violations"],
            warnings=data["warnings"],
        )

    def snapshot_all(self) -> Dict[str, NodeSnapshot]:
        """所有节点快照"""
        return {nid: self.snapshot(nid) for nid in self.nodes}

    # ── 影响追踪 ──

    def trace_impact(self, node_id: str, param_key: str, delta: float) -> ImpactReport:
        """追踪：如果某角色调了某参数（+delta），全链影响是什么
        
        方法：
        1. 保存当前状态
        2. 应用 delta → 传播 → 记录 after
        3. 恢复原始状态 → 传播 → 记录 before
        4. 对比生成 ImpactReport
        """
        if node_id not in self.nodes:
            raise KeyError(f"节点 '{node_id}' 不存在")
        node = self.nodes[node_id]
        if param_key not in node.parameters:
            raise KeyError(f"节点 '{node_id}' 没有参数 '{param_key}'")

        # 保存原始参数
        original_value = node.parameters[param_key].value
        new_value = node.parameters[param_key].clamp(original_value + delta)

        # 计算 before（原始状态传播）
        node.parameters[param_key].value = original_value
        self.propagate()
        before_state = {nid: dict(n.output_signals) for nid, n in self.nodes.items()}

        # 计算 after（新参数传播）
        node.parameters[param_key].value = new_value
        self.propagate()
        after_state = {nid: dict(n.output_signals) for nid, n in self.nodes.items()}

        # 恢复原始
        node.parameters[param_key].value = original_value
        self.propagate()

        # 生成影响报告
        impacts = []
        for nid in self.nodes:
            n = self.nodes[nid]
            before_sigs = before_state.get(nid, {})
            after_sigs = after_state.get(nid, {})
            all_sigs = set(before_sigs.keys()) | set(after_sigs.keys())
            for sig in all_sigs:
                b = before_sigs.get(sig, 0.0)
                a = after_sigs.get(sig, 0.0)
                d = a - b
                if abs(d) > self.CONVERGENCE_EPS:
                    pct = (d / b * 100) if abs(b) > self.CONVERGENCE_EPS else float('inf')
                    impacts.append(ImpactEntry(
                        node_id=nid,
                        node_name=n.name,
                        signal_label=sig.label,
                        before=round(b, 4),
                        after=round(a, 4),
                        delta=round(d, 4),
                        delta_pct=round(pct, 2),
                    ))

        # 传导路径
        chain_path = self._trace_chain_path(node_id)

        # 违反
        violations = []
        for n in self.nodes.values():
            violations.extend(n.violations)

        return ImpactReport(
            source_node_id=node_id,
            param_key=param_key,
            param_before=original_value,
            param_after=new_value,
            impacts=impacts,
            violations=violations,
            chain_path=chain_path,
        )

    def _trace_chain_path(self, start_node_id: str) -> List[str]:
        """BFS 追踪从某节点出发的所有传导路径"""
        paths = []
        visited: Set[str] = set()
        queue: deque = deque([(start_node_id, [start_node_id])])

        while queue:
            current, path = queue.popleft()
            if current in visited:
                continue
            visited.add(current)

            for link in self._outgoing.get(current, []):
                desc = link.label or f"{link.source_signal.label}→{link.target_signal.label}"
                new_path = path + [f"──{desc}──→ {link.target_node_id}"]
                paths.append(" ".join(new_path))
                queue.append((link.target_node_id, new_path))

        return paths if paths else [f"{start_node_id} (无下游)"]

    # ── What-If 分析 ──

    def what_if(self, scenario: Dict[Tuple[str, str], float]) -> Dict[str, NodeSnapshot]:
        """多参数同时调整的 what-if 分析
        
        scenario: {(node_id, param_key): new_value, ...}
        返回：调整后的全图快照（不修改引擎当前状态）
        """
        # 保存当前状态
        saved_params = {}
        for (nid, pkey), val in scenario.items():
            if nid not in self.nodes:
                raise KeyError(f"节点 '{nid}' 不存在")
            node = self.nodes[nid]
            if pkey not in node.parameters:
                raise KeyError(f"节点 '{nid}' 没有参数 '{pkey}'")
            saved_params[(nid, pkey)] = node.parameters[pkey].value
            node.parameters[pkey].set(val)

        # 传播
        self.propagate()

        # 快照
        result = self.snapshot_all()

        # 恢复
        for (nid, pkey), val in saved_params.items():
            self.nodes[nid].parameters[pkey].value = val
        self.propagate()

        return result

    # ── 辅助 ──

    def get_nodes_by_level(self, level: int) -> List[OrgNode]:
        """按层级获取节点"""
        return [n for n in self.nodes.values() if n.level == level]

    def get_chains_for_node(self, node_id: str) -> List[LogicChain]:
        """获取涉及某节点的所有逻辑链"""
        result = []
        for chain in self.chains:
            if node_id in chain.get_involved_nodes():
                result.append(chain)
        return result

    def describe_graph(self) -> str:
        """人类可读的全图描述"""
        lines = ["═══ 组织仿真图 ═══", ""]
        lines.append(f"节点 ({len(self.nodes)}):")
        for nid, node in sorted(self.nodes.items(), key=lambda x: x[1].level):
            lines.append(f"  L{node.level} [{nid}] {node.name} — {node.scope}")
        lines.append("")
        lines.append(f"逻辑链 ({len(self.chains)}):")
        for chain in self.chains:
            lines.append(f"  {chain.describe()}")
        return "\n".join(lines)
