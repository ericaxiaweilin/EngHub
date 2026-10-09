"""引擎自己的故障要自己报出来，不等人去翻 /engine-layers。

10-06 那次心跳断写，是人在库里翻出来的：从我改坏到修好之间几个小时，所有循环的
读数都停在"上一次成功"上，而分层验收页看起来仍然是绿的。这一页把判据变成动作 ——
心跳断写、循环退出、窗口崩溃越线，自动挂一条催办；恢复了它自己关掉。

判据不在这里另立一套：阈值直接取 engine_layers.THRESHOLDS["L1"]，
所以催办上写的数和分层验收那格是同一个数，不会出现"待办说过线、页面说没"。

写入口只有 followup_task_service.create_task 一个（通知、日志、状态机都在那儿）；
关闭与刷新沿用 followup_lifecycle 的写法：一条 (loop, kind) 只留一条未关闭催办，
签名没变就不动库，避免每 10 分钟给人新挂一条。
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

CATEGORY = "engine_watchdog"
# 引擎跑不跑得动是一回事，判据被数据封顶是另一回事：L2B 那几格卡在台账登记世代时，
# 报告里只是一句"覆盖率 0.25 fail"，没人被派活。数据缺口走同一条对账/催办通路，
# 换一个新类别，让收件箱里"补数据"和"救引擎"不混成一堆。
DATA_CATEGORY = "engine_data_gap"
DATA_FOLLOW_INTERVAL_MINUTES = 24 * 60
CREATED_BY = "virtual_factory"
AGENT_KEY = "escalation_agent"
FOLLOW_INTERVAL_MINUTES = 60

# 催办挂在哪个厂区的收件箱。引擎循环是全局的（不分厂区跑），但 followup_tasks 按厂区取，
# 所以点名一个真有人看的收件箱 —— 挂到没人看的厂区等于没挂。
DEFAULT_FACTORY_ID = os.getenv("ENGINE_WATCHDOG_FACTORY_ID", "FAC_MECH_001")

# 一次性任务：跑完就退出是设计如此，把它当"引擎停了"催人是假警报。
ONE_SHOT_LOOPS = {"skill-seed"}

STALLED = "heartbeat_stalled"
FAILED = "loop_failed"
EXITED = "loop_exited"
NEVER = "never_confirmed"
CRASH = "crash_over_line"

CHECK_HINT = ("复核：GET /api/v1/pmc/engine-layers（L1 那格用的就是这些数）、"
              "docker logs enghub-engine --tail 50")

OPEN_SQL = text("""
    SELECT id, title, description, status, payload, created_at
    FROM followup_tasks
    WHERE factory_id = :fid AND status NOT IN ('done', 'cancelled')
      AND payload->>'category' = :cat
    ORDER BY created_at DESC
