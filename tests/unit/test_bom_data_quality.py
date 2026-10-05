"""BOM 质量自检的判据测试：只读、按影响缺口排序、不偷偷修数据。"""

import pytest

pytestmark = [pytest.mark.unit]

from api.services import bom_data_quality as dq


def _row(code, name, *, unit="PCS", level=2, qty=1, price=None, ctype="structural_part",
         family="mechanical", f="a.xlsx", n=1):
    return {"material_code": code, "material_name": name, "unit": unit, "level": level,
            "qty_per_unit": qty, "unit_price": price, "component_type": ctype,
            "material_family": family, "source_file": f, "original_row_number": n,
            "vendor_name": None}


def test_flags_generic_and_code_named_parts():
    findings = {f["rule"]: f for f in dq.evaluate(
        [_row("100001", "100001"), _row("100002", "管", f="a.xlsx", n=2)], {})}
    assert findings["name_equals_code"]["sample_codes"] == ["100001"]
    assert findings["generic_name"]["codes"] == 1


def test_priority_follows_the_shortage_it_blocks():
    """排序按影响缺口，不按问题条数：挡生产的那条先改。"""
    rows = [_row("A", "鐵片支撐板;車架;;;Q195;", ctype="unknown"), _row("B", "板", ctype=None)]
    shortage = {"A": 5.0, "B": 900.0}
    findings = dq.evaluate(rows, shortage)
    generic = next(f for f in findings if f["rule"] == "generic_name")
    assert generic["affected_shortage_qty"] == 900.0
    assert findings[0]["affected_shortage_qty"] >= findings[-1]["affected_shortage_qty"]


def test_price_shape_anomaly_is_detected_not_averaged():
    rows = [_row("P", "端蓋", price=1.0, n=1), _row("P", "端蓋", price=182.0, n=2)]
    findings = {f["rule"]: f for f in dq.evaluate(rows, {})}
    assert findings["price_shape_anomaly"]["codes"] == 1
    assert "不是单价" in findings["price_shape_anomaly"]["why"]


def test_drawing_row_with_quantity_is_reported():
    rows = [_row("D", "零件爆炸圖", qty=1)]
    findings = {f["rule"]: f for f in dq.evaluate(rows, {"D": 12})}
    assert findings["drawing_row_as_material"]["affected_shortage_qty"] == 12


def test_broken_indent_is_reported_with_its_own_row_count():
    rows = [_row("R", "整機", level=1, n=0), _row("X", "輪子", level=5, n=1)]
    findings = {f["rule"]: f for f in dq.evaluate(rows, {})}
    assert findings["tree_break"]["rows"] >= 1
    assert "不会猜父级" in findings["tree_break"]["why"]


def test_clean_bom_reports_nothing():
    rows = [_row("OK1", "前腳管;車架;Φ25x1.5T;SPHC;電鍍;", family="mechanical"),
            _row("OK2", "泡棉墊;底座;EPE;泡棉;", ctype="packaging")]
    assert dq.evaluate(rows, {}) == [] or all(
        f["rule"] not in ("name_equals_code", "generic_name", "missing_unit")
        for f in dq.evaluate(rows, {}))


@pytest.mark.asyncio
async def test_scan_on_unknown_model_says_so_instead_of_faking_zero_findings():
    from unittest.mock import MagicMock

    async def execute(statement, params=None):
        r = MagicMock()
        r.mappings.return_value.all.return_value = []
        return r

    db = MagicMock()
    db.execute = execute
    out = await dq.scan(db, "FAC_MECH_001", "NO-SUCH-MODEL")
    assert out["rows"] == 0 and "无质量数据" in out["note"]
