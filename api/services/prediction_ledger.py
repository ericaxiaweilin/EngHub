"""交期预测留痕账本：引擎每天对在流程单说一句"预计几号能交"，完工那天和实际对一次。

为什么要有这张表 —— L2B 的"回测 MAPE"一直是算不出的：35 张已完工单里 30 张没留
计划开工日，剩下 3 对样本远够不上判线。更要命的是那条路本身是"用**今天**的 BOM、
工时、提前期重跑一遍历史单"，那不是"引擎当时说了什么"，是"引擎现在会说什么" ——
拿它当准度证据是自证。

这一格只记事实：
  · made_on = 说这句话的那天，predicted_finish = 那天按 time_basis 流水线口径算出的完工日；
  · 一张单一天一行（唯一键 work_order_id + made_on），当天重复跑不改已有行；
  · 完工时回填 error_days = 实际完工日 − 当时预计完工日（正数=晚交）。
所以样本只能随真实完工长出来，不能补 —— 这张表的第一作用是把"以后能不能验"变成"在攒证据"。
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# 预计口径只认这一条：time_basis 的流水线口径（数量÷线产能 + 首件节拍，按线自己声明的班时折算）。
BASIS = "time_basis_flow"
MIN_PAIRS_FOR_MAPE = 10

DDL = """
CREATE TABLE IF NOT EXISTS engine_order_predictions (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(50) NOT NULL,
    work_order_id TEXT NOT NULL,
    work_order_code VARCHAR(50),
    model_code VARCHAR(50),
    units NUMERIC,
    made_on DATE NOT NULL,
    planned_due DATE,
    predicted_finish DATE,
    estimated_days NUMERIC,
    line_code VARCHAR(50),
    basis VARCHAR(40) NOT NULL,
    actual_complete DATE,
    error_days INTEGER,
    paired_on TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""
DDL_INDEXES = [
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_order_prediction_day "
    "ON engine_order_predictions (work_order_id, made_on, basis)",
    "CREATE INDEX IF NOT EXISTS ix_order_prediction_factory "
    "ON engine_order_predictions (factory_id, made_on DESC)",
    "CREATE INDEX IF NOT EXISTS ix_order_prediction_paired "
    "ON engine_order_predictions (factory_id, paired_on DESC)",
]

OPEN_SQL = """
    SELECT o.id AS work_order_id, o.work_order_code,
           COALESCE(pp.product_code, p.product_code, o.product_id) AS model_code,
           o.planned_qty AS units, o.planned_due::date AS planned_due,
           COALESCE((SELECT count(*) FROM routings r,
                     jsonb_array_elements(r.steps::jsonb) e(s)
                     WHERE r.id = o.routing_id), 0) AS route_steps
    FROM work_orders o
    LEFT JOIN products p ON p.id::text = o.product_id OR p.product_code = o.product_id
    LEFT JOIN work_orders par ON par.id = o.parent_work_order_id
    LEFT JOIN products pp ON pp.factory_id = par.factory_id
         AND (pp.id::text = par.product_id OR pp.product_code = par.product_id)
    WHERE o.factory_id = :fid
      AND o.status IN ('pending','released','in_progress')
      AND o.id NOT LIKE 'wo-vf-%'
      AND o.planned_qty > 0
    ORDER BY o.planned_due NULLS LAST, o.created_at DESC
    LIMIT :limit
"""

COMPLETED_SQL = """
    SELECT o.id AS work_order_id, o.actual_complete::date AS actual_complete
    FROM work_orders o
    WHERE o.factory_id = :fid AND o.status = 'completed'
      AND o.actual_complete IS NOT NULL
      AND EXISTS (SELECT 1 FROM engine_order_predictions e
                  WHERE e.work_order_id = o.id AND e.factory_id = :fid
                    AND e.paired_on IS NULL AND e.predicted_finish IS NOT NULL)
"""

# 一天的留痕只覆盖当天还没说过的单；重跑同一天不改已有行（那句话已经说出去了）
INSERT_SQL = """
    INSERT INTO engine_order_predictions
        (id, factory_id, work_order_id, work_order_code, model_code, units, made_on,
         planned_due, predicted_finish, estimated_days, line_code, basis)
    VALUES (:id, :fid, :wid, :code, :model, :units, :made_on, :due, :finish,
            :days, :line, :basis)
    ON CONFLICT (work_order_id, made_on, basis) DO NOTHING
"""

PAIR_SQL = """
    UPDATE engine_order_predictions
    SET actual_complete = :actual::date,
        error_days = (:actual::date - predicted_finish)::int,
        paired_on = NOW()
    WHERE work_order_id = :wid AND factory_id = :fid AND paired_on IS NULL
      AND predicted_finish IS NOT NULL AND made_on = :made_on
"""

LEDGER_SQL = """
    SELECT min(made_on) AS first_day, max(made_on) AS last_day,
           COUNT(DISTINCT work_order_id) AS orders_recorded,
           COUNT(*) AS rows_recorded,
           COUNT(*) FILTER (WHERE paired_on IS NOT NULL) AS paired,
           COUNT(*) FILTER (WHERE paired_on IS NULL) AS still_open,
           AVG(ABS(error_days)) FILTER (WHERE paired_on IS NOT NULL) AS mae_days,
           AVG(ABS(error_days)::numeric / GREATEST(1, (actual_complete - made_on)::int))
               FILTER (WHERE paired_on IS NOT NULL) AS mape
    FROM engine_order_predictions WHERE factory_id = :fid
"""

BANDS_SQL = """
    SELECT CASE WHEN error_days <= -8 THEN 'a. 早于预计 8 天以上'
                WHEN error_days <= -2 THEN 'b. 早 2-7 天'
                WHEN error_days <= 2  THEN 'c. 准（±2 天）'
                WHEN error_days <= 7  THEN 'd. 晚 3-7 天'
                ELSE 'e. 晚 8 天以上' END AS band,
           COUNT(*) AS n, min(error_days) AS lo, max(error_days) AS hi
    FROM engine_order_predictions
    WHERE factory_id = :fid AND paired_on IS NOT NULL
    GROUP BY 1 ORDER BY 1
"""


async def ensure_schema(db: AsyncSession) -> None:
    """建表幂等：这格第一次上线、以及换环境部署时都只该说一句"有就用"。"""
    await db.execute(text(DDL))
    for stmt in DDL_INDEXES:
        await db.execute(text(stmt))


def _today() -> date:
    return datetime.now(timezone.utc).date()


def predicted_finish_for(made_on: date, estimated_days: float) -> date:
    """把"还要几个工作日"落在日历上：不足一天进一天（不把半天说成早于预计）。"""
    return made_on + timedelta(days=max(1, int(-(-float(estimated_days) // 1))))


async def record_predictions(db: AsyncSession, factory_id: str, *,
                             limit: int = 400, apply: bool = True,
                             today: Optional[date] = None) -> Dict[str, Any]:
    """给今天在流程单各记一行"我以为这天能交"（一天一行，重复跑不改已有行）。"""
    await ensure_schema(db)
    made_on = today or _today()
    rows = (await db.execute(text(OPEN_SQL),
                             {"fid": factory_id, "limit": max(1, int(limit))})).mappings().all()
    from api.services.time_basis import load_time_basis

    basis = await load_time_basis(db, factory_id)
    receipt: Dict[str, Any] = {"factory_id": factory_id, "made_on": made_on.isoformat(),
                               "apply": apply, "open_orders": len(rows), "recorded": 0,
                               "already_recorded_today": 0, "no_line_capacity": 0}
    pending: Dict[str, Any] = {}
    for r in rows:
        est = basis.order_flow_estimate(model=str(r["model_code"] or ""),
                                       qty=float(r["units"] or 0),
                                       steps=int(r["route_steps"] or 1))
        if not est or not est.get("estimated_days"):
            receipt["no_line_capacity"] += 1
            continue
        finish = predicted_finish_for(made_on, float(est["estimated_days"]))
        params = {"id": str(uuid.uuid4()), "fid": factory_id, "wid": str(r["work_order_id"]),
                  "code": r["work_order_code"], "model": str(r["model_code"] or ""),
                  "units": float(r["units"] or 0), "made_on": made_on,
                  "due": r["planned_due"], "finish": finish,
                  "days": float(est["estimated_days"]), "line": est.get("line_code"),
                  "basis": BASIS}
        if not apply:
            receipt["recorded"] += 1
            receipt.setdefault("examples", [])
            if len(receipt.get("examples", [])) < 5:
                receipt["examples"].append({"code": params["code"], "finish": finish.isoformat(),
                                            "days": params["days"], "due": str(params["due"])})
            continue
        res = await db.execute(text(INSERT_SQL), params)
        if (res.rowcount or 0) > 0:
            receipt["recorded"] += 1
        else:
            receipt["already_recorded_today"] += 1
        pending[str(r["work_order_id"])] = finish
    if apply:
        await db.commit()
    else:
        await db.rollback()
    receipt["status"] = "ok"
    receipt["message"] = (f"{'记下' if apply else '预演'} {receipt['recorded']} 张单的预计完工日"
                          f"（今天已记过的 {receipt['already_recorded_today']} 张不改，"
                          f"机种没落到声明日产量的线上算不出 {receipt['no_line_capacity']} 张）")
    return receipt


async def pair_completed_predictions(db: AsyncSession, factory_id: str, *,
                                     apply: bool = True) -> Dict[str, Any]:
    """把已完工单和**当时那条留痕**配对：误差 = 实际完工日 − 当时说的完工日。

    配最早的一条（不是最近的一条）：交期承诺是在下单当天说的，越晚说的越像事后诸葛。
    """
    await ensure_schema(db)
    rows = (await db.execute(text(COMPLETED_SQL), {"fid": factory_id})).mappings().all()
    out = {"factory_id": factory_id, "apply": apply, "completed_to_pair": len(rows), "paired": 0}
    for r in rows:
        actual = r["actual_complete"]
        if actual is None:
            continue
        first = (await db.execute(text("""
            SELECT min(made_on) AS first_day FROM engine_order_predictions
            WHERE factory_id = :fid AND work_order_id = :wid AND predicted_finish IS NOT NULL
              AND paired_on IS NULL"""),
            {"fid": factory_id, "wid": str(r["work_order_id"])})).mappings().first()
        made_on = (first or {}).get("first_day")
        if made_on is None:
            continue
        if not apply:
            out["paired"] += 1
            continue
        res = await db.execute(text(PAIR_SQL), {"actual": actual, "wid": str(r["work_order_id"]),
                                                "fid": factory_id, "made_on": made_on})
        out["paired"] += int(res.rowcount or 0)
    if apply:
        await db.commit()
    else:
        await db.rollback()
    return out


def summarize(ledger: Dict[str, Any], bands: Dict[str, int], pairs_needed: int,
              pop: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """把账本读成一句能判线的话：样本不够就明说还差几条，不给 0 分也不给假绿灯。"""
    paired = int(ledger.get("paired") or 0)
    mape = ledger.get("mape")
    out = {
        "orders_recorded": int(ledger.get("orders_recorded") or 0),
        "rows_recorded": int(ledger.get("rows_recorded") or 0),
        "paired": paired,
        "still_open": int(ledger.get("still_open") or 0),
        "first_recorded_on": str(ledger.get("first_day") or ""),
        "last_recorded_on": str(ledger.get("last_day") or ""),
        "mae_days": (round(float(ledger.get("mae_days")), 2) if ledger.get("mae_days") is not None else None),
        "mape": (round(float(mape), 4) if mape is not None else None),
        "error_bands": bands,
        "min_pairs": pairs_needed,
    }
    out["state"] = ("reported" if paired < pairs_needed or mape is None else
                    ("pass" if float(mape) <= 0.20 else "fail"))
    if paired < pairs_needed:
        out["missing"] = pairing_missing(paired, pairs_needed, pop)
    elif mape is None:
        # 样本够但算不出数：这是数据形状问题（预计日或实际日为空），不能拿"样本不足"当解释
        out["missing"] = (f"成对 {paired} 对但误差算不出：paired_on 有值而 mape 为空，"
                          "说明 predicted_finish 或 actual_complete 有空 —— 查账本写入路径")
    else:
        out["missing"] = None
    return out


POPULATION_SQL = """
WITH led AS (SELECT DISTINCT model_code FROM engine_order_predictions),
done AS (
    SELECT COALESCE(p.product_code, o.product_id::text) AS model,
           o.actual_complete::date AS d
    FROM work_orders o
    LEFT JOIN products p ON p.factory_id = o.factory_id
         AND (p.id::text = o.product_id OR p.product_code = o.product_id::text)
    WHERE o.factory_id = :fid AND o.status = 'completed' AND o.actual_complete IS NOT NULL
),
recorded_done AS (
    SELECT DISTINCT o.id
    FROM engine_order_predictions e
    JOIN work_orders o ON o.id::text = e.work_order_id
    WHERE o.status = 'completed' AND o.actual_complete IS NOT NULL
)
SELECT (SELECT COUNT(*) FROM done) AS completed_total,
       (SELECT COUNT(*) FROM done WHERE d <= CURRENT_DATE) AS completed_dated_past,
       (SELECT COUNT(*) FROM done
         WHERE model IN (SELECT model_code FROM led)) AS completed_on_ledger_models,
       (SELECT COUNT(*) FROM recorded_done) AS completed_in_ledger,
       (SELECT COUNT(*) FROM led) AS ledger_models
"""


def pairing_missing(paired: int, pairs_needed: int, pop: Optional[Dict[str, Any]] = None) -> str:
    """成对样本不够时点名缺的是**天数**还是**人群** —— 这两种"再等等"完全不是一回事。

    等天数：账本里已有单完工，只是还没配上 —— 下一轮闸门自然会长。
    等人群：已完工的那批单从来没被留痕（10-09 实测：完工的是组件号子单，
    账本记的是整机机种的在流程单）—— 等多久都是 0 对，要动的是留痕覆盖的人群。
    """
    base = f"成对样本 {paired} 对（判线要 ≥{pairs_needed} 对）："
    pop = pop or {}
    done = int(pop.get("completed_total") or 0)
    if not pop or done == 0:
        return base + "这座厂还没有一张已完工单 —— 没有完工事件可配，样本只能攒不能补"
    in_led = int(pop.get("completed_in_ledger") or 0)
    if in_led == 0:
        future = done - int(pop.get("completed_dated_past") or 0)
        return base + (f"{done} 张已完工单里没有一张在账本里（账本覆盖 "
                       f"{pop.get('ledger_models')} 个机种的在流程单；完工单落在这些机种上的 "
                       f"{pop.get('completed_on_ledger_models')} 张）—— "
                       "缺的不是天数，是**会完工的那批单从来没被留痕**。"
                       f"另：完工单里完工日 ≤ 今天 {pop.get('completed_dated_past')} 张、"
                       f"未来日期 {future} 张 —— 那些单还没真做过，"
                       "把它们当实绩配对会算出假误差")
    return base + (f"账本里已有 {in_led} 张单完工，下一轮 delivery_prediction_ledger（每 24 小时）"
                   "会把它们配上")


async def delivery_accuracy(db: AsyncSession, factory_id: str) -> Dict[str, Any]:
    """留痕法交期准度（只读）：记了多少、配了多少、误差分布长什么样。"""
    await ensure_schema(db)
    ledger = (await db.execute(text(LEDGER_SQL), {"fid": factory_id})).mappings().first() or {}
    bands = {str(r["band"]): int(r["n"]) for r in
             (await db.execute(text(BANDS_SQL), {"fid": factory_id})).mappings().all()}
    pop = dict((await db.execute(text(POPULATION_SQL),
                                 {"fid": factory_id})).mappings().first() or {})
    out = summarize(dict(ledger), bands, MIN_PAIRS_FOR_MAPE, pop)
    out["population"] = pop
    out["method"] = ("当时说了什么 vs 实际哪天完工（最早一条留痕配对）。"
                     "与 /sim-backtest 那条追溯法回测不是一件事：那条是用今天的主数据重跑历史单")
    out["caveat"] = ("误差带按实际日历日算（含停工日）；机种没落到声明过日产量的线上时当天不记，"
                     "所以账本覆盖的是有产能依据的那部分单")
    return out
