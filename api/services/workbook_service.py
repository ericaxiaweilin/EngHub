"""XLSX <-> Univer workbook snapshot bridge.

The browser editor uses Univer's workbook JSON.  This service keeps the raw
workbook snapshot as JSON and converts it to/from XLSX without collapsing
formulas into their calculated values.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from openpyxl import Workbook, load_workbook
from openpyxl.cell.cell import TYPE_ERROR
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.styles.numbers import is_date_format
from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.utils.cell import coordinate_from_string
import re


MAX_SHEETS = 50
MAX_ROWS = 5000
MAX_COLS = 200


def _safe_text(value: Any) -> str:
    return "" if value is None else str(value)


def _cell_to_univer(cell) -> Dict[str, Any]:
    item: Dict[str, Any] = {}
    if cell.value is not None:
        if isinstance(cell.value, str) and cell.value.startswith("="):
            item["f"] = cell.value
            item["v"] = ""
        elif cell.data_type == TYPE_ERROR:
            item["v"] = str(cell.value)
        elif cell.is_date and hasattr(cell.value, "isoformat"):
            # JSONB cannot bind Python date/datetime objects.  Keep the ISO
            # value and the original number format so Excel/Univer still
            # display it as a date after import/export.
            item["v"] = cell.value.isoformat()
        else:
            item["v"] = cell.value
    if cell.number_format and cell.number_format != "General":
        item["s"] = {"n": {"pattern": cell.number_format}}
    if cell.font and (cell.font.bold or cell.font.italic or cell.font.color):
        style: Dict[str, Any] = {}
        if cell.font.bold:
            style["bl"] = 1
        if cell.font.italic:
            style["it"] = 1
        if cell.font.color and cell.font.color.type == "rgb":
            style["cl"] = {"rgb": cell.font.color.rgb[-6:]}
        if style:
            item["s"] = {**item.get("s", {}), **style}
    if cell.fill and cell.fill.fill_type == "solid" and cell.fill.fgColor.type == "rgb":
        item["s"] = {**item.get("s", {}), "bg": {"rgb": cell.fill.fgColor.rgb[-6:]}}
    return item


def _sheet_to_univer(ws) -> Dict[str, Any]:
    max_row = min(max(ws.max_row or 1, 1), MAX_ROWS)
    max_col = min(max(ws.max_column or 1, 1), MAX_COLS)
    cell_data: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for row in ws.iter_rows(min_row=1, max_row=max_row, min_col=1, max_col=max_col):
        row_data: Dict[str, Dict[str, Any]] = {}
        for cell in row:
            item = _cell_to_univer(cell)
            if item:
                row_data[str(cell.column - 1)] = item
        if row_data:
            cell_data[str(row[0].row - 1)] = row_data
    freeze = ws.freeze_panes
    if freeze:
        if isinstance(freeze, str):
            freeze_col, freeze_row = coordinate_from_string(freeze)
            freeze_x, freeze_y = column_index_from_string(freeze_col) - 1, int(freeze_row) - 1
        else:
            freeze_x, freeze_y = freeze.column - 1, freeze.row - 1
    else:
        freeze_x = freeze_y = 0
    return {
        "id": f"sheet-{abs(hash(ws.title)) % 10**10}",
        "name": ws.title[:31] or "Sheet1",
        "rowCount": max(max_row + 50, 100),
        "columnCount": max(max_col + 5, 20),
        "cellData": cell_data,
        "rowData": {str(i): {"h": float(ws.row_dimensions[i + 1].height)} for i in range(max_row) if ws.row_dimensions[i + 1].height},
        "columnData": {str(i): {"w": float(ws.column_dimensions[get_column_letter(i + 1)].width)} for i in range(max_col) if ws.column_dimensions[get_column_letter(i + 1)].width},
        "freeze": {"xSplit": freeze_x, "ySplit": freeze_y} if freeze else None,
    }


def xlsx_to_workbook_snapshot(path: Path) -> Dict[str, Any]:
    """Read all worksheets and preserve formulas, basic styles, dimensions and freezes."""
    wb = load_workbook(path, read_only=False, data_only=False, keep_vba=path.suffix.lower() == ".xlsm")
    try:
        sheets = [_sheet_to_univer(ws) for ws in wb.worksheets[:MAX_SHEETS]]
        return {
            "id": "workbook-import",
            "name": path.stem,
            "sheetOrder": [sheet["id"] for sheet in sheets],
            "sheets": {sheet["id"]: sheet for sheet in sheets},
            "locale": "zhCN",
            "source": {"filename": path.name, "format": path.suffix.lower().lstrip(".")},
        }
    finally:
        wb.close()


def _snapshot_sheets(snapshot: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    order = snapshot.get("sheetOrder") or list((snapshot.get("sheets") or {}).keys())
    sheets = snapshot.get("sheets") or {}
    for sheet_id in order[:MAX_SHEETS]:
        sheet = sheets.get(sheet_id)
        if sheet:
            yield sheet


def _rgb(value: Any) -> Optional[str]:
    if not isinstance(value, dict):
        return None
    color = value.get("rgb")
    if not color:
        return None
    color = str(color).replace("#", "")
    return color[-6:].upper() if len(color) >= 6 else None


def _apply_style(cell, style: Any) -> None:
    if not isinstance(style, dict):
        return
    cell.font = Font(
        name=style.get("ff") or "Calibri",
        sz=style.get("fs") or 11,
        bold=bool(style.get("bl")),
        italic=bool(style.get("it")),
        color=_rgb(style.get("cl")),
    )
    bg = _rgb(style.get("bg"))
    if bg:
        cell.fill = PatternFill("solid", fgColor=bg)
    number = style.get("n")
    if isinstance(number, dict) and number.get("pattern"):
        cell.number_format = str(number["pattern"])


def _write_snapshot_sheet(ws, sheet: Dict[str, Any]) -> None:
    cell_data = sheet.get("cellData") or {}
    for row_key, row in list(cell_data.items())[:MAX_ROWS]:
        try:
            row_idx = int(row_key) + 1
        except (TypeError, ValueError):
            continue
        if not isinstance(row, dict):
            continue
        for col_key, item in list(row.items())[:MAX_COLS]:
            try:
                col_idx = int(col_key) + 1
            except (TypeError, ValueError):
                continue
            if not isinstance(item, dict):
                continue
            cell = ws.cell(row=row_idx, column=col_idx)
            formula = item.get("f")
            value = item.get("v")
            if formula:
                cell.value = formula
            elif value not in (None, ""):
                number_format = ((item.get("s") or {}).get("n") or {}).get("pattern")
                if isinstance(value, str) and number_format and is_date_format(str(number_format)):
                    try:
                        value = datetime.fromisoformat(value) if "T" in value else date.fromisoformat(value)
                    except ValueError:
                        pass
                cell.value = value
            _apply_style(cell, item.get("s"))
    for key, meta in (sheet.get("rowData") or {}).items():
        if isinstance(meta, dict) and meta.get("h"):
            ws.row_dimensions[int(key) + 1].height = float(meta["h"])
    for key, meta in (sheet.get("columnData") or {}).items():
        if isinstance(meta, dict) and meta.get("w"):
            ws.column_dimensions[get_column_letter(int(key) + 1)].width = float(meta["w"])
    freeze = sheet.get("freeze")
    if isinstance(freeze, dict) and (freeze.get("xSplit") or freeze.get("ySplit")):
        ws.freeze_panes = ws.cell(row=int(freeze.get("ySplit", 0)) + 1, column=int(freeze.get("xSplit", 0)) + 1)


def workbook_snapshot_to_xlsx(snapshot: Dict[str, Any], output: Path) -> None:
    """Export a Univer snapshot to XLSX, preserving formulas as formulas."""
    wb = Workbook()
    # Univer stores the formula text but does not provide Excel's cached
    # calculation result.  Tell Excel/LibreOffice to recalculate on open so
    # exported MRP/DOH/负荷 formulas do not appear stale.
    wb.calculation.fullCalcOnLoad = True
    wb.calculation.forceFullCalc = True
    wb.calculation.calcMode = "auto"
    first = True
    for sheet in _snapshot_sheets(snapshot):
        name = _safe_text(sheet.get("name") or "Sheet1")[:31] or "Sheet1"
        ws = wb.active if first else wb.create_sheet()
        first = False
        ws.title = name
        _write_snapshot_sheet(ws, sheet)
    if first:
        wb.active.title = "Sheet1"
    wb.save(output)


def snapshot_json(snapshot: Dict[str, Any]) -> str:
    return json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), default=str)


def parse_snapshot(raw: str) -> Dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict) or not isinstance(value.get("sheets"), dict):
        raise ValueError("工作簿快照格式无效")
    return value


_CELL_RE = re.compile(r"^([A-Za-z]{1,3})([1-9][0-9]*)$")


def _cell_coordinate(value: str) -> tuple[int, int]:
    match = _CELL_RE.match(str(value or "").strip())
    if not match:
        raise ValueError(f"单元格地址无效: {value}")
    return int(match.group(2)) - 1, column_index_from_string(match.group(1).upper()) - 1


def _find_sheet(snapshot: Dict[str, Any], sheet_ref: Optional[str]) -> Dict[str, Any]:
    sheets = snapshot.get("sheets") or {}
    for sheet in _snapshot_sheets(snapshot):
        if not sheet_ref or sheet.get("id") == sheet_ref or sheet.get("name") == sheet_ref:
            return sheet
    raise ValueError(f"工作表不存在: {sheet_ref}")


def _set_snapshot_cell(sheet: Dict[str, Any], cell_ref: str, value: Any = None, formula: Optional[str] = None) -> None:
    row, col = _cell_coordinate(cell_ref)
    if row >= MAX_ROWS or col >= MAX_COLS:
        raise ValueError(f"单元格超出允许范围: {cell_ref}")
    cell_data = sheet.setdefault("cellData", {})
    row_data = cell_data.setdefault(str(row), {})
    if value in (None, "") and not formula:
        row_data.pop(str(col), None)
        return
    inferred_formula = formula
    if not inferred_formula and isinstance(value, str) and value.startswith("="):
        inferred_formula = value
        value = ""
    item: Dict[str, Any] = {"v": "" if inferred_formula else value}
    if inferred_formula:
        item["f"] = inferred_formula if str(inferred_formula).startswith("=") else f"={inferred_formula}"
    row_data[str(col)] = item


def apply_workbook_operations(
    snapshot: Dict[str, Any], operations: List[Dict[str, Any]],
) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Apply explicit cell edits used by the chatbot and return an audit list."""
    changed: List[Dict[str, Any]] = []
    for operation in operations[:500]:
        kind = str(operation.get("type") or operation.get("op") or "").lower()
        sheet = _find_sheet(snapshot, operation.get("sheet") or operation.get("sheet_name"))
        sheet_name = sheet.get("name") or sheet.get("id")
        if kind in {"set_cell", "set_value", "set_formula", "clear_cell"}:
            cell = str(operation.get("cell") or "")
            formula = operation.get("formula") if kind in {"set_formula"} or operation.get("formula") else None
            value = operation.get("value") if kind not in {"clear_cell", "set_formula"} else None
            if kind == "clear_cell":
                value = None
                formula = None
            audit_formula = formula or (value if isinstance(value, str) and value.startswith("=") else None)
            _set_snapshot_cell(sheet, cell, value=value, formula=formula)
            changed.append({"sheet": sheet_name, "cell": cell, "type": kind, "formula": audit_formula, "value": value})
        elif kind == "append_rows":
            rows = operation.get("rows") or []
            start_row = int(operation.get("start_row") or 0)
            existing = sheet.setdefault("cellData", {})
            if not start_row:
                start_row = max([int(key) for key in existing.keys() if str(key).isdigit()] or [-1]) + 1
            for row_offset, values in enumerate(rows[:MAX_ROWS]):
                for col, value in enumerate((values or [])[:MAX_COLS]):
                    _set_snapshot_cell(sheet, f"{get_column_letter(col + 1)}{start_row + row_offset + 1}", value=value)
            changed.append({"sheet": sheet_name, "type": kind, "rows": min(len(rows), MAX_ROWS), "start_row": start_row + 1})
        elif kind == "flash_fill":
            changed.append(_apply_flash_fill(sheet, operation))
        else:
            raise ValueError(f"不支持的表格操作: {kind}")
    return snapshot, changed


