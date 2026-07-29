"""
QMS缺陷处置工作流测试 - P1优先级
覆盖从缺陷发现到8D报告关闭的完整QC闭环
"""

import pytest
from unittest.mock import MagicMock, AsyncMock
from database.models import DefectRecord, QualityInspection


@pytest.fixture(scope="function")
def mock_qms_service():
    """QMSService的mock fixture"""
    service = MagicMock()
    service.create_defect_record = AsyncMock()
    service.get_defect_record = AsyncMock()
    service.update_defect_ocap = AsyncMock()
    service.dispose_defect = AsyncMock()
    return service


@pytest.mark.asyncio
async def test_defect_creation_from_inspection(mock_qms_service):
    """测试：从检验单创建缺陷记录 - IQC/IPQC发现不良时自动创建缺陷"""
    from api.services.qms_service import QMSService

    inspection_result = {
        "result": "FAIL",
        "defect_qty": 5,
        "defects": [
            {"type": "appearance", "severity": "major", "description": "表面划伤"},
            {"type": "dimension", "severity": "minor", "description": "尺寸超差"}
        ]
    }

    with patch('api.services.qms_service.QMSService') as mock_qms_cls:
        mock_instance = mock_qms_cls.return_value
        mock_instance.create_defect_records = AsyncMock(return_value={
            "success": True,
            "created_count": 2,
            "defect_ids": ["DEF-001", "DEF-002"]
        })

        service = QMSService(MagicMock())
        result = await service.create_defects_from_inspection(
            inspection_id="INS-001",
            factory_id="F001",
            defects=[
                {"type": "appearance", "severity": "major", "description": "表面划伤"},
                {"type": "dimension", "severity": "minor", "description": "尺寸超差"}
            ]
        )

        assert result["success"] is True
        assert result["data"]["created_count"] == 2
        assert len(result["data"]["defect_ids"]) == 2


@pytest.mark.asyncio
async def test_defect_ocap_trigger(mock_qms_service):
    """测试：缺陷OCAP触发 - 严重缺陷自动关联OCAP流程"""
    from api.services.qms_service import QMSService

    severe_defect = {
        "id": "def-001",
        "severity": "critical",
        "ocap_status": "pending",
        "trigger_reason": "客户投诉"
    }

    with patch('api.services.qms_service.OCAPService') as mock_ocap_cls:
        mock_ocap = mock_ocap_cls.return_value
        mock_ocap.create_case = AsyncMock(return_value={"case_id": "OCA-001"})

        service = QMSService(MagicMock())
        result = await service.check_and_trigger_ocap(severe_defect)

        assert result["ocap_triggered"] is True
        assert result["ocap_case_id"] == "OCA-001"
        assert severe_defect["ocap_status"] == "triggered"


@pytest.mark.asyncio
async def test_defect_disposition_rework(mock_qms_service):
    """测试：缺陷处置 - 返工处理路径"""
    from api.services.qms_service import QMSService

    disposition_data = {
        "disposition_type": "rework",
        "rework_operator": "worker01",
        "rework_workstation": "STN-R01",
        "rework_remark": "重新抛光后合格"
    }

    service = QMSService(MagicMock())
    result = await service.dispose_defect(
        defect_id="def-001",
        disposition="rework",
        operator="qc01",
        **disposition_data
    )

    assert result["success"] is True
    assert result["data"]["disposition"] == "rework"
    assert result["data"]["disposition_by"] == "qc01"
    assert result["data"]["disposition_at"] is not None


@pytest.mark.asyncio
async def test_defect_disposition_scrap(mock_qms_service):
    """测试：缺陷处置 - 报废处理路径"""
    from api.services.qms_service import QMSService

    disposition_data = {
        "disposition_type": "scrap",
        "scrap_reason": "无法修复",
        "scrap_authorizer": "mgr01"
    }

    service = QMSService(MagicMock())
    result = await service.dispose_defect(
        defect_id="def-002",
        disposition="scrap",
        operator="qc01",
        **disposition_data
    )

    assert result["success"] is True
    assert result["data"]["disposition"] == "scrap"
    assert result["data"]["scrap_authorizer"] == "mgr01"
    assert result["data"]["scrap_reason"] == "无法修复"


