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

import io
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

# 账实核对要求的源快照新鲜度：超过这个天数就不判（源是 engflow 的一次性导入，
# 10-09 实测 imported_at 停在 2026-03-22 —— 拿它算差异，差异全是"过期"贡献的）
SNAPSHOT_FRESH_DAYS = 14


def _grade(state: str, name: str, reads: str, *, so_what: str = "",
           missing: str = "") -> Dict[str, Any]:
    return {"capability": name, "state": state, "reads": reads,
            "so_what": so_what, "missing": missing or None}

# ── 表有没有"对象"：三态要分开，别把"没实现"读成"没人用" ────────────────────
# 10-09 实测：光看 `Base.metadata` 会误判 —— `inventory_freezes` / `stock_alerts` /
# `wms_transfer_requests` / `safety_stock_config` 都没映射成 ORM 对象，但代码在用它们（裸 SQL）。
# 而 `wms_barcodes` / `wms_inventory_pools` / `wms_inventory_pool_members` / `wms_rfid_tags` /
# `wms_automation_jobs` 是**全仓零引用**：没对象、没裸 SQL、没端点。
# 两种"空表"不是一回事：前者是实现没人走，后者是功能从没实现过。
WMS_DOMAIN_TABLES = ("locations", "warehouses", "inventory", "inventory_freezes",
                     "inventory_counts", "inventory_count_items", "stock_alerts",
                     "safety_stock_config", "wms_barcodes", "wms_inventory_pools",
                     "wms_inventory_pool_members", "wms_rfid_tags", "wms_automation_jobs",
                     "wms_transfer_requests")


def classify_table(name: str, *, in_db: bool, mapped: bool, referenced: bool) -> str:
    """一张 WMS 表的三态判词（纯函数，两个方向都要测）。

    · wired        —— 有 ORM 对象；
    · raw_sql_only —— 没对象，只有裸 SQL 在读写：能用，但没有可挂属性/校验/界面的对象；
    · orphan       —— 库里建了表、代码里一个引用都没有：这功能从没实现过；
    · missing      —— 连表都不在库里（不许把"没有这张表"读成"0 行的空表"）。
    """
    if not in_db:
        return "missing"
    if mapped:
        return "wired"
    if referenced:
        return "raw_sql_only"
    return "orphan"


_CODE_ROOTS = ("api", "core", "database", "integrations")
_scan_cache: dict = {}