def snapshot_to_table(snapshot: Dict[str, Any], sheet_ref: Optional[str] = None, max_rows: int = 100, max_cols: int = 50) -> Dict[str, Any]:
    """Create a bounded table view for chatbot grounding."""
    sheet = _find_sheet(snapshot, sheet_ref)
    cell_data = sheet.get("cellData") or {}
    rows: List[List[Any]] = []
    row_keys = sorted((key for key in cell_data if str(key).isdigit()), key=lambda key: int(key))[:max_rows]
    max_seen_col = max(
        (int(col_key) for row_key in row_keys for col_key in (cell_data.get(row_key) or {}) if str(col_key).isdigit()),
        default=0,
    )
    for row_key in row_keys:
        row = cell_data.get(row_key) or {}
        values: List[Any] = []
        for col in range(min(max_seen_col + 1, max_cols)):
            item = row.get(str(col)) or {}
            values.append(item.get("v", "") if not item.get("f") else item.get("f"))
        rows.append(values)
    headers = rows[0] if rows else []
    table_rows = [
        {f"c{i}": value for i, value in enumerate(row)}
        for row in rows[1:]
    ]
    return {
        "title": sheet.get("name") or "在线工作表",
        "sheet_name": sheet.get("name"),
        "workbook_id": snapshot.get("id"),
        "columns": [{"key": f"c{i}", "label": _safe_text(value) or f"列{i + 1}"} for i, value in enumerate(headers)],
        "rows": table_rows,
        "row_count": max(0, len(rows) - 1),
        "formula_cells": sum(1 for row in cell_data.values() for item in (row or {}).values() if isinstance(item, dict) and item.get("f")),
    }


