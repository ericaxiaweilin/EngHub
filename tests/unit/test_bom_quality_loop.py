"""例行自检这一步的合约：只读、有范围、心跳里放得下。"""

from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.unit]

from api.services import bom_data_quality as dq


def _row(code, name, **kw):
    return {"material_code": code, "material_name": name, "unit": kw.get("unit", "PCS"),
            "level": kw.get("level", 2), "qty_per_unit": kw.get("qty", 1),
            "unit_price": kw.get("price"), "component_type": kw.get("ctype", "structural_part"),
            "material_family": kw.get("family", "mechanical"),
            "source_file": "a.xlsx", "original_row_number": kw.get("n", 1), "vendor_name": None}


@pytest.mark.asyncio
async def test_scan_plant_reports_the_finding_that_blocks_the_most_shortage():
    rows = [_row("100001", "100001"), _row("板", "板", ctype=None, n=2)]
    calls = []

    async def execute(statement, params=None):
        sql = str(statement)
        calls.append(sql)
        r = MagicMock()
        if "ORDER BY gap DESC" in sql or "ORDER BY lines DESC" in sql:
            r.mappings.return_value.all.return_value = [{"product_model": "M-1", "lines": 2}]
        elif "FROM enghub_bom_items" in sql:
            r.mappings.return_value.all.return_value = rows
        else:
            r.mappings.return_value.all.return_value = []
        r.mappings.return_value.first.return_value = None
        return r

    db = MagicMock()
    db.execute = execute
    out = await dq.scan_plant(db, "FAC_MECH_001", limit=2)
    assert out["models_scanned"] == 1
    assert out["worst_finding"]["product_model"] == "M-1"
    assert out["worst_finding"]["rule"] in ("name_equals_code", "generic_name", "missing_classification")
    assert not any("INSERT" in c or "UPDATE" in c for c in calls), "例行自检必须只读"


@pytest.mark.asyncio
async def test_scan_plant_without_bom_rows_says_no_data_instead_of_zero_findings():
    async def execute(statement, params=None):
        r = MagicMock()
        r.mappings.return_value.all.return_value = []
        r.mappings.return_value.first.return_value = None
        return r

    db = MagicMock()
    db.execute = execute
    out = await dq.scan_plant(db, "FAC_NOBODY", limit=2)
    assert out["models_scanned"] == 0 and out["worst_finding"] is None