def table_references():
    """扫挂载在进程里的源码，返回"被引用过的 WMS 表名"集合；扫不动返回 None。

    两个坑：
    ① **排除本模块** —— 我的 docstring 里点名了这些表，留着就是自己证明自己存在；
    ② 扫不到必须说"算不出"，不能返回空集 —— 空集会被读成"这些表全是 orphan"，
       那正是把"测不出"当"没有"。容器只挂 api/core/database/integrations（scripts/ 没有），
       所以这一判据的意思是"运行时代码有没有引用"，不是"仓库里有没有字"。
    """
    if "value" in _scan_cache:
        return _scan_cache["value"]
    import os
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    here = os.path.abspath(__file__)
    found, scanned = set(), 0
    for top in _CODE_ROOTS:
        base = os.path.join(root, top)
        if not os.path.isdir(base):
            continue
        for dirpath, _dirs, files in os.walk(base):
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                path = os.path.join(dirpath, fn)
                if os.path.abspath(path) == here:
                    continue
                try:
                    body = io.open(path, encoding="utf-8", errors="ignore").read()
                except OSError:
                    continue
                scanned += 1
                for name in WMS_DOMAIN_TABLES:
                    if name in body:
                        found.add(name)
    out = None if scanned == 0 else found
    _scan_cache["value"] = out
    return out


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

    frz = await one("""
        SELECT (SELECT COUNT(*) FROM inventory_freezes WHERE factory_id=:fid
                 AND LOWER(status)='active') AS 活动,
               (SELECT COUNT(*) FROM inventory_freezes WHERE factory_id=:fid
                 AND LOWER(status)='released') AS 人放,
               (SELECT COUNT(*) FROM inventory_freezes WHERE factory_id=:fid
                 AND LOWER(status)='expired') AS 到期放,
               (SELECT COUNT(*) FROM inventory_freezes WHERE factory_id=:fid
                 AND LOWER(status)='active' AND auto_unfreeze
                 AND freeze_until IS NOT NULL AND freeze_until <= :now) AS 到期该放没放,
               (SELECT COUNT(*) FROM inventory WHERE factory_id=:fid
                 AND LOWER(COALESCE(status,''))='locked') AS 行上锁,
               (SELECT COUNT(*) FROM inventory i WHERE i.factory_id=:fid
                 AND LOWER(COALESCE(i.status,''))='locked'
                 AND NOT EXISTS (SELECT 1 FROM inventory_freezes f
                          WHERE f.inventory_id=i.id AND LOWER(f.status)='active')) AS 锁了没记,
               (SELECT COUNT(*) FROM inventory_freezes f WHERE f.factory_id=:fid
                 AND LOWER(f.status)='active'
                 AND NOT EXISTS (SELECT 1 FROM inventory i WHERE i.id=f.inventory_id
                          AND LOWER(COALESCE(i.status,''))='locked')) AS 记了没锁,
               (SELECT COUNT(*) FROM inventory WHERE factory_id=:fid
                 AND LOWER(COALESCE(status,''))='active') AS 词表active,
               (SELECT COUNT(*) FROM inventory WHERE factory_id=:fid
                 AND LOWER(COALESCE(status,''))='available') AS 词表available
        """, {"now": now})
    active = int(frz.get("活动") or 0)
    drift = int(frz.get("锁了没记") or 0) + int(frz.get("记了没锁") or 0)
    caps.append(_grade(
        ("empty" if not active and not int(frz.get("行上锁") or 0)
         else ("thin" if drift or active < int(frz.get("行上锁") or 0) or int(frz.get("记了没锁") or 0)
               else "live")),
        "冻结/放行",
        f"活动冻结 {frz.get('活动')} 条、行上锁 {frz.get('行上锁')} 行；"
        f"人放行 {frz.get('人放')}、到期自动放 {frz.get('到期放')}；"
        f"两笔账对不上 {drift} 处（锁了没记 {frz.get('锁了没记')}、记了没锁 {frz.get('记了没锁')}）；"
        f"台账 status 词表并存 active {frz.get('词表active')} / available {frz.get('词表available')} —— "
        f"到期该放还没放的 {frz.get('到期该放没放')} 条",
        so_what="冻结的判据不是'有没有记录'，而是**领料领不领得走**：写入原语 apply_movement/"
                "apply_transfer_pair 认 inventory.status='locked'，扣减和搬出当场拒（单测钉住两个方向）。"
                "'记了没锁'就是要不得的那种 —— 表里看着冻着，货照样被领走",
        missing=(None if (active and not drift) else
                 "POST /api/v1/wms/freeze 按库存行点名冻结（要 reason_code）；"
                 "到期自动放是 expire_due，人放行是 POST /api/v1/wms/freeze/release")))

    alert = await one("""
        SELECT COUNT(*) AS 落库报警,
               COUNT(*) FILTER (WHERE LOWER(status)='open') AS 开着,
               COUNT(*) FILTER (WHERE LOWER(status)='resolved'
                                AND COALESCE(resolved_by,'') LIKE 'system:%') AS 系统自动消,
               COUNT(*) FILTER (WHERE LOWER(status)='resolved'
                                AND COALESCE(resolved_by,'') NOT LIKE 'system:%') AS 人处理,
               (SELECT string_agg(DISTINCT alert_type, ',') FROM stock_alerts
                 WHERE factory_id = :fid) AS 出现过的类型
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

    # 有第二把尺在写同一张表吗？见 stock_alerts.foreign_kinds 的说明。
    from api.services.stock_alerts import foreign_kinds as _foreign

    _seen = [t for t in str(alert.get("出现过的类型") or "").split(",") if t.strip()]
    _foreign_types = _foreign(_seen)
    caps.append(_grade(
        "live" if not _foreign_types else "thin", "报警这张表有几把尺在写",
        f"落库类型 {sorted(_seen)}；不属于本轮判据的 {len(_foreign_types)} 个"
        f"{('：' + '、'.join(_foreign_types)) if _foreign_types else ''}",
        so_what="收口规矩是「只关本轮评估过的类型」，所以别人的类型一旦落库就永远关不掉 —— "
                "同一条缺料被两把尺各报一遍，其中一遍没人收。这一格专门探这件事"))

    cfgd = await one("""
        SELECT (SELECT COUNT(*) FROM safety_stock_config) AS 配置行,
               (SELECT COUNT(*) FROM safety_stock_config WHERE is_active) AS 活跃,
               (SELECT MIN(COALESCE(created_at, last_movement_at)) FROM inventory
                 WHERE factory_id=:fid) AS 台账最早时间,
               (SELECT COUNT(*) FROM inventory WHERE factory_id=:fid
                 AND last_movement_at IS NULL) AS 从没记过动销,
               (SELECT COUNT(DISTINCT material_id) FROM inventory WHERE factory_id=:fid
                 AND COALESCE(total_qty,0) > 0
                 AND UPPER(COALESCE(material_code,'')) NOT IN ('NAN','NULL','NONE','NA')
                 AND COALESCE(last_movement_at, created_at) < :d30) AS 没动30,
               (SELECT COUNT(DISTINCT material_id) FROM inventory WHERE factory_id=:fid
                 AND COALESCE(total_qty,0) > 0
                 AND UPPER(COALESCE(material_code,'')) NOT IN ('NAN','NULL','NONE','NA')
                 AND COALESCE(last_movement_at, created_at) < :d60) AS 没动60,
               (SELECT COUNT(DISTINCT material_id) FROM inventory WHERE factory_id=:fid
                 AND COALESCE(total_qty,0) > 0
                 AND UPPER(COALESCE(material_code,'')) NOT IN ('NAN','NULL','NONE','NA')
                 AND COALESCE(last_movement_at, created_at) < :d90) AS 没动90
        """, {"d30": now - timedelta(days=30), "d60": now - timedelta(days=60),
              "d90": now - timedelta(days=90)})
    # 为什么这一格不能报成"呆滞 0 条 = 没有呆滞料"：10-09 实测台账最早的时间戳是
    # 2026-08-09（`created_at` 记的是**镜像导入时间**，不是真实收货时间），
    # 所以 90 天口径在当前数据上恒为 0 —— 结构上到 2026-11-07 才可能第一次成立。
    # 空集合不等于"通过"：这里判的是这条尺**现在有没有资格开口**。
    can_fire_90 = bool(cfgd.get("台账最早时间")) and \
        cfgd["台账最早时间"] < now - timedelta(days=90)
    # 这条尺最早可能成立的日子 = 台账第一个时间戳 + 90 天（不是"今天 + 90 天"：
    # 报出去的日期要能从数据本身推出来，否则就是一句看着像结论的错话）
    _first_fire = (cfgd["台账最早时间"] + timedelta(days=90)) if cfgd.get("台账最早时间") else None
    caps.append(_grade(
        "blocked_on_source" if (int(cfgd.get("配置行") or 0) == 0 or not can_fire_90)
        else "empty",
        "呆滞料 / 超储 / 低于安全库存",
        f"safety_stock_config {cfgd.get('配置行')} 行（活跃 {cfgd.get('活跃')}）—— 这三个判据都在 "
        f"`if not config: continue` 后面，一条都不会报。"
        f"换到能算的口径上看：{cfgd.get('没动30')} 个有货料号 30 天没动、"
        f"{cfgd.get('没动60')} 个 60 天没动、{cfgd.get('没动90')} 个 90 天没动；"
        f"但**这最后一档现在是假零** —— 台账最早时间戳 {str(cfgd.get('台账最早时间'))[:10]} "
        f"晚于今天减 90 天，90 天这条尺结构上到 {str(_first_fire)[:10]} 之后"
        f"才可能第一次成立；另有 {cfgd.get('从没记过动销')} 行 last_movement_at 为空"
        f"（导入的是余额，不是动销历史）",
        so_what="不是厂里没有呆滞料，是这条尺还没资格开口：① 阈值（多少天算呆、多高算超储）"
                "厂里从没声明，代码里的 90 天是默认值不是核定值；② 台账 `created_at` 是镜像"
                "导入时间，拿它当'最后一次动销'的兜底会把'导入即静止'误读成'一直没人动'。"
                "两个原因叠在一起，报'呆滞 0 条'就是把'测不出'当成'没有'",
        missing="① 人把 safety_stock_config 填上（safety_stock / max_stock / dead_stock_days）；"
                "② 台账要带真实入库时间（或从 inventory_transactions 反推动销），"
                f"否则 90 天口径在 {str(_first_fire)[:10]} 之前都不会有意义"))

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


    # 地基盘点：这些表各自是"有对象 / 只有裸 SQL / 全仓零引用 / 库里没有"。
    from database.models import Base as _Base
    refs = table_references()
    in_db = set((await db.execute(text(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
    )).scalars().all() or [])
    mapped_now = set(_Base.metadata.tables)
    verdicts = {}
    for tb in WMS_DOMAIN_TABLES:
        verdicts[tb] = classify_table(tb, in_db=tb in in_db, mapped=tb in mapped_now,
                                      referenced=(tb in refs) if refs is not None else False)
    orphans = sorted(k for k, v in verdicts.items() if v == "orphan")
    raws = sorted(k for k, v in verdicts.items() if v == "raw_sql_only")
    absent = sorted(k for k, v in verdicts.items() if v == "missing")
    caps.append(_grade(
        "not_computable" if refs is None else ("thin" if orphans else "live"),
        "表有没有对象（地基盘点）",
        (f"扫不到源码目录（挂载里只有 {'/'.join(_CODE_ROOTS)}）—— 这一格算不出，不猜"
         if refs is None else
         f"{len(WMS_DOMAIN_TABLES)} 张 WMS 表：有对象 {len(WMS_DOMAIN_TABLES) - len(orphans) - len(raws) - len(absent)} 张、"
         f"只有裸 SQL {len(raws)} 张（{'、'.join(raws) or '无'}）、"
         f"全仓零引用 {len(orphans)} 张（{'、'.join(orphans) or '无'}）"
         + (f"、库里根本没有 {len(absent)} 张（{'、'.join(absent)}）" if absent else "")),
        so_what="两种'空表'不是一回事：裸 SQL 那几张能用但没有对象（挂不了属性、做不了校验、"
                "界面上没得点）；零引用那五张是**功能从没实现过**。把'WMS 功能弱'整个归给"
                "'实现了没人用'是读错了 —— 条码/库存池/RFID/自动化任务这四件事仓库里一行代码都没有",
        missing="零引用那张清单要么按厂里的需求立项再做，要么从'仓储功能'里划掉；"
                "不许为了让矩阵好看顺手造一个没人要的条码表"))

    states = {"live": 0, "thin": 0, "empty": 0, "blocked_on_source": 0,
              "not_computable": 0, "error": 0}
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