""")


# read_states 的判死线是 2×标称间隔，那一格报"新鲜度"没问题；拿它直接挂催办会误报：
# periodic-scheduler 的一轮要跑多少时间取决于这一轮里落了哪几道闸门（日报/BOM 同步是 4-6 小时一道，
# 落进同一轮时单轮就能 >240 秒），10-07 实测就被这样连挂过两条"断写"。
# 所以挂催办要再宽一倍：真死的循环会一直不过线，正常的长轮下一轮就自己回来了。
STALL_RAISE_FACTOR = 2


def stall_deadline_seconds(row: Dict[str, Any]) -> float:
    interval = int(row.get("interval_seconds") or 0)
    return max(interval, 1) * 2 * STALL_RAISE_FACTOR


# ── 判据：台账 → 需要人看的条目（纯函数，不动库）────────────────────────────
def is_down(row: Dict[str, Any]) -> bool:
    """这个循环现在能不能被算成"没在跑"。

    分两种死法：台账「自己报出来的」（failed / exited）是事实，立刻成立；
    靠"没动静"推断出来的（只记到 spawned 或状态不认识）要给宽限 ——
    read_states 把"活着"定义成"逐轮心跳新鲜"，刚起来的进程那一笔是 spawned，
    没有宽限就会在引擎重启后的头 1-2 分钟挂出 N 条"从未在跑"的假警报。
    """
    if row.get("alive"):
        return False
    status = str(row.get("last_status") or "")
    loop = str(row.get("loop") or "")
    if status == "tick":
        # 报着报着不跳了：判死线在新鲜度之上再宽一倍（见 STALL_RAISE_FACTOR）
        return float(row.get("stale_seconds") or 0) > stall_deadline_seconds(row)
    if status in ("failed", "exited"):
        # 引擎自己记下"这一跳崩了/这循环结束了"就是事实：每轮失败都会把 last_tick_at 刷新，
        # 再等 2 个间隔就永远等不到 —— 恢复了 last_status 会变回 tick，这条判据自己就消失。
        return status == "failed" or loop not in ONE_SHOT_LOOPS
    return float(row.get("stale_seconds") or 0) > stall_deadline_seconds(row)


def _one_line(value: Any, limit: int = 200) -> str:
    return " ".join(str(value or "").split())[:limit]


def _fmt_span(seconds: Optional[float]) -> str:
    if seconds is None:
        return "时长未知"
    span = float(seconds)
    if span < 3600:
        return f"{span / 60:.0f} 分钟"
    if span < 86400:
        return f"{span / 3600:.1f} 小时"
    return f"{span / 86400:.1f} 天"


def _stamp(value: Any) -> str:
    """心跳时刻报成人话。列里存的是 UTC 墙钟，不写 UTC 就会被当成本地时间差 8 小时。"""
    if not value:
        return "（库里没有心跳记录）"
    return f"{str(value)[:19].replace('T', ' ')} UTC"


def _recent_errors(row: Dict[str, Any], limit: int = 3) -> List[str]:
    raw = row.get("recent_errors")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "[]")
        except json.JSONDecodeError:
            raw = []
    out: List[str] = []
    for item in (raw or [])[:limit]:
        if isinstance(item, dict):
            out.append(f"{str(item.get('at') or '')[:16]} {_one_line(item.get('error'), 160)}")
        else:
            out.append(_one_line(item, 160))
    return out


def _rate_bucket(rate: Any) -> float:
    """崩溃率进签名的粒度：5% 一档。每跳都重算的浮点原值会把催办刷成日志。"""
    return round(round(float(rate) * 20) / 20, 2)


def _evidence(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "loop": str(row.get("loop") or ""),
        "host": row.get("host"),
        "pid": row.get("pid"),
        "interval_seconds": row.get("interval_seconds"),
        "stale_seconds": row.get("stale_seconds"),
        "last_tick_at": str(row.get("last_tick_at") or ""),
        "last_status": str(row.get("last_status") or ""),
        "last_error": _one_line(row.get("last_error"), 200),
        "recent_errors": _recent_errors(row),
        "window_started_at": str(row.get("window_started_at") or ""),
        "window_ticks": int(row.get("window_ticks") or 0),
        "window_failures": int(row.get("window_failures") or 0),
        "window_crash_rate": row.get("window_crash_rate"),
    }


def findings(states: List[Dict[str, Any]], *, crash_rate_limit: float,
             min_window_ticks: int) -> List[Dict[str, Any]]:
    """把心跳台账换成"哪几个循环需要人看"，只出判定。

    进签名的是停跳的时刻、错误类型、窗口起始日、崩溃率档位这几件人会用来自做决定的事；
    "已断 3.1 小时 / 3.2 小时"这种每轮都动的数只出现在正文里 —— 拿它当签名就会每 10 分钟
    刷新一次待办，跟进日志被同一条故障刷满。
    """
    # 台账是全局的：整台引擎进程停掉时，所有循环会一起不再跳。
    # 那时挂出来的是 N 条"独立故障"，人得先看 docker ps 而不是逐个查代码 —— 所以把同时停跳
    # 的台数算出来写进正文。判据不变（每条还是各挂各的），只是别让人误以为是 N 个 bug。
    stopped = [row for row in states if is_down(row)]
    concurrent = len(stopped)
    out: List[Dict[str, Any]] = []
    for row in states:
        ev = _evidence(row)
        status = ev["last_status"]

        if is_down(row):
            kind = (STALLED if status == "tick" else
                    FAILED if status == "failed" else
                    EXITED if status == "exited" else NEVER)
            out.append(_build(ev, kind, crash_rate_limit, min_window_ticks, concurrent))

        rate = ev["window_crash_rate"]
        if (rate is not None and ev["window_ticks"] >= min_window_ticks
                and float(rate) > float(crash_rate_limit)):
            out.append(_build(ev, CRASH, crash_rate_limit, min_window_ticks, concurrent))
    return out


def _build(ev: Dict[str, Any], kind: str, crash_rate_limit: float,
           min_window_ticks: int, concurrent: int = 1) -> Dict[str, Any]:
    loop = ev["loop"]
    interval = ev["interval_seconds"] or 0
    deadline = (f"2 × {int(interval)} 秒 × {STALL_RAISE_FACTOR}（新鲜度判线再宽一倍的挂线）"
                if interval else "预期间隔未知")
    span = _fmt_span(ev["stale_seconds"])
    errors = ev["recent_errors"]
    rate = ev["window_crash_rate"]
    facts = {**ev, "kind": kind, "crash_rate_limit": float(crash_rate_limit),
             "min_window_ticks": int(min_window_ticks),
             "loops_not_ticking": int(concurrent)}

    if kind == STALLED:
        sig = f"stalled|{_stamp(ev['last_tick_at'])}"
        severity = "critical"
        title = f"引擎｜{loop} 心跳断写：最后一次跳动距今 {span}"
        why = (f"还在报逐轮心跳的循环，最近一跳已超过判死线（{deadline}）。"
               f"最后一次心跳 {_stamp(ev['last_tick_at'])}，距今 {span}。\n"
               f"这一停，L1 以上所有读数都停在\u201c上一次成功\u201d上 —— 分层验收页看着仍是绿的，"
               f"但它证明不了引擎在跑。")
        block = f"{loop} 心跳断写 {span}，需确认循环是卡住还是已退出"
    elif kind == FAILED:
        head = _one_line((errors[-1] if errors else ev["last_error"]).split(":")[0], 60)
        sig = f"failed|{head}|{str(ev['last_tick_at'])[:10]}"
        severity = "critical"
        title = f"引擎｜{loop} 异常退出后没再跳出心跳（{span}无心跳）"
        why = (f"循环抛异常退出，退避 30 秒重启后到现在没有新心跳（最后一次记录 "
               f"{_stamp(ev['last_tick_at'])}）。\n"
               f"引擎侧记到的错误原文见下，改一次代码要能同时看到错误小环。")
        block = f"{loop} failed 且 {span} 无心跳"
    elif kind == EXITED:
        sig = f"exited|{str(ev['last_tick_at'])[:16]}"
        severity = "critical"
        title = f"引擎｜{loop} 自行返回，引擎不再重启它"
        why = (f"注册成无限循环的任务自己返回了（记录 {_stamp(ev['last_tick_at'])}，"
               f"距今 {span}）。按 engine_runner 的口径，返回 = 结束，不再重启 —— "
               f"这一格以前只在 _supervise 的日志里出现过一次。")
        block = f"{loop} 自行结束，需要人来决定是重启还是收掉这条注册"
    elif kind == NEVER:
        sig = f"never|{ev['last_status'] or 'unknown'}|{str(ev['last_tick_at'])[:10]}"
        severity = "warning"
        title = f"引擎｜{loop} 起过进程但一跳到过完（状态 {ev['last_status'] or 'unknown'}）"
        why = (f"台账里这条只有进程起来那一笔（last_status={ev['last_status'] or 'unknown'}），"
               f"距今 {span} 没有逐轮心跳：没人能证明它在跑，也不能说它活着。\n"
               f"上次错误原文：{ev['last_error'] or '（无）'}")
        block = f"{loop} 从未确认在跑"
    else:
        bucket = _rate_bucket(rate)
        sig = f"crash|{ev['window_started_at'][:10]}|{bucket:.2f}"
        severity = "warning"
        title = (f"引擎｜{loop} 窗口崩溃率 {float(rate):.1%}"
                 f"（{ev['window_failures']}/{ev['window_ticks']} 跳）超 L1 判线 "
                 f"{float(crash_rate_limit):.0%}")
        why = (f"窗口自 {_stamp(ev['window_started_at'])} 起 {ev['window_ticks']} 跳里失败 "
               f"{ev['window_failures']} 跳 = {float(rate):.1%}，判线 ≤{float(crash_rate_limit):.0%}。"
               f"过线意味着这一层以上的数不可引用；累计口径里那些查不到成因的历史失败不算在这里，"
               f"但窗口内的每一次都有错误小环可查。")
        block = f"{loop} 窗口崩溃率 {float(rate):.1%} 越过 {float(crash_rate_limit):.0%}"

    lines = [why, ""]
    if kind != CRASH and concurrent >= 3:
        lines.insert(1, (f"注意：台账上同时有 {concurrent} 个循环没在跳。引擎的循环跑在同一个进程里，"
                         f"一起停跳更像整个进程停了（先看 docker ps enghub-engine 与最后一次重启时间），"
                         f"而不是 {concurrent} 个独立故障。"))
    if errors:
        lines.append("最近错误小环（引擎逐跳记的原文，不是复述）：")
        lines.extend(f"· {e}" for e in errors)
    elif ev["last_error"]:
        lines.append(f"最近错误：{ev['last_error']}")
    lines.append("")
    lines.append(f"台账读数：loop={loop} host={ev['host']} pid={ev['pid']} "
                 f"预期间隔={interval}s 窗口内 ticks={ev['window_ticks']} "
                 f"failures={ev['window_failures']}")
    lines.append(CHECK_HINT)
    return {
        "loop": loop, "kind": kind, "sig": f"{loop}|{sig}"[:200],
        "severity": severity, "title": title[:200],
        "description": "\n".join(lines)[:4000], "block_reason": block[:500],
        "evidence": facts,
    }


# ── 对账：新挂 / 刷新 / 关闭 / 不动（纯函数）───────────────────────────────
def plan_actions(open_tasks: List[Dict[str, Any]],
                 found: List[Dict[str, Any]], *,
                 protected_loops: Optional[frozenset] = None) -> List[Dict[str, Any]]:
    """一条 (loop, kind) 只留一条未关闭催办；签名没变就不动库。

    同一键下的历史重复条目（旧版本代码留下的）一并收掉，不然收件箱里三条说的是同一件事。
    protected_loops 里的格子只做 create/refresh/去重，不做关闭（见 DATA_LOOPS）。
    """
    grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for task in open_tasks:
        payload = task.get("payload")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload or "{}")
            except (json.JSONDecodeError, TypeError):
                payload = {}
        payload = payload or {}
        key = (str(payload.get("loop") or ""), str(payload.get("kind") or ""))
        grouped.setdefault(key, []).append({**task, "watchdog": payload})

    keys = {(f["loop"], f["kind"]) for f in found}
    actions: List[Dict[str, Any]] = []
    for finding in found:
        key = (finding["loop"], finding["kind"])
        rows = grouped.get(key) or []
        if not rows:
            actions.append({"action": "create", "finding": finding})
            continue
        current = rows[0]
        for duplicate in rows[1:]:
            actions.append({"action": "close_duplicate", "task_id": duplicate.get("id"),
                            "task": duplicate, "finding": finding})
        # 只看 sig 会漏掉一件事：sig 按 10/100 分档，档没跨过时把催办文案改准（补数据的人
        # 靠描述知道该量哪一批）永远不会写回库里，收件箱留着的是旧说法。
        if (str(current["watchdog"].get("sig") or "") != finding["sig"]
                or str(current.get("title") or "") != str(finding.get("title") or "")
                or str(current.get("description") or "") != str(finding.get("description") or "")):
            actions.append({"action": "refresh", "task_id": current.get("id"),
                            "task": current, "finding": finding})
        else:
            actions.append({"action": "unchanged", "task_id": current.get("id"),
                            "finding": finding})

    for key, rows in grouped.items():
        if key in keys:
            continue
        if protected_loops and key[0] in protected_loops:
            actions.append({"action": "protected", "task_id": rows[0].get("id"),
                            "task": rows[0],
                            "finding": {"loop": key[0], "kind": key[1],
                                        "sig": str(rows[0]["watchdog"].get("sig") or ""),
                                        "title": rows[0].get("title")}})
            continue
        actions.append({"action": "close", "task_id": rows[0].get("id"),
                        "task": rows[0],
                        "finding": {"loop": key[0], "kind": key[1],
                                    "sig": str(rows[0]["watchdog"].get("sig") or "")}})
    return actions


async def scan(db: AsyncSession, factory_id: str = DEFAULT_FACTORY_ID, *,
               apply: bool = False, states: Optional[List[Dict[str, Any]]] = None
               ) -> Dict[str, Any]:
    """巡检一次并回报会动什么。apply=False（默认）只出判定不动库。"""
    from api.services.engine_heartbeat import read_states
    from api.services.engine_layers import THRESHOLDS

    limits = {"crash_rate_limit": float(THRESHOLDS["L1"]["crash_rate"]),
              "min_window_ticks": int(THRESHOLDS["L1"]["crash_window_min_ticks"])}
    rows = states if states is not None else await read_states()
    found = findings(rows, **limits)
    outcome = await _reconcile(db, factory_id, found, CATEGORY, apply)

    return {
        "factory_id": factory_id, "apply": apply,
        "loops_seen": len(rows), "alive": sum(1 for r in rows if r.get("alive")),
        # 刚重启的进程里"这轮还没跳到"不等于"挂了"：只按新鲜度报 alive 会读成 1/6，
        # 所以同时报"没有任何一个循环自己报过死"的数，两个数一起才不被误读。
        "self_reported_running": sum(1 for r in rows
                                     if str(r.get("last_status") or "")
                                     not in ("failed", "exited", "disabled")),
        "thresholds": limits, "window_hours": _window_hours(),
        "counts": outcome["counts"], "findings": found, "items": outcome["items"],
        "rule": ("心跳超过 2 个预期间隔没跳、循环退出/异常后无新心跳、窗口崩溃率越过 L1 判线 —— "
                 "每一种挂一条催办；同一条故障签名不变就不重复动库，恢复后自动关闭。"
                 "一次性任务（跑完退出）不算故障。"),
    }


async def _reconcile(db: AsyncSession, factory_id: str, found: List[Dict[str, Any]],
                     category: str, apply: bool, *,
                     protected_loops: Optional[frozenset] = None) -> Dict[str, Any]:
    """对账 + 落库的公共一段：运行时故障与数据缺口走同一条路（只有判据来源不同）。"""
    open_rows = [dict(r) for r in (await db.execute(
        OPEN_SQL, {"fid": factory_id, "cat": category})).mappings().all()]
    counts = {"create": 0, "refresh": 0, "close": 0, "close_duplicate": 0,
              "unchanged": 0, "protected": 0}
    items: List[Dict[str, Any]] = []
    for act in plan_actions(open_rows, found, protected_loops=protected_loops):
        counts[act["action"]] = counts.get(act["action"], 0) + 1
        item = {"action": act["action"], "loop": act["finding"]["loop"],
                "kind": act["finding"]["kind"], "sig": act["finding"]["sig"],
                "title": act["finding"].get("title"), "task_id": act.get("task_id")}
        if apply:
            item.update(await _apply(db, factory_id, act))
        items.append(item)
    if not apply:
        await db.rollback()
    return {"counts": counts, "items": items}


def _window_hours() -> int:
    from api.services.engine_heartbeat import window_hours

    return window_hours()


async def _apply(db: AsyncSession, factory_id: str, act: Dict[str, Any]) -> Dict[str, Any]:
    from api.services.followup_task_service import _append_log, create_task

    finding = act["finding"]

    def _payload() -> str:
        # 只有 create/refresh 需要整份读数；close 那条的 finding 是对账时现造的最小字典
        # （只有 loop/kind/sig），在这里统一算 payload 会把关闭动作直接带崩。
        return json.dumps({
            "category": finding.get("category") or CATEGORY, "loop": finding["loop"],
            "kind": finding["kind"], "sig": finding["sig"], "severity": finding.get("severity"),
            **(finding.get("evidence") or {}),
        }, ensure_ascii=False, default=str)

    payload = _payload()
    if act["action"] == "create":
        created = await create_task(
            db, factory_id, CREATED_BY, finding["title"],
            description=finding["description"],
            agent_key=finding.get("agent_key") or AGENT_KEY, item_type="followup",
            block_reason=finding["block_reason"], source=CREATED_BY,
            conversation_hint=finding.get(
                "hint") or "先确认循环是真停了还是在跑长任务；要重启引擎得先说影响面。",
            # 数据缺口按天跟就够了：主数据不是 60 分钟能补出来的东西，
            # 一小时一次的 LLM 跟进只会把网关和收件箱一起刷满。
            follow_interval_minutes=int(finding.get("interval") or FOLLOW_INTERVAL_MINUTES),
            payload=payload,
        )
        task_id = created.get("task_id")
        if task_id:
            # 收件箱按 next_follow_at 升序只渲染前几行：按 60 分钟节奏挂出来会沉到第二页，
            # 界面上等于没挂过。第一次跟进提前到 5 分钟后，之后照 60 分钟走。
            await db.execute(text(
                "UPDATE followup_tasks SET next_follow_at = NOW() + INTERVAL '5 minutes' "
                "WHERE id = :id"), {"id": str(task_id)})
            await db.commit()
        return {"task_id": task_id, "written": True}

    if act["action"] == "refresh":
        await db.execute(text("""
            UPDATE followup_tasks
            SET title = :title, description = :desc, payload = CAST(:payload AS jsonb),
                block_reason = :block, updated_at = NOW()
            WHERE id = :id AND status NOT IN ('done', 'cancelled')
        """), {
            "title": finding["title"], "desc": finding["description"],
            "block": finding["block_reason"], "id": str(act["task_id"]),
            "payload": payload,
        })
        await _append_log(db, str(act["task_id"]), factory_id, "watchdog_refresh",
                          f"同一条判据有新读数：{finding['title']}", "open", 0, CREATED_BY)
        await db.commit()
        return {"task_id": str(act["task_id"]), "written": True}

    if act["action"] in ("close", "close_duplicate"):
        note = (finding.get("recovered_note")
                or f"自动关闭：台账恢复 —— {finding['loop']} 现在活着且窗口崩溃率没过 L1 判线。"
                ) if act["action"] == "close" else (
            f"自动关闭：同一故障重复挂的条目，并入最新一条（{finding['title']}）。")
        await db.execute(text("""
            UPDATE followup_tasks
            SET status = 'done', progress_pct = 100.0, last_follow_note = :note,
                result_summary = :note, closed_at = NOW(), next_follow_at = NULL,
                updated_at = NOW()
            WHERE id = :id AND status NOT IN ('done', 'cancelled')
        """), {"note": note, "id": str(act["task_id"])})
        await _append_log(db, str(act["task_id"]), factory_id,
                          "watchdog_recovered" if act["action"] == "close" else "watchdog_dedupe",
                          note, "done", 100, CREATED_BY)
        await db.commit()
        return {"task_id": str(act["task_id"]), "note": note, "written": True}

    return {"written": False}


# ── 数据缺口：判据被主数据封顶时，把"补哪个数据"挂成催办 ────────────────────
# 机种归属沿用齐套判据那条规则（ORDER_SHORT_SQL）：子工单算到「父工单的机种」头上。
# 不这么写的话，A-50-04-F 那批半成品子单的键是组件编码，在镜像里查不到行，
# 登记世代这一格就永远不响 —— 同一个厂里两套"这台单属于哪个机种"的口径是量不准的根源。
KIT_GENERATION_SQL = """
WITH o AS (
    SELECT w.id, COALESCE(pp.product_code, p.product_code, w.product_id) AS model
    FROM work_orders w
    LEFT JOIN products p ON p.factory_id = w.factory_id
         AND (p.id::text = w.product_id OR p.product_code = w.product_id)
    LEFT JOIN work_orders par ON par.id = w.parent_work_order_id
    LEFT JOIN products pp ON pp.factory_id = par.factory_id
         AND (pp.id::text = par.product_id OR pp.product_code = par.product_id)
    WHERE w.factory_id = :fid AND w.status IN ('pending', 'released', 'in_progress')
      AND w.id NOT LIKE 'wo-vf-%'
), k AS (
    SELECT o.id, o.model,
           COUNT(*) FILTER (WHERE wm.item_type = 'buy') AS buy_lines
    FROM o LEFT JOIN work_order_materials wm ON wm.work_order_id = o.id
    GROUP BY 1, 2
)
SELECT COUNT(*) AS in_flow,
       COUNT(*) FILTER (WHERE k.buy_lines BETWEEN 1 AND 20
                        AND EXISTS (SELECT 1 FROM enghub_bom_items e
                                     WHERE e.factory_id = :fid AND e.product_model = k.model)) AS stale_gen,
       COUNT(*) FILTER (WHERE k.buy_lines = 0) AS no_lines
