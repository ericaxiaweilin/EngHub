

"""
EngHub MES Application Entry Point
"""
import os
import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from api.routes import (
    auth_router,
    bom_router,
    chat_router,
    employee_skill_router,
    ie_router,
    ie_advanced_router,
    mes_router,
    pp_router,
    pmc_router,
    trainer_router,
    workflow_diagram_router,
    qms_router,
    sim_erp_router,
    sim_factory_router,
    wms_router,
    tms_router,
)
from api.routes.andon_routes import router as andon_router
from api.routes.test_switch import test_router
from api.routes.data_consistency_routes import router as data_consistency_router
from api.routes.expert_system_routes import router as expert_system_router
from api.routes.work_order_template_routes import router as work_order_template_router
from api.routes.rcc_routes import router as rcc_router
from api.routes.rcc_data_routes import router as rcc_data_router
from api.routes.rcc_decision_routes import router as rcc_decision_router
from api.routes.production_dashboard_routes import router as production_dashboard_router
from api.routes.search_routes import router as search_router
from api.routes.code_table_routes import router as code_table_router
from api.routes.file_routes import router as file_router
from api.routes.workbook_routes import router as workbook_router
from api.routes.routing_template_routes import router as routing_template_router
from api.routes.alert_intelligence_routes import router as alert_intelligence_router
from api.routes.intelligence_routes import router as intelligence_router
from api.routes.aps_routes import router as aps_router
from api.routes.equipment_routes import router as equipment_router
from api.routes.production_phase1_routes import router as production_phase1_router
from api.routes.production_phase2_routes import router as production_phase2_router
from api.routes.wms_phase3_routes import router as wms_phase3_router
from api.routes.qms_phase4_routes import router as qms_phase4_router
from api.routes.equipment_phase5_routes import router as equipment_phase5_router
from api.routes.hr_routes import router as hr_router
from api.routes.notification_routes import router as notification_router
from api.routes.role_elimination_routes import router as role_elimination_router
from api.routes.workflow_analytics_routes import router as workflow_analytics_router
from api.routes.automation_level_routes import router as automation_level_router
from api.routes.collaboration_routes import router as collaboration_router
from api.routes.agent_supervisor_routes import router as agent_supervisor_router
from api.routes.agent_routes import router as agent_router
from api.routes.quick_command_routes import router as quick_command_router
from api.routes.task_center_routes import router as task_center_router
from api.routes.crew_routes import router as crew_router
from api.routes.orchestrator_routes import router as orchestrator_router
from api.routes.commander_routes import router as commander_router
from api.routes.work_team_routes import router as work_team_router
from api.routes.virtual_factory_routes import router as virtual_factory_router
from api.routes.traceability_routes import router as traceability_router
from core.org_panel.api_adapter import router as org_panel_router

app = FastAPI(
    title="EngHub MES",
    description="Manufacturing Execution System API with TMS (Task Management System)",
    version="2.5.0"
)

# Include routers
app.include_router(auth_router, prefix="/api/v1")
app.include_router(bom_router)            # BOM - EngFlow 数据对接
app.include_router(ie_router)           # Industrial Engineering Module - 精益生产IE基础模块
app.include_router(ie_advanced_router)  # Advanced IE Module - 精益生产IE扩展模块
app.include_router(mes_router)
app.include_router(pp_router)
app.include_router(pmc_router)
app.include_router(trainer_router)  # 职位训练器：接口驱动的岗位训练包与测验
app.include_router(workflow_diagram_router)  # 统一业务工作流图目录与渲染接口
app.include_router(qms_router)
app.include_router(wms_router)
if employee_skill_router is not None:
    app.include_router(employee_skill_router)
