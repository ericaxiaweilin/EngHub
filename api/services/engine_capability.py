"""把"人办一件事的三种能力"量成三格：推演 / 分析 / 总结。

分层验收（L1..L4）量的是引擎的**部件**：内核稳不稳、参数敏不敏感、和真实对不对得上、
能不能被问。这三格量的是另一件事 —— 一个人交办一件事时，他会依次要引擎给出：
  推演：给我会出现什么结果（哪个方案在坏天气下最不吃亏）；
  分析：告诉我为什么是这个结果、松哪一项值几天、这个数能信到几成；
  总结：把上面两件事说成一段人话，且不编。
前两格早有实测值散在 L2A/L2B/L3/契约自检里，第三格一直没有数 —— 于是"回答得像不像话"
只能靠人读，而人不可能逐条读 30 天的回复。这一页把三格统一成可判线的数。

三格的数都不新算：推演引用 L1..L4 的同名实测值，分析走对外契约的真实反事实，
总结用和 L4 同一把尺（reply_sanitizer 的 numeric_claims/is_disclosed）回查真实对话。
只读：不改工单、不写台账、不调模型。
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# 回答里"引用了引擎给的要点"要能核对：这些工具的返回带结构化要点，才谈得上覆盖率
HEADLINE_TOOLS = ("query_engine_attribution", "query_simulation_sensitivity",
                  "query_simulation_recommendation", "query_engine_capability_layers",
                  "query_sim_evidence_readiness", "virtual_factory_simulate")

# 判线：三格各自的门槛。定在这里、写清为什么，别散在文案里
THRESHOLDS = {
    "forecast_reproducible": 1.0,        # 同输入不同结果 = 三格全部作废
    "forecast_direction_hit": 1.0,       # 方向错就是模型坏，不是精度差
    "forecast_agreement": 0.70,          # 与台账同一口径的瓶颈件一致率（L2B 已定线）
    "analysis_relief_trustworthy": 0.60,  # 给出的"松哪项值几天"里方向可信的比例
    "analysis_explainable_orders": 0.80,  # 点名被哪一项卡住的单占比
    "summary_number_backing": 0.90,      # 正文数字有出处的比例（与 L4 同一把尺）
    "summary_gap_disclosure": 0.80,      # 引擎报了缺口的轮次里，答复点名了缺口的比例（下界）
}


def _nums(raw: Any) -> List[str]:
    """正文里的"数据读数"，与 L4 用同一条正则（年份/ID 片段不算，见 reply_sanitizer）。"""
    from core.kernel.reply_sanitizer import numeric_claims

    return [str(n).replace(",", "") for n in numeric_claims(str(raw or ""))]


def _hits(claims: List[str], corpus: str) -> List[str]:
    """能在语料里找到的读数。允许前 4 位命中：工具给 3,299.6 而正文写 3,299 是同一件事。"""
    hay = corpus.replace(",", "")
    return [n for n in claims
            if n in hay or (len(n) > 4 and n[:4] in hay)]


def headline_items(result: Any) -> List[str]:
    """一次工具返回里"人该被答复到"的要点：每条 metrics/unavailable 取它的中文面。

    为什么取中文面 —— 正文是中文转述，拿 `expedite_bottleneck_to_days` 这种字段名去比对
    正文永远比不中，覆盖率会假报成 0；判据必须打在答复真能带出来的那个串上。
    一条要点没有中文面（只有字段名）时退回字段名，并照数进分母 —— 那是真的没带到。
    """
    if isinstance(result, list):
        out: List[str] = []
        for one in result:
            out.extend(headline_items(one))
        return sorted(set(out))
    body = result if isinstance(result, dict) else {}
    blocks: List[Any] = [body, body.get("answers") or {}]
    layers = body.get("layers")
    if isinstance(layers, list):
        blocks.extend(layers)
    names: List[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        for key in ("metrics", "unavailable", "failed", "not_computable"):
            for item in block.get(key) or []:
                if isinstance(item, dict):
                    name = _surface(item)
                    if name:
                        names.append(name)
    return sorted(set(names))


_CJK = re.compile("[\u4e00-\u9fff]")


def _surface(entry: Dict[str, Any]) -> str:
    """要点在中文答复里长什么样：优先带汉字的那个标签，其次字段名。"""
    cands = [str(entry.get(k) or "").strip()
             for k in ("label", "metric", "ask", "name", "input")]
    cands = [c for c in cands if c]
    for c in cands:
        if _CJK.search(c):
            return c
    return cands[0] if cands else ""


# 答复里"点名了缺口"的字面记号。这是**下界**判据：带记号不等于把那条缺口说清了，
# 但一条都没有就一定是在静默降级 —— 所以它只用来判不及格，不用来宣布优秀。
GAP_WORDS = ("算不出", "没有算出", "无法", "拿不到", "没有依据", "未核实", "未经核实",
             "不可信", "缺", "no_evidence", "not_computable")

# 总结格的样本线：4 条回复算不出比例，只算线索；够 10 条才判。
MIN_SUMMARY_REPLIES = 10


def summary_score(replies: List[Dict[str, Any]]) -> Dict[str, Any]:
    """总结格：正文里的数字有没有出处；引擎报的缺口有没有被带进答复。

    出处语料按**会话**算：上一轮查到的数这一轮引用是正常且必要的，只有整个会话里
    都找不到出处的数才是编的。人自己报给引擎的数单列（numbers_from_user），不进判线分母。
    缺口那一半不逐字比要点标题 —— 引擎的 unavailable[].ask 是一句 15 字指令，
    中文转述不可能原样带出来，逐字比会永远得 0，那是尺错不是答复错。
    """
    from core.kernel.reply_sanitizer import is_disclosed

    backed = unbacked = disclosed = 0
    from_user = 0
    gap_items = replies_with_gaps = gap_named_replies = 0
    verbatim_num = verbatim_den = 0
    per_reply: List[Dict[str, Any]] = []
    for row in replies:
        reply = str(row.get("content") or "")
        claims = _nums(reply)
        gaps = headline_items(_result_of(row.get("tool_json"), only="unavailable"))
        items = headline_items(_result_of(row.get("tool_json")))
        if items:
            verbatim_den += len(items)
            verbatim_num += sum(1 for it in items if it in reply)
        if gaps:
            gap_items += len(gaps)
            replies_with_gaps += 1
            if any(w in reply for w in GAP_WORDS):
                gap_named_replies += 1
        if not claims:
            continue
        eng = _hits(claims, str(row.get("session_tools") or ""))
        usr = _hits([c for c in claims if c not in eng], str(row.get("session_user") or ""))
        still = [c for c in claims if c not in eng and c not in usr]
        from_user += len(usr)
        if not eng and usr and not still:
            # 这条回复的数全部来自人自己说的话：这一轮不判引擎（既不算有出处也不算编）
            continue
        if not still:
            backed += 1
        elif is_disclosed(reply):
            disclosed += 1
        else:
            unbacked += 1
            if len(per_reply) < 6:
                per_reply.append({"session": str(row.get("session_id") or "")[:8],
                                  "numbers": still[:4],
                                  "excerpt": re.sub(r"\s+", " ", reply)[:110]})
    judged = backed + disclosed + unbacked
    return {
        "replies_scanned": len(replies),
        "replies_with_claims": judged,
        "numbers_backed": backed, "numbers_disclosed": disclosed, "numbers_unbacked": unbacked,
        "numbers_from_user": from_user,
        "number_backing_rate": round((backed + disclosed) / judged, 3) if judged else None,
        "engine_gap_items": gap_items,
        "replies_with_engine_gaps": replies_with_gaps,
        "gap_named_replies": gap_named_replies,
        "gap_disclosure_rate": (round(gap_named_replies / replies_with_gaps, 3)
                                if replies_with_gaps else None),
        "headline_verbatim_rate": round(verbatim_num / verbatim_den, 3) if verbatim_den else None,
        "unbacked_samples": per_reply,
        "meaning": ("「数字有出处率」分母=窗口内报过数字且本会话调过引擎工具的助手回复；"
                    "「缺口点名率」分母=引擎返回里带 unavailable 的那几轮，是下界判据（只用来判不及格）；"
                    "人自己报的数单列在 numbers_from_user，不算引擎编的"),
    }


def _as_list(raw: Any) -> List[Any]:
    if isinstance(raw, list):
        return raw
    try:
        parsed = json.loads(str(raw or "[]"))
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _result_of(tool_calls_raw: Any, only: Optional[str] = None) -> List[Dict[str, Any]]:
    """一条回复里的各工具返回体（库里存成 [{tool,result},...]，要点在各 result 里）。"""
    out: List[Dict[str, Any]] = []
    for el in (tool_calls_raw if isinstance(tool_calls_raw, list) else _as_list(tool_calls_raw)):
        if not isinstance(el, dict):
            continue
        if str(el.get("tool") or "") not in HEADLINE_TOOLS:
            continue
        res = el.get("result")
        if isinstance(res, dict):
            out.append(res)
    if only == "unavailable":
        return [r for r in out if (r.get("unavailable") or r.get("failed")
                                   or (r.get("answers") or {}).get("unavailable"))]
    return out


def _as_dict(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(str(raw or "{}"))
    except (TypeError, ValueError):
        return {}


def analysis_score(attribution: Dict[str, Any]) -> Dict[str, Any]:
    """分析格：归因是否点名了卡点、给出的改善建议里有几条方向可信、有没有把噪声当建议。"""
    answers = attribution.get("answers") or {}
    relief = answers.get("relief_attribution") or []
    states: Dict[str, int] = {}
    for r in relief:
        states[str(r.get("state") or "unknown")] = states.get(str(r.get("state") or "unknown"), 0) + 1
    constraint = answers.get("constraint_attribution") or {}
    per_order = constraint.get("per_order") or []
    named = sum(1 for o in per_order if o.get("constrained_by"))
    # no_effect_measured 也是测出来的：它如实说"这一维现在不是约束"，可信但不该当动作建议
    UNTRUSTWORTHY = ("suspicious_direction", "unknown_expectation")
    trusted = [r for r in relief if str(r.get("state") or "") not in UNTRUSTWORTHY]
    actionable = [r for r in relief if r.get("state") == "measured"]
    targeted = {str(t) for r in actionable for t in (r.get("relieves") or ())}

    def _codes(order: Dict[str, Any]) -> List[str]:
        return [str(c.get("code")) if isinstance(c, dict) else str(c)
                for c in (order.get("constrained_by") or [])]

    orders_with_lever = sum(1 for o in per_order if targeted & set(_codes(o)))
    return {
        "relief_entries": len(relief), "relief_states": states,
        "trustworthy_rate": (round(len(trusted) / len(relief), 3) if relief else None),
        "actionable_rate": (round(len(actionable) / len(relief), 3) if relief else None),
        "orders_explained": named, "orders_total": len(per_order),
        "explainable_rate": round(named / len(per_order), 3) if per_order else None,
        "orders_with_an_actionable_lever": orders_with_lever,
        "refuses_noise_advice": bool(all(r.get("do_this") is None
                                         for r in relief if r.get("state") != "measured")),
        "meaning": ("「方向可信率」= 不是 suspicious_direction/unknown_expectation 的比例（含如实测出 0 效果的项）；"
                    "「可当动作的比例」另有 actionable_rate —— 0 效果项可信，但不该写成动作；"
                    "「拒绝把 0 效果项写成动作」必须是 true，否则计划员会被推着去做没用的事"),
    }


async def _load_replies(db: AsyncSession, factory_id: str, days: int) -> List[Dict[str, Any]]:
    """本厂区近 N 天里调过引擎工具的助手回复，带上整会话的出处语料。

    chat_messages 没有 factory_id —— 厂区挂在 chat_sessions 上，所以按会话 join。
    """
    rows = (await db.execute(text("""
        SELECT m.session_id, m.content, m.tool_calls::text AS tool_json, m.created_at
        FROM chat_messages m
        JOIN chat_sessions s ON s.id = m.session_id
        WHERE s.factory_id = :fid
          AND m.role = 'assistant' AND COALESCE(m.content,'') <> ''
          AND m.created_at > NOW() - make_interval(days => :days)
          AND EXISTS (SELECT 1 FROM jsonb_array_elements(CASE WHEN jsonb_typeof(m.tool_calls)='array' THEN m.tool_calls ELSE '[]'::jsonb END) e
                       WHERE e->>'tool' = ANY(CAST(:tools AS text[])))
        ORDER BY m.created_at DESC
        LIMIT 120
    """), {"fid": factory_id, "days": days, "tools": list(HEADLINE_TOOLS)})).mappings().all()
    out = [dict(r) for r in rows]
    sids = sorted({str(r["session_id"]) for r in out})
    if not sids:
        return out
    corpus = (await db.execute(text("""
        SELECT session_id,
               COALESCE(string_agg(CASE WHEN role='assistant'
                                        THEN COALESCE(tool_calls::text,'') END, ' '), '') AS tools,
               COALESCE(string_agg(CASE WHEN role='user'
                                        THEN COALESCE(content,'') END, ' '), '') AS users
        FROM chat_messages
        WHERE session_id = ANY(CAST(:sids AS text[])) AND role IN ('assistant','user')
        GROUP BY session_id
    """), {"sids": sids})).mappings().all()
    by_sid = {str(c["session_id"]): c for c in corpus}
    for r in out:
        c = by_sid.get(str(r["session_id"])) or {}
        r["session_tools"] = str(c.get("tools") or "")
        r["session_user"] = str(c.get("users") or "")
    return out


async def capability_profile(db: AsyncSession, factory_id: str, models: List[str], *,
                             layers: Optional[Dict[str, Any]] = None,
                             days: int = 30, use_cache: bool = True) -> Dict[str, Any]:
    """三格一起出：每格给判据、给实测值、给"这格现在能不能判"。

    推演格的数不在这里算 —— 引用分层验收（L1..L4）里的同名实测值，避免同一件事两套尺。
    """
    from api.services.engine_contract import attribution as contract_attribution

    out: Dict[str, Any] = {"factory_id": factory_id, "window_days": days,
                           "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                           "models": models}
    # ── 分析格：走对外契约，拿真实反事实 ────────────────────────────────
    try:
        req = {"models": models[:3], "n_models": len(models[:3]) or 1,
               "as_of": datetime.now(timezone.utc).date().isoformat(),
               "conditions": {"weather": "storm"},
               "compare": {"baseline": {},
                           "alternative": {"purchase_lead_time": {"value": 50,
                                                                  "unit": "percent_of_record"}}}}
        out["analysis"] = analysis_score(await contract_attribution(db, factory_id, req))
    except Exception as exc:  # noqa: BLE001 - 一格查崩不拖垮整份画像，但必须写出来
        out["analysis"] = {"error": f"{type(exc).__name__}: {exc}"}
    # ── 总结格：回查真实对话 ──────────────────────────────────────────
    try:
        out["summary"] = summary_score(await _load_replies(db, factory_id, days))
    except Exception as exc:  # noqa: BLE001
        out["summary"] = {"error": f"{type(exc).__name__}: {exc}"}
    # ── 推演格：引用分层验收 ──────────────────────────────────────────
    if layers is None:
        import asyncio

        from api.services.engine_layers import layered_acceptance
        try:
            layers = await asyncio.wait_for(
                layered_acceptance(db, factory_id, models, use_cache=use_cache), timeout=900)
        except Exception as exc:  # noqa: BLE001 - 同上，这一格崩了要写出来
            layers = {"error": f"{type(exc).__name__}: {exc}"}
    out["forecast"] = forecast_score(layers)

    f, a, s = out["forecast"], out["analysis"], out["summary"]
    out["verdict"] = {
        "推演": _verdict(f, [("同输入可复现率", "forecast_reproducible"),
                          ("方向命中率", "forecast_direction_hit"),
                          ("瓶颈件一致率（提前期口径）", "forecast_agreement")]),
        "分析": _verdict(a, [("trustworthy_rate", "analysis_relief_trustworthy"),
                           ("explainable_rate", "analysis_explainable_orders")],
                        extra_true=[("refuses_noise_advice", "拒绝把 0 效果项写成动作")]),
        "总结": _verdict(s, [("number_backing_rate", "summary_number_backing"),
                           ("gap_disclosure_rate", "summary_gap_disclosure")],
                         min_n=("replies_with_claims", MIN_SUMMARY_REPLIES)),
    }
    out["rule"] = ("三格分别是：推演=给结果（复现/方向/与台账一致）、分析=给原因（点名卡点 + "
                   "反事实可信 + 不把噪声当建议）、总结=给一段不编的话（数字有出处 + 引擎给的要点被带到）。"
                   "任何一格算不出就写算不出并点名缺什么，不给 0 分。")
    return out


def forecast_score(layers: Dict[str, Any]) -> Dict[str, Any]:
    """推演格的四个数全部引用分层验收的同名实测值；闸门 None = 四层全过线。"""
    keys = ("同输入可复现率", "方向命中率", "瓶颈件一致率（提前期口径）",
            "推荐相对基线的再跑差值（暴雨档）")
    if layers.get("error"):
        out = {k: None for k in keys}
        out.update({"error": layers["error"], "闸门": None, "可引用层": None})
        return out
    vals: Dict[str, Any] = {}
    for lay in layers.get("layers") or []:
        for m in lay.get("metrics") or []:
            vals[str(m.get("metric"))] = m.get("value")
    out = {k: vals.get(k) for k in keys}
    out["闸门"] = (layers.get("gate") or {}).get("first_unmet_layer")
    out["可引用层"] = (layers.get("gate") or {}).get("reportable_through")
    out["meaning"] = "这四个数就是 L1/L2A/L2B/L3 里的同名实测值，画像不另算一套尺"
    return out


def _verdict(block: Dict[str, Any], checks: List[tuple],
             extra_true: Optional[List[tuple]] = None,
             min_n: Optional[tuple] = None) -> Dict[str, Any]:
    if block.get("error"):
        return {"state": "not_computable", "missing": f"这一格查崩了：{block['error']}"}
    if min_n is not None:
        key, need = min_n
        got_n = int(block.get(key) or 0)
        if got_n < need:
            return {"state": "not_computable",
                    "missing": f"样本不足：{key}={got_n}，判线要 ≥{need} —— 不够就不判，也不给 0 分",
                    "n": got_n}
    items, fails = [], []
    for key, thr in checks:
        val = block.get(key)
        if val is None:
            fails.append(f"{key} 算不出")
            continue
        ok = float(val) >= THRESHOLDS[thr]
        items.append({"metric": key, "value": val, "threshold": THRESHOLDS[thr], "pass": ok})
        if not ok:
            fails.append(f"{key}={val} 低于判线 {THRESHOLDS[thr]}")
    for key, label in (extra_true or []):
        if block.get(key) is not True:
            fails.append(f"{label} 未成立")
    return {"state": "pass" if not fails else "fail", "checks": items, "failed": fails}
