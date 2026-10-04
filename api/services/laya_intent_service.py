"""Laya System-1 意图路由客户端 —— Phase 1：从影子接进线上。

Laya（Convai Innovations，`laya==0.3.24`）是一个**非自回归 System 1 决策引擎**：
给一句用户话 + 一组候选 criteria，返回带校准概率的 choice。它只回答
「这句话属于哪一类意图」，**不做业务决策**（业务规则在
`api/services/factory_commander.py`）。

影子阶段（`~/laya-shadow`）已经用线上真实消息跑了几十轮。本模块把同一套
8 类意图接到线上确定性路由（`chat_tools_service.resolve_intent`）上。

三种模式（`LAYA_INTENT_MODE`）：

==================  ==========================================================
off                 完全不调用，回退纯关键词路由
fallback（默认）      仅当关键词路由**没命中**时才问 Laya —— 零回归
primary             先问 Laya；命中且置信度够就用它，否则回退关键词
==================  ==========================================================

安全约束（这几条比"接上"更重要）：

1. **任何异常都返回 None**：超时、连不上、JSON 解析失败、非 200 —— 一律当作
   "没有意见"，绝不抛出、绝不改变原有路由行为。
2. **置信度门槛**：低于 `LAYA_MIN_CONFIDENCE`（默认 0.6）一律视为不确定。
3. **只映射能一一对应的意图**：8 类里只有 3 类能明确对应到线上工具，其余
   返回 None。宁可不动，也不要猜错工具把用户带偏。
4. **熔断**：连续失败 `_FAIL_THRESHOLD` 次后冷却 `_COOLDOWN_SECONDS` 秒，
   避免 sidecar 挂掉时每个请求都白等一个超时。
5. 本客户端是**同步** urllib（`resolve_intent` 是同步函数），所以超时必须短。

⚠️ 已知代价（要盯着的一条）：`resolve_intent` 的调用点都在 `async` 路由里
（`chat_routes._handle_kernel_chat` / `_legacy_chat_disabled` / `_legacy_stream_disabled`），
而本客户端是同步阻塞的 —— 所以一次 Laya 调用会**阻塞事件循环**最多
`LAYA_TIMEOUT_SECONDS`。当前把默认超时压到 0.5s，且默认 `fallback` 模式只在关键词
**没命中**时才调用（真实流量绝大多数会命中关键词），因此线上影响是「偶发、有界」的。
彻底消除阻塞的做法是把调用点改成 `await asyncio.to_thread(resolve_intent, text)`
（或在本模块提供 async 变体）—— 列为下一步加固项，不在本次接线范围内。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.request

_logger = logging.getLogger(__name__)

# ── 配置 ────────────────────────────────────────────────────────────────────
DEFAULT_URL = "http://host.docker.internal:14200"
DEFAULT_MODE = "fallback"
DEFAULT_MIN_CONFIDENCE = 0.6
# 同步阻塞调用：超时即事件循环停顿时长上限。热态 Laya 实测 ~10-20ms（冷态 p90 423ms），
# 0.5s 已很宽裕；连不上时 socket 会立即报错，不会等满超时。
DEFAULT_TIMEOUT = 0.5
VALID_MODES = ("off", "fallback", "primary")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        return default


def sidecar_url() -> str:
    return (os.getenv("LAYA_SIDECAR_URL") or DEFAULT_URL).rstrip("/")


def mode() -> str:
    m = (os.getenv("LAYA_INTENT_MODE") or DEFAULT_MODE).strip().lower()
    return m if m in VALID_MODES else DEFAULT_MODE


def min_confidence() -> float:
    return _env_float("LAYA_MIN_CONFIDENCE", DEFAULT_MIN_CONFIDENCE)


def timeout_seconds() -> float:
    return _env_float("LAYA_TIMEOUT_SECONDS", DEFAULT_TIMEOUT)


def is_enabled() -> bool:
    return mode() != "off"


# ── 意图口径（与影子 `~/laya-shadow/sampler.py` 的 CRITERIA 保持一致） ──────
INTENT_CRITERIA = {
    "查库存": "查询物料库存、库存数量、容量占比、出入库",
    "查工单": "查询工单、在制工单、工单状态和进度",
    "排产计划": "排产、生产计划、交期、下达工单",
    "工艺路线BOM": "工艺路线、BOM、物料清单、产品结构",
    "设备状态": "设备状态、停机、维修保养、点检",
    "预警异常": "预警、异常、合规检查、报警",
    "确认继续": "确认、同意、继续执行上一轮的提议",
    "其他闲聊": "打招呼、闲聊、无法归类",
}

# 只有能与线上工具一一对应的意图才给映射。其余（排产计划/工艺路线BOM/
# 预警异常/确认继续/其他闲聊）语义太宽或根本不是"查工具"，一律不给工具，
# 让原来的模型编排去处理。
INTENT_TO_TOOL = {
    "查库存": "query_inventory",
    "查工单": "query_work_orders",
    "设备状态": "query_equipment",
}

# ── 熔断 ────────────────────────────────────────────────────────────────────
_FAIL_THRESHOLD = 3
_COOLDOWN_SECONDS = 60.0
_lock = threading.Lock()
_fail_count = 0
_open_until = 0.0


def _circuit_open() -> bool:
    with _lock:
        return time.monotonic() < _open_until


def _record(ok: bool) -> None:
    global _fail_count, _open_until
    with _lock:
        if ok:
            _fail_count = 0
            _open_until = 0.0
            return
        _fail_count += 1
        if _fail_count >= _FAIL_THRESHOLD:
            _open_until = time.monotonic() + _COOLDOWN_SECONDS
            _fail_count = 0
            _logger.warning(
                "[laya] sidecar 连续失败，熔断 %.0fs", _COOLDOWN_SECONDS,
            )


def circuit_state() -> dict:
    """给健康检查/诊断用。"""
    with _lock:
        return {"open": time.monotonic() < _open_until,
                "open_until_in": max(0.0, _open_until - time.monotonic()),
                "fail_count": _fail_count}


# ── 调用 ────────────────────────────────────────────────────────────────────
def classify(text: str) -> dict | None:
    """问 Laya 这句话属于哪类意图。

    返回 ``{"intent", "confidence", "probabilities", "ms"}``；
    任何问题（禁用/熔断/超时/解析失败）都返回 ``None``。
    """
    if not is_enabled() or not text:
        return None
    if _circuit_open():
        return None

    body = json.dumps({
        "state": text,
        "questions": {"intent": {
            "type": "choice",
            "instructions": "用户这句话是想做什么？只选其一。",
            "criteria": INTENT_CRITERIA,
        }},
    }, ensure_ascii=False).encode()

    req = urllib.request.Request(
        sidecar_url() + "/v1/systemone",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds()) as resp:
            if resp.status != 200:
                _record(False)
                return None
            payload = json.load(resp)
    except Exception as exc:  # noqa: BLE001 — 任何异常都不得影响主链路
        _record(False)
        _logger.debug("[laya] classify 失败: %s: %s", type(exc).__name__, exc)
        return None

    _record(True)
    try:
        ans = (payload.get("answers") or {}).get("intent") or {}
        probs = ans.get("probabilities") or {}
        intent = ans.get("choice") or (max(probs, key=probs.get) if probs else None)
        return {
            "intent": intent,
            "confidence": ans.get("confidence"),
            "probabilities": probs,
            "ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as exc:  # noqa: BLE001
        _logger.debug("[laya] 解析响应失败: %s", exc)
        return None


def resolve_tool(text: str) -> dict | None:
    """把 Laya 的意图映射成线上工具。

    返回 ``{"tool", "args", "intent", "confidence", "source": "laya"}``；
    置信度不足、意图无对应工具、或调用失败时返回 ``None``。
    """
    hit = classify(text)
    if not hit or not hit.get("intent"):
        return None
    conf = hit.get("confidence")
    if conf is not None and conf < min_confidence():
        return None
    tool = INTENT_TO_TOOL.get(hit["intent"])
    if not tool:
        return None
    return {"tool": tool, "args": {}, "intent": hit["intent"],
            "confidence": conf, "source": "laya"}


def health() -> dict:
    """诊断用：sidecar 是否可达 + 熔断状态 + 当前配置。"""
    reachable = False
    detail = None
    try:
        with urllib.request.urlopen(sidecar_url() + "/health", timeout=2.0) as r:
            reachable = r.status == 200
            detail = json.load(r)
    except Exception as exc:  # noqa: BLE001
        detail = f"{type(exc).__name__}: {exc}"
    return {
        "enabled": is_enabled(),
        "mode": mode(),
        "url": sidecar_url(),
        "min_confidence": min_confidence(),
        "timeout_seconds": timeout_seconds(),
        "reachable": reachable,
        "sidecar": detail,
        "circuit": circuit_state(),
        "mapped_intents": INTENT_TO_TOOL,
    }