app.include_router(sim_erp_router)
app.include_router(sim_factory_router)
app.include_router(chat_router)
app.include_router(tms_router)
app.include_router(andon_router)  # Andon 2.0 智能工单系统
app.include_router(data_consistency_router)
app.include_router(expert_system_router)
app.include_router(work_order_template_router)
app.include_router(production_dashboard_router)  # 生产看板聚合（真实数据，复用仿真结果UI组件）
app.include_router(aps_router)  # APS 高级排程引擎
app.include_router(equipment_router)  # 设备 TPM
app.include_router(search_router)  # 全站系统搜索
app.include_router(code_table_router)  # 统一码表/基础数据管理
app.include_router(file_router)  # 文件/附件上传下载（chatbot 多模态 + 表单/报告导出）
app.include_router(workbook_router)  # 在线工作簿：公式保留、保存、导入导出
app.include_router(routing_template_router)  # 工艺路线模板 CRUD（016 工序流转）
app.include_router(alert_intelligence_router)  # 预警情报审查（017 Chatbot 主动智能）
app.include_router(intelligence_router)  # 制造智能核心：Chatbot/PMC/预警/合规的统一只读视图
app.include_router(production_phase1_router)  # 岗位替代 Phase 1: 报工终端/实时看板/报表中心
app.include_router(production_phase2_router)  # 岗位替代 Phase 2: 订单管理/APS排程
app.include_router(wms_phase3_router)  # 岗位替代 Phase 3: 仓管操作/库存预警/盘点
app.include_router(qms_phase4_router)  # 岗位替代 Phase 4: 检验终端/SPC/不良分析
app.include_router(equipment_phase5_router)  # 岗位替代 Phase 5: 维保终端/OEE/故障预测
app.include_router(hr_router)  # HR 人力档案 + 工厂切换
app.include_router(work_team_router)  # 报工小组 CRUD（操作人便捷选择/批量报工）
app.include_router(notification_router)  # 站内通知（报告/异常/系统）
app.include_router(role_elimination_router)  # 岗位替代（调度员/采购员/工艺员）
app.include_router(workflow_analytics_router)  # 工作流交叉分析（深层数据）
app.include_router(automation_level_router)  # 自动化等级配置（L0-L3可选）
app.include_router(collaboration_router)  # 岗位协同网络（事件+边界）
app.include_router(agent_supervisor_router)  # 智能体监督（长任务+卡住+预测+闭环）
app.include_router(agent_router)  # 排产+仓储智能体
app.include_router(quick_command_router)  # Chatbot 快速命令 CRUD + 智能体调度列表
app.include_router(task_center_router)  # 任务中心（待办跟进 + 定期扫描）
app.include_router(crew_router)  # CrewAI推理层+个人知识层
app.include_router(orchestrator_router)  # 多智能体并行编排
app.include_router(commander_router)  # 工厂指挥官（自主决策引擎）
app.include_router(virtual_factory_router)  # 虚拟工厂脉搏（订单/拆单/报工/预警）
app.include_router(traceability_router)  # 统一穿透式追溯（看板聚合数 → 来源记录）
app.include_router(rcc_router)
app.include_router(rcc_data_router)
app.include_router(rcc_decision_router)
app.include_router(org_panel_router)  # 全组织层级参数驱动仿真面板
app.include_router(test_router)  # 测试模式角色切换（仅 TEST_MODE=true 时可用）


@app.get("/health")
def health():
    return {"status": "healthy", "version": "2.5.0"}


# ---------- 后台定时调度器（安灯超时升级 + 提醒 + 预警巡检） ----------
_SCHEDULER_INTERVAL = int(os.getenv("SCHEDULER_INTERVAL_SEC", "300"))  # 默认 5 分钟
_logger = logging.getLogger("scheduler")

# 循环体只在 engine_runner（独立进程）里跑，API worker 不再启动它，见 engine_asgi.py；
# 心跳间隔的判据在 api/services/engine_heartbeat.py 的 LOOP_INTERVAL_SECONDS。