FROM k
"""

SUPPLIER_GAP_SQL = """
    SELECT COUNT(DISTINCT wm.material_code) AS no_supplier
    FROM work_order_materials wm
    JOIN work_orders o ON o.id = wm.work_order_id
    LEFT JOIN materials m ON m.material_code = wm.material_code AND m.factory_id = o.factory_id
    WHERE o.factory_id = :fid AND wm.item_type = 'buy' AND COALESCE(wm.shortage_qty, 0) > 0
      AND COALESCE(m.default_supplier, '') = ''
"""

TEMPERATURE_OBSERVATION_SQL = """
    SELECT (SELECT count(*) FROM equipment_readings er
              WHERE er.factory_id = :fid
                AND (er.metric_type ILIKE '%temp%' OR er.unit IN ('C', '℃', 'celsius', 'Celsius'))) AS sensor_rows,
           (SELECT count(*) FROM equipment_readings WHERE factory_id = :fid) AS reading_rows,
           (SELECT count(DISTINCT a.date) FROM attendance a WHERE a.factory_id = :fid) AS attendance_days
"""


MIN_STALE_ORDERS = 10
MIN_RERUNNABLE_ORDERS = 10
MIN_SUPPLIER_GAP_PARTS = 20
# 提前期普查的两格阈值：整组只有一个取值 = 这一类件压根没分供应商/分规格量过；
# 自制/外购在两列上互相矛盾的行数，决定"同一个件会不会被两头做出不同动作"。
MIN_UNVERIFIED_LEAD_PARTS = 1000
MIN_MOB_CONTRADICTION_ROWS = 500
# 少于这么多个动作没支撑，就不值得占收件箱（一个工段本来就可能有一两条没写过的规则）
MIN_UNDECLARED_ACTIONS = 3
# 模式要攒够几个样本才敢提"这条规律值得确认"
MIN_PATTERN_SAMPLES = 5
MIN_PENDING_RULES = 1
# 政策网格想过这么多次、现场一次记录都没有 —— 才值得占一格收件箱
MIN_SILENT_CONSIDERED = 10

LEAD_DEFAULT_SQL = """
    WITH g AS (
        SELECT make_or_buy, material_type, count(*) AS n,
               count(DISTINCT lead_time_days) AS distinct_values,
               mode() WITHIN GROUP (ORDER BY lead_time_days) AS modal_days
        FROM materials WHERE factory_id = :fid AND lead_time_days IS NOT NULL
        GROUP BY 1,2)
    SELECT count(*) FILTER (WHERE g.n >= 50 AND g.distinct_values <= 15
                              AND m.lead_time_days = g.modal_days) AS unverified,
           count(*) AS buy_rows,
           count(DISTINCT m.lead_time_days) AS ledger_distinct_values
    FROM materials m
    JOIN g ON g.make_or_buy = m.make_or_buy AND g.material_type = m.material_type
    WHERE m.factory_id = :fid AND m.make_or_buy = '外购'
