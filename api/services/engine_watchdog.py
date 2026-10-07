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
    SELECT id, title, status, payload, created_at
    FROM followup_tasks
    WHERE factory_id = :fid AND status NOT IN ('done', 'cancelled')
      AND payload->>'category' = :cat
    ORDER BY created_at DESC
""")


# ── 判据：台账 → 需要人看的条目（纯函数，不动库）────────────────────────────
def is_down(row: Dict[str, Any]) -> bool:
    """这个循环现在能不能被算成"没在跑"。

    分两种死法：台账**自己报出来的**（failed / exited）是事实，立刻成立；
    靠"没动静"推断出来的（只记到 spawned 或状态不认识）要给宽限 ——
    read_states 把"活着"定义成"逐轮心跳新鲜"，刚起来的进程那一笔是 spawned，
    没有宽限就会在引擎重启后的头 1-2 分钟挂出 N 条"从未在跑"的假警报。
    """
    if row.get("alive"):
        return False
    status = str(row.get("last_status") or "")
    loop = str(row.get("loop") or "")
    if status == "tick":
        return True                        # 报着报着不跳了：判死线由 read_states 算过了
    if status in ("failed", "exited"):
        # 引擎自己记下"这一跳崩了/这循环结束了"就是事实：每轮失败都会把 last_tick_at 刷新，
        # 再等 2 个间隔就永远等不到 —— 恢复了 last_status 会变回 tick，这条判据自己就消失。
        return status == "failed" or loop not in ONE_SHOT_LOOPS
    interval = int(row.get("interval_seconds") or 0)
    return float(row.get("stale_seconds") or 0) > 2 * max(interval, 1)


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
    deadline = f"2 × {int(interval)} 秒" if interval else "预期间隔未知"
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
                 found: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """一条 (loop, kind) 只留一条未关闭催办；签名没变就不动库。

    同一键下的历史重复条目（旧版本代码留下的）一并收掉，不然收件箱里三条说的是同一件事。
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
        if str(current["watchdog"].get("sig") or "") != finding["sig"]:
            actions.append({"action": "refresh", "task_id": current.get("id"),
                            "task": current, "finding": finding})
        else:
            actions.append({"action": "unchanged", "task_id": current.get("id"),
                            "finding": finding})

    for key, rows in grouped.items():
        if key in keys:
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
    open_rows = [dict(r) for r in (await db.execute(
        OPEN_SQL, {"fid": factory_id, "cat": CATEGORY})).mappings().all()]
    actions = plan_actions(open_rows, found)

    counts = {"create": 0, "refresh": 0, "close": 0, "close_duplicate": 0, "unchanged": 0}
    items: List[Dict[str, Any]] = []
    for act in actions:
        counts[act["action"]] = counts.get(act["action"], 0) + 1
        item = {"action": act["action"], "loop": act["finding"]["loop"],
                "kind": act["finding"]["kind"], "sig": act["finding"]["sig"],
                "title": act["finding"].get("title"),
                "task_id": act.get("task_id")}
        if apply:
            item.update(await _apply(db, factory_id, act))
        items.append(item)
    if not apply:
        await db.rollback()

    return {
        "factory_id": factory_id, "apply": apply,
        "loops_seen": len(rows), "alive": sum(1 for r in rows if r.get("alive")),
        "thresholds": limits, "window_hours": _window_hours(),
        "counts": counts, "findings": found, "items": items,
        "rule": ("心跳超过 2 个预期间隔没跳、循环退出/异常后无新心跳、窗口崩溃率越过 L1 判线 —— "
                 "每一种挂一条催办；同一条故障签名不变就不重复动库，恢复后自动关闭。"
                 "一次性任务（跑完退出）不算故障。"),
    }


def _window_hours() -> int:
    from api.services.engine_heartbeat import window_hours

    return window_hours()


async def _apply(db: AsyncSession, factory_id: str, act: Dict[str, Any]) -> Dict[str, Any]:
    from api.services.followup_task_service import _append_log, create_task

    finding = act["finding"]
    if act["action"] == "create":
        created = await create_task(
            db, factory_id, CREATED_BY, finding["title"],
            description=finding["description"],
            agent_key=AGENT_KEY, item_type="followup",
            block_reason=finding["block_reason"], source=CREATED_BY,
            conversation_hint="先确认循环是真停了还是在跑长任务；要重启引擎得先说影响面。",
            follow_interval_minutes=FOLLOW_INTERVAL_MINUTES,
            payload=json.dumps({
                "category": CATEGORY, "loop": finding["loop"], "kind": finding["kind"],
                "sig": finding["sig"], "severity": finding["severity"],
                **finding["evidence"],
            }, ensure_ascii=False, default=str),
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
            "payload": json.dumps({
                "category": CATEGORY, "loop": finding["loop"], "kind": finding["kind"],
                "sig": finding["sig"], "severity": finding["severity"],
                **finding["evidence"],
            }, ensure_ascii=False, default=str),
        })
        await _append_log(db, str(act["task_id"]), factory_id, "watchdog_refresh",
                          f"同一条故障有新读数：{finding['title']}", "open", 0, CREATED_BY)
        await db.commit()
        return {"task_id": str(act["task_id"]), "written": True}

    if act["action"] in ("close", "close_duplicate"):
        note = (f"自动关闭：台账恢复 —— {finding['loop']} 现在活着且窗口崩溃率没过 L1 判线。"
                if act["action"] == "close" else
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
