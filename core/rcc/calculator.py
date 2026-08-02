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

    async def _rollback_after_error(self) -> None:
        """Clear failed DB transactions so later RCC sections can still render."""
        try:
            await self.db.rollback()
        except Exception:
            pass

    async def _get_param_value(self, param_code: str) -> Optional[str]:
        """读取全局可调参数值"""
        try:
            q = await self.db.execute(
                sql_text("SELECT current_value FROM global_adjustable_params WHERE param_code = :code"),
                {"code": param_code},
            )
            return q.scalar()
        except Exception:
            await self._rollback_after_error()
            return None

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
        result = {
            "factory_id": factory_id,
            "calculated_at": datetime.now(timezone.utc).isoformat(),
            "headcount": {},
            "total_active_workers": 0,
            "department_breakdown": {},
            "by_station": [],
            "skill_distribution": {},
            "attendance_rate_pct": 0,
            "load_threshold_pct": 85,
            "absence_warning_threshold_pct": 3,
            "alerts": [],
        }

        try:
            # 总编制统计
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
            row = rows.mappings().first()
            if row:
                result["headcount"] = dict(row)
            
            total = result["headcount"].get("total", 0) or 0
            active = result["headcount"].get("active", 0) or 0
            # Prefer the operational attendance ledger when today's sample exists.
            attendance_rows = await self.db.execute(sql_text("""
                SELECT COUNT(*)::int AS total,
                       COUNT(*) FILTER (WHERE status IN ('present','late'))::int AS attended,
                       COUNT(*) FILTER (WHERE status = 'leave')::int AS on_leave,
                       COUNT(*) FILTER (WHERE status = 'rest')::int AS rest,
                       COUNT(*) FILTER (WHERE status = 'late')::int AS late
                FROM attendance
                WHERE factory_id = :fid AND date = CURRENT_DATE::text
            """), {"fid": factory_id})
            attendance = attendance_rows.mappings().first()
            if attendance and attendance["total"]:
                result["attendance_rate_pct"] = round(attendance["attended"] / attendance["total"] * 100, 1)
                result["attendance"] = dict(attendance)
            else:
                result["attendance_rate_pct"] = round(active / total * 100, 1) if total > 0 else 0

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
            result["by_station"] = [dict(r) for r in station_rows.mappings().all()]

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
            result["department_breakdown"] = {r.department: r.active for r in dept_rows.mappings().all()}

            # 技能等级分布
            skill_rows = await self.db.execute(sql_text("""
                SELECT skill_level, COUNT(*)::int AS cnt
                FROM hr_employees
                WHERE factory_id = :fid AND status = 'active' AND department NOT IN ('HR部','行政部','财务部','品质部')
                GROUP BY skill_level
            """), {"fid": factory_id})
            result["skill_distribution"] = {r.skill_level or "unlabeled": r.cnt for r in skill_rows.mappings().all()}

            result["total_active_workers"] = sum(st["active_in_station"] for st in result["by_station"]) if result["by_station"] else active

            # 参数基线偏差判断
            load_threshold_str = await self._get_param_value('personnel_load_rate_threshold')
            result["load_threshold_pct"] = self._parse_float(load_threshold_str, 85.0)
            
            absence_warn_str = await self._get_param_value('absence_warning_threshold')
            absence_warn = self._parse_float(absence_warn_str, 3.0)
            result["absence_warning_threshold_pct"] = absence_warn

            # 生成预警
            for st in result["by_station"]:
                if st["total_in_station"] > 0 and st["active_in_station"] == 0:
                    result["alerts"].append({
                        "type": "zero_active", "station": st["station"],
                        "message": f"{st['station']} 无在岗人员！"
                    })
                elif st["total_in_station"] > 0 and abs(1 - st["active_in_station"]/st["total_in_station"]) < absence_warn / 100:
                    result["alerts"].append({
                        "type": "understaffed", "station": st["station"],
                        "message": f"{st['station']} 在岗率 {round(st['active_in_station']/st['total_in_station']*100)}% 偏低"
                    })

        except Exception as e:
            await self._rollback_after_error()
            result["error"] = str(e)

        return result

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
        result = {
            "factory_id": factory_id,
            "calculated_at": datetime.now(timezone.utc).isoformat(),
            "total_equipment": 0,
            "status_distribution": {},
            "by_station": [],
            "oee_target_pct": 80,
            "pm_overdue_count": 0,
            "pm_overdue": [],
            "actual_today_production": {},
            "capacity_warnings": [],
        }

        try:
            # 设备状态总览
            equip_rows = await self.db.execute(sql_text("""
                SELECT id, equipment_code, equipment_name, status, station_id
                FROM equipment
                WHERE factory_id = :fid
            """), {"fid": factory_id})
            equip_list = [dict(r) for r in equip_rows.mappings().all()]
            result["total_equipment"] = len(equip_list)

            status_dist = {}
            for eq in equip_list:
                key = eq["status"] or "unknown"
                status_dist[key] = status_dist.get(key, 0) + 1
            result["status_distribution"] = status_dist

            # OEE目标参数
            oee_val = await self._get_param_value('oee_target_pct')
            if oee_val:
                try:
                    result["oee_target_pct"] = self._parse_float(oee_val)
                except ValueError:
                    pass

            # 实际产量（production_reports有good_qty）
            prod_rows = await self.db.execute(sql_text("""
                SELECT pr.station_id, SUM(pr.good_qty)::int AS today_good_qty,
                       COUNT(*)::int AS report_count
                FROM production_reports pr
                WHERE pr.factory_id = :fid AND pr.created_at >= CURRENT_DATE
                GROUP BY pr.station_id
                ORDER BY pr.station_id
            """), {"fid": factory_id})
            actual_output = {r.station_id: r.today_good_qty for r in prod_rows.mappings().all()}
            result["actual_today_production"] = actual_output

            # 7-day OEE baseline for RCC. Keep downtime and production in
            # separate aggregates so two one-to-many joins cannot multiply data.
            equipment_count = (await self.db.execute(sql_text(
                "SELECT COUNT(*)::int FROM equipment WHERE factory_id = :fid"
            ), {"fid": factory_id})).scalar() or 0
            downtime_row = await self.db.execute(sql_text("""
                SELECT COALESCE(SUM(duration_minutes), 0)::float AS downtime_minutes
                FROM equipment_downtime
                WHERE factory_id = :fid AND start_time >= NOW() - INTERVAL '7 days'
            """), {"fid": factory_id})
            production_row = await self.db.execute(sql_text("""
                SELECT COALESCE(SUM(good_qty + defect_qty + scrap_qty), 0)::float AS produced,
                       COALESCE(SUM(defect_qty + scrap_qty), 0)::float AS defects
                FROM production_reports
                WHERE factory_id = :fid AND created_at >= NOW() - INTERVAL '7 days'
            """), {"fid": factory_id})
            downtime = float((downtime_row.mappings().first() or {}).get("downtime_minutes", 0) or 0)
            production = production_row.mappings().first() or {}
            produced = float(production.get("produced", 0) or 0)
            defects = float(production.get("defects", 0) or 0)
            # RCC's factory KPI uses the same 12-hour daily production window
            # as the TPM service; equipment count is shown separately.
            planned = 7 * 12 * 60
            running = max(planned - downtime, 1)
            availability = max(0.0, (planned - downtime) / planned) if planned else 0.0
            performance = min(1.0, produced * 0.2 / running)
            quality = (produced - defects) / produced if produced else 1.0
            result["oee_actual_pct"] = round(availability * performance * quality * 100, 1)
            result["oee_detail"] = {
                "availability": round(availability * 100, 1),
                "performance": round(performance * 100, 1),
                "quality": round(quality * 100, 1),
                "downtime_minutes": round(downtime, 1),
                "produced": int(produced),
                "defects": int(defects),
            }

            pm_rows = await self.db.execute(sql_text("""
                SELECT p.plan_code, p.equipment_id, p.plan_name, p.next_due_at,
                       e.equipment_code, e.equipment_name
                FROM maintenance_plans p
                LEFT JOIN equipment e ON e.id = p.equipment_id
                WHERE p.factory_id = :fid AND p.is_active = TRUE
                ORDER BY p.next_due_at ASC NULLS LAST
            """), {"fid": factory_id})
            pm_items = [dict(row) for row in pm_rows.mappings().all()]
            result["pm_overdue"] = [item for item in pm_items if item.get("next_due_at") and item["next_due_at"] < datetime.utcnow()]
            result["pm_overdue_count"] = len(result["pm_overdue"])

            owner_rows = await self.db.execute(sql_text("""
                SELECT e.equipment_code, e.equipment_name, e.status,
                       e.responsible_engineer_id, h.employee_code, h.name AS engineer_name
                FROM equipment e
                LEFT JOIN hr_employees h ON h.id = e.responsible_engineer_id
                WHERE e.factory_id = :fid
                ORDER BY CASE WHEN e.status IN ('broken','fault','failure') THEN 0
                              WHEN e.status='maintenance' THEN 1
                              WHEN e.status IN ('idle','offline') THEN 2 ELSE 3 END,
                         e.equipment_code
            """), {"fid": factory_id})
            result["equipment_details"] = [dict(row) for row in owner_rows.mappings().all()]

        except Exception as e:
            await self._rollback_after_error()
            result["error"] = str(e)

        return result

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
        result = {
            "factory_id": factory_id,
            "calculated_at": datetime.now(timezone.utc).isoformat(),
            "total_work_orders": 0,
            "status_distribution": {},
            "priority_distribution": {},
            "urgent_orders": [],
            "delivery_risk_count": 0,
            "delivery_risk_orders": [],
            "aps_status": {
                "total_tasks": 0,
                "latest_end": None,
                "confirmed_count": 0,
                "draft_count": 0,
                "unscheduled_count": 0,
            },
            "material_readiness": {
                "ready_count": 0,
                "not_ready_count": 0,
            },
            "adjustable_params": {},
        }

        try:
            # 工单状态分布
            wo_status_rows = await self.db.execute(sql_text("""
                SELECT status, COUNT(*)::int AS cnt
                FROM work_orders
                WHERE factory_id = :fid
                GROUP BY status
                ORDER BY cnt DESC
            """), {"fid": factory_id})
            result["status_distribution"] = {r.status or "unlabeled": r.cnt for r in wo_status_rows.mappings().all()}

            # 优先级别分布
            priority_rows = await self.db.execute(sql_text("""
                SELECT priority, COUNT(*)::int AS cnt
                FROM work_orders
                WHERE factory_id = :fid AND status NOT IN ('cancelled', 'closed')
                GROUP BY priority
                ORDER BY cnt DESC
            """), {"fid": factory_id})
            result["priority_distribution"] = {r.priority or "medium": r.cnt for r in priority_rows.mappings().all()}

            # 急单
            urgent_result = await self.db.execute(sql_text("""
                SELECT work_order_code, product_id, planned_qty, completed_qty,
                       priority, planned_due, status,
                       ROUND((completed_qty::float / NULLIF(planned_qty, 0) * 100), 1) AS progress_pct
                FROM work_orders
                WHERE factory_id = :fid AND priority IN ('urgent', 'emergency') 
                      AND status NOT IN ('cancelled','closed')
                ORDER BY planned_due ASC NULLS LAST
            """), {"fid": factory_id})
            result["urgent_orders"] = [dict(r) for r in urgent_result.mappings().all()][:20]

            # 交期风险
            risk_result = await self.db.execute(sql_text("""
                SELECT work_order_code, product_id, planned_qty, completed_qty,
                       planned_due, status,
                       ROUND(EXTRACT(EPOCH FROM NOW() - planned_due) / 86400.0)::int AS days_overdue
                FROM work_orders
                WHERE factory_id = :fid AND planned_due IS NOT NULL AND planned_due < NOW()
                  AND status NOT IN ('cancelled', 'closed', 'completed')
                ORDER BY planned_due ASC
            """), {"fid": factory_id})
            result["delivery_risk_orders"] = [dict(r) for r in risk_result.mappings().all()]
            result["delivery_risk_count"] = len(result["delivery_risk_orders"])

            # 可调参数
            for code in ["priority_weight_urgent", "priority_weight_high", "priority_weight_medium",
                          "delivery_grace_period_hours", "max_parallel_orders_per_station"]:
                val = await self._get_param_value(code)
                if val is not None:
                    try:
                        result["adjustable_params"][code] = float(val)
                    except (ValueError, TypeError):
                        pass

            result["total_work_orders"] = (
                result["status_distribution"].get("released", 0) + 
                result["status_distribution"].get("in_progress", 0) + 
                result["status_distribution"].get("pending", 0)
            )

        except Exception as e:
            await self._rollback_after_error()
            result["error"] = str(e)

        return result

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
        result = {
            "factory_id": factory_id,
            "calculated_at": datetime.now(timezone.utc).isoformat(),
            "standards": {
                "temperature": {"min": 18, "max": 28, "unit": "°C"},
                "humidity": {"min": 30, "max": 70, "unit": "%"},
                "dust": {"limit_ug_m3": 100},
                "noise": {"limit_db": 85},
            },
            "last_reading": None,
            "has_data": False,
            "warnings": [],
            "alert": False,
        }

        try:
            # 环境标准参数
            standards = {}
            for code, fallback in [
                ("env_temperature_min_c", 18), ("env_temperature_max_c", 28),
                ("env_humidity_min_pct", 30), ("env_humidity_max_pct", 70),
                ("env_dust_limit_ug_m3", 100), ("env_noise_limit_db", 85)
            ]:
                val = await self._get_param_value(code)
                standards[code] = self._parse_float(val) if val is not None else fallback

            result["standards"] = {
                "temperature": {"min": standards["env_temperature_min_c"], "max": standards["env_temperature_max_c"], "unit": "°C"},
                "humidity": {"min": standards["env_humidity_min_pct"], "max": standards["env_humidity_max_pct"], "unit": "%"},
                "dust": {"limit_ug_m3": standards["env_dust_limit_ug_m3"]},
                "noise": {"limit_db": standards["env_noise_limit_db"]},
            }

            # 最近一次读数
            reading_result = await self.db.execute(sql_text("""
                SELECT * FROM environment_readings
                WHERE factory_id = :fid AND reading_type = 'iot_sensor'
                ORDER BY measured_at DESC LIMIT 1
            """), {"fid": factory_id})
            last_reading = reading_result.mappings().first()
            if not last_reading:
                weather_result = await self.db.execute(sql_text("""
                    SELECT * FROM environment_readings
                    WHERE factory_id = :fid AND reading_type = 'weather'
                    ORDER BY measured_at DESC LIMIT 1
                """), {"fid": factory_id})
                last_reading = weather_result.mappings().first()

            result["last_reading"] = dict(last_reading) if last_reading else None
            result["has_data"] = bool(last_reading)

            warnings = []
            if last_reading:
                temp = last_reading.get("temperature_c")
                hum = last_reading.get("humidity_pct")
                dust = last_reading.get("dust_ug_m3")

                if temp is not None:
                    std = result["standards"]["temperature"]
                    if temp < std["min"]:
                        warnings.append({"type": "temp_low", "value": temp, "standard": std, "message": f"温度{temp}°C低于下限{std['min']}°C"})
                    elif temp > std["max"]:
                        warnings.append({"type": "temp_high", "value": temp, "standard": std, "message": f"温度{temp}°C高于上限{std['max']}°C"})
                if hum is not None:
                    std = result["standards"]["humidity"]
                    if hum < std["min"]:
                        warnings.append({"type": "humidity_low", "value": hum, "standard": std, "message": f"湿度{hum}%低于下限{std['min']}%"})
                    elif hum > std["max"]:
                        warnings.append({"type": "humidity_high", "value": hum, "standard": std, "message": f"湿度{hum}%高于上限{std['max']}%"})
                if dust is not None:
                    std = result["standards"]["dust"]
                    if dust > std["limit_ug_m3"]:
                        warnings.append({"type": "dust_high", "value": dust, "standard": std, "message": f"粉尘{dust}µg/m³超过限值{std['limit_ug_m3']}"})

            result["warnings"] = warnings
            result["alert"] = len(warnings) > 0

        except Exception as e:
            await self._rollback_after_error()
            result["error"] = str(e)

        return result

    # ──────────────────────────────────────────────────────────
    # Process Baseline — 工艺基线
    # ──────────────────────────────────────────────────────────

    async def process_baseline(self, factory_id: str) -> Dict[str, Any]:
        """
        工艺基线：
        1. 工艺路线版本数
        2. 标准节拍时间（从 shift_summaries 中推导，若表为空则默认）
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
        result = {
            "factory_id": factory_id,
            "calculated_at": datetime.now(timezone.utc).isoformat(),
            "routing_count": 0,
            "process_cycles": [],
            "yield_baseline_30d": None,
            "total_output_30d": 0,
            "top_defects_30d": [],
            "aql_levels": {"General-II": 1},
            "quality_goals": {},
        }

        try:
            # 工艺路线统计（routings表有 factory_id, is_active）
            routing_rows = await self.db.execute(sql_text("""
                SELECT COUNT(*)::int AS count
                FROM routings
                WHERE factory_id = :fid AND is_active = TRUE
            """), {"fid": factory_id})
            result["routing_count"] = routing_rows.scalar() or 0

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
            if yield_row:
                result["yield_baseline_30d"] = yield_row["avg_yield_pct"]
                result["total_output_30d"] = yield_row["total_output"]

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
            result["top_defects_30d"] = [dict(r) for r in defect_rows.mappings().all()]

        except Exception as e:
            await self._rollback_after_error()
            result["error"] = str(e)

        return result

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
        try:
            people = await self.people_baseline(factory_id)
            equipment = await self.equipment_baseline(factory_id)
            work_orders = await self.work_order_baseline(factory_id)
            environment = await self.environment_baseline(factory_id)
            process = await self.process_baseline(factory_id)
        except Exception as e:
            await self._rollback_after_error()
            return {
                "factory_id": factory_id,
                "synced_at": datetime.now(timezone.utc).isoformat(),
                "baseline": {},
                "error": str(e),
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
                    "oee_actual_pct": equipment.get("oee_actual_pct", 0),
                    "oee_detail": equipment.get("oee_detail", {}),
                    "pm_overdue_count": equipment.get("pm_overdue_count"),
                    "pm_overdue": equipment.get("pm_overdue", []),
                    "equipment_details": equipment.get("equipment_details", []),
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
