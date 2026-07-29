"""
组织面板 REST API 适配层
=========================

将 OrgSimEngine 暴露为 REST API 供前端面板调用。

端点：
GET  /api/v1/org-panel/nodes              → 所有节点列表（按层级）
GET  /api/v1/org-panel/nodes/{id}/detail  → 节点微观数据快照
POST /api/v1/org-panel/nodes/{id}/param   → 调整参数
POST /api/v1/org-panel/propagate          → 执行传播，返回全图快照
POST /api/v1/org-panel/what-if            → 多参数what-if
GET  /api/v1/org-panel/chains             → 所有逻辑链及其传导状态
GET  /api/v1/org-panel/trace/{node_id}/{param_key} → 影响追踪
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from core.org_panel.presets import build_electronics_factory
from core.org_panel.signals import SignalType

router = APIRouter(prefix="/api/v1/org-panel", tags=["org-panel"])

# ── 全局引擎实例（单例） ──
_engine = None


def get_engine():
    """获取/初始化引擎单例"""
    global _engine
    if _engine is None:
        _engine = build_electronics_factory()
        _engine.propagate()  # 初始传播
    return _engine


# ==================== Schemas ====================

class ParamSetRequest(BaseModel):
    """参数调整请求"""
    param_key: str
    value: float


class WhatIfRequest(BaseModel):
    """What-If 请求：多参数同时调整"""
    adjustments: Dict[str, float]  # "node_id.param_key" → new_value


class PropagateResponse(BaseModel):
    """传播响应"""
    nodes: Dict[str, dict]
    violations: List[str]


# ==================== 端点 ====================

@router.get("/nodes")
def list_nodes(level: Optional[int] = Query(None, description="按层级过滤 (1-5)")):
    """获取所有组织节点列表（按层级排序）"""
    engine = get_engine()
    nodes = []
    for nid, node in sorted(engine.nodes.items(), key=lambda x: (x[1].level, x[0])):
        if level is not None and node.level != level:
            continue
        nodes.append({
            "node_id": node.node_id,
            "name": node.name,
            "level": node.level,
            "scope": node.scope,
            "param_count": len(node.parameters),
            "capability_count": len(node.capabilities),
            "has_violations": len(node.violations) > 0,
        })
    return {"nodes": nodes, "total": len(nodes)}


@router.get("/nodes/{node_id}/detail")
def node_detail(node_id: str):
    """获取节点微观数据快照（该角色视角看到的一切）"""
    engine = get_engine()
    if node_id not in engine.nodes:
        raise HTTPException(status_code=404, detail=f"节点 '{node_id}' 不存在")
    snap = engine.snapshot(node_id)
    return {
        "node_id": snap.node_id,
        "name": snap.name,
        "level": snap.level,
        "scope": snap.scope,
        "parameters": snap.parameters,
        "capabilities": snap.capabilities,
        "inputs": snap.inputs,
        "outputs": snap.outputs,
        "violations": snap.violations,
        "warnings": snap.warnings,
    }


@router.post("/nodes/{node_id}/param")
def set_param(node_id: str, req: ParamSetRequest):
    """调整某节点的某参数，自动传播并返回全图影响"""
    engine = get_engine()
    if node_id not in engine.nodes:
        raise HTTPException(status_code=404, detail=f"节点 '{node_id}' 不存在")
    node = engine.nodes[node_id]
    if req.param_key not in node.parameters:
        raise HTTPException(
            status_code=400,
            detail=f"参数 '{req.param_key}' 不存在。可用: {list(node.parameters.keys())}"
        )

    # 设值（自动截断）
    actual_value = engine.set_parameter(node_id, req.param_key, req.value)
    # 传播
    engine.propagate()

    # 收集违反
    all_violations = []
    for n in engine.nodes.values():
        all_violations.extend(n.violations)

    return {
        "node_id": node_id,
        "param_key": req.param_key,
        "requested_value": req.value,
        "actual_value": actual_value,
        "propagated": True,
        "violations": all_violations,
        "current_outputs": {
            nid: {k.label: round(v, 4) for k, v in n.output_signals.items()}
            for nid, n in engine.nodes.items()
        },
    }


@router.post("/propagate")
def propagate():
    """手动触发全图传播，返回所有节点最新状态"""
    engine = get_engine()
    engine.propagate()

    all_violations = []
    nodes_data = {}
    for nid, node in engine.nodes.items():
        nodes_data[nid] = {
            "name": node.name,
            "level": node.level,
            "outputs": {k.label: {"value": round(v, 4), "unit": k.unit} for k, v in node.output_signals.items()},
            "violations": node.violations,
        }
        all_violations.extend(node.violations)

    return {"nodes": nodes_data, "violations": all_violations}


@router.post("/what-if")
def what_if(req: WhatIfRequest):
    """多参数 What-If 分析（不修改引擎当前状态）
    
    adjustments 格式: {"line_leader.speed": 1.5, "line_leader.shifts": 3}
    """
    engine = get_engine()

    # 解析 "node_id.param_key" → (node_id, param_key)
    scenario: Dict[Tuple[str, str], float] = {}
    for composite_key, value in req.adjustments.items():
        parts = composite_key.split(".", 1)
        if len(parts) != 2:
            raise HTTPException(
                status_code=400,
                detail=f"键格式错误: '{composite_key}'，应为 'node_id.param_key'"
            )
        scenario[(parts[0], parts[1])] = value

    try:
        result = engine.what_if(scenario)
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "scenario": req.adjustments,
        "results": {
            nid: {
                "name": snap.name,
                "level": snap.level,
                "outputs": snap.outputs,
                "violations": snap.violations,
            }
            for nid, snap in result.items()
        },
    }


@router.get("/chains")
def list_chains():
    """获取所有逻辑链及其传导状态"""
    engine = get_engine()
    chains_data = []
    for chain in engine.chains:
        links_data = []
        for link in chain.links:
            # 获取当前传导值
            source_node = engine.nodes.get(link.source_node_id)
            current_value = None
            propagated_value = None
            if source_node and link.source_signal in source_node.output_signals:
                current_value = source_node.output_signals[link.source_signal]
                propagated_value = link.propagate(current_value)

            links_data.append({
                "source": link.source_node_id,
                "target": link.target_node_id,
                "signal": link.source_signal.label,
                "target_signal": link.target_signal.label,
                "label": link.label,
                "latency_h": link.latency_hours,
                "current_value": round(current_value, 4) if current_value is not None else None,
                "propagated_value": round(propagated_value, 4) if propagated_value is not None else None,
            })
        chains_data.append({
            "chain_id": chain.chain_id,
            "name": chain.name,
            "links": links_data,
            "involved_nodes": chain.get_involved_nodes(),
        })
    return {"chains": chains_data, "total": len(chains_data)}


@router.get("/trace/{node_id}/{param_key}")
def trace_impact(
    node_id: str,
    param_key: str,
    delta: float = Query(..., description="参数变化量（+/-）"),
):
    """影响追踪：如果某角色调了某参数（+delta），全链确定性影响"""
    engine = get_engine()
    if node_id not in engine.nodes:
        raise HTTPException(status_code=404, detail=f"节点 '{node_id}' 不存在")
    if param_key not in engine.nodes[node_id].parameters:
        raise HTTPException(status_code=400, detail=f"参数 '{param_key}' 不存在")

    report = engine.trace_impact(node_id, param_key, delta)
    return {
        "source_node": node_id,
        "param_key": param_key,
        "param_before": report.param_before,
        "param_after": report.param_after,
        "chain_path": report.chain_path,
        "impacts": [
            {
                "node_id": imp.node_id,
                "node_name": imp.node_name,
                "signal": imp.signal_label,
                "before": imp.before,
                "after": imp.after,
                "delta": imp.delta,
                "delta_pct": imp.delta_pct,
            }
            for imp in report.impacts
        ],
        "violations": report.violations,
    }


@router.get("/graph")
def graph_description():
    """获取全图的人类可读描述"""
    engine = get_engine()
    return {"description": engine.describe_graph()}


@router.post("/reset")
def reset_engine():
    """重置引擎到初始状态"""
    global _engine
    _engine = build_electronics_factory()
    _engine.propagate()
    return {"status": "reset", "message": "引擎已重置为电子厂初始状态"}
