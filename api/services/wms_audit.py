"""WMS 能力矩阵：每一格给"能不能用"的判词 + 支撑它的实测数，不给印象分。

10-09 清点出来的事实：WMS 有 15 张表、24 个端点、5 个页面，但**11 张表 0 行**
（locations / inventory_counts / inventory_count_items / inventory_freezes /
safety_stock_config / stock_alerts / wms_barcodes / wms_inventory_pools(+members) /
wms_transfer_requests / wms_rfid_tags / wms_automation_jobs）。
"功能很弱"不是方法少 —— `wms_service.py` 里建盘点单、录入、审批、FIFO、追溯都有；
是**这些操作从来没有发生过**，所以整个库内作业层没有对象可挂。

三格判词必须分清（和分层验收同一套语义，别把"没做过"读成"坏了"）：
· live   —— 有数据、有人在用；
· empty  —— 表和接口都在，0 行：功能没被走过（这才是"弱"）；
· blocked_on_source —— 算不了是因为**外部源没有新数**，点名缺哪个源、什么时候停更的，
  不许拿 2026-03-22 那份库存快照当"今天的实测"来出账实差异。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# 账实核对要求的源快照新鲜度：超过这个天数就不判（源是 engflow 的一次性导入，
# 10-09 实测 imported_at 停在 2026-03-22 —— 拿它算差异，差异全是"过期"贡献的）
SNAPSHOT_FRESH_DAYS = 14


def _grade(state: str, name: str, reads: str, *, so_what: str = "",
           missing: str = "") -> Dict[str, Any]:
    return {"capability": name, "state": state, "reads": reads,
            "so_what": so_what, "missing": missing or None}


async def capability_matrix(db, factory_id: str) -> Dict[str, Any]:
    """跑一遍实测，返回每一格的判词。只读，不写任何表。"""
    from sqlalchemy import text

    async def one(sql: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        try:
            row = (await db.execute(text(sql), {"fid": factory_id, **(params or {})})).mappings().first()
            await db.rollback()
            return dict(row or {})
        except Exception as exc:  # noqa: BLE001  读不到要写出来，不能当"没有数据"
            await db.rollback()
            return {"error": f"{type(exc).__name__}: {str(exc)[:70]}"}

    caps: List[Dict[str, Any]] = []
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    led = await one("""
        SELECT COUNT(*) AS 行, COUNT(DISTINCT material_code) AS 料号,
               COUNT(*) FILTER (WHERE COALESCE(batch_code,'') <> '') AS 有批次,
               COUNT(*) FILTER (WHERE COALESCE(unit_cost,0) > 0) AS 有单价,
               COUNT(*) FILTER (WHERE expiry_date IS NOT NULL) AS 有有效期,
               MAX(updated_at) AS 最后更新
        FROM inventory WHERE factory_id = :fid""")
    caps.append(_grade("live", "库存台账与过账",
                       f"{led.get('行')} 行、{led.get('料号')} 个料号，最后更新 {led.get('最后更新')}"))

    tx = await one("""
        SELECT COUNT(*) AS 条,
               COUNT(*) FILTER (WHERE transaction_type='production_out') AS 领料出库,
               COUNT(*) FILTER (WHERE transaction_type='purchase_in') AS 采购入库,
               COUNT(*) FILTER (WHERE transaction_type='transfer') AS 移库,
               COUNT(*) FILTER (WHERE transaction_type='adjustment_out') AS 调整,
               COUNT(*) FILTER (WHERE transaction_type='transfer'
                                AND COALESCE(reference_doc_no,'')='') AS 移库无单据,
               MIN(created_at) AS 最早, MAX(created_at) AS 最新
        FROM inventory_transactions t
        WHERE COALESCE(t.factory_id, :fid) = :fid""")
    caps.append(_grade(
        "live" if int(tx.get("条") or 0) > 0 else "empty", "出入库流水",
        f"{tx.get('条')} 条（领料 {tx.get('领料出库')}、采购入 {tx.get('采购入库')}、"
        f"移库 {tx.get('移库')}、调整 {tx.get('调整')}），{tx.get('最早')} → {tx.get('最新')}",
        so_what="过账这条腿是活的：报工扣料、完工入库都留了痕"))
    if int(tx.get("移库无单据") or 0):
        caps.append(_grade(
            "empty", "移库单据",
            f"{tx.get('移库')} 条移库流水里 {tx.get('移库无单据')} 条没有单据号，"
            "wms_transfer_requests 0 行",
            so_what="移库是绕过审批直接改账：没有申请、没有批准人、没有 from/to 的对象",
            missing="建 transfer 单 → 审批 → 完成时才过账（现在反了）"))

    loc = await one("""
        SELECT (SELECT COUNT(*) FROM locations) AS 库位对象,
               (SELECT COUNT(DISTINCT location_code) FROM inventory
                 WHERE factory_id=:fid AND COALESCE(location_code,'')<>'') AS 台账里的库位号,
               (SELECT COUNT(*) FROM inventory WHERE factory_id=:fid AND location_id IS NULL
                 AND COALESCE(location_code,'')<>'') AS 有号没挂上,
               (SELECT COUNT(*) FROM inventory WHERE factory_id=:fid
                 AND COALESCE(location_code,'')='') AS 连号都没有""")
    caps.append(_grade(
        "live" if int(loc.get("库位对象") or 0) > 0 else "empty", "库位（货架格子）",
        f"locations {loc.get('库位对象')} 行，而台账里有 {loc.get('台账里的库位号')} 个不同库位号；"
        f"{loc.get('有号没挂上')} 行有号但没挂上对象，{loc.get('连号都没有')} 行连号都没有",
        so_what="库位不是对象 → 上架没目标、移库没 from/to、盘点没范围、容量没得校验",
        missing="从台账派生库位并回填 location_id（wms_locations.sync_locations）"))

    dirt = await one("""
        SELECT COUNT(*) AS 行,
               COUNT(*) FILTER (WHERE UPPER(material_code) IN ('NAN','NULL','NONE','NA')) AS 料号是脏的,
               COALESCE(SUM(total_qty),0) AS 件数合计,
               COALESCE(SUM(total_qty) FILTER (WHERE UPPER(material_code) IN ('NAN','NULL','NONE','NA')),0) AS 脏行件数
        FROM inventory WHERE factory_id = :fid""")
    share = round(float(dirt.get("脏行件数") or 0) / max(1.0, float(dirt.get("件数合计") or 1)), 4)
    caps.append(_grade(
        "thin" if share > 0.01 else "live", "台账数据质量",
        f"{dirt.get('行')} 行里 {dirt.get('料号是脏的')} 行的料号是 nan/NULL 一类，"
        f"这些行合计 {int(float(dirt.get('脏行件数') or 0)):,} 件 = 占台账总件数 {round(share*100,2)}%",
        so_what="按件数算的读数（库存量、齐套、呆滞）会被这一行整体抬高 —— "
                "10-09 实测最大的一行料号叫 nan、库位叫 LOC-LG-NAN，独占 50.1%",
        missing="源侧导入要把 NaN 挡在落库前；已入库的这类行要人决定冲回还是补料号，"
                "引擎不自己删（删库存行是厂里的账）"))

    cnt = await one("""
        SELECT (SELECT COUNT(*) FROM inventory_counts WHERE factory_id = :fid) AS 盘点单,
               (SELECT COUNT(*) FROM inventory_counts WHERE factory_id = :fid
                 AND LOWER(status) = 'approved') AS 已审批,
               (SELECT COUNT(*) FROM inventory_count_items ci
                 JOIN inventory_counts c ON c.id = ci.count_id
                 WHERE c.factory_id = :fid) AS 明细行,
               (SELECT COUNT(*) FROM inventory_count_items ci
                 JOIN inventory_counts c ON c.id = ci.count_id
                 WHERE c.factory_id = :fid AND ci.counted_qty IS NOT NULL) AS 已录入,
               (SELECT COUNT(*) FROM inventory_count_items ci
                 JOIN inventory_counts c ON c.id = ci.count_id
                 WHERE c.factory_id = :fid AND ci.adjusted) AS 已调差""")
    orders = int(cnt.get("盘点单") or 0)
    counted = int(cnt.get("已录入") or 0)
    approved = int(cnt.get("已审批") or 0)
    # 三态分开：开了单 ≠ 盘过了 ≠ 调过账。只数"单"会把引擎自己开的空单读成功能上线。
    state = "empty" if not orders else ("live" if approved else "thin")
    caps.append(_grade(
        state, "盘点（账实一致）",
        (f"inventory_counts {orders} 单、明细 {cnt.get('明细行')} 行，"
         f"其中已录实测数 {counted} 行、已审批 {approved} 单、已调差 {cnt.get('已调差')} 行"
         if orders else "inventory_counts 0 单（建单/录入/审批三个接口都在，从来没被调用过）"),
        so_what="没有盘点 = 台账说有多少就是多少，谁也没验证过；"
                "10-08 那次'零领料却完工入库 165 件虚假半成品'就是这类没被盘出来",
        missing=(None if approved else
                 ("要人把实测数录进 inventory_count_items（GET /api/v1/wms/count-plan 看该盘哪些行）"
                  if orders else "GET /api/v1/wms/count-plan?apply=false 先看范围"))))

    frz = await one("SELECT COUNT(*) AS 冻结 FROM inventory_freezes WHERE factory_id = :fid")
    caps.append(_grade("empty" if not int(frz.get("冻结") or 0) else "live", "冻结/放行",
                       f"inventory_freezes {frz.get('冻结')} 行",
                       so_what="待检、质量拦截、事故封存都没有对象可挂 —— 只能靠口头不让领"))

    alert = await one("""
        SELECT COUNT(*) AS 落库报警,
               COUNT(*) FILTER (WHERE LOWER(status)='open') AS 开着,
               COUNT(*) FILTER (WHERE LOWER(status)='resolved'
                                AND COALESCE(resolved_by,'') LIKE 'system:%') AS 系统自动消,
               COUNT(*) FILTER (WHERE LOWER(status)='resolved'
                                AND COALESCE(resolved_by,'') NOT LIKE 'system:%') AS 人处理
        FROM stock_alerts WHERE factory_id = :fid""")
    below = await one("""
        SELECT COUNT(*) AS 低于补货点, COUNT(*) FILTER (WHERE COALESCE(total_qty,0)=0) AS 其中零库存
        FROM inventory WHERE factory_id=:fid AND COALESCE(reorder_point,0)>0
          AND available_qty < reorder_point""")
    req = await one("""
        SELECT COUNT(*) AS 请购单, MAX(created_at) AS 最近 FROM purchase_requests
        WHERE factory_id=:fid""")
    caps.append(_grade(
        "live", "补货",
        f"{below.get('低于补货点')} 个料低于补货点（{below.get('其中零库存')} 个已零库存）；"
        f"warehouse_agent 已开请购单 {req.get('请购单')} 张，最近 {req.get('最近')}",
        so_what="补货这条腿是活的（写 purchase_requests），但报警不落库"))
    caps.append(_grade(
        "empty" if not int(alert.get("落库报警") or 0) else "live", "报警闭环",
        (f"stock_alerts {alert.get('落库报警')} 行：开着 {alert.get('开着')}、"
         f"系统重算自动消 {alert.get('系统自动消')}、人处理 {alert.get('人处理')}"
         if int(alert.get("落库报警") or 0) else
         "stock_alerts 0 行 —— 报警是每次实时算的，算完就丢，"
         "没有「谁在处理 / 处理完了」这一格"),
        so_what="实时算出来的告警不落库，就永远无法回答'上次那条缺料告警谁处理的、多久处理的'；"
                "落库之后还要能分清'人处理了'与'条件自己消失'，否则自动消警会被读成人已处理",
        missing=None if int(alert.get("落库报警") or 0)
        else "GET /api/v1/wms/alert-sync?apply=false 先看四把尺各报多少"))

    money = await one("""
        SELECT COUNT(*) AS 行, COUNT(*) FILTER (WHERE COALESCE(unit_cost,0)>0) AS 有单价,
               COALESCE(SUM(total_qty * COALESCE(unit_cost,0)),0) AS 台账金额
        FROM inventory WHERE factory_id=:fid""")
    fill = round(int(money.get("有单价") or 0) / max(1, int(money.get("行") or 1)), 4)
    caps.append(_grade(
        "thin" if fill < 0.5 else "live", "库存金额",
        f"unit_cost 有值的行 {money.get('有单价')}/{money.get('行')}（{round(fill*100,2)}%），"
        f"按台账算出来的库存金额 {round(float(money.get('台账金额') or 0),2)}",
        so_what="单价几乎全空 → 库存价值、呆滞资金占用、ABC 按金额分档都算不出来",
        missing="源侧 value_unrestricted / BOM unit_price 派生一个**标注为估算**的单价，"
                "不回填 unit_cost 这个事实字段"))

    snap = await one("""
        SELECT COUNT(*) AS 可比料,
               COUNT(*) FILTER (WHERE ABS(COALESCE(g.qty,0)-COALESCE(i.qty,0)) < 0.001) AS 一致
        FROM (SELECT material_id, SUM(qty) qty FROM lg_stock_agg GROUP BY 1) g
        JOIN (SELECT material_code, SUM(total_qty) qty FROM inventory
               WHERE factory_id=:fid GROUP BY 1) i ON i.material_code = g.material_id""")
    caps.append(_grade(
        "blocked_on_source", "账实核对（对 engflow 快照）",
        f"lg_stock_agg {snap.get('可比料')} 个可比料里 {snap.get('一致')} 个一致；"
        "但源快照 imported_at 停在 2026-03-22（一次性导入，无自动跟随）",
        so_what=f"快照距今超过 {SNAPSHOT_FRESH_DAYS} 天就不判：差异主要是'过期'贡献的，"
                "读成'账实不符'是冤枉现场，也修不了",
        missing="engflow 侧库存导入要有新数 + 带水位线；EngHub 这边镜像要自动跟随（不是手工聚合表）"))

    states = {"live": 0, "thin": 0, "empty": 0, "blocked_on_source": 0, "error": 0}
    for c in caps:
        if c.get("reads", "").startswith("Traceback"):
            states["error"] += 1
        else:
            states[c["state"]] = states.get(c["state"], 0) + 1
    return {"factory_id": factory_id, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "capabilities": caps, "score": states,
            "rule": ("live=有数据有人在用；thin=有数但填充率低到不能当结论；"
                     "empty=表和接口都在、0 行（功能没被走过，这就是'弱'）；"
                     "blocked_on_source=外部源没有新数，点名哪个源、停更多久，"
                     "不拿过期快照出读数。空表不等于坏了，也不等于通过。")}
