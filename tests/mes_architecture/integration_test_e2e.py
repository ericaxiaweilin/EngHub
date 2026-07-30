"""End-to-end integration test for MES Adapter with real database."""

import asyncio
import pytest
from api.services.mes_architecture.adapters.mes_adapter import MESAdapter
from api.schemas.mes_schemas import WorkOrderQueryCriteria
from database.db_config import db_config


@pytest.fixture(scope="session")
async def get_db_session():
    """Get a database session for integration tests."""
    async with db_config.session_factory() as db:
        yield db


@pytest.mark.asyncio
async def test_mesa_adapter_get_work_orders_with_real_data(get_db_session):
    """Test querying work orders from the real database."""
    from api.services.mes_architecture.repository.mes_repository import MESRepository
    from api.services.mes_architecture.formatter.response_formatter import ResponseFormatter
    from core.mes.state_machine.work_order_state_machine import WorkOrderStateMachine
    
    db = await get_db_session
    adapter = MESAdapter(
        db=db,
        current_user_id="test_user",
        repository=MESRepository(db),
        response_formatter=ResponseFormatter(),
        state_machine=WorkOrderStateMachine()
    )
    
    criteria = WorkOrderQueryCriteria(
        factory_id="F01",
        page=1,
        size=10
    )
    
    result = await adapter.get_work_orders(criteria)
    
    assert isinstance(result, dict)
    assert "items" in result
    assert "total" in result
    print(f"✅ Got {len(result['items'])} work orders for F01")


@pytest.mark.asyncio
async def test_mesa_adapter_create_production_report(get_db_session):
    """Test creating a production report via the adapter."""
    from api.services.mes_architecture.repository.mes_repository import MESRepository
    from api.services.mes_architecture.formatter.response_formatter import ResponseFormatter
    from core.mes.state_machine.work_order_state_machine import WorkOrderStateMachine
    from api.schemas.mes_schemas import ProductionReportRequest
    
    db = await get_db_session
    adapter = MESAdapter(
        db=db,
        current_user_id="test_user",
        repository=MESRepository(db),
        response_formatter=ResponseFormatter(),
        state_machine=WorkOrderStateMachine()
    )
    
    # Disable recovery strategies for this test (they'd block based on real data limits)
    adapter.recovery_strategies = []
    
    report_data = ProductionReportRequest(
        factory_id="F01",
        work_order_id="WO-20260723-476716",
        station_id="ST-ASSY-01",
        operator_id="operator_01",
        quantity=100,
        good_qty=95,
        defect_qty=5
    )
    
    result = await adapter.create_production_report(report_data)
    
    assert isinstance(result, dict)
    assert result["good_qty"] == 95
    assert result["defect_qty"] == 5
    yield_pct = result.get("yield_rate", 0)
    assert abs(yield_pct - 95.0) < 0.1, f"Expected ~95% yield, got {yield_pct}%"
    print(f"✅ Created production report: yield={yield_pct:.1f}%")