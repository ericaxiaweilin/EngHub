"""设备 OEE 口径回归：UUID 站位折 code；同工位多机计划分钟按台累加、应有产出不重复算。"""

from datetime import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit]

from api.services.equipment_service import EquipmentTpmService


class _Model:
    def __init__(self, pieces):
        self.daily_pieces = pieces
        self.calendar_source = "aps_work_calendars"

    def slots_on(self, day):
        return [(time(8, 0), time(20, 0))]


def _oee_db(machines):
    db = MagicMock()

    def _exec(statement, *args, **kwargs):
        s = str(statement)
        res = MagicMock()
        if "FROM stations" in s:
            res.mappings.return_value.all.return_value = [
                {"id": "UUID-1", "station_code": "ST-A"},
                {"id": "UUID-2", "station_code": "ST-A"},
            ]
        elif "equipment_downtime" in s:
            res.scalar.return_value = 0
        elif "production_reports" in s:
            res.fetchone.return_value = (35, 0)
        else:  # equipment 台账
            res.scalars.return_value.all.return_value = list(machines)
        return res

    db.execute = AsyncMock(side_effect=_exec)
    return db


def _patch_load(seen):
    async def _fake(db, factory_id, station_ids, start, end):
        seen.extend(station_ids)
        return {"ST-A": _Model(10)} if "ST-A" in station_ids else {}

    return patch("core.mes.capacity_math.load_station_models", _fake)


def _machine(uuid):
    return SimpleNamespace(station_id=uuid, equipment_code="EQ-" + uuid[-1], id="ID-" + uuid)


@pytest.mark.asyncio
async def test_uuid_station_id_resolves_to_code_capacity():
    seen = []
    db = _oee_db([_machine("UUID-1")])
    with _patch_load(seen):
        out = await EquipmentTpmService(db).calculate_oee("FAC1", days=7)
    assert seen == ["ST-A"]
    assert out["expected_pieces"] == 70.0
    assert out["oee_basis"]["unconfigured_daily_pieces_stations"] == []
    assert out["performance"] == 50.0
    assert out["availability"] == 100.0
    assert out["oee"] == 50.0


@pytest.mark.asyncio
async def test_two_machines_share_station_capacity_once():
    seen = []
    db = _oee_db([_machine("UUID-1"), _machine("UUID-2")])
    with _patch_load(seen):
        out = await EquipmentTpmService(db).calculate_oee("FAC1", days=7)
    assert out["planned_minutes"] == 10080.0
    assert out["expected_pieces"] == 70.0