async def _periodic_scheduler():
    """后台循环：每 N 秒执行安灯超时检测 + 提醒推送 + 预警巡检 + 日报自动生成。"""
    from database.db_config import db_config
    from api.services.andon_service import AndonService
    from api.services.alert_intelligence_service import patrol
    from api.services.report_generator_service import ReportGeneratorService

    await asyncio.sleep(30)  # 启动后 30s 再开始，等 DB 就绪
    # 心脏每轮报 `{}`：看上去在跳，却分不清"这轮真干了活"和"什么都没人做"。
    # 逐轮把做过的事和各个节流档距上次多久报出去，无人运行的事实才可核对。
    _GATES = {
        "patrol": "_last_patrol",
        "report": "_last_report",
        "aps_generate": "_last_aps",
        "equipment_pm": "_last_pm",
        "auto_dispatch": "_last_dispatch",
        "exception_escalation": "_last_escalation",
        "agent_stalled_check": "_last_agent_check",
        "warehouse_replenish": "_last_warehouse_check",
        "engine_watchdog": "_last_engine_watchdog",
        "engine_data_gap": "_last_engine_data_gap",
        "engine_kit_backfill": "_last_engine_kit_backfill",
        "delivery_prediction_ledger": "_last_delivery_ledger",
        "blocked_followup_recheck": "_last_blocked_recheck",
        "wms_alert_sync": "_last_wms_alert_sync",
        "wms_freeze_expiry": "_last_wms_freeze_expiry",
    }
    while True:
        did = {}
        try:
            async with db_config.session_factory() as db:
                svc = AndonService(db)
                escalations = await svc.process_timeout_escalations()
                reminders = await svc.process_timed_reminders()
                did["andon_escalated"] = len(escalations or [])
                did["andon_reminded"] = len(reminders or [])
                if escalations:
                    _logger.info(f"[scheduler] 安灯自动升级 {len(escalations)} 条")
                if reminders:
                    _logger.info(f"[scheduler] 安灯提醒 {len(reminders)} 条")
        except Exception as e:
            _logger.warning(f"[scheduler] 安灯巡检异常: {e}")

        # 预警巡检（工单超时 + 安灯未响应）—— 每 30 分钟跑一次（避免频繁调 LLM）
        try:
            import time as _t
            if not hasattr(_periodic_scheduler, "_last_patrol"):
                _periodic_scheduler._last_patrol = 0
            if _t.time() - _periodic_scheduler._last_patrol > 1800:
                _periodic_scheduler._last_patrol = _t.time()
                async with db_config.session_factory() as db:
                    result = await patrol(db, factory_id="FAC_ELEC_DEMO_2026")
                    if result.get("reviews_created"):
                        _logger.info(f"[scheduler] 预警巡检: {result}")
        except Exception as e:
            _logger.warning(f"[scheduler] 预警巡检异常: {e}")

        # 日报自动生成 —— 每 4 小时跑一次（覆盖班次交接）
        try:
            import time as _t2
            if not hasattr(_periodic_scheduler, "_last_report"):
                _periodic_scheduler._last_report = 0
            if _t2.time() - _periodic_scheduler._last_report > 14400:  # 4h
                _periodic_scheduler._last_report = _t2.time()
                async with db_config.session_factory() as db:
                    rpt_svc = ReportGeneratorService(db)
                    for fid in ["FAC_ELEC_DEMO_2026", "FAC_MECH_001"]:
                        try:
                            res = await rpt_svc.auto_generate_and_notify(fid)
                            _logger.info(f"[scheduler] 日报生成: {fid}, 异常 {res.get('anomalies', []).__len__()} 条")
                        except Exception as ex:
                            await db.rollback()
                            _logger.warning(f"[scheduler] 日报生成失败 {fid}: {ex}")
        except Exception as e:
            _logger.warning(f"[scheduler] 日报任务异常: {e}")

        # 自动排产默认关闭：APS 版本必须由计划员明确生成/确认/下达，
        # 防止后台每 8 小时制造无法解释的草案并污染版本审计。
        try:
            import time as _t3
            if os.getenv("APS_AUTO_GENERATE_ENABLED", "false").lower() == "true" and not hasattr(_periodic_scheduler, "_last_aps"):
                _periodic_scheduler._last_aps = 0
            if os.getenv("APS_AUTO_GENERATE_ENABLED", "false").lower() == "true" and _t3.time() - _periodic_scheduler._last_aps > 28800:  # 8h
                _periodic_scheduler._last_aps = _t3.time()
                from api.services.aps_service import ApsService
                async with db_config.session_factory() as db:
                    aps_svc = ApsService(db)
                    for fid in ["FAC_ELEC_DEMO_2026", "FAC_MECH_001"]:
                        try:
                            res = await aps_svc.generate_schedule(fid, created_by="scheduler")
                            if res.get("schedule_id"):
                                _logger.info(f"[scheduler] 自动排产: {fid}, {res.get('total_tasks', 0)} 任务")
                        except Exception as ex:
                            await db.rollback()
                            _logger.warning(f"[scheduler] 自动排产失败 {fid}: {ex}")
        except Exception as e:
            _logger.warning(f"[scheduler] 排产任务异常: {e}")

        # 设备 PM 自动排程 —— 每 12 小时跑一次
        try:
            import time as _t4
            if not hasattr(_periodic_scheduler, "_last_pm"):
                _periodic_scheduler._last_pm = 0
            if _t4.time() - _periodic_scheduler._last_pm > 43200:  # 12h
                _periodic_scheduler._last_pm = _t4.time()
                from api.services.maintenance_service import MaintenanceService
                async with db_config.session_factory() as db:
                    mnt_svc = MaintenanceService(db)
                    for fid in ["FAC_ELEC_DEMO_2026", "FAC_MECH_001"]:
                        try:
                            res = await mnt_svc.auto_schedule_pm(fid, created_by="scheduler")
                            if res.get("tasks_created"):
                                _logger.info(f"[scheduler] 设备PM: {fid}, 生成 {res['tasks_created']} 个保养任务")
                        except Exception as ex:
                            await db.rollback()
                            _logger.warning(f"[scheduler] 设备PM失败 {fid}: {ex}")
        except Exception as e:
            _logger.warning(f"[scheduler] 设备PM任务异常: {e}")

        # 事件驱动自派发 —— 每 2 分钟扫描一次（替代调度员手动派工）
        try:
            import time as _t5
            if not hasattr(_periodic_scheduler, "_last_dispatch"):
                _periodic_scheduler._last_dispatch = 0
            if _t5.time() - _periodic_scheduler._last_dispatch > 120:  # 2min
                _periodic_scheduler._last_dispatch = _t5.time()
                from api.services.dispatch_service import auto_dispatch_station
                async with db_config.session_factory() as db:
                    for fid in ["FAC_ELEC_DEMO_2026", "FAC_MECH_001"]:
                        try:
                            res = await auto_dispatch_station(db, fid)
                            if res.get("dispatched_count"):
                                _logger.info(f"[scheduler] 自派发: {fid}, {res['dispatched_count']} 单")
                        except Exception as ex:
                            await db.rollback()
                            _logger.warning(f"[scheduler] 自派发失败 {fid}: {ex}")
                    await db.commit()
        except Exception as e:
            _logger.warning(f"[scheduler] 自派发任务异常: {e}")

        # 异常超时升级 —— 每 5 分钟扫描（岗位消除安全网）
        try:
            import time as _t6
            if not hasattr(_periodic_scheduler, "_last_escalation"):
                _periodic_scheduler._last_escalation = 0
            if _t6.time() - _periodic_scheduler._last_escalation > 300:  # 5min
                _periodic_scheduler._last_escalation = _t6.time()
                from api.services.exception_engine_service import ExceptionEngine
                async with db_config.session_factory() as db:
                    engine = ExceptionEngine(db)
                    for fid in ["FAC_ELEC_DEMO_2026", "FAC_MECH_001"]:
                        try:
                            res = await engine.check_escalation(fid)
                            if res.get("escalated_count"):
                                _logger.info(f"[scheduler] 异常升级: {fid}, {res['escalated_count']} 条")
                        except Exception as ex:
                            await db.rollback()
                            _logger.warning(f"[scheduler] 异常升级失败 {fid}: {ex}")
        except Exception as e:
            _logger.warning(f"[scheduler] 异常升级任务异常: {e}")

        # 智能体卡住检测 + 预测性扫描 —— 每 10 分钟
        try:
            import time as _t7
            if not hasattr(_periodic_scheduler, "_last_agent_check"):
                _periodic_scheduler._last_agent_check = 0
            if _t7.time() - _periodic_scheduler._last_agent_check > 600:  # 10min
                _periodic_scheduler._last_agent_check = _t7.time()
                from api.services.agent_supervisor_service import AgentSupervisor
                async with db_config.session_factory() as db:
                    supervisor = AgentSupervisor(db)
                    for fid in ["FAC_ELEC_DEMO_2026", "FAC_MECH_001"]:
                        try:
                            stalled = await supervisor.check_stalled(fid)
                            if stalled.get("stalled_count"):
                                _logger.info(f"[scheduler] 智能体卡住: {fid}, {stalled['stalled_count']}个任务")
                        except Exception as ex:
                            await db.rollback()
                            _logger.warning(f"[scheduler] 卡住检测失败 {fid}: {ex}")
        except Exception as e:
            _logger.warning(f"[scheduler] 智能体监督任务异常: {e}")

        # 仓储智能体：补货检查 —— 每 60 分钟
        try:
            import time as _t8
            if not hasattr(_periodic_scheduler, "_last_warehouse_check"):
                _periodic_scheduler._last_warehouse_check = 0
            if _t8.time() - _periodic_scheduler._last_warehouse_check > 3600:  # 60min
                _periodic_scheduler._last_warehouse_check = _t8.time()
                from api.services.warehouse_agent_service import WarehouseAgent
                async with db_config.session_factory() as db:
                    agent = WarehouseAgent(db)
                    for fid in ["FAC_ELEC_DEMO_2026", "FAC_MECH_001"]:
                        try:
                            result = await agent.on_stock_below_safety(fid)
                            if result.get("total_items"):
                                _logger.info(f"[warehouse] {fid}: {result['total_items']}项物料需补货")
                        except Exception as ex:
                            await db.rollback()
                            _logger.warning(f"[warehouse] 补货检查失败 {fid}: {ex}")
        except Exception as e:
            _logger.warning(f"[scheduler] 仓储智能体任务异常: {e}")

        # 交期智能体：T+3 交期风险扫描 —— 每 60 分钟（高风险真实提优先级，幂等）
        try:
            import time as _t10
            if not hasattr(_periodic_scheduler, "_last_delivery_check"):
                _periodic_scheduler._last_delivery_check = 0
            if _t10.time() - _periodic_scheduler._last_delivery_check > 3600:  # 60min
                _periodic_scheduler._last_delivery_check = _t10.time()
                from api.services.delivery_agent_service import DeliveryAgent
                async with db_config.session_factory() as db:
                    agent = DeliveryAgent(db)
                    for fid in ["FAC_ELEC_DEMO_2026", "FAC_MECH_001"]:
                        try:
                            res = await agent.check_delivery_risks(fid)
                            if res.get("scanned_risks"):
                                _logger.info(f"[delivery] {fid}: 风险{res['scanned_risks']}单，提级{len(res.get('escalated', []))}单")
                        except Exception as ex:
                            await db.rollback()
                            _logger.warning(f"[delivery] 交期扫描失败 {fid}: {ex}")
        except Exception as e:
            _logger.warning(f"[scheduler] 交期智能体任务异常: {e}")

        # 虚拟工厂脉搏 —— 每 120 分钟按真实节奏接单/拆单/报工/预警
        # 原为 60 分钟：测试/开发阶段每次 pulse 都会真实落库（报工/工单/订单/通知），
        # 放慢一倍直接把写入量减半，压掉 WAL 与表膨胀。节奏参数在 PulseConfig 里。
        try:
            import time as _t_vf
            if not hasattr(_periodic_scheduler, "_last_virtual_factory"):
                _periodic_scheduler._last_virtual_factory = 0
            if _t_vf.time() - _periodic_scheduler._last_virtual_factory > 7200:  # 120min
                _periodic_scheduler._last_virtual_factory = _t_vf.time()
                from api.services.virtual_factory_service import PulseConfig, VirtualFactoryService
                async with db_config.session_factory() as db:
                    svc = VirtualFactoryService(db)
                    for fid in ["FAC_ELEC_DEMO_2026", "FAC_MECH_001"]:
                        try:
                            result = await svc.pulse(PulseConfig(factory_id=fid))
                            created = len(result.get("created_orders", []))
                            advanced = result.get("advanced", {}).get("containers_reported", 0)
                            if created or advanced:
                                _logger.info(f"[virtual-factory] {fid}: 新单{created}, 推进{advanced}柜")
                        except Exception as ex:
                            await db.rollback()
                            _logger.warning(f"[virtual-factory] 脉搏失败 {fid}: {ex}")
        except Exception as e:
            _logger.warning(f"[scheduler] 虚拟工厂任务异常: {e}")

        # BOM 镜像跟随 engflow —— 每 6 小时按水位线增量补一次
        # 源在 engflow 项目的库里（481,557 行），本地 enghub_bom_items 只是镜像；
        # 没有这一步镜像就会一直停在某次手动同步的日子，领料读到过期需求。
        try:
            import time as _t_bom
            if not hasattr(_periodic_scheduler, "_last_bom_sync"):
                _periodic_scheduler._last_bom_sync = 0
            if _t_bom.time() - _periodic_scheduler._last_bom_sync > 21600:  # 6h
                _periodic_scheduler._last_bom_sync = _t_bom.time()
                from api.services.bom_sync_service import BomSyncService
                async with db_config.session_factory() as db:
                    svc = BomSyncService(db)
                    if not svc.source_configured:
                        _logger.warning(
                            "[bom-sync] 未配置 ENGFLOW_DATABASE_URL，跳过本轮"
                            "（不会退回本地表当源）"
                        )
                    else:
                        res = await svc.incremental_sync()
                        if res.get("status") == "success":
                            _logger.info(
                                f"[bom-sync] 增量完成：写 {res.get('rows_upserted')} 行，"
                                f"镜像 {res.get('mirror', {}).get('mirrored')} / "
                                f"源 {res.get('source', {}).get('total')} 行"
                            )
                        else:
                            _logger.warning(f"[bom-sync] 增量失败: {res.get('error')}")
                        await db.commit()
        except Exception as e:
            _logger.warning(f"[scheduler] BOM 镜像同步异常: {e}")

        # 排产智能体：产能平衡检查 —— 每 30 分钟
        try:
            import time as _t9
            if not hasattr(_periodic_scheduler, "_last_scheduling_check"):
                _periodic_scheduler._last_scheduling_check = 0
            if _t9.time() - _periodic_scheduler._last_scheduling_check > 1800:  # 30min
                _periodic_scheduler._last_scheduling_check = _t9.time()
                from api.services.scheduling_agent_service import SchedulingAgent
                async with db_config.session_factory() as db:
                    agent = SchedulingAgent(db)
                    for fid in ["FAC_ELEC_DEMO_2026", "FAC_MECH_001"]:
                        try:
                            balance = await agent.capacity_balance(fid)
                            if not balance.get("balanced", True):
                                _logger.info(f"[scheduling] {fid}: 产能不平衡 ({balance.get('imbalance_ratio', 0):.0%})")
                        except Exception as ex:
                            await db.rollback()
                            _logger.warning(f"[scheduling] 产能检查失败 {fid}: {ex}")
        except Exception as e:
            _logger.warning(f"[scheduler] 排产智能体任务异常: {e}")

        # 引擎自身健康巡检 —— 每 10 分钟：心跳断写、循环退出、窗口崩溃越线自动挂催办
        # 10-06 那次心跳断写写坏了几个小时，全靠人翻库才发现；判据本来就是 L1 那一格，
        # 现在让它自己开口：挂了哪条、恢复了自己关，同一条故障不重复挂。
        try:
            import time as _t_ew
            if not hasattr(_periodic_scheduler, "_last_engine_watchdog"):
                _periodic_scheduler._last_engine_watchdog = 0
            if _t_ew.time() - _periodic_scheduler._last_engine_watchdog > 600:  # 10min
                _periodic_scheduler._last_engine_watchdog = _t_ew.time()
                from api.services.engine_watchdog import scan as _watchdog_scan
                async with db_config.session_factory() as db:
                    res = await _watchdog_scan(
                        db, apply=os.getenv("ENGINE_WATCHDOG_APPLY", "true").lower()
                            not in {"0", "false", "no", "off"})
                    changed = {k: v for k, v in res["counts"].items()
                               if v and k != "unchanged"}
                    if changed:
                        _logger.info(f"[engine-watchdog] {changed}")
                    did["engine_watchdog"] = {
                        "loops_alive": res["alive"], "loops_seen": res["loops_seen"],
                        "findings": len(res["findings"]), "actions": changed,
                    }
        except Exception as e:
            _logger.warning(f"[scheduler] 引擎健康巡检异常: {e}")

        # 数据缺口巡检 —— 每 6 小时：判据被台账/主数据封顶时自动挂一条补数据催办
        # L2B 那几格读着"覆盖率 0.25 fail"却没人被派活，缺的就是这一道。
        try:
            import time as _t_ed
            if not hasattr(_periodic_scheduler, "_last_engine_data_gap"):
                _periodic_scheduler._last_engine_data_gap = 0
            if _t_ed.time() - _periodic_scheduler._last_engine_data_gap > 21600:  # 6h
                _periodic_scheduler._last_engine_data_gap = _t_ed.time()
                from api.services.engine_watchdog import scan_data as _data_scan
                async with db_config.session_factory() as db:
                    res = await _data_scan(
                        db, apply=os.getenv("ENGINE_WATCHDOG_APPLY", "true").lower()
                            not in {"0", "false", "no", "off"})
                    changed = {k: v for k, v in res["counts"].items()
                               if v and k != "unchanged"}
                    if changed:
                        _logger.info(f"[engine-data] {changed}")
                    did["engine_data_gap"] = {
                        "findings": len(res["findings"]),
                        "actions": changed,
                        "titles": [f["title"][:60] for f in res["findings"]][:3],
                        # 这一格只在真的跑过那一轮的 tick 里出现；held_open 是"这轮没报但
                        # 判据住在本文件里，所以不关闭"的格子，cells_without_guard 非空说明
                        # 新增了数据格子却没进保护名单（缺席就会被当修好，等于自动放行假绿灯）。
                        "held_open": res.get("held_open"),
                        "cleared": res.get("cleared_this_round"),
                        "cells_without_guard": res.get("cells_without_guard"),
                    }
        except Exception as e:
            _logger.warning(f"[scheduler] 引擎数据缺口巡检异常: {e}")

        # 库存报警落库 —— 每 30 分钟。为什么要有这一道：`stock_alerts` 长期 0 行，
        # 报警是每次实时算完就丢的，于是"上次那条缺料告警谁处理了、多久处理的"永远答不出。
        # 四把尺分开存、不合并（按行声明的补货点 vs 代码里写死的 <10 是两件事，
        # 合成一个数就等于替厂里选阈值）；关闭只发生在本轮评估过且条件已消失的告警上。
        try:
            import time as _t_wa
            if not hasattr(_periodic_scheduler, "_last_wms_alert_sync"):
                _periodic_scheduler._last_wms_alert_sync = 0
            if _t_wa.time() - _periodic_scheduler._last_wms_alert_sync > 1800:  # 30min
                _periodic_scheduler._last_wms_alert_sync = _t_wa.time()
                from api.services.engine_watchdog import DEFAULT_FACTORY_ID as _WA_FID
                from api.services.stock_alerts import sync_alerts as _sync_alerts
                async with db_config.session_factory() as db:
                    res = await _sync_alerts(
                        db, _WA_FID,
                        apply=os.getenv("WMS_ALERT_SYNC_APPLY", "true").lower()
                            not in {"0", "false", "no", "off"})
                    did["wms_alert_sync"] = {
                        "applied": res["apply"], "counts": res["counts"],
                        "created": res.get("created", 0), "closed": res.get("closed", 0),
                        "renewed": res["renewed_count"], "left_alone": res["left_alone_count"],
                        "failed_kinds": res["failed"]}
                    if res.get("created") or res.get("closed"):
                        _logger.info(f"[wms-alert] 新增 {res.get('created')} 消 {res.get('closed')}")
        except Exception as e:
            # 落库失败只影响"告警有没有历史可查"，不能把整个调度器带停
            _logger.warning(f"[scheduler] 库存报警落库异常: {e}")

        # 冻结到期放行 —— 每 30 分钟。为什么这道门默认关着：`expire_due` 写出来之后
        # 全仓没有一处调用它（10-09 grep 只有定义、审计格的提示文字和端点注释），
        # 于是"到期自动放"那本账永远是 0，而 `freeze_until` 早过的行一直挂着 ——
        # 审计里"到期该放还没放"只会长不会短，读起来像功能坏了。
        # 只有**建单时明确勾了 auto_unfreeze** 的行会被放，其余继续挡着等人签：
        # 到期是提醒，不是质量放行。开关 WMS_FREEZE_EXPIRY_APPLY=true 才真写。
        try:
            import time as _t_fz
            if not hasattr(_periodic_scheduler, "_last_wms_freeze_expiry"):
                _periodic_scheduler._last_wms_freeze_expiry = 0
            if _t_fz.time() - _periodic_scheduler._last_wms_freeze_expiry > 1800:  # 30min
                _periodic_scheduler._last_wms_freeze_expiry = _t_fz.time()
                from api.services.engine_watchdog import DEFAULT_FACTORY_ID as _FZ_FID
                from api.services.wms_freezes import expire_due as _expire_due
                async with db_config.session_factory() as db:
                    res = await _expire_due(
                        db, _FZ_FID,
                        apply=os.getenv("WMS_FREEZE_EXPIRY_APPLY", "false").lower()
                            in {"1", "true", "yes", "on"})
                    did["wms_freeze_expiry"] = {"applied": res["apply"], "due": res["due"],
                                                "expired": res["expired"]}
                    if res.get("expired"):
                        _logger.info(f"[wms-freeze] 到期自动放行 {res['expired']} 条")
        except Exception as e:
            # 放行门挂了只影响"到期的还挡着"（偏保守那一侧），不能把调度器带停
            _logger.warning(f"[scheduler] 冻结到期放行异常: {e}")

        # 齐套行覆盖补齐 —— 每 2 小时补 25 张单（只加不改不删，每张 ≤400 行）。
        # 为什么要自动、为什么闸口放到 400 行：10-08 把一致率按登记深度切开实测是
        #   ≥400 行那档 0.967 / 100-399 行那档 0.103 / 1-99 行那档 0.0，
        # 封顶的是台账登记深度，不是引擎判错。只捞"最薄的 ≤80 行"会永远漏掉
        # 登记了一半的那 142 张 —— 那才是整池 0.542 上不去的大头。
        try:
            import time as _t_kb
            if not hasattr(_periodic_scheduler, "_last_engine_kit_backfill"):
                _periodic_scheduler._last_engine_kit_backfill = 0
            if _t_kb.time() - _periodic_scheduler._last_engine_kit_backfill > 7200:  # 2h
                _periodic_scheduler._last_engine_kit_backfill = _t_kb.time()
                from api.services.component_orders import reupgrade_stale_kit_lines
                from api.services.engine_watchdog import DEFAULT_FACTORY_ID as _KB_FID
                async with db_config.session_factory() as db:
                    res = await reupgrade_stale_kit_lines(
                        db, _KB_FID,
                        apply=os.getenv("ENGINE_KIT_BACKFILL_APPLY", "true").lower()
                            not in {"0", "false", "no", "off"},
                        limit=max(1, int(os.getenv("ENGINE_KIT_BACKFILL_PER_ROUND", "25"))),
                        max_lines=max(1, int(os.getenv("ENGINE_KIT_BACKFILL_MAX_LINES", "400"))))
                    did["engine_kit_backfill"] = {
                        "applied": res["apply"], "candidates": res["orders_stale"],
                        "orders_upgraded": res["orders_upgraded"],
                        "lines_added": res["lines_added"],
                        "skipped_existing": res["lines_skipped_existing"],
                        "skipped_zero_requirement": res["lines_skipped_zero"],
                        "no_structure": res["orders_no_structure"]}
                    if res["lines_added"]:
                        _logger.info(f"[kit-backfill] {did['engine_kit_backfill']}")
        except Exception as e:
            _logger.warning(f"[scheduler] 齐套行补登异常: {e}")

        # 交期留痕账本 —— 每天记一次、完工时配对一次。没有这一步，"引擎交期准不准"永远
        # 只能拿今天的主数据重跑历史单来猜；攒够成对样本才谈得上回测。
        try:
            import time as _t_dl
            if not hasattr(_periodic_scheduler, "_last_delivery_ledger"):
                _periodic_scheduler._last_delivery_ledger = 0
            if _t_dl.time() - _periodic_scheduler._last_delivery_ledger > 86400:  # 每天
                _periodic_scheduler._last_delivery_ledger = _t_dl.time()
                from api.services.prediction_ledger import (delivery_accuracy,
                                                            pair_completed_predictions,
                                                            record_predictions)
                from api.services.engine_watchdog import DEFAULT_FACTORY_ID as _DL_FID
                async with db_config.session_factory() as db:
                    rec = await record_predictions(db, _DL_FID, limit=600, apply=True)
                    par = await pair_completed_predictions(db, _DL_FID, apply=True)
                    acc = await delivery_accuracy(db, _DL_FID)
                    did["delivery_prediction_ledger"] = {
                        "recorded": rec.get("recorded"),
                        "no_line_capacity": rec.get("no_line_capacity"),
                        "paired_now": par.get("paired"),
                        "paired_total": acc.get("paired"),
                        "mae_days": acc.get("mae_days"), "mape": acc.get("mape")}
                    _logger.info(f"[delivery-ledger] {did['delivery_prediction_ledger']}")
        except Exception as e:
            _logger.warning(f"[scheduler] 交期留痕账本异常: {e}")

        # blocked 催办的台账复判 —— 每 30 分钟。升级出去的单不会自己消失：
        # 106 条从 8 月挂到现在，其中相当一部分的缺口早补平了，只是没人再去看台账。
        # 复判只朝一个方向动：台账说补平了才关；还缺着的原样留着等人工裁决。
        try:
            import time as _t_br
            if not hasattr(_periodic_scheduler, "_last_blocked_recheck"):
                _periodic_scheduler._last_blocked_recheck = 0
            if _t_br.time() - _periodic_scheduler._last_blocked_recheck > 1800:  # 30min
                _periodic_scheduler._last_blocked_recheck = _t_br.time()
                from api.services.followup_lifecycle import sweep_blocked
                from api.services.engine_watchdog import DEFAULT_FACTORY_ID as _BR_FID
                async with db_config.session_factory() as db:
                    sw = await sweep_blocked(
                        db, _BR_FID, limit=80,
                        apply=os.getenv("BLOCKED_FOLLOWUP_RECHECK_APPLY", "true").lower()
                            not in {"0", "false", "no", "off"})
                    did["blocked_followup_recheck"] = {
                        "applied": sw["apply"], "examined": sw["examined"],
                        "actions": sw["action_counts"]}
                    if sw["action_counts"].get("close_kit_complete"):
                        _logger.info(f"[blocked-recheck] {sw['action_counts']}")
        except Exception as e:
            _logger.warning(f"[scheduler] blocked 催办复判异常: {e}")

        from api.services.engine_heartbeat import record as _heartbeat
        import time as _gt
        did["aps_auto_generate_enabled"] = (
            os.getenv("APS_AUTO_GENERATE_ENABLED", "false").lower() == "true")
        did["gates_seconds_since_last"] = {
            name: (None if not hasattr(_periodic_scheduler, attr)
                   else round(_gt.time() - float(getattr(_periodic_scheduler, attr) or 0)))
            for name, attr in _GATES.items()
        }
        await _heartbeat("periodic-scheduler", "tick", detail=did)
        await asyncio.sleep(_SCHEDULER_INTERVAL)