"""

MOB_CONTRADICTION_SQL = """
    SELECT count(*) AS rows_conflict
    FROM materials
    WHERE factory_id = :fid
      AND ((make_or_buy = '外购' AND material_type = 'make')
        OR (make_or_buy = '自制' AND material_type IN ('purchased', 'raw')))
"""


# 这几格的判据住在本文件里：data_findings 这轮没报某格，有两种可能 —— 缺口真的缩到
# 判据线以下，或者那一格的查数没跑成（列没了、厂区没数据、依赖的服务抛异常被吞）。
# 光看"没报"分不出这两种，而分不出就自动关闭会把"暂时没查"写成"已经修好"，补数据的人
# 丢的正是那条待办。所以这一组只刷新、不关闭；要真收掉得有人明确判一次。
MIN_ATTENDANCE_DAYS_FOR_SLOPE = 3
MIN_UNCLAIMED_MODELS = 1

# 每一格数据判据都要在这里登记：漏登记的那格一旦某轮没跑成判据，
# 对账会把它当"缩到线下"自动关掉 —— 读起来就是"问题自己好了"的假绿灯。
# 巡检读数里的 cells_without_guard 就是用来抓这种漏登记的。
DATA_LOOPS = frozenset({
    "kit_line_generation", "kit_line_missing", "supplier_master",
    "lead_time_evidence", "material_make_or_buy_conflict",
    "action_constraints", "action_execution_silence", "candidate_rules",
    "working_conditions_evidence", "kit_line_coverage",
    "line_profile_coverage", "station_efficiency_basis", "rule_ledger_write",
    "reply_grounding",
})


def _gap(loop: str, kind: str, sig: str, title: str, description: str, block: str,
         agent_key: str, hint: str, evidence: Dict[str, Any],
         interval: int = DATA_FOLLOW_INTERVAL_MINUTES) -> Dict[str, Any]:
    return {"loop": loop, "kind": kind, "sig": f"{loop}|{sig}"[:200], "severity": "warning",
            "category": DATA_CATEGORY, "agent_key": agent_key, "hint": hint,
            "interval": interval,
            "title": title[:200], "description": description[:4000],
            "block_reason": block[:500], "evidence": evidence,
            "recovered_note": f"自动关闭：{loop} 这一格的数据缺口已经缩到判据线以下（曾报：{title}）。"}


async def data_findings(db: AsyncSession, factory_id: str, *,
                        readiness_out: Optional[Dict[str, Any]] = None,
                        evaluated_out: Optional[set] = None
                        ) -> List[Dict[str, Any]]:
    """把五格查数收齐交给 gap_readings()：查询与判据分开，判据才单测得到。

    evaluated_out 是一份"这一格本轮真的跑过判据"的名单（调用方传集合进来）：
    缺数据/查不动的格不能既不出声又被当成修好了。
    """
    gen = (await db.execute(text(KIT_GENERATION_SQL), {"fid": factory_id})).mappings().first()
    sup = (await db.execute(text(SUPPLIER_GAP_SQL), {"fid": factory_id})).mappings().first()
    lead = (await db.execute(text(LEAD_DEFAULT_SQL), {"fid": factory_id})).mappings().first()
    mob = (await db.execute(text(MOB_CONTRADICTION_SQL), {"fid": factory_id})).mappings().first()
    wc = (await db.execute(text(TEMPERATURE_OBSERVATION_SQL), {"fid": factory_id})).mappings().first()
    from core.mes.capacity_math import efficiency_basis_census
    from core.mes.data_evidence import line_claim_coverage

    claim = await line_claim_coverage(db, factory_id)
    eff = await efficiency_basis_census(db, factory_id)
    # 覆盖率要把引擎本轮的展开和门的判定配成对，一轮 ~1 分钟；查不动时 cov=None，
    # 判据那侧据此不关这条催办（读不到数 ≠ 没有缺口）。
    try:
        from api.services.sim_backtest import kit_coverage_gap

        cov = await kit_coverage_gap(db, factory_id, per_model=8, max_orders=24)
    except Exception:  # noqa: BLE001
        cov = None
    # 转述忠实度：答复里的数字在引擎返回里找不到的那些条（够样本才判，判不动时不关旧条目）
    try:
        from api.services.engine_capability import grounding_report

        ground = await grounding_report(db, factory_id, days=30)
    except Exception:  # noqa: BLE001 - 查不动时这一格不许被当成"通过"或"已修好"
        ground = {}
    if evaluated_out is not None:
        evaluated_out.update({"kit_line_generation", "supplier_master",
                              "lead_time_evidence", "material_make_or_buy_conflict",
                              "candidate_rules", "working_conditions_evidence",
                              "line_profile_coverage", "station_efficiency_basis",
                              "kit_line_coverage", "reply_grounding"})
    try:
        from core.mes.action_constraints import action_constraints

        cons = await action_constraints(db, factory_id)
    except Exception:  # noqa: BLE001  约束层查不动时不挂这一格，别把整轮巡检带崩
        cons = {}
    try:
        from core.mes.measurement_priority import measurement_priority

        mp = await measurement_priority(db, factory_id, units=1200)
    except Exception:  # noqa: BLE001  活单查不动不影响别的格，但不能当成"没有活要干"
        mp = {}
    try:
        # 先记账再挖：台账是"事件→动作→结果"的唯一载体，挖出来的 candidate 全靠它
        # 挂在巡检里（6 小时一轮），不靠人记得去点；推荐变了没变都刷，实绩一变达成率就跟变
        from core.mes.factory_rules import (backfill_decision_ledger, mine_patterns,
                                            record_candidates_from_census, sweep_adoption)

        await backfill_decision_ledger(db, factory_id, limit=60, apply=True)
        # 自动回查"推荐过的事做了没"，做了的写进台账 —— 这样达成率才有真样本，不用人记得报
        await sweep_adoption(db, factory_id, limit=60, apply=True)

        mined = await mine_patterns(db, factory_id, min_samples=MIN_PATTERN_SAMPLES, apply=True)
        derived = await record_candidates_from_census(db, factory_id, apply=True)
    except Exception:  # noqa: BLE001  挖不动就不挂这一格，绝不把没跑到说成没有候选
        mined, derived = {"error": "mining_unavailable"}, {"error": "derive_unavailable"}
    # 候选写不进去（词表挡了、校验挡了）以前是悄悄丢返回值：这里把它变成一条催办，
    # 否则"没落库"和"这条事实不存在"在读数上长得一模一样
    rejected = [w for w in ((derived or {}).get("write_errors") or []) if isinstance(w, dict)]
    pending = await _pending_rules(db, factory_id)
    ready = readiness_out if readiness_out is not None else await _readiness(db, factory_id)
    return gap_readings(gen=dict(gen or {}), sup=dict(sup or {}), ready=ready or {},
                        lead=dict(lead or {}), mob=dict(mob or {}), cons=dict(cons or {}),
                        wc=dict(wc or {}), claim=claim or {}, eff=eff or {}, rejected=rejected,
                        pending=list(pending or []), mp=dict(mp or {}),
                        cov=cov or {}, ground=ground or {},
                        evaluated_out=evaluated_out)


# 齐套行覆盖率：台账登记的缺口行 ÷ 引擎本轮算出的缺口件。线取 0.6 的理由是
# L2B 那一格要有可比行才谈得上对错；低于六成时命中率读数是取数封顶，不是引擎判错。
MIN_KIT_COVERAGE_RATE = 0.60
# 一次催办至少值这么多行才占收件箱：补 30 行不值得挂一条待办，重跑一次就完了
MIN_KIT_COVERAGE_ROWS = 200
# 门判 ready 而引擎算出缺件 = 可举证的放行洞，一张就报（这张单会被直接下达开工）
MIN_KIT_GATE_HOLE_ORDERS = 1

# 转述忠实度：够 10 条才判（与总结格同一条件），线跟总结格同一条 0.90。
MIN_GROUNDING_REPLIES = 10
MIN_GROUNDING_BACKING = 0.90

MIN_STATIONS_FOR_EFFICIENCY_GAP = 5


def gap_readings(*, gen: Dict[str, Any], sup: Dict[str, Any],
                 ready: Dict[str, Any], lead: Optional[Dict[str, Any]] = None,
                 mob: Optional[Dict[str, Any]] = None,
                 eff: Optional[Dict[str, Any]] = None,
                 cons: Optional[Dict[str, Any]] = None,
                 pending: Optional[List[Dict[str, Any]]] = None,
                 mp: Optional[Dict[str, Any]] = None,
                 cov: Optional[Dict[str, Any]] = None,
                 ground: Optional[Dict[str, Any]] = None,
                 wc: Optional[Dict[str, Any]] = None,
                 claim: Optional[Dict[str, Any]] = None,
                 rejected: Optional[List[Dict[str, Any]]] = None,
                 evaluated_out: Optional[set] = None) -> List[Dict[str, Any]]:
    """五格"不是引擎算不出，是台账没跟上"的缺口，量出来就派一条补数据催办。

    阈值写成张数/料号数而不是比例：少于十几张时重跑一次的成本比挂一条待办更划算，
    不值得占收件箱。签名按 10 张/10 个一档，补掉一档就刷新、缩到线下就自动关。
    evaluated_out 会被填上"本轮真跑过判据的格子"：调用方据此区分"缩到线下"与"这格没查成"。
    """
    out: List[Dict[str, Any]] = []
    ev = evaluated_out if evaluated_out is not None else set()
    if ready:
        ev.add("kit_line_missing")
    if cons:
        ev.add("action_constraints")
        basis = cons.get("grid_usage_basis") or {}
        if basis.get("coverage_known"):
            ev.add("action_execution_silence")
    if cov:
        ev.add("kit_line_coverage")
        rate = cov.get("coverage_rate")
        rows = int(cov.get("rows_to_register") or 0)
        holes = int(cov.get("gate_ready_but_engine_short") or 0)
        acted = int(cov.get("already_released_but_engine_short") or 0)
        if holes >= MIN_KIT_GATE_HOLE_ORDERS:
            who = ", ".join(str(s.get("work_order_code"))
                            for s in (cov.get("gate_ready_proven_samples") or [])[:4])
            out.append(_gap(
                "kit_line_coverage", "gate_ready_but_engine_short", f"hole|{holes}",
                f"放行洞｜门判齐套可下达的 {holes} 张单，引擎本轮算出外购缺件（{who}）",
                "齐套门读的是齐套表：这些单在台账里没有对应的缺口行，门就看不见缺件。\n"
                f"本轮抽样 {cov.get('orders_sampled')} 张，引擎缺口件 {cov.get('engine_short_part_rows')}、"
                f"台账登记缺口行 {cov.get('ledger_short_rows')}（覆盖率 {rate}）。\n"
                "复核：GET /api/v1/pmc/kit-coverage-gap、GET /api/v1/pmc/plan-commit-gate。",
                f"{holes} 张单被门判成齐套但引擎算出缺件", "pmc_agent",
                "先补这些单的齐套缺口行（只加不改不删，走 /kit-lines-reupgrade 的显式开关），"
                "再复核门是否放行。",
                {"orders_sampled": cov.get("orders_sampled"), "coverage_rate": rate,
                 "gate_ready_but_engine_short": holes, "rows_to_register": rows}))
        if rate is not None and rate < MIN_KIT_COVERAGE_RATE and rows >= MIN_KIT_COVERAGE_ROWS:
            out.append(_gap(
                "kit_line_coverage", "under_registered", f"cov|{int(rows // 200)}",
                f"补数据｜台账只登记了引擎本轮缺口件的 {rate}（差 {rows} 行）",
                "引擎按多层 BOM 加当前库存算出该缺哪些件，台账（工单齐套表）只登记了其中一部分："
                "缺的那部分既进不了催办，也进不了 L2B 的对照 —— 命中率读数被取数封顶，"
                "不是引擎判错。\n"
                f"本轮抽样 {cov.get('orders_sampled')} 张（机种 {cov.get('models')}）："
                f"引擎缺口件 {cov.get('engine_short_part_rows')} 行、台账缺口行 {cov.get('ledger_short_rows')} 行。\n"
                f"补的写入成本约 {rows} 行；另有 {acted} 张已下达的单引擎算出缺件"
                "（下达发生在历史某一版，本轮门判不到）。\n"
                "复核：GET /api/v1/pmc/kit-coverage-gap、GET /api/v1/pmc/sim-readiness。",
                f"齐套缺口行只登记了 {rate}，差 {rows} 行", "pmc_agent",
                "补登记会新增行并把相关单变成不齐套（这是对的），所以只在显式开关下做，"
                "且只加行、不改不删已有行。",
                {"orders_sampled": cov.get("orders_sampled"), "coverage_rate": rate,
                 "engine_short_part_rows": cov.get("engine_short_part_rows"),
                 "ledger_short_rows": cov.get("ledger_short_rows"),
                 "rows_to_register": rows,
                 "already_released_but_engine_short": acted}))
    if ground:
        ev.add("reply_grounding")
        n = int(ground.get("replies_with_claims") or 0)
        rate = ground.get("number_backing_rate")
        unbacked_claims = int(ground.get("numbers_unbacked") or 0)
        dirty_replies = int(ground.get("replies_with_unbacked") or 0)
        if n >= MIN_GROUNDING_REPLIES and rate is not None and rate < MIN_GROUNDING_BACKING:
            samples = ground.get("unbacked_samples") or []
            numbers = sorted({x for s in samples for x in (s.get("numbers") or [])})[:8]
            kinds = ground.get("unbacked_kinds") or {}
            kinds_txt = ("、".join(f"{k} {v} 处" for k, v in sorted(kinds.items()))
                         if kinds else "本轮未分类")
            derived = sum(int(v or 0) for k, v in kinds.items() if k != "找不到来源")
            out.append(_gap(
                "reply_grounding", "unsourced_numbers", f"ground|{n}|{int(rate * 100) // 5 * 5}",
                f"转述失真｜近 30 天 {n} 条带数字的答复报出 {ground.get('claims_total')} 个读数，"
                f"其中 {unbacked_claims} 个在引擎返回里找不到"
                f"（有出处率 {rate}，判线 {MIN_GROUNDING_BACKING}）",
                f"这些数字既不在本会话任何引擎工具的返回里，也不是人自己报过的数。分类：{kinds_txt}。"
                "「两数之差/两数之和/百分数写法/千分位写法」是引擎只给了分量、没给派生结果 —— "
                "修法是工具把那个数返回出来（这一类正在逐个补到出口上）；"
                f"其中真正「找不到来源」的是 {kinds.get('找不到来源', 0)} 处"
                f"（派生缺失 {derived} 处）—— 无人工厂里这两种都得当场见光，"
                "不能靠读的人凭感觉分辨。\n"
                f"判线按**读数条数**算（每个数一票），不是按答复条数：这 {unbacked_claims} 个数"
                f"落在 {dirty_replies} 条答复里，其余答复通篇都能回溯"
                f"（reply_clean_rate={ground.get('reply_clean_rate')}，那一格只报数、不判线 —— "
                "它会把「一张表里 1 个派生数没出处」和「整段都在编」算成同一个扣分）。\n"
                f"找不到的数：{numbers}；样例见 payload.unbacked_samples。\n"
                "复核：GET /api/v1/pmc/engine-capability-profile（总结格）、"
                "GET /api/v1/pmc/kit-coverage-gap 之外的证据链见 /api/v1/pmc/engine-layers 的 L4。",
                f"{unbacked_claims} 个读数查无出处（{dirty_replies} 条答复）", "pmc_agent",
                "先在出口把这些数标出来（chat_routes 的未经核实标注目前只在「本轮没调工具」时触发，"
                "调了工具但复述了没有的数不标 —— 那是这一格剩下的缺口）。",
                {"replies_with_claims": n, "number_backing_rate": rate,
                 "claims_total": ground.get("claims_total"),
                 "numbers_unbacked": unbacked_claims,
                 "replies_with_unbacked": dirty_replies,
                 "reply_clean_rate": ground.get("reply_clean_rate"),
                 "unbacked_kinds": kinds, "derived_missing": derived,
                 "unbacked_samples": samples[:6]}))
    if wc is not None and int(wc.get("attendance_days") or 0) >= MIN_ATTENDANCE_DAYS_FOR_SLOPE:
        ev.add("working_conditions_evidence")
        if int(wc.get("sensor_rows") or 0) == 0:
            out.append(_gap(
                "working_conditions_evidence", "no_temperature_measurement", "sensor|0",
                "补数据｜工况缺勤率的斜率没法验证：全厂没有一条车间温度实测",
                ("合规仿真已经把温湿度折成 WBGT→缺勤增量→到岗比例，并接进了产能"
                 "（`query_working_condition_impact`：闷热天扣的是可用人头，不是效率折扣）。"
                 f"但 attendance 有 {int(wc.get('attendance_days') or 0)} 个出勤日、"
                 f"equipment_readings 里温度 0 行（总读数 {int(wc.get('reading_rows') or 0)} 行）—— "
                 "缺勤序列与温度序列没有可对撞的那一维，所以包里 1.0pp/℃ 这条斜率只能是「本厂声明值」。"
                 "\n补法不讲究精度：工位传感器、每天定点抄表、巡检拍照都行，"
                 "按 factory_id+date 记 ℃ 与 RH，攒到 20 天上下就能回归出本厂斜率替换声明值；"
                 "那之前对外只能说「按标准折算的情景值」，不能说「本厂实测」。"),
                "不影响出数（照算），影响的是这条数能不能对外说是量过的",
                "query_working_condition_impact",
                "把日级车间温度与台账缺勤配起来回归斜率，斜率一改就要重跑工况影响对照",
                {"sensor_rows": int(wc.get("sensor_rows") or 0),
                 "reading_rows": int(wc.get("reading_rows") or 0),
                 "attendance_days": int(wc.get("attendance_days") or 0),
                 "declared_slope_pp_per_c": 1.0},
            ))

    if eff is not None:
        # 排程分母的效率是哪来的：占位与未填都等于按 100% 效率排产，
        # 于是利用率看着有余量、交期看着宽裕，其实是没人量过这条线的效率
        ev.add("station_efficiency_basis")
        total = int(eff.get("active_stations") or 0)
        if total >= MIN_STATIONS_FOR_EFFICIENCY_GAP and eff.get("all_unverified"):
            out.append(_gap(
                "station_efficiency_basis", "efficiency_all_placeholder",
                f"eff|{total // 5}",
                f"补数据｜{total} 个工位的排程效率全是没验证的（负荷与交期按 100% 效率算）",
                ("station_capacity 是负荷与交期承诺的分母来源。"
                 f"{eff.get('reading')}。"
                 f"\n涉及的工位：{('、'.join(str(x) for x in (eff.get('placeholder_stations') or [])))}"
                 "\n后果要说准：这不是算错，是把上界当成了可达 —— 利用率因此偏低（界面看着还有余量）、"
                 "交期因此偏乐观；同一版排程复用判断（input_fingerprint）也把 efficiency_rate 算进去了，"
                 "所以一旦 IE 填了实测值，历史方案会自动重算而不是继续复用。"
                 "\n补法：IE 逐工位量一次（或确认档案默认值），写进 station_capacity.efficiency_rate "
                 "并填 verified_at —— 有 verified_at 才算量过，读数会把它从占位挪到已验证。"
                 "注意不要用报工台账的 cycle_time_sec 反推：`production_reports` 这批行是仿真自写的，"
                 "拿它当实测等于把自己的输出当现场事实。"),
                "不影响出数（照排），影响的是这版负荷与交期能不能对外当承诺",
                "get_capacity_load",
                "IE 填 station_capacity.efficiency_rate 并标 verified_at 后，这一格自动缩到线下",
                {"active_stations": total, "placeholder": int(eff.get("placeholder") or 0),
                 "unset": int(eff.get("unset") or 0), "verified": int(eff.get("verified") or 0),
                 "used_values": eff.get("used_values") or []},
            ))

    if rejected is not None:
        ev.add("rule_ledger_write")
        if rejected:
            out.append(_gap(
                "rule_ledger_write", "candidate_rejected_by_guard", f"rejected|{len(rejected)}",
                f"引擎自己挖的候选有 {len(rejected)} 条写不进台账（被词表或校验挡了）",
                ("candidate 规则从花名册/打卡里挖出来后要落 factory_rules 才能被人确认；"
                 "upsert_rule 按封闭动作词表与字段校验挡回来的那些，过去直接丢返回值，"
                 "于是「没落库」和「这条事实不存在」在读数上没区别。"
                 f"\n被挡的条目：{json.dumps(rejected, ensure_ascii=False)[:900]}"
                 "\n要么这确实是动作之外的信息（该走工位/线档案或 capacity_questions），"
                 "要么词表要扩 —— 但扩词表要人决定，引擎不自己放开。"),
                "挖到的事实进不了台账，人就看不到、也确认不了",
                "record_factory_rule",
                "判一条：是改写载体（工位/线档案、催办问题）还是补进动作词表",
                {"rejected": rejected[:6]},
            ))

    if claim is not None:
        ev.add("line_profile_coverage")
        unclaimed = int(claim.get("unclaimed_models") or 0)
        if unclaimed >= MIN_UNCLAIMED_MODELS:
            codes = [str(c) for c in (claim.get("unclaimed_codes") or [])][:6]
            missing_st = [str(x) for x in (claim.get("route_stations_missing") or [])]
            out.append(_gap(
                "line_profile_coverage", "open_orders_without_line_profile", f"models|{unclaimed // 2}",
                f"补数据｜{unclaimed} 个在流程单没有线档案认领"
                + (f"（现在缺的只有工位 {'、'.join(missing_st)} 那一行）" if missing_st else ""),
                ("这些机种有 pending/released/in_progress 的母单，line_profiles 里没有任何一条线的 "
                 "can_make_models 写着它。原先推演因此完全不算产能（line=null，人力动作全乘不上）；"
                 "现在改成按工位路线算产能下界 —— min(站点声明台/小时, 在册人数÷IE单件工时) × "
                 "实测标称班时（班时取该厂行数最多班次的打卡中位，实测 10.0h，不是写死的 11h）——"
                 "所以到岗曲线、加班/双班/借人、工况扣人这几条已经乘得上了。"
                 f"\n涉及的机种：{('、'.join(codes))}；开放母单 {int(claim.get('unclaimed_orders') or 0)} 张、"
                 f"{int(float(claim.get('unclaimed_units') or 0))} 台。"
                 + (f"\n只剩一行要补：路线点名的工位 {'、'.join(missing_st)} 在 stations 里没有档案，"
                    "这一档没有产能读数（引擎拿其余工序算，读数里标 incomplete）。"
                    "同类站台账里有：组立一线/二线/三线这类 station_type=assembly 的行 —— "
                    "要么路线写的是别名，要么补一行 stations 档案。" if missing_st else "")
                 + "\n另一件要收口的（不影响能不能算，影响算得准不准）："
                 "stations.capacity_per_hour 与「在册人数÷IE单件工时」两读法实测差 1.1~38.9 倍"
                 "（成品检验 1.1×=两读一致；焊接车间 38.9×、加工车间 26.9×=整站读数；"
                 "组立一/二/三线 1.5~1.9×=像每人每件每小时），"
                 "说明 capacity 那列在不同站里是两种口径。引擎取两读法下界，"
                 "所以不会把产能说大；要说准就得由厂里定这列的含义，或填 station_capacity "
                 "的每站可用工时与效率（那台账里的效率折扣全是占位 1.0，没有一条 verified_at 晚于"
                 " created_at 的实测）。"),
                "工位路线产能已按下界计算；这一格剩的是路线别名/工位档案那一行与两读法收口",
                "run_sandbox",
                "把路线里对不上档案的工位认成已有站（或补一条 stations 行）；再定 capacity_per_hour 的口径",
                {"unclaimed_models": unclaimed, "orders": int(claim.get("unclaimed_orders") or 0),
                 "units": int(float(claim.get("unclaimed_units") or 0)), "codes": codes,
                 "stations": claim.get("stations"), "station_capacity_rows": claim.get("station_capacity_rows"),
                 "capacity_unit_mix": claim.get("capacity_unit_mix")},
            ))

    stale = int(gen.get("stale_gen") or 0)
    in_flow = int(gen.get("in_flow") or 0)
    if stale >= MIN_STALE_ORDERS:
        out.append(_gap(
            "kit_line_generation", "stale_generation", f"gen|{stale // 10}",
            f"补数据｜{stale}/{in_flow} 张在流程单的齐套行还是旧单层快照（≤20 行外购行）",
            "L2B 的「台账缺口行覆盖率」被这一格压着（当前读数见 /engine-layers），"
            "一致率与 top-5 重叠都到不了顶：这些单的机种"
            f"在 engflow 镜像里有行，可台账只登记了十几行外购件（同机种按多层展开登记过的单能到 "
            f"680 行、深 9 层）。\n这是「登记世代」差，不是源侧没结构 —— 修法是把这 {stale} 张单的"
            "齐套行按 bom_source 重登记一次（component_orders 那条路径）。\n"
            "动手前必须先定一件事：重登记会把台账的毛需求换成引擎用的低层码净额，"
            "采购缺口会变小（实测 3,299 行配对里 861 行引擎判 0），直接影响催办量与齐套放行门。\n"
            "复核：GET /api/v1/pmc/sim-readiness、GET /api/v1/pmc/engine-layers 的 L2B 那几格。",
            f"{stale} 张单的齐套行停在旧登记世代，L2B 命中率被封顶",
            "pmc_agent", "先定毛/净口径再批量重登记：刷台账会同时改变采购缺口读数。",
            {"in_flow_orders": in_flow, "stale_orders": stale,
             "no_kit_line_orders": int((gen or {}).get("no_lines") or 0)}))

    rerun = int((ready or {}).get("fixable_by_rerun_orders") or 0)
    if rerun >= MIN_RERUNNABLE_ORDERS:
        out.append(_gap(
            "kit_line_missing", "rerunnable_gap", f"rerun|{rerun // 10}",
            f"补数据｜{rerun} 张在流程单没有齐套行，但键有 BOM 行（重跑一次就能补）",
            "这类单既不能被判齐套，也不能算进精度对照 —— 齐套门只能写 no_evidence。\n"
            f"它们和「镜像里没有组件级子 BOM」那类不一样：这 {rerun} 张的产品键在 BOM 源里"
            "是有行的，跑一次展开就有依据（子 BOM 缺的那部分另见 #46，不是这一格）。"
            "复核：GET /api/v1/pmc/sim-readiness 的 kit_gaps（reason=flow_missing_kit）。",
            f"{rerun} 张在流程单没有齐套行但可重跑补齐",
            "pmc_agent", "重跑齐套登记前先看这批单是不是已经停工，停工单不用补。",
            {"rerunnable_orders": rerun}))

    # 第六格：引擎能想到的动作里，有多少根本没有规则支撑（约束层只读现有落库数据）
    undeclared = [a for a in ((cons or {}).get("actions") or [])
                  if str(a.get("verdict") or "").startswith(("undeclared", "forbidden"))]
    if len(undeclared) >= MIN_UNDECLARED_ACTIONS:
        gaps = (cons or {}).get("constraint_gaps") or []
        out.append(_gap(
            "action_constraints", "undeclared_actions", f"act|{len(undeclared)}",
            f"补数据｜引擎候选动作里 {len(undeclared)} 个没有规则支撑（{'、'.join(str(a.get('action')) for a in undeclared[:4])}）",
            "约束层的三类判定里，`undeclared` = 厂里没人写过这条规则，引擎就不该把它当可选项端出来："
            f"暴雨能不能外发、加班上限几小时、普通作业员能不能顶检测员，现在系统里一个都没落库。\n"
            f"要填的列（含该谁填）：{json.dumps(gaps, ensure_ascii=False)[:900]}\n"
            "这些是专家脑中的经验，第一阶段就得由人写进来；写进来之后引擎的候选集才会被真实边界过滤，"
            "之后才谈得上用运行数据比较'能做的事里哪个最有效'。\n"
            "复核：GET /api/v1/pmc/action-constraints?factory_id=<厂区>&model=<机种>&line=<线>",
            f"{len(undeclared)} 个候选动作没有落库规则支撑，方案空间等于没被现实约束过",
            "pmc_agent", "由 IE/厂里把不能做什么写进对应列或政策表；写不出的先明确允许默认值。",
            {"undeclared_actions": [str(a.get("action")) for a in undeclared],
             "gaps": gaps}))

    # 第六格B：引擎想过但现场一次都没记的动作 —— 学习侧的"沉默"，和"没规则"是两种病
    silent = [a for a in ((cons or {}).get("actions") or [])
              if int((((a.get("usage") or {}).get("considered_last_grid")) or 0)) >= MIN_SILENT_CONSIDERED
              and int(((a.get("usage") or {}).get("recorded_executions_30d")) or 0) == 0]
    basis = (cons or {}).get("grid_usage_basis") or {}
    if basis.get("coverage_known") and silent:
        ranked = sorted(silent, key=lambda a: -int((a.get("usage") or {}).get("considered_last_grid") or 0))
        out.append(_gap(
            "action_execution_silence", "considered_but_unrecorded",
            f"silent|{len(silent)}|{sum(int((a.get('usage') or {}).get('considered_last_grid') or 0) for a in silent) // 10}",
            f"补数据｜{len(silent)} 个动作引擎这轮想过 "
            f"{sum(int((a.get('usage') or {}).get('considered_last_grid') or 0) for a in silent)} 次，现场 30 天 0 记录"
            f"（{'、'.join(str(a.get('action')) for a in ranked[:4])}）",
            "推演推荐每轮都在比较这些杠杆，但决策台账里没有一笔执行记录 —— 那就永远只能拿仿真数自证。\n"
            "两种可能都要分开写：现场真没做（那这条动作该降权），还是做了没记（那缺的是记录入口）。\n"
            "记一笔的入口：POST /api/v1/pmc/execution-events（或对助手说一句\"XX线今天加了3小时班\"）。\n"
            f"覆盖度取自最近一张带 action_coverage 的记分卡（{basis.get('card_at')}）；"
            "没有这张卡时这一格不响 —— 读不到数不等于没人做过。",
            f"{len(silent)} 个动作被反复考虑却没有任何现场执行记录，效果无从验证",
            "pmc_agent", "先确认是没做还是没记；没记就把执行事件补进 execution_events，别改推荐口径。",
            {"silent_actions": [{"action": str(a.get("action")),
                                 "considered": int((a.get("usage") or {}).get("considered_last_grid") or 0)}
                                for a in ranked],
             "coverage_card_at": basis.get("card_at")}))

    # 第七格：系统自己挖出来的 candidate 规则等着人确认（不确认就永远不拦引擎）
    pending = list(pending or [])
    ev.add("candidate_rules")
    if len(pending) >= MIN_PENDING_RULES:
        kinds = sorted({str(r.get("source") or "") for r in pending})
        out.append(_gap(
            "candidate_rules", "awaiting_confirmation", f"cand|{len(pending)}",
            f"补数据｜{len(pending)} 条系统自己发现的规则等着人确认（来源 {'、'.join(kinds)}）",
            "这些不是空白，是「从数据里挖出来的候选规律」：人手能顶哪个工位（从技能台账推）、"
            "某种状态下哪个动作历史上达成率高（从决策台账推）。它们现在只是 candidate，不拦引擎；"
            "确认过的才升成 declared/validated 并开始过滤候选动作。\n"
            f"待确认清单：{json.dumps(pending[:8], ensure_ascii=False)[:1200]}\n"
            "确认方式：对话里说一句或在界面 POST /api/v1/pmc/factory-rules（status=validated）。\n"
            "复核：GET /api/v1/pmc/decision-ledger?factory_id=<厂区>&mine=true、"
            "GET /api/v1/pmc/action-constraints?factory_id=<厂区>",
            f"{len(pending)} 条候选规则没人确认",
            "pmc_agent", "逐条确认或驳回；驳回也是结果，别让它一直挂着。",
            {"pending": len(pending), "sources": kinds}))

    lt = int((lead or {}).get("unverified") or 0)
    if lt >= MIN_UNVERIFIED_LEAD_PARTS:
        out.append(_gap(
            "lead_time_evidence", "unverified_default", f"lt|{lt // 10}",
            f"补数据｜{lt} 个外购料号的提前期是按类别铺的默认值，交期吃的就是这个数",
            "判据：同组（采购属性×物料类别）≥50 个料号、该组提前期只有 ≤15 个取值、本件取值==该组众数。"
            f"实测机械厂：{lt} 行命中，全厂外购行的提前期只有 "
            f"{(lead or {}).get('ledger_distinct_values')} 个不同取值。\n"
            "而本厂 65 单真采购的下单→到货实测中位 54 天、最长 123 天 —— 台账均值只有 9.9 天；"
            "引擎点名的瓶颈件（见 /virtual-run 的 bottleneck_part.lead_evidence）目前 0 个有实测支撑。"
            "把提前期从默认量级推到实测量级，机械厂两台机的最晚延误从 6 天变 75 天。\n"
            "而且「瓶颈件」在这里不是一个件：实测 A-50-04-F 有 349 个料号并列最长到货日（第 12 天）、"
            "HTM1481-00 有 450 个，第二长的一档只有第 7 天 —— 只量其中一个，交期一天也买不回来。"
            "要量就得按'最长那一档'整批量（读 /virtual-run 的 arrival_critical_parts 与 "
            "arrival_critical_count），或者把承诺口径从件级提前期改成到货批次日。\n"
            "这不是算法能补的：要么按料号量出实际到货天数（先量决定交期的那几十个），"
            "要么把承诺口径改成不依赖未量的提前期。\n"
            "复核：GET /api/v1/pmc/data-evidence?factory_id=<厂区>、"
            "GET /api/v1/pmc/measurement-priority（该先量哪一档、几个件、值几天）。\n"
            f"先量这些：{json.dumps((mp or {}).get('per_model') or [], ensure_ascii=False, default=str)[:900]}",
            f"{lt} 个外购料号的提前期没有实测证据，交期结论建在铺出来的默认值上",
            "procurement_agent", "按料号量到货天数，先量引擎点名的瓶颈件，别铺全厂默认值。",
            {"unverified_buy_rows": lt, "buy_rows": int((lead or {}).get("buy_rows") or 0),
             "ledger_distinct_values": (lead or {}).get("ledger_distinct_values")}))

    mob = int((mob or {}).get("rows_conflict") or 0)
    if mob >= MIN_MOB_CONTRADICTION_ROWS:
        out.append(_gap(
            "material_make_or_buy_conflict", "self_make_contradiction", f"mob|{mob // 10}",
            f"补数据｜{mob} 个料号的自制/外购在两列上说法相反，同一个件有两种动作",
            "materials.make_or_buy 说外购、material_type 却是 make（或反之，raw/purchased 标成自制）。"
            f"实测 {mob} 行。\n排产与齐套按 make_or_buy 判要不要买，另一些读料路径按 material_type "
            "判要不要自制 —— 同一个件会得出「等 4 天到货」和「线上自己做」两种动作，两边都觉得自己有依据。"
            "而且矛盾组里 7,007 行的提前期全是同一个 4 天，说明这一列是整批铺出来的。\n"
            "这是主数据决定（哪一列作准），不是算法能替厂里填的；定了之后另一列要么删要么改成派生值。\n"
            "复核：GET /api/v1/pmc/data-evidence 的 make_or_buy_contradiction。",
            f"{mob} 个料号的自制/外购两列互相矛盾",
            "pmc_agent", "先定哪一列作准（排产/齐套已吃 make_or_buy），再批量对齐另一列。",
            {"rows_conflict": mob}))

    no_sup = int((sup or {}).get("no_supplier") or 0)
    if no_sup >= MIN_SUPPLIER_GAP_PARTS:
        out.append(_gap(
            "supplier_master", "missing_supplier", f"sup|{no_sup // 10}",
            f"补数据｜{no_sup} 个外购缺口料号没有供应商主数据，缺口永远算不平",
            "这些料号在台账里被判为外购缺口，但 materials 主数据没有 default_supplier："
            "引擎能给「该催哪件、催多少」，却给不出「向谁催、几天到」——"
            "催购建议落到人工请购单时就断在这儿（源侧 engflow 的 BOM 行 vendor_code/vendor_name "
            "本来就是空的，不是镜像丢的）。\n复核：GET /api/v1/pmc/data-authority、"
            "GET /api/v1/pmc/engine-layers 的 L2B「BOM 取数来源」。",
            f"{no_sup} 个外购缺口料号缺供应商主数据",
            "procurement_agent", "供应商要么从采购台账补进 materials，要么改承诺口径（按提前期不指名供应商）。",
            {"shortage_parts_without_supplier": no_sup}))
    return out


async def _pending_rules(db: AsyncSession, factory_id: str) -> List[Dict[str, Any]]:
    """等着人确认的候选规则（candidate），按发现时间倒序取前若干条。"""
    try:
        rows = (await db.execute(text("""
            SELECT subject, verdict, statement, source, params::text AS params, updated_at
            FROM factory_rules
            WHERE factory_id = :fid AND status = 'candidate'
            ORDER BY updated_at DESC LIMIT 20
        """), {"fid": factory_id})).mappings().all()
    except Exception:  # noqa: BLE001  表还没建好时这格不挂，别把整轮巡检带崩
        return []
    return [{"subject": r["subject"], "verdict": r["verdict"], "statement": r["statement"],
             "source": r["source"], "params": r["params"], "observed_at": str(r["updated_at"])}
            for r in rows]


async def _readiness(db: AsyncSession, factory_id: str) -> Dict[str, Any]:
    try:
        from api.services.sim_backtest import readiness

        return await readiness(db, factory_id)
    except Exception:  # noqa: BLE001  就绪度查不动就不挂这一格，别把整轮巡检带崩
        return {}


async def scan_data(db: AsyncSession, factory_id: str = DEFAULT_FACTORY_ID, *,
                    apply: bool = False) -> Dict[str, Any]:
    """数据缺口巡检：判据被主数据封顶时自动成一条补数据催办，补齐后自动关闭。"""
    evaluated: set = set()
    found = await data_findings(db, factory_id, evaluated_out=evaluated)
    seen = {str(f["loop"]) for f in found}
    # 分三种：这轮报了缺口的（正常刷新）、这轮跑过判据但没报的（真缩到线下，允许自动关）、
    # 这轮压根没跑成判据的（不许关，只保护）。上一版把第二、第三种混在一起一律不关，
    # 结果是修好的红条永远挂在收件箱里 —— 过期判据也是红。
    cleared = frozenset((evaluated - seen) & DATA_LOOPS)
    protected = frozenset(DATA_LOOPS - seen - evaluated)
    outcome = await _reconcile(db, factory_id, found, DATA_CATEGORY, apply,
                               protected_loops=protected)
    return {
        "factory_id": factory_id, "apply": apply, "thresholds": {
            "stale_generation_orders": MIN_STALE_ORDERS,
            "rerunnable_orders": MIN_RERUNNABLE_ORDERS,
            "supplier_gap_parts": MIN_SUPPLIER_GAP_PARTS,
            "kit_coverage_rate_min": MIN_KIT_COVERAGE_RATE,
            "kit_coverage_rows_min": MIN_KIT_COVERAGE_ROWS,
            "kit_gate_hole_orders_min": MIN_KIT_GATE_HOLE_ORDERS,
            "grounding_backing_min": MIN_GROUNDING_BACKING,
            "grounding_min_replies": MIN_GROUNDING_REPLIES,
            "unverified_lead_parts": MIN_UNVERIFIED_LEAD_PARTS,
            "mob_contradiction_rows": MIN_MOB_CONTRADICTION_ROWS,
            "undeclared_actions": MIN_UNDECLARED_ACTIONS,
            "silent_considered_actions": MIN_SILENT_CONSIDERED,
            "pending_rule_samples": MIN_PATTERN_SAMPLES,
        },
        "counts": outcome["counts"], "findings": found, "items": outcome["items"],
        "held_open": sorted(protected),
        "cleared_this_round": sorted(cleared),
        "cells_without_guard": sorted(l for l in seen if l not in DATA_LOOPS),
        "rule": ("这几格不是引擎算不出，是台账/主数据没跟上：齐套行登记世代、可重跑补齐的缺行单、"
                 "外购缺口的供应商、没量过的提前期、自制/外购两列矛盾、动作想过没人记。"
                 "跑过判据又缩到线下的自动关；这轮没跑成判据的一律不关（held_open），"
                 "读不到数不等于没人做过。"),
    }