def _snapshot_cell_value(sheet: Dict[str, Any], row: int, col: int) -> Any:
    item = ((sheet.get("cellData") or {}).get(str(row)) or {}).get(str(col)) or {}
    if item.get("f"):
        return None
    return item.get("v")


_FLASH_TOKEN_RE = re.compile(r"[A-Za-z]+|[0-9]+|[\u4e00-\u9fff]+")


def _flash_tokens(value: Any) -> List[str]:
    return _FLASH_TOKEN_RE.findall(str(value or ""))


def _infer_flash_token(source: Any, target: Any) -> Optional[int]:
    target_text = str(target or "").strip()
    if not target_text:
        return None
    tokens = _flash_tokens(source)
    for index, token in enumerate(tokens):
        if token == target_text:
            return index
    return None


def _apply_flash_fill(sheet: Dict[str, Any], operation: Dict[str, Any]) -> Dict[str, Any]:
    """Implement the common Ctrl+E pattern: extract the same token from a column."""
    source_col = str(operation.get("source_column") or "").strip().upper()
    target_col = str(operation.get("target_column") or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{1,3}", source_col) or not re.fullmatch(r"[A-Z]{1,3}", target_col):
        raise ValueError("快速填充需要合法的源列和目标列，例如 A、B")
    source_index = column_index_from_string(source_col) - 1
    target_index = column_index_from_string(target_col) - 1
    start_row = max(int(operation.get("start_row") or 2), 1)
    cell_data = sheet.setdefault("cellData", {})
    max_source_row = max([int(key) for key in cell_data if str(key).isdigit()] or [start_row - 1]) + 1
    end_row = min(int(operation.get("end_row") or max_source_row), MAX_ROWS)
    samples: List[tuple[Any, Any]] = []
    for excel_row in range(start_row, end_row + 1):
        row = excel_row - 1
        source = _snapshot_cell_value(sheet, row, source_index)
        target = _snapshot_cell_value(sheet, row, target_index)
        if source not in (None, "") and target not in (None, ""):
            samples.append((source, target))
        if len(samples) >= 2:
            break
    if not samples:
        raise ValueError("请先在目标列至少填写一行示例，例如从 A1001-2024-01 填出 2024")
    token_indexes = [_infer_flash_token(source, target) for source, target in samples]
    if any(index is None for index in token_indexes) or len(set(token_indexes)) != 1:
        raise ValueError("无法识别统一填充规律，请让目标列示例对应源列的同一段文本")
    token_index = token_indexes[0]
    overwrite = bool(operation.get("overwrite"))
    filled = 0
    for excel_row in range(start_row, end_row + 1):
        row = excel_row - 1
        source = _snapshot_cell_value(sheet, row, source_index)
        current = _snapshot_cell_value(sheet, row, target_index)
        if source in (None, "") or (current not in (None, "") and not overwrite):
            continue
        tokens = _flash_tokens(source)
        if token_index is None or token_index >= len(tokens):
            continue
        _set_snapshot_cell(sheet, f"{target_col}{excel_row}", value=tokens[token_index])
        filled += 1
    return {
        "sheet": sheet.get("name") or sheet.get("id"),
        "type": "flash_fill",
        "source_column": source_col,
        "target_column": target_col,
        "start_row": start_row,
        "end_row": end_row,
        "filled": filled,
        "token_index": token_index,
    }


def _snapshot_matrix(sheet: Dict[str, Any], max_rows: int = MAX_ROWS, max_cols: int = MAX_COLS) -> List[List[Any]]:
    cell_data = sheet.get("cellData") or {}
    rows: List[List[Any]] = []
    row_keys = sorted((key for key in cell_data if str(key).isdigit()), key=lambda key: int(key))[:max_rows]
    max_col = min(
        max((int(col) for row_key in row_keys for col in (cell_data.get(row_key) or {}) if str(col).isdigit()), default=0),
        max_cols - 1,
    )
    for row_key in row_keys:
        row = cell_data.get(row_key) or {}
        rows.append([_snapshot_cell_value(sheet, int(row_key), col) for col in range(max_col + 1)])
    return rows


def build_pivot_summary(
    snapshot: Dict[str, Any],
    sheet_ref: Optional[str],
    row_field: str,
    value_field: str,
    aggregation: str = "sum",
    output_sheet_name: str = "透视汇总",
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Create a persisted, refreshable-style summary sheet from tabular data."""
    source = _find_sheet(snapshot, sheet_ref)
    matrix = _snapshot_matrix(source, max_rows=MAX_ROWS, max_cols=MAX_COLS)
    if not matrix:
        raise ValueError("源工作表没有可透视的数据")
    headers = [str(value or "") for value in matrix[0]]

    def resolve_field(field: str) -> int:
        value = str(field or "").strip()
        if value.isdigit() and 0 <= int(value) < len(headers):
            return int(value)
        if value in headers:
            return headers.index(value)
        raise ValueError(f"透视字段不存在: {value}")

    row_index = resolve_field(row_field)
    value_index = resolve_field(value_field)
    aggregation = str(aggregation or "sum").lower()
    if aggregation not in {"sum", "count", "avg"}:
        raise ValueError("透视汇总仅支持 sum、count、avg")
    grouped: Dict[str, List[float]] = {}
    for values in matrix[1:]:
        key = str(values[row_index] if row_index < len(values) and values[row_index] not in (None, "") else "(空白)")
        raw = values[value_index] if value_index < len(values) else None
        if aggregation == "count":
            grouped.setdefault(key, []).append(1.0)
            continue
        try:
            number = float(str(raw).replace(",", "")) if raw not in (None, "") else 0.0
        except (TypeError, ValueError):
            continue
        grouped.setdefault(key, []).append(number)
    if not grouped:
        raise ValueError("没有可汇总的数值行")
    summary_rows: List[List[Any]] = []
    for key in sorted(grouped):
        numbers = grouped[key]
        result = len(numbers) if aggregation == "count" else sum(numbers) if aggregation == "sum" else sum(numbers) / len(numbers)
        summary_rows.append([key, int(result) if float(result).is_integer() else round(result, 4)])

    output_name = (str(output_sheet_name or "透视汇总").strip() or "透视汇总")[:31]
    output_id = f"pivot-{abs(hash((source.get('id'), output_name))) % 10**10}"
    existing_sheets = snapshot.setdefault("sheets", {})
    order = snapshot.setdefault("sheetOrder", list(existing_sheets.keys()))
    for sheet_id, existing in list(existing_sheets.items()):
        if existing.get("name") == output_name or sheet_id == output_id:
            existing_sheets.pop(sheet_id, None)
            if sheet_id in order:
                order.remove(sheet_id)
    pivot_sheet = _template_sheet(output_id, output_name, [headers[row_index], f"{aggregation.upper()}({headers[value_index]})"])
    for row_offset, values in enumerate(summary_rows, start=1):
        pivot_sheet["cellData"][str(row_offset)] = {
            "0": {"v": values[0]},
            "1": {"v": values[1]},
        }
    existing_sheets[output_id] = pivot_sheet
    order.append(output_id)
    return snapshot, {
        "source_sheet": source.get("name"),
        "output_sheet": output_name,
        "row_field": headers[row_index],
        "value_field": headers[value_index],
        "aggregation": aggregation,
        "groups": len(summary_rows),
    }


def _template_cell(row: Dict[str, Dict[str, Any]], col: int, value: Any = "", formula: Optional[str] = None, style: Optional[Dict[str, Any]] = None) -> None:
    item: Dict[str, Any] = {"v": "" if formula else value}
    if formula:
        item["f"] = formula
    if style:
        item["s"] = style
    row[str(col)] = item


def _template_sheet(sheet_id: str, name: str, headers: List[str], formula_rows: Optional[Dict[int, Dict[int, str]]] = None) -> Dict[str, Any]:
    header_style = {"bl": 1, "bg": {"rgb": "D9EAF7"}}
    cell_data: Dict[str, Dict[str, Any]] = {"0": {}}
    for col, header in enumerate(headers):
        _template_cell(cell_data["0"], col, header, style=header_style)
    for row_idx, formulas in (formula_rows or {}).items():
        row: Dict[str, Any] = {}
        for col, formula in formulas.items():
            _template_cell(row, col, formula=formula)
        cell_data[str(row_idx)] = row
    return {
        "id": sheet_id,
        "name": name,
        "rowCount": max(100, max((int(row) for row in cell_data), default=0) + 50),
        "columnCount": max(10, len(headers) + 3),
        "cellData": cell_data,
        "freeze": {"xSplit": 0, "ySplit": 1},
    }


def build_pmc_workbook_template() -> Dict[str, Any]:
    """Build a formula-ready PMC workbook for first-use and external-data paste-in."""
    mrp_formulas: Dict[int, Dict[int, str]] = {}
    inventory_formulas: Dict[int, Dict[int, str]] = {}
    capacity_formulas: Dict[int, Dict[int, str]] = {}
    for row in range(1, 201):  # zero-based Univer row; Excel row is row + 1
        excel_row = row + 1
        mrp_formulas[row] = {
            1: f'=IF(A{excel_row}="","",IFERROR(INDEX(\'BOM\'!$C$2:$C$501,MATCH(A{excel_row},\'BOM\'!$B$2:$B$501,0)),""))',
            2: f'=IF(A{excel_row}="","",SUMPRODUCT((\'BOM\'!$B$2:$B$501=A{excel_row})*\'BOM\'!$D$2:$D$501*SUMIF(\'订单池\'!$B$2:$B$501,\'BOM\'!$A$2:$A$501,\'订单池\'!$C$2:$C$501)))',
            3: f'=IF(A{excel_row}="","",SUMIF(\'库存\'!$A$2:$A$501,A{excel_row},\'库存\'!$C$2:$C$501))',
            4: f'=IF(A{excel_row}="","",SUMIF(\'库存\'!$A$2:$A$501,A{excel_row},\'库存\'!$D$2:$D$501))',
            5: f'=IF(A{excel_row}="","",MAX(C{excel_row}+E{excel_row}-D{excel_row},0))',
            6: f'=IF(A{excel_row}="","",F{excel_row})',
            7: f'=IF(A{excel_row}="","",IF(F{excel_row}>0,"欠料","齐套"))',
        }
        inventory_formulas[row] = {5: f'=IFERROR(C{excel_row}/E{excel_row},0)'}
        capacity_formulas[row] = {
            4: f'=IFERROR(C{excel_row}/D{excel_row},0)',
            5: f'=IF(A{excel_row}="","",IF(E{excel_row}>1,"超负荷","正常"))',
        }

    practice = _template_sheet(
        "pmc-practice",
        "公式练习",
        ["料号", "名称(VLOOKUP)", "库存(XLOOKUP)", "供应商", "未到货欠料(SUMIFS)"],
    )
    practice["cellData"].update({
        "1": {
            "0": {"v": "MAT-001"},
            "1": {"f": '=VLOOKUP(A2,\'物料库\'!$A$2:$C$4,2,FALSE)', "v": ""},
            "2": {"f": '=XLOOKUP(A2,\'物料库\'!$A$2:$A$4,\'物料库\'!$C$2:$C$4,"未找到")', "v": ""},
            "3": {"v": "供应商A"},
            "4": {"f": '=SUMIFS(\'采购明细\'!$D$2:$D$5,\'采购明细\'!$B$2:$B$5,D2,\'采购明细\'!$C$2:$C$5,"未到货")', "v": ""},
        },
        "2": {
            "0": {"v": "MAT-002"},
            "1": {"f": '=VLOOKUP(A3,\'物料库\'!$A$2:$C$4,2,FALSE)', "v": ""},
            "2": {"f": '=XLOOKUP(A3,\'物料库\'!$A$2:$A$4,\'物料库\'!$C$2:$C$4,"未找到")', "v": ""},
            "3": {"v": "供应商B"},
            "4": {"f": '=SUMIFS(\'采购明细\'!$D$2:$D$5,\'采购明细\'!$B$2:$B$5,D3,\'采购明细\'!$C$2:$C$5,"未到货")', "v": ""},
        },
    })
    materials = _template_sheet("pmc-materials", "物料库", ["料号", "物料名称", "可用库存"])
    materials["cellData"].update({
        "1": {"0": {"v": "MAT-001"}, "1": {"v": "铝壳"}, "2": {"v": 120}},
        "2": {"0": {"v": "MAT-002"}, "1": {"v": "铜柱"}, "2": {"v": 80}},
        "3": {"0": {"v": "MAT-003"}, "1": {"v": "螺丝"}, "2": {"v": 500}},
    })
    purchases = _template_sheet("pmc-purchases", "采购明细", ["采购单号", "供应商", "状态", "欠料数量"])
    purchases["cellData"].update({
        "1": {"0": {"v": "PO-001"}, "1": {"v": "供应商A"}, "2": {"v": "未到货"}, "3": {"v": 50}},
        "2": {"0": {"v": "PO-002"}, "1": {"v": "供应商A"}, "2": {"v": "已到货"}, "3": {"v": 30}},
        "3": {"0": {"v": "PO-003"}, "1": {"v": "供应商B"}, "2": {"v": "未到货"}, "3": {"v": 70}},
        "4": {"0": {"v": "PO-004"}, "1": {"v": "供应商B"}, "2": {"v": "未到货"}, "3": {"v": 20}},
    })

    sheets = [
        _template_sheet("pmc-bom", "BOM", ["产品编码", "物料编码", "物料名称", "单位用量", "单位"]),
        _template_sheet("pmc-orders", "订单池", ["计划号", "产品编码", "计划数量", "需求日期", "状态"]),
        _template_sheet("pmc-inventory", "库存", ["物料编码", "物料名称", "可用库存", "安全库存", "日均需求", "DOH"], inventory_formulas),
        _template_sheet("pmc-mrp", "MRP", ["物料编码", "物料名称", "毛需求", "可用库存", "安全库存", "净需求", "建议采购量", "状态"], mrp_formulas),
        _template_sheet("pmc-capacity", "产能负荷", ["日期", "工作中心", "计划工时", "可用工时", "负荷率", "预警"], capacity_formulas),
        practice,
        materials,
        purchases,
    ]
    return {
        "id": "pmc-template",
        "name": "PMC物料动态计算模板",
        "sheetOrder": [sheet["id"] for sheet in sheets],
        "sheets": {sheet["id"]: sheet for sheet in sheets},
        "locale": "zhCN",
        "source": {"filename": "PMC物料动态计算模板", "format": "template"},
    }