@app.on_event("startup")
async def _start_scheduler():
    # Agent Event Bus：开启 DB 审计持久化（失败不阻断实时事件流）。
    from core.agent import AgentEventBus
    from database.db_config import db_config
    event_persistence_enabled = os.getenv(
        "AGENT_EVENT_PERSISTENCE_ENABLED", "1"
    ).lower() not in {"0", "false", "no", "off"}
    AgentEventBus.get_instance().configure_persistence(
        db_config.session_factory,
        enabled=event_persistence_enabled,
    )
    _logger.info(
        "[event-bus] DB persistence %s",
        "enabled" if event_persistence_enabled else "disabled",
    )
    checkpoint_persistence_enabled = os.getenv(
        "CHECKPOINT_PERSISTENCE_ENABLED", "0"
    ).lower() not in {"0", "false", "no", "off"}
    _logger.info(
        "[checkpoint] DB cold storage %s (migration 084 required)",
        "enabled" if checkpoint_persistence_enabled else "disabled",
    )

    # 引擎后台循环不在这里起：uvicorn --workers 2 会让每个 worker 各起一套
    # （重复下单/重复报工），而且 create_task 的返回值没人存，任务可能被 GC ——
    # 实测 API 全部正常而引擎静默停摆。循环改由独立进程 engine_asgi.py 持有，
    # API 侧只通过 engine_loop_state 心跳表看它活没活。


# ---------- 前端静态托管（FastAPI 同源服务，替代 nginx） ----------
FRONTEND_DIST = Path(os.environ.get("FRONTEND_DIST", str(Path(__file__).parent / "frontend_dist")))

if FRONTEND_DIST.is_dir():
    # 带 hash 的静态资源 (js/css/woff/png...)
    _assets_dir = FRONTEND_DIST / "assets"
    if _assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="static-assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(request: Request, full_path: str):
        """SPA fallback：非 API 路由全部返回前端页面"""
        file_path = FRONTEND_DIST / full_path
        if full_path and file_path.is_file():
            return FileResponse(str(file_path))
        # index.html 禁止缓存，确保发版后用户立即拿到新代码（js/css 带 hash 可长期缓存）
        return FileResponse(
            str(FRONTEND_DIST / "index.html"),
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )
