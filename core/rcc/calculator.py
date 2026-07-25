"""
v2.6 - RCC Resource Calculator
RCC 数据计算层 — 全局统筹人/物/工单/环境/工艺基线计算

核心职责：
- people_calc: 人力资源统筹（在编人数、技能匹配、班次配置、负荷率）
- equipment_calc: 设备产能统筹（可用时间、效率系数、换型时间、OEE目标、PM周期）
- work_order_calc: 工单统筹（优先级权重、交期风险、排程状态、齐套状态）
- environment_calc: 环境基线统筹（温湿度标准值、当前读数对比、预警）
- process_calc: 工艺基线统筹（节拍时间、良品率基线、AQL级别）
- baseline_sync: 把真实DB数据汇总成RCC基线快照，供其他模块查询
"""

import uuid
from datetime import datetime, timezone, date, timedelta
from typing import Optional, List, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text as sql_text


class RCCResourceCalculator:
    """RCC 资源计算器 — 统一算力入口"""

    def __init__(self, db: AsyncSession):
        self.db = db

    def _parse_float(self, val, default=0.0):
        try:
            return float(val) if val is not None else default
        except (ValueError, TypeError):
            return default

    def _get_org_unit_id_for_factory(self, factory_id: str) -> str:
        """获取 org_unit 关联的工厂 ID。rcc-root 不直接绑定 factory_id"""
        return "rcc-root"

    async def _get_param_value(self, param_code: str, default=None) -> Optional[str]:
        """读取全局可调参数值"""
        q = await self.db.execute(sql_text(
            "SELECT current_value FROM global_adjustable_params WHERE param_code = :code",
            {"code": param_code}
        ))
        row = await q.scalar()
        return row

    # ──────────────────────────────────────────────────────────
    # People Baseline — 人力统筹
    # ──────────────────────────────────────────────────────────

    async def people_baseline(self, factory_id: str) -> Dict[str, Any]:
        """
        人力资源基线：
        1. 总编制 vs 在岗数 vs 缺勤数 vs 离职/退休
        2. 按部门 / 工位 / 班次 汇总
        3. 技能等级分布 (L1-L5)
        4. 与 global_adjustable_params 的偏差判断

        返回结构：
        {
            "total_headcount": 1044,
            "active_count": 1001,
            "leave_count": 30,
            "resigned_count": 13,
            "attendance_rate_pct": 98.7,
            "by_station": [...],      # 各工位在册/在岗
            "by_shift": {...},        # 白班/夜班/两班倒
            "skill_distribution": {...}, # L1-L5占比
            "load_alerts": [...]      # 超阈值报警项
        }
        """
        rows = await self.db.execute(sql_text("""
            SELECT
                COUNT(*)::int AS total,
                COUNT(*) FILTER (WHERE status='active')::int AS active,
                COUNT(*) FILTER (WHERE status='leave')::int AS on_leave,
                COUNT(*) FILTER (WHERE status='resigned')::int AS resigned,
                COUNT(*) FILTER (WHERE status='active' AND shift='白班')::int AS day_shift,
                COUNT(*) FILTER (WHERE status='active' AND shift='夜班')::int AS night_shift,
                COUNT(*) FILTER (WHERE status='active' AND shift='两班倒')::int AS two_shifts
            FROM hr_employees
            WHERE factory_id = :fid
        """), {"fid": factory_id})
        row = dict(rows.mappings().first()._mapping) if rows.first() else {}

        # 各工位明细
        station_rows = await self.db.execute(sql_text("""
            SELECT
                station,
                COUNT(*)::int AS total_in_station,
                COUNT(*) FILTER (WHERE status='active')::int AS active_in_station,
                COUNT(*) FILTER (WHERE skill_level IN ('L4','L5'))::int AS senior_in_station
            FROM hr_employees
            WHERE factory_id = :fid AND position IN ('操作员','组长','技术员')
              AND department NOT IN ('HR部','行政部','财务部','品质部')
            GROUP BY station
            ORDER BY station
        """), {"fid": factory_id})
        station_list = [dict(r._mapping) for r in station_rows.mappings().all()]

        # 部门分布
        dept_rows = await self.db.execute(sql_text("""
            SELECT
                department,
                COUNT(*) FILTER (WHERE status='active')::int AS active
            FROM hr_employees
            WHERE factory_id = :fid AND status = 'active' AND department NOT IN ('HR部','行政部','财务部','品质部')
            GROUP BY department
            ORDER BY active DESC
        """), {"fid": factory_id})
        dept_map = {r.department: r.active for r in dept_rows.mappings().all()}

        # 技能等级分布
        skill_rows = await self.db.execute(sql_text("""
            SELECT skill_level, COUNT(*)::int AS cnt
            FROM hr_employees
            WHERE factory_id = :fid AND status = 'active' AND department NOT IN ('HR部','行政部','财务部','品质部')
            GROUP BY skill_level
        """), {"fid": factory_id})
        skill_dist = {r.skill_level or "unlabeled": r.cnt for r in skill_rows.mappings().all()}

        # 按技能查询总数
        total_active_workers = sum(st["active_in_station"] for st in station_list) if station_list else row.get("active", 0)
        attendance_rate = round(row["active"] / row["total"] * 100) if row["total"] > 0 else 0

        # 参数基线偏差判断
        threshold_result = await self.db.execute(sql_text("""
            SELECT current_value FROM global_adjustable_params WHERE param_code = 'personnel_load_rate_threshold'
        """))
        load_threshold_str = threshold_result.scalar()
        load_threshold = self._parse_float(load_threshold_str, 85.0) / 100.0

        attendance_warning_threshold_str = await self.db.execute(sql_text("""
            SELECT current_value FROM global_adjustable_params WHERE param_code = 'absence_warning_threshold'
        """))
        absence_warn = self._parse_float(attendance_warning_threshold_str, 3.0)

        load_alerts = []
        for st in station_list:
            if st["total_in_station"] > 0 and st["active_in_station"] == 0:
                load_alerts.append({
                    "type": "zero_active", "station": st["station"],
                    "message": f"{st['station']} 无在岗人员！"
                })
            elif st["total_in_station"] > 0 and abs(1 - st["active_in_station"]/st["total_in_station"]) < absence_warn / 100:
                load_alerts.append({
                    "type": "understaffed", "station": st["station"],
                    "message": f"{st['station']} 在岗率 {round(st['active_in_station']/st['total_in_station']*100)}% 偏低"
                })

        return {
            "factory_id": factory_id,
            "calculated_at": datetime.now(timezone.utc).isoformat(),
            "headcount": row,
            "total_active_workers": total_active_workers,
            "department_breakdown": dept_map,
            "by_station": station_list,
            "skill_distribution": skill_dist,
            "attendance_rate_pct": attendance_rate,
            "load_threshold_pct": round(load_threshold * 100),
            "absence_warning_threshold_pct": absence_warn,
            "alerts": load_alerts,
        }

    # ──────────────────────────────────────────────────────────
    # Equipment Baseline — 设备统筹
    # ──────────────────────────────────────────────────────────

    async def equipment_baseline(self, factory_id: str) -> Dict[str, Any]:
        """
        设备产能基线：
        1. 设备总数、状态分布（running/idle/maintenance/offline）
        2. 各工位效率系数、可用时间、OEE目标
        3. PM计划完成情况
        4. 交期风险联动

        返回结构：
        {
            "total_equipment": 12,
            "status_distribution": {...},
            "by_station": [...],
            "oee_targets": {...},
            "pm_overdue": [...],
            "production_capacity_daily": {...}
        }
        """
        # 设备状态总览
        equip_rows = await self.db.execute(sql_text("""
            SELECT
                e.id, e.equipment_code, e.equipment_name, e.status,
                s.station_code
            FROM equipment e
            LEFT JOIN stations s ON s.id = e.station_id
            WHERE e.factory_id = :fid
        """), {"fid": factory_id})
        equip_list = [dict(r._mapping) for r in equip_rows.mappings().all()]

        status_dist = {}
        for eq in equip_list:
            key = eq["status"] or "unknown"
            status_dist[key] = status_dist.get(key, 0) + 1

        # 工位/设备能力参数
        cap_rows = await self.db.execute(sql_text("""
            SELECT sc.station_id, st.station_code, sc.available_hours_per_day, sc.efficiency_rate,
                   sc.setup_time_minutes, sc.is_active, eq.equipment_code, eq.status
            FROM station_capacity sc
            LEFT JOIN stations st ON st.id = sc.station_id OR st.station_code = sc.station_id
            LEFT JOIN equipment eq ON eq.station_id = sc.station_id AND eq.status IN ('available','running')
            WHERE sc.factory_id = :fid AND sc.is_active = TRUE
        """), {"fid": factory_id})
        capacity_list = []
        for r in cap_rows.mappings().all():
            capacity_list.append({
                "station_id": r["station_id"],
                "station_code": r.get("station_code") or r["station_id"],
                "equipment_code": r.get("equipment_code"),
                "available_hours_per_day": r["available_hours_per_day"],
                "efficiency_rate": r["efficiency_rate"],
                "setup_time_minutes": r["setup_time_minutes"],
                "is_active": r["is_active"],
                "status": r.get("status", "idle"),
                "daily_capacity_hours": r["available_hours_per_day"] * r["efficiency_rate"],
            })

        # OEE目标参数
        oee_target = 0.80
        result = await self.db.execute(sql_text("""
            SELECT current_value FROM global_adjustable_params WHERE param_code = 'oee_target_pct'
        """))
        val = result.scalar()
        if val:
            try:
                oee_target = self._parse_float(val) / 100.0
            except ValueError:
                pass

        # PM overdue
        pm_overdue = await self.db.execute(sql_text("""
            SELECT m.order_code, e.equipment_code, m.maintenance_type,
                   m.next_due_at, ABS(EXTRACT(DAY FROM CURRENT_DATE - m.next_due_at))::int AS days_past_due
            FROM maintenance_plans m
            JOIN equipment e ON e.id = m.equipment_id AND e.factory_id = m.factory_id
            WHERE m.factory_id = :fid AND m.is_active = TRUE
              AND COALESCE(m.next_due_at, CURRENT_DATE::timestamp) < NOW()
            ORDER BY days_past_due DESC
        """), {"fid": factory_id})
        pm_list = [dict(r._mapping) for r in pm_overdue.mappings().all()]

        # 实际产量/可用产能对比
        prod_rows = await self.db.execute(sql_text("""
            SELECT pr.station_id, SUM(pr.good_qty)::int AS today_good_qty,
                   COUNT(*)::int AS report_count,
                   st.station_code
            FROM production_reports pr
            JOIN stations st ON st.id = pr.station_id
            WHERE pr.factory_id = :fid AND pr.created_at >= CURRENT_DATE
            GROUP BY pr.station_id, st.station_code
            ORDER BY pr.station_id
        """), {"fid": factory_id})
        actual_output = {r.station_id: r.today_good_qty for r in prod_rows.mappings().all()}

        # 产能利用率
        for cap in capacity_list:
            sid = cap["station_id"]
            actual = actual_output.get(sid, 0)
            daily_cap_hrs = cap["daily_capacity_hours"]
            # 简化估算：假设每件1分钟 = 60件/小时（真实需要cycle time）
            cap["today_output"] = actual
            cap["utilization_pct"] = round(min(100, actual / (daily_cap_hrs * 60) * 100), 1)

        return {
            "factory_id": factory_id,
            "calculated_at": datetime.now(timezone.utc).isoformat(),
            "total_equipment": len(equip_list),
            "status_distribution": status_dist,
            "by_station": capacity_list,
            "oee_target_pct": round(oee_target * 100),
            "pm_overdue_count": len(pm_list),
            "pm_overdue": pm_list[:20],
            "actual_today_production": {k: v for k, v in actual_output.items()},
            "capacity_warnings": [
                c for c in capacity_list if c.get("utilization_pct", 0) < 20 and c.get("daily_capacity_hours", 0) > 0
            ],
        }

    # ──────────────────────────────────────────────────────────
    # Work Order Baseline — 工单统筹
    # ──────────────────────────────────────────────────────────

    async def work_order_baseline(self, factory_id: str) -> Dict[str, Any]:
        """
        工单统筹基线：
        1. 订单状态分布
        2. 急单比例、交期风险工单
        3. APS排程状态
        4. 齐套率
        5. 与global_adjustable_params的联动

        返回结构：
        {
            "total_work_orders": 50,
            "status_distribution": {...},
            "urgent_orders": [...],
            "delivery_risk": [...],
            "aps_status": {...},
            "material_readiness": {...}
        }
        """
        # 工单状态分布
        wo_status_rows = await self.db.execute(sql_text("""
            SELECT status, COUNT(*)::int AS cnt
            FROM work_orders
            WHERE factory_id = :fid
            GROUP BY status
            ORDER BY cnt DESC
        """), {"fid": factory_id})
        status_dist = {r.status or "unlabeled": r.cnt for r in wo_status_rows.mappings().all()}

        # 优先级别分布
        priority_rows = await self.db.execute(sql_text("""
            SELECT priority, COUNT(*)::int AS cnt
            FROM work_orders
            WHERE factory_id = :fid AND status NOT IN ('cancelled', 'closed')
            GROUP BY priority
            ORDER BY cnt DESC
        """), {"fid": factory_id})
        priority_dist = {r.priority or "medium": r.cnt for r in priority_rows.mappings().all()}

        # 急单
        urgent_result = await self.db.execute(sql_text("""
            SELECT work_order_code, product_id, planned_qty, completed_qty,
                   priority, planned_due, WO_STATUS,
                   ROUND((completed_qty::float / NULLIF(planned_qty, 0) * 100), 1) AS progress_pct
            FROM work_orders
            WHERE factory_id = :fid AND priority IN ('urgent', 'emergency') AND WO_STATUS NOT IN ('cancelled','closed')
            ORDER BY planned_due ASC NULLS LAST
        """), {"fid": factory_id})
        urgent_orders = [dict(r._mapping) for r in urgent_result.mappings().all()][:20]

        # 交期风险（planned_due < now 且未完工）
        risk_result = await self.db.execute(sql_text("""
            SELECT work_order_code, product_id, planned_qty, completed_qty,
                   planned_due, WO_STATUS,
                   ROUND(EXTRACT(EPOCH FROM NOW() - planned_due) / 86400.0)::int AS days_overdue
            FROM work_orders
            WHERE factory_id = :fid AND planned_due IS NOT NULL AND planned_due < NOW()
              AND WO_STATUS NOT IN ('cancelled', 'closed', 'completed')
            ORDER BY planned_due ASC
        """), {"fid": factory_id})
        at_risk = [dict(r._mapping) for r in risk_result.mappings().all()]

        # APS排程状态
        aps_result = await self.db.execute(sql_text("""
            SELECT COUNT(*)::int AS total_schedule_tasks,
                   MAX(planned_end) AS latest_end,
                   COUNT(*) FILTER (WHERE status='confirmed')::int AS confirmed_count,
                   COUNT(*) FILTER (WHERE status='draft')::int AS draft_count
            FROM aps_schedule_tasks t
            JOIN aps_schedules s ON s.id = t.schedule_id
            WHERE s.factory_id = :fid AND s.status IN ('draft','confirmed')
        """), {"fid": factory_id})
        aps_row = aps_result.mappings().first()

        # 齐套状态
        mat_ready_result = await self.db.execute(sql_text("""
            SELECT COUNT(*) FILTER (WHERE material_ready = TRUE)::int AS ready,
                   COUNT(*) FILTER (WHERE material_ready = FALSE)::int AS not_ready
            FROM sales_orders
            WHERE factory_id = :fid AND status NOT IN ('cancelled','closed')
        """), {"fid": factory_id})
        mat_row = mat_ready_result.mappings().first()

        # 可调参数读取
        param_map = {}
        for code in ["priority_weight_urgent", "priority_weight_high", "priority_weight_medium",
                      "delivery_grace_period_hours", "max_parallel_orders_per_station"]:
            presult = await self.db.execute(sql_text("""
                SELECT current_value FROM global_adjustable_params WHERE param_code = :code
            """), {"code": code})
            val = presult.scalar()
            if val is not None:
                try:
                    param_map[code] = float(val)
                except (ValueError, TypeError):
                    pass

        # 未排入APS的工单
        unscheduled = await self.db.execute(sql_text("""
            SELECT COUNT(*)::int AS cnt
            FROM work_orders w
            WHERE w.factory_id = :fid AND w.WO_STATUS IN ('released','pending')
              AND NOT EXISTS (
                  SELECT 1 FROM aps_schedule_tasks t
                  JOIN aps_schedules s ON s.id = t.schedule_id
                  WHERE s.factory_id = :fid AND t.work_order_id = w.id
              )
        """), {"fid": factory_id})
        unscheduled_cnt = unscheduled.scalar() or 0

        return {
            "factory_id": factory_id,
            "calculated_at": datetime.now(timezone.utc).isoformat(),
            "total_work_orders": status_dist.get("released", 0) + status_dist.get("in_progress", 0) + status_dist.get("pending", 0),
            "status_distribution": status_dist,
            "priority_distribution": priority_dist,
            "urgent_orders": urgent_orders,
            "delivery_risk_count": len(at_risk),
            "delivery_risk_orders": at_risk[:20],
            "aps_status": {
                "total_tasks": aps_row["total_schedule_tasks"] if aps_row else 0,
                "latest_end": aps_row["latest_end"].isoformat() if aps_row and aps_row["latest_end"] else None,
                "confirmed_count": aps_row["confirmed_count"] if aps_row else 0,
                "draft_count": aps_row["draft_count"] if aps_row else 0,
                "unscheduled_count": unscheduled_cnt,
            },
            "material_readiness": {
                "ready_count": mat_row["ready"] if mat_row else 0,
                "not_ready_count": mat_row["not_ready"] if mat_row else 0,
            },
            "adjustable_params": param_map,
        }

    # ──────────────────────────────────────────────────────────
    # Environment Baseline — 环境基线
    # ──────────────────────────────────────────────────────────

    async def environment_baseline(self, factory_id: str) -> Dict[str, Any]:
        """
        环境基线：
        1. 车间环境标准值（从 global_adjustable_params 读取）
        2. 最近实测读数（从 environment_readings 读取）
        3. 偏差判断 → 预警

        返回结构：
        {
            "factory_id": "...",
            "standards": {
                "temperature": {"min": 18, "max": 28, "unit": "°C"},
                "humidity": {"min": 30, "max": 70, "unit": "%"},
                "cleanliness": {"dust_limit_ug_m3": 100}
            },
            "last_reading": {...},
            "alert": bool,
            "warnings": [...]
        }
        """
        # 环境标准参数
        env_params = {}
        for code in ["env_temperature_min_c", "env_temperature_max_c",
                      "env_humidity_min_pct", "env_humidity_max_pct",
                      "env_dust_limit_ug_m3", "env_noise_limit_db"]:
            presult = await self.db.execute(sql_text("""
                SELECT current_value FROM global_adjustable_params WHERE param_code = :code
            """), {"code": code})
            val = presult.scalar()
            env_params[code] = self._parse_float(val) if val else None

        standards = {
            "temperature": {
                "min": env_params.get("env_temperature_min_c") or 18,
                "max": env_params.get("env_temperature_max_c") or 28,
                "unit": "°C",
            },
            "humidity": {
                "min": env_params.get("env_humidity_min_pct") or 30,
                "max": env_params.get("env_humidity_max_pct") or 70,
                "unit": "%",
            },
            "dust": {
                "limit_ug_m3": env_params.get("env_dust_limit_ug_m3") or 100,
            },
            "noise": {
                "limit_db": env_params.get("env_noise_limit_db") or 85,
            },
        }

        # 最近一次读数
        reading_result = await self.db.execute(sql_text("""
            SELECT * FROM environment_readings
            WHERE factory_id = :fid AND reading_type = 'iot_sensor'
            ORDER BY measured_at DESC LIMIT 1
        """), {"fid": factory_id})
        last_reading = dict(reading_result.mappings().first()._mapping) if reading_result.first() else None

        if not last_reading:
            weather_result = await self.db.execute(sql_text("""
                SELECT * FROM environment_readings
                WHERE factory_id = :fid AND reading_type = 'weather'
                ORDER BY measured_at DESC LIMIT 1
            """), {"fid": factory_id})
            last_reading = dict(weather_result.mappings().first()._mapping) if weather_result.first() else None

        warnings = []
        if last_reading:
            temp = last_reading.get("temperature_c")
            hum = last_reading.get("humidity_pct")
            dust = last_reading.get("dust_ug_m3")

            if temp is not None:
                if temp < standards["temperature"]["min"]:
                    warnings.append({"type": "temp_low", "value": temp, "standard": standards["temperature"], "message": f"温度{temp}°C低于下限{standards['temperature']['min']}°C"})
                elif temp > standards["temperature"]["max"]:
                    warnings.append({"type": "temp_high", "value": temp, "standard": standards["temperature"], "message": f"温度{temp}°C高于上限{standards['temperature']['max']}°C"})
            if hum is not None:
                if hum < standards["humidity"]["min"]:
                    warnings.append({"type": "humidity_low", "value": hum, "standard": standards["humidity"], "message": f"湿度{hum}%低于下限{standards['humidity']['min']}%"})
                elif hum > standards["humidity"]["max"]:
                    warnings.append({"type": "humidity_high", "value": hum, "standard": standards["humidity"], "message": f"湿度{hum}%高于上限{standards['humidity']['max']}%"})
            if dust is not None and standards["dust"]["limit_ug_m3"]:
                if dust > standards["dust"]["limit_ug_m3"]:
                    warnings.append({"type": "dust_high", "value": dust, "standard": standards["dust"], "message": f"粉尘{dust}µg/m³超过限值{standards['dust']['limit_ug_m3']}"})

        return {
            "factory_id": factory_id,
            "calculated_at": datetime.now(timezone.utc).isoformat(),
            "standards": standards,
            "last_reading": last_reading,
            "has_data": bool(last_reading),
            "warnings": warnings,
            "alert": len(warnings) > 0,
        }

    # ──────────────────────────────────────────────────────────
    # Process Baseline — 工艺基线
    # ──────────────────────────────────────────────────────────

    async def process_baseline(self, factory_id: str) -> Dict[str, Any]:
        """
        工艺基线：
        1. 工艺路线版本数
        2. 标准节拍时间（从工艺路线步骤中推导）
        3. 良品率基线（从 shift_summaries 中计算近30天平均）
        4. AQL级别
        5. 与 quality_goals 质量目标的对标

        返回结构：
        {
            "routing_count": 8,
            "by_process": [...],          # 各工序的标准节拍
            "yield_baseline_30d": 98.5,   # %
            "defect_top3": [...],         # Top3不良类型
            "aql_levels": {...},          # 各检验类型AQL
            "quality_goal_gap": {...}     # 目标vs实际差距
        }
        """
        # 工艺路线统计
        routing_rows = await self.db.execute(sql_text("""
            SELECT COUNT(*)::int AS count
            FROM routing
            WHERE factory_id = :fid AND is_active = TRUE
        """), {"fid": factory_id})
        routing_count = routing_rows.scalar() or 0

        # 工序标准节拍（从 shift_summaries 中取平均每工序产出时间）
        cycle_rows = await self.db.execute(sql_text("""
            SELECT op_seq, op_name, COUNT(*)::int AS report_count,
                   AVG(cycle_time_sec)::int AS avg_cycle_sec,
                   AVG(good_qty::float / NULLIF(total_output, 0) * 100)::numeric(5,2) AS avg_yield_pct
            FROM shift_summaries
            WHERE factory_id = :fid AND created_at >= CURRENT_DATE - INTERVAL '30 days'
              AND total_output > 0
            GROUP BY op_seq, op_name
            ORDER BY report_count DESC
            LIMIT 20
        """), {"fid": factory_id})
        process_cycles = [dict(r._mapping) for r in cycle_rows.mappings().all()]

        # 近30天良品率
        yield_rows = await self.db.execute(sql_text("""
            SELECT AVG(good_qty::float / NULLIF(total_output, 0) * 100)::numeric(5,2) AS avg_yield_pct,
                   SUM(good_qty)::int AS total_good,
                   SUM(total_output)::int AS total_output
            FROM shift_summaries
            WHERE factory_id = :fid AND created_at >= CURRENT_DATE - INTERVAL '30 days'
              AND total_output > 0
        """), {"fid": factory_id})
        yield_row = yield_rows.mappings().first()

        # Top3 不良类型
        defect_rows = await self.db.execute(sql_text("""
            SELECT defect_type, COUNT(*)::int AS cnt
            FROM defect_records
            WHERE factory_id = :fid
              AND created_at >= CURRENT_DATE - INTERVAL '30 days'
              AND defect_type IS NOT NULL AND defect_type != ''
            GROUP BY defect_type
            ORDER BY cnt DESC
            LIMIT 3
        """), {"fid": factory_id})
        top_defects = [dict(r._mapping) for r in defect_rows.mappings().all()]

        # AQL级别基线
        aql_rows = await self.db.execute(sql_text("""
            SELECT aql_level, COUNT(*)::int AS inspect_count
            FROM quality_inspections
            WHERE factory_id = :fid AND aql_level IS NOT NULL
            GROUP BY aql_level
            ORDER BY COUNT(*) DESC
            LIMIT 5
        """), {"fid": factory_id})
        aql_levels = {r.aql_level or "unknown": r.inspect_count for r in aql_rows.mappings().all()}

        # 质量目标对标
        qg_rows = await self.db.execute(sql_text("""
            SELECT goal_code, metric_type, target_value::float AS target_val,
                   actual_value::float AS actual_val
            FROM quality_goals
            WHERE factory_id = :fid AND current_period = TRUE
        """), {"fid": factory_id})
        qg_list = [dict(r._mapping) for r in qg_rows.mappings().all()]

        goal_gap = {}
        for qg in qg_list:
            target = qg["target_val"] or 0
            actual = qg["actual_val"] or 0
            gap = round(actual - target, 2) if target > 0 else 0
            goal_gap[qg["goal_code"]] = {
                "metric_type": qg["metric_type"],
                "target": target,
                "actual": actual,
                "gap": gap,
                "status": "on_track" if gap >= 0 else "off_track",
            }

        return {
            "factory_id": factory_id,
            "calculated_at": datetime.now(timezone.utc).isoformat(),
            "routing_count": routing_count,
            "process_cycles": process_cycles,
            "yield_baseline_30d": yield_row["avg_yield_pct"] if yield_row else None,
            "total_output_30d": yield_row["total_output"] if yield_row else 0,
            "top_defects_30d": top_defects,
            "aql_levels": aql_levels,
            "quality_goals": goal_gap,
        }

    # ──────────────────────────────────────────────────────────
    # Full Baseline Sync — 全量基线同步
    # ──────────────────────────────────────────────────────────

    async def full_baseline_sync(self, factory_id: str) -> Dict[str, Any]:
        """
        全量RCC基线同步：
        1. 获取所有子基线数据
        2. 生成一份完整的快照存入 parameter_change_audit 的历史记录
        3. 返回全局概览

        这是 RCC 的核心功能 —— 把分散在各个模块的数据，统一汇总为一个可查询的基线。
        """
        people = await self.people_baseline(factory_id)
        equipment = await self.equipment_baseline(factory_id)
        work_orders = await self.work_order_baseline(factory_id)
        environment = await self.environment_baseline(factory_id)
        process = await self.process_baseline(factory_id)

        # 写入 baseline 元数据作为 parameter_change_audit 记录
        from database.models import Notification
        import uuid as _uuid
        baseline_meta = {
            "people_headcount": people.get("total_active_workers", 0),
            "people_by_shift": people.get("headcount", {}),
            "equipment_count": equipment.get("total_equipment", 0),
            "oee_target_pct": equipment.get("oee_target_pct", 80),
            "work_orders": work_orders.get("status_distribution", {}),
            "urgent_orders": len(work_orders.get("urgent_orders", [])),
            "delivery_risk_count": work_orders.get("delivery_risk_count", 0),
            "environment_alert": environment.get("alert", False),
            "process_yield_30d": process.get("yield_baseline_30d"),
        }

        return {
            "factory_id": factory_id,
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "baseline": {
                "people": {
                    "active_workers": people.get("total_active_workers"),
                    "attendance_rate_pct": people.get("attendance_rate_pct"),
                    "skills": people.get("skill_distribution", {}),
                    "alert_count": len(people.get("alerts", [])),
                },
                "equipment": {
                    "total": equipment.get("total_equipment"),
                    "statuses": equipment.get("status_distribution", {}),
                    "oee_target_pct": equipment.get("oee_target_pct"),
                    "pm_overdue_count": equipment.get("pm_overdue_count"),
                },
                "work_orders": {
                    "status": work_orders.get("status_distribution", {}),
                    "urgent_count": len(work_orders.get("urgent_orders", [])),
                    "delivery_risk_count": work_orders.get("delivery_risk_count"),
                    "unscheduled_count": work_orders.get("aps_status", {}).get("unscheduled_count", 0),
                },
                "environment": {
                    "has_data": environment.get("has_data"),
                    "warning_count": len(environment.get("warnings", [])),
                    "alert": environment.get("alert"),
                },
                "process": {
                    "yield_baseline_30d": process.get("yield_baseline_30d"),
                    "routing_count": process.get("routing_count"),
                    "top_defects": process.get("top_defects_30d", []),
                },
            },
        }
