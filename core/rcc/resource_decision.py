"""
v2.6 - RCC Resource Decision Engine
RCC资源决策引擎 — 基于基线数据生成资源调度决策

核心能力：
- worker_assignment: 人->工位->班次智能分配
- equipment_scheduling: 设备->状态->任务匹配
- work_order_priority: 工单优先级决策（交期紧迫度+产能约束）
- bottleneck_resolution: 产能瓶颈预警+分流方案
- environment_response: 环境异常时自动停线/检验加严
- process_response: 工艺参数偏离时的决策
"""

import uuid
from datetime import datetime, timezone, date, timedelta
from typing import Optional, List, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text as sql_text


class RCCResourceDecisionEngine:
    """RCC 资源决策引擎 — 基于基线数据生成资源决策"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ──────────────────────────────────────────────────────────
    # Worker Assignment — 人力分配决策
    # ──────────────────────────────────────────────────────────

    async def recommend_worker_assignment(self, factory_id: str) -> Dict[str, Any]:
        """
        人力分配决策：
        1. 按工位缺勤率排序，识别最紧缺的工位
        2. 找跨工位技能匹配的人（L2+可支援）
        3. 如果当前工位无人，建议从其他工位借调

        返回结构：
        {
            "station_assignments": [...],  # 各工位建议分配
            "cross_training_needed": [...], # 需要跨岗培训的人
            "suggested_transfers": [...]   # 建议调配方案
        }
        """
        result = {
            "factory_id": factory_id,
            "calculated_at": datetime.now(timezone.utc).isoformat(),
            "station_assignments": [],
            "cross_training_needed": [],
            "suggested_transfers": [],
        }

        try:
            # 获取各工位在岗率
            station_rows = await self.db.execute(sql_text("""
                SELECT
                    station,
                    COUNT(*)::int AS total_in_station,
                    COUNT(*) FILTER (WHERE status='active')::int AS active_in_station,
                    COUNT(*) FILTER (WHERE status='leave')::int AS on_leave,
                    COUNT(*) FILTER (WHERE skill_level IN ('L4','L5'))::int AS senior_in_station,
                    COUNT(*) FILTER (WHERE shift='白班')::int AS day_shift_count,
                    COUNT(*) FILTER (WHERE shift='夜班')::int AS night_shift_count,
                    COUNT(*) FILTER (WHERE shift='两班倒')::int AS two_shifts_count
                FROM hr_employees
                WHERE factory_id = :fid AND position IN ('操作员','组长','技术员')
                  AND department NOT IN ('HR部','行政部','财务部','品质部')
                GROUP BY station
                ORDER BY active_in_station::float / NULLIF(total_in_station, 0) ASC
            """), {"fid": factory_id})
            
            stations = []
            for r in station_rows.mappings().all():
                total = r["total_in_station"]
                active = r["active_in_station"]
                leave = r["on_leave"]
                if total > 0:
                    utilization = round(active / total * 100, 1)
                    alert_level = "critical" if utilization < 50 else "warning" if utilization < 75 else "normal"
                else:
                    utilization = 0
                    alert_level = "critical"
                
                stations.append({
                    "station": r["station"],
                    "total_in_station": total,
                    "active_in_station": active,
                    "on_leave": leave,
                    "senior_in_station": r["senior_in_station"],
                    "day_shift_count": r["day_shift_count"],
                    "night_shift_count": r["night_shift_count"],
                    "two_shifts_count": r["two_shifts_count"],
                    "utilization_pct": utilization,
                    "alert_level": alert_level,
                    "needs_more_workers": active == 0 or utilization < 50,
                })
            
            result["station_assignments"] = stations

            # 找出低出勤率的工位，建议从其他工位调剂
            for station in stations:
                if station["needs_more_workers"]:
                    # 找同工种、技能等级合适、出勤率>90%的工位支援
                    potential_sources = [
                        s for s in stations
                        if s["station"] != station["station"]
                        and s["utilization_pct"] > 90
                        and s["active_in_station"] > 2
                    ]
                    
                    if potential_sources:
                        source = potential_sources[0]  # 取最饱和的
                        result["suggested_transfers"].append({
                            "from_station": source["station"],
                            "to_station": station["station"],
                            "reason": f"{station['station']} 在岗率{station['utilization_pct']}%低于50%",
                            "source_station_utilization": source["utilization_pct"],
                            "suggested_count": max(1, (source["active_in_station"] - 2) // 2),
                            "action": "borrow_worker"
                        })

        except Exception as e:
            result["error"] = str(e)

        return result

    # ──────────────────────────────────────────────────────────
    # Equipment Scheduling — 设备调度决策
    # ──────────────────────────────────────────────────────────

    async def recommend_equipment_schedule(self, factory_id: str) -> Dict[str, Any]:
        """
        设备调度决策：
        1. 设备状态分布（running/idle/maintenance/offline）
        2. 空闲设备分配给待排工单
        3. 维护计划逾期预警

        返回结构：
        {
            "equipment_status": {...},
            "idle_equipment": [...],      # 空闲设备
            "maintenance_alerts": [...],  # PM逾期
            "recommended_actions": [...]  # 建议动作
        }
        """
        result = {
            "factory_id": factory_id,
            "calculated_at": datetime.now(timezone.utc).isoformat(),
            "equipment_status": {},
            "idle_equipment": [],
            "maintenance_alerts": [],
            "recommended_actions": [],
        }

        try:
            # 设备状态总览
            equip_rows = await self.db.execute(sql_text("""
                SELECT status, COUNT(*)::int AS cnt
                FROM equipment
                WHERE factory_id = :fid
                GROUP BY status
            """), {"fid": factory_id})
            result["equipment_status"] = {r.status or "unknown": r.cnt for r in equip_rows.mappings().all()}

            # 空闲设备详情
            idle_rows = await self.db.execute(sql_text("""
                SELECT id, equipment_code, equipment_name, station_id
                FROM equipment
                WHERE factory_id = :fid AND status = 'idle'
            """), {"fid": factory_id})
            result["idle_equipment"] = [dict(r) for r in idle_rows.mappings().all()]

            # 维修计划逾期
            pm_result = await self.db.execute(sql_text("""
                SELECT m.id, m.order_code, e.equipment_code, m.maintenance_type,
                       m.next_due_at, ABS(EXTRACT(DAY FROM CURRENT_DATE - m.next_due_at))::int AS days_past_due
                FROM maintenance_plans m
                JOIN equipment e ON e.id = m.equipment_id AND e.factory_id = m.factory_id
                WHERE m.factory_id = :fid AND m.is_active = TRUE
                  AND COALESCE(m.next_due_at, CURRENT_DATE::timestamp) < NOW()
                ORDER BY days_past_due DESC
            """), {"fid": factory_id})
            result["maintenance_alerts"] = [dict(r) for r in pm_result.mappings().all()][:10]

            # 如果设备故障影响排程 → 建议调整
            if len(result["maintenance_alerts"]) > 0:
                result["recommended_actions"].append({
                    "action": "check_affected_work_orders",
                    "reason": "有维护逾期设备可能影响排程",
                    "priority": "high",
                })

        except Exception as e:
            result["error"] = str(e)

        return result

    # ──────────────────────────────────────────────────────────
    # Work Order Priority — 工单优先级决策
    # ──────────────────────────────────────────────────────────

    async def recommend_work_order_priority(self, factory_id: str) -> Dict[str, Any]:
        """
        工单优先级决策：
        1. 按交期紧迫度排序（距到期时间/生产周期）
        2. 紧急工单（urgent/emergency）自动置顶
        3. 产能充足时可以插单，否则建议延期

        返回结构：
        {
            "priority_ranking": [...],    # 工单优先级排序
            "delivery_risk": [...],       # 交期风险
            "capacity_assessment": {...}, # 产能评估
            "suggested_priority_changes": [...]  # 建议调整
        }
        """
        result = {
            "factory_id": factory_id,
            "calculated_at": datetime.now(timezone.utc).isoformat(),
            "priority_ranking": [],
            "delivery_risk": [],
            "capacity_assessment": {},
            "suggested_priority_changes": [],
        }

        try:
            # 获取所有未完成的工单
            wo_rows = await self.db.execute(sql_text("""
                SELECT work_order_code, product_id, planned_qty, completed_qty,
                       priority, planned_due, status,
                       ROUND(EXTRACT(EPOCH FROM (planned_due - NOW())) / 86400.0)::int AS days_remaining,
                       ROUND((completed_qty::float / NULLIF(planned_qty, 0) * 100), 1) AS progress_pct
                FROM work_orders
                WHERE factory_id = :fid AND status NOT IN ('cancelled', 'closed', 'completed')
                ORDER BY 
                    CASE WHEN priority IN ('urgent', 'emergency') THEN 1
                         WHEN priority = 'high' THEN 2
                         ELSE 3 END,
                    planned_due ASC NULLS LAST
            """), {"fid": factory_id})
            
            work_orders = [dict(r) for r in wo_rows.mappings().all()]
            result["priority_ranking"] = work_orders[:20]

            # 交付风险（planned_due < now 且未完工）
            risk_rows = await self.db.execute(sql_text("""
                SELECT work_order_code, planned_due, status,
                       ROUND(EXTRACT(EPOCH FROM NOW() - planned_due) / 86400.0)::int AS days_overdue
                FROM work_orders
                WHERE factory_id = :fid AND planned_due IS NOT NULL AND planned_due < NOW()
                  AND status NOT IN ('cancelled', 'closed', 'completed')
                ORDER BY days_overdue DESC
            """), {"fid": factory_id})
            result["delivery_risk"] = [dict(r) for r in risk_rows.mappings().all()]

            # 产能评估（根据设备状态和产能参数）
            total_work_orders = len(work_orders)
            urgent_count = len([wo for wo in work_orders if wo["priority"] in ("urgent", "emergency")])
            result["capacity_assessment"] = {
                "total_pending_orders": total_work_orders,
                "urgent_order_count": urgent_count,
                "urgent_ratio_pct": round(urgent_count / total_work_orders * 100) if total_work_orders > 0 else 0,
                "capacity_status": "overloaded" if urgent_count / max(total_work_orders, 1) > 0.5 else "normal"
            }

            # 建议
            if result["capacity_assessment"]["capacity_status"] == "overloaded":
                result["suggested_priority_changes"].append({
                    "action": "prioritize_urgent",
                    "reason": f"紧急订单占比{result['capacity_assessment']['urgent_ratio_pct']}%超过50%，需要优先处理",
                    "priority": "critical",
                })

            if len(result["delivery_risk"]) > 0:
                result["suggested_priority_changes"].append({
                    "action": "escalate_late_orders",
                    "reason": f"{len(result['delivery_risk'])}个工单已超期，需要升级处理",
                    "priority": "high",
                })

        except Exception as e:
            result["error"] = str(e)

        return result

    # ──────────────────────────────────────────────────────────
    # Bottleneck Resolution — 产能瓶颈决策
    # ──────────────────────────────────────────────────────────

    async def recommend_bottleneck_resolution(self, factory_id: str) -> Dict[str, Any]:
        """
        产能瓶颈决策：
        1. 找出利用率最高/最低的工位
        2. 推荐平衡方案（转移工单/增加人员/加班）
        3. 如果OEE低于目标 → 建议检修或换人

        返回结构：
        {
            "bottleneck_stations": [...],
            "balanced_recommendations": [...],
            "oee_alerts": [...]
        }
        """
        result = {
            "factory_id": factory_id,
            "calculated_at": datetime.now(timezone.utc).isoformat(),
            "bottleneck_stations": [],
            "balanced_recommendations": [],
            "oee_alerts": [],
        }

        try:
            # 获取各工位实际产量和产能利用率
            station_rows = await self.db.execute(sql_text("""
                SELECT
                    s.station_code,
                    s.station_name,
                    COUNT(CASE WHEN pr.created_at >= CURRENT_DATE THEN 1 END)::int AS today_reports,
                    SUM(CASE WHEN pr.created_at >= CURRENT_DATE THEN pr.good_qty ELSE 0 END)::int AS today_good_qty,
                    MAX(pr.created_at) AS last_report_time,
                    sc.available_hours_per_day,
                    sc.efficiency_rate
                FROM stations s
                LEFT JOIN production_reports pr ON pr.station_id = s.id AND pr.factory_id = s.factory_id
                LEFT JOIN station_capacity sc ON sc.station_id = s.id AND sc.factory_id = s.factory_id
                WHERE s.factory_id = :fid
                GROUP BY s.station_code, s.station_name, sc.available_hours_per_day, sc.efficiency_rate
                ORDER BY sc.efficiency_rate DESC NULLS LAST
            """), {"fid": factory_id})
            
            stations = []
            for r in station_rows.mappings().all():
                efficiency = r["efficiency_rate"] or 0.85
                available_hours = r["available_hours_per_day"] or 16
                
                # 简化估算：报告数越多说明该工位越忙
                workload_score = (r["today_reports"] or 0) * (r["today_good_qty"] or 0) / 10000
                utilization = min(100, round(workload_score / (available_hours * efficiency) * 100, 1))
                
                stations.append({
                    "station_code": r["station_code"],
                    "station_name": r["station_name"],
                    "today_reports": r["today_reports"] or 0,
                    "today_good_qty": r["today_good_qty"] or 0,
                    "last_report_time": r["last_report_time"],
                    "efficiency_rate": efficiency,
                    "available_hours_per_day": available_hours,
                    "utilization_pct": utilization,
                    "is_bottleneck": utilization > 90,
                })
            
            result["bottleneck_stations"] = stations
            
            # 识别瓶颈和高负载
            high_load = [s for s in stations if s["utilization_pct"] > 90]
            low_load = [s for s in stations if s["utilization_pct"] < 30]
            
            if high_load and low_load:
                for hl in high_load:
                    for ll in low_load:
                        result["balanced_recommendations"].append({
                            "from_station": hl["station_code"],
                            "to_station": ll["station_code"],
                            "reason": f"{hl['station_code']} 负载{hl['utilization_pct']}%过高，{ll['station_code']} 负载{ll['utilization_pct']}%过低",
                            "action": "transfer_work_order",
                            "priority": "medium",
                        })

            # OEE异常
            oee_target = await self._get_param_value('oee_target_pct')
            if oee_target:
                try:
                    target = float(oee_target)
                    for station in stations:
                        if station["utilization_pct"] < target:
                            result["oee_alerts"].append({
                                "station_code": station["station_code"],
                                "current_efficiency": station["utilization_pct"],
                                "target": target,
                                "gap": target - station["utilization_pct"],
                                "recommendation": "检查设备状态/人员配置",
                            })
                except ValueError:
                    pass

        except Exception as e:
            result["error"] = str(e)

        return result

    # ──────────────────────────────────────────────────────────
    # Environment Response — 环境异常决策
    # ──────────────────────────────────────────────────────────

    async def recommend_environment_response(self, factory_id: str) -> Dict[str, Any]:
        """
        环境异常决策：
        1. 温湿度超标时是否停线/加严检验
        2. 粉尘浓度超标时是否要求佩戴防护
        3. 噪声超标时是否需要听力保护

        返回结构：
        {
            "environment_alerts": [...],  # 环境异常
            "suggested_actions": [...]    # 建议动作
        }
        """
        result = {
            "factory_id": factory_id,
            "calculated_at": datetime.now(timezone.utc).isoformat(),
            "environment_alerts": [],
            "suggested_actions": [],
        }

        try:
            # 获取最新环境读数
            reading_result = await self.db.execute(sql_text("""
                SELECT * FROM environment_readings
                WHERE factory_id = :fid
                ORDER BY measured_at DESC LIMIT 1
            """), {"fid": factory_id})
            last_reading = reading_result.mappings().first()

            if not last_reading:
                return result

            last_reading = dict(last_reading)

            warnings = []

            # 温度异常
            temp = last_reading.get("temperature_c")
            if temp is not None:
                if temp < 18:  # 温度下限
                    warnings.append({
                        "type": "temp_low",
                        "value": temp,
                        "message": f"温度{temp}°C低于18°C，建议启动加热或减少户外作业",
                        "action": "warn_and_monitor",
                    })
                elif temp > 28:  # 温度上限
                    warnings.append({
                        "type": "temp_high",
                        "value": temp,
                        "message": f"温度{temp}°C高于28°C，建议开启空调/增加通风",
                        "action": "activate_climate_control",
                    })

            # 湿度异常
            hum = last_reading.get("humidity_pct")
            if hum is not None:
                if hum < 30:  # 湿度下限
                    warnings.append({
                        "type": "humidity_low",
                        "value": hum,
                        "message": f"湿度{hum}%低于30%，静电风险增加",
                        "action": "monitor_anti_static",
                    })
                elif hum > 70:  # 湿度上限
                    warnings.append({
                        "type": "humidity_high",
                        "value": hum,
                        "message": f"湿度{hum}%高于70%，需检查除湿设备",
                        "action": "activate_dehumidifier",
                    })

            # 粉尘浓度异常
            dust = last_reading.get("dust_ug_m3")
            if dust is not None and dust > 100:
                warnings.append({
                    "type": "dust_high",
                    "value": dust,
                    "message": f"粉尘{dust}µg/m³超过100限值，需加强通风和佩戴N95口罩",
                    "action": "activate_filtration_and_ppe",
                })

            # 噪声超标
            noise = last_reading.get("noise_db")
            if noise is not None and noise > 85:
                warnings.append({
                    "type": "noise_high",
                    "value": noise,
                    "message": f"噪声{noise}dB超过85dB限值，需佩戴耳塞",
                    "action": "require_hearing_protection",
                })

            result["environment_alerts"] = warnings
            result["suggested_actions"] = [w["action"] for w in warnings]

        except Exception as e:
            result["error"] = str(e)

        return result

    # ──────────────────────────────────────────────────────────
    # Process Response — 工艺异常决策
    # ──────────────────────────────────────────────────────────

    async def recommend_process_response(self, factory_id: str) -> Dict[str, Any]:
        """
        工艺异常决策：
        1. 良品率下降时是否加严检验
        2. 节拍时间超标时是否调整生产节奏
        3. 不良类型集中时是否需要工艺变更

        返回结构：
        {
            "process_alerts": [...],  # 工艺异常
            "quality_implications": [...]  # 质量影响
        }
        """
        result = {
            "factory_id": factory_id,
            "calculated_at": datetime.now(timezone.utc).isoformat(),
            "process_alerts": [],
            "quality_implications": [],
        }

        try:
            # 良品率趋势
            yield_rows = await self.db.execute(sql_text("""
                SELECT AVG(good_qty::float / NULLIF(total_output, 0) * 100)::numeric(5,2) AS avg_yield_pct,
                       SUM(good_qty)::int AS total_good,
                       SUM(total_output)::int AS total_output
                FROM shift_summaries
                WHERE factory_id = :fid AND created_at >= CURRENT_DATE - INTERVAL '7 days'
                  AND total_output > 0
            """), {"fid": factory_id})
            yield_row = yield_rows.mappings().first()
            
            if yield_row and yield_row["avg_yield_pct"]:
                yield_pct = float(yield_row["avg_yield_pct"])
                if yield_pct < 95:
                    result["process_alerts"].append({
                        "type": "yield_drop",
                        "current_yield_pct": yield_pct,
                        "threshold_pct": 95,
                        "message": f"近7天良品率{yield_pct}%低于95%警戒线",
                        "action": "increase_inspection_frequency",
                    })
                elif yield_pct < 98:
                    result["process_alerts"].append({
                        "type": "yield_warning",
                        "current_yield_pct": yield_pct,
                        "threshold_pct": 98,
                        "message": f"近7天良品率{yield_pct}%低于98%目标值",
                        "action": "review_process_parameters",
                    })

            # Top不良类型
            defect_rows = await self.db.execute(sql_text("""
                SELECT defect_type, COUNT(*)::int AS cnt
                FROM defect_records
                WHERE factory_id = :fid AND created_at >= CURRENT_DATE - INTERVAL '7 days'
                GROUP BY defect_type
                ORDER BY cnt DESC
                LIMIT 3
            """), {"fid": factory_id})
            
            top_defects = [dict(r) for r in defect_rows.mappings().all()]
            for defect in top_defects:
                if defect["cnt"] >= 3:  # 同一类型>=3次触发预警
                    result["quality_implications"].append({
                        "defect_type": defect["defect_type"],
                        "count": defect["cnt"],
                        "message": f"缺陷类型'{defect['defect_type']}'出现{defect['cnt']}次，可能需要工艺变更",
                        "action": "investigate_root_cause",
                    })

            # 工艺参数偏离（如果有global_adjustable_params记录）
            presult = await self.db.execute(sql_text("""
                SELECT current_value FROM global_adjustable_params WHERE param_code = 'yield_rate_target_pct'
            """))
            target_yield_str = presult.scalar()
            if target_yield_str:
                try:
                    target_yield = float(target_yield_str)
                    if yield_row and yield_row["avg_yield_pct"]:
                        actual_yield = float(yield_row["avg_yield_pct"])
                        gap = actual_yield - target_yield
                        if gap < -2:  # 差距超过2个百分点
                            result["quality_implications"].append({
                                "type": "yield_gap",
                                "gap": round(gap, 2),
                                "message": f"良品率比目标低{round(-gap)}个百分点，需要工艺调整",
                                "action": "adjust_process_parameters",
                            })
                except ValueError:
                    pass

        except Exception as e:
            result["error"] = str(e)

        return result

    # ──────────────────────────────────────────────────────────
    # Full Resource Decision — 全量资源决策
    # ──────────────────────────────────────────────────────────

    async def full_resource_decision(self, factory_id: str) -> Dict[str, Any]:
        """
        全量资源决策：
        1. 收集所有子决策
        2. 综合判断优先级和联动影响
        3. 生成一份完整的资源决策报告

        这是 RCC 的核心能力 —— 把分散在各个模块的数据，统一汇总为可执行资源决策。
        """
        try:
            worker_assignment = await self.recommend_worker_assignment(factory_id)
            equipment_schedule = await self.recommend_equipment_schedule(factory_id)
            work_order_priority = await self.recommend_work_order_priority(factory_id)
            bottleneck_resolution = await self.recommend_bottleneck_resolution(factory_id)
            environment_response = await self.recommend_environment_response(factory_id)
            process_response = await self.recommend_process_response(factory_id)
        except Exception as e:
            return {
                "factory_id": factory_id,
                "decision_time": datetime.now(timezone.utc).isoformat(),
                "decisions": {},
                "error": str(e),
            }

        # 综合判断优先级
        overall_priority = "low"
        critical_count = sum([
            len(work_order_priority.get("suggested_priority_changes", [])),
            len(environment_response.get("environment_alerts", [])),
            len(process_response.get("process_alerts", [])),
        ])

        if critical_count >= 3:
            overall_priority = "critical"
        elif critical_count >= 1:
            overall_priority = "high"

        return {
            "factory_id": factory_id,
            "decision_time": datetime.now(timezone.utc).isoformat(),
            "overall_priority": overall_priority,
            "decisions": {
                "worker_assignment": {
                    "stations_with_alerts": [s for s in worker_assignment.get("station_assignments", []) if s.get("alert_level") == "critical"],
                    "suggested_transfers": worker_assignment.get("suggested_transfers", []),
                },
                "equipment_schedule": {
                    "idle_count": len(equipment_schedule.get("idle_equipment", [])),
                    "maintenance_alerts": equipment_schedule.get("maintenance_alerts", []),
                    "recommended_actions": equipment_schedule.get("recommended_actions", []),
                },
                "work_order_priority": {
                    "priority_ranking_count": len(work_order_priority.get("priority_ranking", [])),
                    "delivery_risk_count": len(work_order_priority.get("delivery_risk", [])),
                    "capacity_assessment": work_order_priority.get("capacity_assessment", {}),
                    "suggested_priority_changes": work_order_priority.get("suggested_priority_changes", []),
                },
                "bottleneck_resolution": {
                    "bottleneck_count": len(bottleneck_resolution.get("bottleneck_stations", [])),
                    "recommendations": bottleneck_resolution.get("balanced_recommendations", []),
                    "oee_alerts": bottleneck_resolution.get("oee_alerts", []),
                },
                "environment_response": {
                    "alert_count": len(environment_response.get("environment_alerts", [])),
                    "suggested_actions": environment_response.get("suggested_actions", []),
                },
                "process_response": {
                    "alert_count": len(process_response.get("process_alerts", [])),
                    "quality_implications": process_response.get("quality_implications", []),
                },
            },
        }

    async def _get_param_value(self, param_code: str) -> Optional[str]:
        """读取全局可调参数值"""
        try:
            q = await self.db.execute(sql_text(
                "SELECT current_value FROM global_adjustable_params WHERE param_code = :code",
                {"code": param_code}
            ))
            return q.scalar()
        except Exception:
            return None
