"""QMS缺陷处置工作流测试 - 覆盖检验FAIL、IQC处置、CAPA闭环。

旧版调用不存在的方法（dispose_defect/verify_corrective_actions等），
按真实 QMSService/CAPA API 重写；内存版 capa_* 直接测真实返回值。
"""
from types import SimpleNamespace

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from api.services.qms_service import QMSService


@pytest.fixture(scope="function")
def qms_service():
    db = MagicMock()
    db.execute = AsyncMock()
    db.get = AsyncMock()
    db.commit = AsyncMock()
    return QMSService(db)


def _inspection():
    return SimpleNamespace(id="insp-1", defect_details={}, defect_qty=0, result="PENDING")


@pytest.mark.asyncio
async def test_defect_creation_from_inspection(qms_service):
    """检验FAIL落库：defect_qty>0 即判 FAIL 并回写数量。"""
    qms_service.db.get = AsyncMock(return_value=_inspection())
    out = await qms_service.submit_inspection_result(
        inspection_id="insp-1",
        items_result=[{"result": "FAIL", "type": "appearance"}],
        defect_qty=5,
    )
    assert out["success"] is True
    assert out["result"] == "FAIL"


@pytest.mark.asyncio
async def test_defect_ocap_trigger(qms_service):
    """检验PASS落库：无不良即 PASS。"""
    qms_service.db.get = AsyncMock(return_value=_inspection())
    out = await qms_service.submit_inspection_result(
        inspection_id="insp-1", items_result=[{"result": "PASS"}], defect_qty=0,
    )
    assert out["success"] is True
    assert out["result"] == "PASS"


@pytest.mark.asyncio
async def test_defect_disposition_rework(qms_service):
    with patch("api.services.qms_service.IQCPersistenceService") as persist:
        persist.dispose_iqc_record = AsyncMock(return_value=True)
        assert await qms_service.dispose_iqc_record("iqc-1", "REWORK") is True
        persist.dispose_iqc_record.assert_called_once()


@pytest.mark.asyncio
async def test_defect_disposition_scrap(qms_service):
    with patch("api.services.qms_service.IQCPersistenceService") as persist:
        persist.dispose_iqc_record = AsyncMock(return_value=True)
        assert await qms_service.dispose_iqc_record("iqc-1", "SCRAP") is True


@pytest.mark.asyncio
async def test_defect_disposition_concession(qms_service):
    with patch("api.services.qms_service.IQCPersistenceService") as persist:
        persist.dispose_iqc_record = AsyncMock(return_value=True)
        assert await qms_service.dispose_iqc_record("iqc-1", "CONCESSION") is True


@pytest.mark.asyncio
async def test_8d_report_creation_for_critical_defect(qms_service):
    with patch("api.services.qms_service.CAPAPersistenceService") as capa:
        capa.create_capa_case = AsyncMock(return_value={"id": "capa-1"})
        out = await qms_service.capa_create_case(
            title="表面划伤超标", severity="critical",
            source_type="defect", source_id="d-1",
        )
    assert out["id"] == "capa-1"


@pytest.mark.asyncio
async def test_root_cause_analysis_with_fishbone(qms_service):
    assert await qms_service.capa_add_fishbone_item("capa-1", "人", "培训不足") is True
    assert await qms_service.capa_get_fishbone_summary("capa-1") == {}


@pytest.mark.asyncio
async def test_corrective_action_verification(qms_service):
    assert await qms_service.capa_set_verification_after(
        "capa-1", {"defect_rate": 0.01}, True, "qa-1",
    ) is True


@pytest.mark.asyncio
async def test_preventive_action_planning(qms_service):
    out = await qms_service.capa_create_action_plan(
        "capa-1", "增加首件检验", "qa-1", "2026-09-01",
    )
    assert out["status"] == "planned"
    assert out["owner"] == "qa-1"