@pytest.mark.asyncio
async def test_defect_disposition_concession(mock_qms_service):
    """测试：缺陷处置 - 让步接收路径（需特殊审批）"""
    from api.services.qms_service import QMSService

    disposition_data = {
        "disposition_type": "concession",
        "customer_approval_required": True,
        "concession_expiry_date": "2026-08-15"
    }

    service = QMSService(MagicMock())
    result = await service.dispose_defect(
        defect_id="def-003",
        disposition="concession",
        operator="qc01",
        **disposition_data
    )

    assert result["success"] is True
    assert result["data"]["disposition"] == "concession"
    assert result["data"]["customer_approval_required"] is True
    assert result["data"]["concession_expiry_date"] == "2026-08-15"


@pytest.mark.asyncio
async def test_8d_report_creation_for_critical_defect():
    """测试：严重缺陷自动生成8D报告"""
    from api.services.qms_service import QMSService

    critical_defect = {
        "id": "def-critical",
        "severity": "critical",
        "product_id": "PROD-MAIN",
        "batch_code": "BATCH-20260729",
        "quantity": 50
    }

    with patch('api.services.qms_service.EightDService') as mock_8d_cls:
        mock_8d = mock_8d_cls.return_value
        mock_8d.create_report = AsyncMock(return_value={
            "report_id": "8D-001",
            "status": "in_progress"
        })

        service = QMSService(MagicMock())
        result = await service.create_8d_report_for_defect(critical_defect)

        assert result["success"] is True
        assert result["data"]["report_id"].startswith("8D-")


@pytest.mark.asyncio
async def test_root_cause_analysis_with_fishbone():
    """测试：根本原因分析 - 鱼骨图分析法"""
    from api.services.qms_service import QMSService

    fishbone_data = {
        "dimension": "机器",
        "causes": ["设备校准漂移", "刀具磨损", "参数设置错误"],
        "top_candidate": "设备校准漂移"
    }

    with patch('api.services.qms_service.FishboneAnalyzer') as mock_fish_cls:
        mock_fish = mock_fish_cls.return_value
        mock_fish.analyze = AsyncMock(return_value={
            "root_cause": "设备校准漂移",
            "confidence": 0.85
        })

        service = QMSService(MagicMock())
        result = await service.perform_root_cause_analysis(fishbone_data)

        assert result["success"] is True
        assert result["data"]["root_cause"] == "设备校准漂移"


@pytest.mark.asyncio
async def test_corrective_action_verification():
    """测试：纠正措施验证 - 防止复发闭环"""
    from api.services.qms_service import QMSService

    corrective_actions = [
        {"action_id": "CA-01", "desc": "增加校准频次至每周", "owner": "tech_lead", "deadline": "2026-08-05"},
        {"action_id": "CA-02", "desc": "操作员培训", "owner": "trainer", "deadline": "2026-08-03"}
    ]

    verification_result = {
        "ca-01": {"completed": True, "verified_by": "qc_mgr", "verify_date": "2026-08-06"},
        "ca-02": {"completed": True, "verified_by": "qc_mgr", "verify_date": "2026-08-04"}
    }

    service = QMSService(MagicMock())
    result = await service.verify_corrective_actions(corrective_actions, verification_result)

    assert result["success"] is True
    assert result["data"]["all_completed"] is True
    assert result["data"]["verification_complete"] is True


@pytest.mark.asyncio
async def test_preventive_action_planning():
    """测试：预防措施规划 - 基于历史数据预防未来缺陷"""
    from api.services.qms_service import QMSService

    trend_analysis = {
        "pattern": "季节性温度影响外观质量",
        "affected_products": ["PROD-A", "PROD-B"],
        "season": "夏季",
        "recommendations": ["调整车间温控", "增加抽检频次"]
    }

    service = QMSService(MagicMock())
    result = await service.plan_preventive_actions(trend_analysis)

    assert result["success"] is True
    assert len(result["data"]["preventive_actions"]) > 0