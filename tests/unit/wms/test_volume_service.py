"""WMS 体积服务单元测试。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.services.wms_volume_service import (
    WmsVolumeService,
    _calc_unit_volume_m3,
    CONTAINER_SPECS,
)


def _mock_db(rows_sequence=None):
    db = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()

    if rows_sequence is not None:
        responses = []
        for item in rows_sequence:
            result = MagicMock()
            if isinstance(item, list):
                result.mappings.return_value.all.return_value = item
            elif item is None:
                result.mappings.return_value.first.return_value = None
            else:
                result.mappings.return_value.first.return_value = item
            responses.append(result)
        db.execute.side_effect = responses
    return db


class TestVolumeHelpers:
    def test_calc_unit_volume_m3(self):
        assert _calc_unit_volume_m3(100, 50, 20) == pytest.approx(0.1)
        assert _calc_unit_volume_m3(None, 50, 20) == 0.0
        assert _calc_unit_volume_m3(0, 50, 20) == 0.0

    def test_container_specs(self):
        assert "40HQ" in CONTAINER_SPECS
        assert CONTAINER_SPECS["40HQ"]["usable_m3"] > 0


@pytest.mark.asyncio
async def test_track_volume_insert():
    db = _mock_db([
        None,  # no existing spec
        None,  # insert
        {"unit_volume_m3": 0.1, "unit_weight_kg": 2.5, "length_cm": 100, "width_cm": 50, "height_cm": 20},
    ])
    svc = WmsVolumeService(db)
    result = await svc.track_volume(
        "FAC_TEST",
        "MAT-001",
        length_cm=100,
        width_cm=50,
        height_cm=20,
        unit_weight_kg=2.5,
        quantity=10,
    )
    assert result["material_code"] == "MAT-001"
    assert result["unit_volume_m3"] == pytest.approx(0.1)
    assert result["total_volume_m3"] == pytest.approx(1.0)
    assert result["total_weight_kg"] == pytest.approx(25.0)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_track_volume_update_existing():
    db = _mock_db([
        {"id": "spec-1", "unit_volume_m3": 0.05, "unit_weight_kg": 1.0},
        None,  # update
        {"unit_volume_m3": 0.1, "unit_weight_kg": 2.0, "length_cm": 100, "width_cm": 50, "height_cm": 20},
    ])
    svc = WmsVolumeService(db)
    result = await svc.track_volume(
        "FAC_TEST",
        "MAT-002",
        length_cm=100,
        width_cm=50,
        height_cm=20,
        unit_weight_kg=2.0,
        quantity=5,
    )
    assert result["spec_id"] == "spec-1"
    assert result["inventory_qty"] == 5


@pytest.mark.asyncio
async def test_get_volume_summary():
    db = _mock_db([
        [
            {
                "material_code": "MAT-A",
                "material_name": "物料A",
                "qty": 100,
                "unit_volume_m3": 0.01,
                "unit_weight_kg": 0.5,
            },
            {
                "material_code": "MAT-B",
                "material_name": "物料B",
                "qty": 50,
                "unit_volume_m3": 0.02,
                "unit_weight_kg": 1.0,
            },
        ],
    ])
    svc = WmsVolumeService(db)
    result = await svc.get_volume_summary("FAC_TEST")
    assert result["sku_count"] == 2
    assert result["total_qty"] == 150
    assert result["total_volume_m3"] == pytest.approx(2.0)
    assert result["total_weight_kg"] == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_calculate_shipping_volume():
    db = _mock_db([
        {"unit_volume_m3": 0.5, "unit_weight_kg": 10.0, "material_name": "大箱"},
        {"unit_volume_m3": 0.1, "unit_weight_kg": 2.0, "material_name": "小盒"},
    ])
    svc = WmsVolumeService(db)
    result = await svc.calculate_shipping_volume(
        "FAC_TEST",
        [
            {"material_code": "BOX-L", "quantity": 10},
            {"material_code": "BOX-S", "quantity": 20},
        ],
        container_type="40HQ",
    )
    assert result["total_volume_m3"] == pytest.approx(7.0)
    assert result["total_weight_kg"] == pytest.approx(140.0)
    assert result["containers_needed"] >= 1
    assert len(result["lines"]) == 2


@pytest.mark.asyncio
async def test_calculate_shipping_with_inline_dimensions():
    db = _mock_db([None])
    svc = WmsVolumeService(db)
    result = await svc.calculate_shipping_volume(
        "FAC_TEST",
        [{"material_code": "MAT-X", "quantity": 100, "length_cm": 10, "width_cm": 10, "height_cm": 10}],
    )
    assert result["total_volume_m3"] == pytest.approx(0.1)
    assert result["lines"][0]["unit_volume_m3"] == pytest.approx(0.001)


@pytest.mark.asyncio
async def test_get_space_utilization():
    db = _mock_db([
        [
            {
                "id": "wh-1",
                "warehouse_code": "WH-RAW",
                "warehouse_name": "原料仓",
                "capacity_m3": 100.0,
                "location_capacity_units": 50,
            },
        ],
        [
            {
                "material_code": "MAT-A",
                "material_name": "A",
                "qty": 10,
                "unit_volume_m3": 2.0,
                "unit_weight_kg": 1.0,
            },
        ],
        [{"warehouse_id": "wh-1", "used_m3": 20.0}],
    ])
    svc = WmsVolumeService(db)
    result = await svc.get_space_utilization("FAC_TEST")
    assert result["warehouse_count"] == 1
    assert result["warehouses"][0]["utilization_pct"] == pytest.approx(20.0)
    assert result["overall_utilization_pct"] == pytest.approx(20.0)


@pytest.mark.asyncio
async def test_update_volume_delegates_to_track():
    db = _mock_db([
        None,
        None,  # insert
        {"unit_volume_m3": 0.001, "unit_weight_kg": 0.2, "length_cm": 10, "width_cm": 10, "height_cm": 10},
    ])
    svc = WmsVolumeService(db)
    result = await svc.update_volume(
        "FAC_TEST",
        "MAT-U",
        length_cm=10,
        width_cm=10,
        height_cm=10,
        unit_weight_kg=0.2,
    )
    assert result["material_code"] == "MAT-U"
    assert result["inventory_qty"] == 0
