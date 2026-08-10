"""
API Routes initialization
"""

from fastapi import APIRouter

from api.routes.qms_routes import router as qms_router
try:
    from api.routes.qms_red_tag_routes import router as qms_red_tag_router
except ImportError:
    # 红牌模块的数据模型尚未合入时，不应阻断 PMC/MES 等其余路由启动。
    qms_red_tag_router = None
from api.routes.mes_routes import router as mes_router
from api.routes.wms_routes import router as wms_router
from api.routes.pp_routes import router as pp_router
from api.routes.pmc_routes import router as pmc_router
from api.routes.trainer_routes import router as trainer_router
from api.routes.equipment_routes import router as equipment_router
from api.routes.hr_routes import router as hr_router
from api.routes.tms_routes import router as tms_router
from api.routes.andon_routes import router as andon_router
from api.routes.notification_routes import router as notification_router
from api.routes.search_routes import router as search_router
from api.routes.auth_routes import router as auth_router
from api.routes.agent_routes import router as agent_router
from api.routes.agent_supervisor_routes import router as agent_supervisor_router
from api.routes.alert_intelligence_routes import router as alert_intelligence_router
from api.routes.aps_routes import router as aps_router
from api.routes.automation_level_routes import router as automation_level_router
from api.routes.bom_routes import router as bom_router
from api.routes.chat_routes import router as chat_router
from api.routes.code_table_routes import router as code_table_router
from api.routes.collaboration_routes import router as collaboration_router
from api.routes.commander_routes import router as commander_router
from api.routes.crew_routes import router as crew_router
from api.routes.data_consistency_routes import router as data_consistency_router
from api.routes.employee_skill_router import router as employee_skill_router
from api.routes.equipment_phase5_routes import router as equipment_phase5_router
from api.routes.expert_system_routes import router as expert_system_router
from api.routes.file_routes import router as file_router
from api.routes.ie_routes import router as ie_router
from api.routes.ie_routes_extended import router as ie_router_extended
ie_advanced_router = ie_router_extended
try:
    from api.routes.mes_adapter_route import router as mes_adapter_router
except ImportError:
    # 适配器实验模块未完成时隔离故障，正式 MES/PMC 路由仍可启动。
    mes_adapter_router = None
from api.routes.orchestrator_routes import router as orchestrator_router
from api.routes.production_dashboard_routes import router as production_dashboard_router
from api.routes.production_phase1_routes import router as production_phase1_router
from api.routes.production_phase2_routes import router as production_phase2_router
from api.routes.qms_phase4_routes import router as qms_phase4_router
from api.routes.qms_routes_append import router as qms_routes_append_router
from api.routes.quick_command_routes import router as quick_command_router
from api.routes.rcc_data_routes import router as rcc_data_router
from api.routes.rcc_decision_routes import router as rcc_decision_router
from api.routes.rcc_routes import router as rcc_router
from api.routes.role_elimination_routes import router as role_elimination_router
from api.routes.routing_template_routes import router as routing_template_router
from api.routes.sim_erp_routes import router as sim_erp_router
from api.routes.sim_factory_routes import router as sim_factory_router
from api.routes.task_center_routes import router as task_center_router
from api.routes.test_switch import test_router as test_switch_router
from api.routes.traceability_routes import router as traceability_router
from api.routes.virtual_factory_routes import router as virtual_factory_router
from api.routes.wms_phase3_routes import router as wms_phase3_router
from api.routes.work_order_template_routes import router as work_order_template_router
from api.routes.work_team_routes import router as work_team_router
from api.routes.workflow_analytics_routes import router as workflow_analytics_router
from api.routes.workflow_diagram_routes import router as workflow_diagram_router

# Create main router
main_router = APIRouter()

# Include all routers
main_router.include_router(qms_router)
if qms_red_tag_router is not None:
    main_router.include_router(qms_red_tag_router)
main_router.include_router(mes_router)
main_router.include_router(wms_router)
main_router.include_router(pp_router)
main_router.include_router(pmc_router)
main_router.include_router(trainer_router)
main_router.include_router(equipment_router)
main_router.include_router(hr_router)
main_router.include_router(tms_router)
main_router.include_router(andon_router)
main_router.include_router(notification_router)
main_router.include_router(search_router)
main_router.include_router(auth_router)
main_router.include_router(agent_router)
main_router.include_router(agent_supervisor_router)
main_router.include_router(alert_intelligence_router)
main_router.include_router(aps_router)
main_router.include_router(automation_level_router)
main_router.include_router(bom_router)
main_router.include_router(chat_router)
main_router.include_router(code_table_router)
main_router.include_router(collaboration_router)
main_router.include_router(commander_router)
main_router.include_router(crew_router)
main_router.include_router(data_consistency_router)
main_router.include_router(employee_skill_router)
main_router.include_router(equipment_phase5_router)
main_router.include_router(expert_system_router)
main_router.include_router(file_router)
main_router.include_router(ie_router)
main_router.include_router(ie_router_extended)
if mes_adapter_router is not None:
    main_router.include_router(mes_adapter_router)
main_router.include_router(orchestrator_router)
main_router.include_router(production_dashboard_router)
main_router.include_router(production_phase1_router)
main_router.include_router(production_phase2_router)
main_router.include_router(qms_phase4_router)
main_router.include_router(qms_routes_append_router)
main_router.include_router(quick_command_router)
main_router.include_router(rcc_data_router)
main_router.include_router(rcc_decision_router)
main_router.include_router(rcc_router)
main_router.include_router(role_elimination_router)
main_router.include_router(routing_template_router)
main_router.include_router(sim_erp_router)
main_router.include_router(sim_factory_router)
main_router.include_router(task_center_router)
main_router.include_router(test_switch_router)
main_router.include_router(traceability_router)
main_router.include_router(virtual_factory_router)
main_router.include_router(wms_phase3_router)
main_router.include_router(work_order_template_router)
main_router.include_router(work_team_router)
main_router.include_router(workflow_analytics_router)
main_router.include_router(workflow_diagram_router)

__all__ = ["main_router"]
