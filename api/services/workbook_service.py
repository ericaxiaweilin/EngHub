"""XLSX <-> Univer workbook snapshot bridge.

The browser editor uses Univer's workbook JSON.  This service keeps the raw
workbook snapshot as JSON and converts it to/from XLSX without collapsing
formulas into their calculated values.
"""

from __future__ import annotations

import json
import ast
import os
import shutil
import subprocess
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from openpyxl import Workbook, load_workbook
from openpyxl.cell.cell import TYPE_ERROR
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.styles.numbers import is_date_format
from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.utils.cell import coordinate_from_string
from openpyxl.workbook.properties import CalcProperties
import re


# These are Excel's worksheet limits.  The old 5,000 x 200 bridge silently
# dropped formulas/data outside that rectangle, which made an uploaded
# workbook impossible to round-trip faithfully.
MAX_SHEETS = 255
MAX_ROWS = 1_048_576
MAX_COLS = 16_384


def _safe_text(value: Any) -> str:
    return "" if value is None else str(value)


def _cell_to_univer(cell, cached_cell=None) -> Dict[str, Any]:
    item: Dict[str, Any] = {}
    if cell.value is not None:
        if isinstance(cell.value, str) and cell.value.startswith("="):
            item["f"] = cell.value
            # ``data_only=False`` is required to preserve the formula text,
            # while Excel's cached result lives in a separate data-only view.
            # Keep both so the chatbot can explain the formula and its last
            # calculated value without flattening the workbook.
            cached_value = cached_cell.value if cached_cell is not None else None
            if cached_value is not None and hasattr(cached_value, "isoformat"):
                cached_value = cached_value.isoformat()
            item["v"] = cached_value if cached_value is not None else ""
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


def _sheet_to_univer(ws, cached_ws=None) -> Dict[str, Any]:
    max_row = min(max(ws.max_row or 1, 1), MAX_ROWS)
    max_col = min(max(ws.max_column or 1, 1), MAX_COLS)
    cell_data: Dict[str, Dict[str, Dict[str, Any]]] = {}
    # Do not use iter_rows over max_row/max_column here.  A workbook can have
    # one formula at XFD1048576; iterating the whole rectangle would allocate
    # billions of empty cells.  openpyxl keeps populated/styled cells in the
    # sparse _cells map, which is exactly what we need for a formula bridge.
    for cell in (getattr(ws, "_cells", {}) or {}).values():
        if cell.row > MAX_ROWS or cell.column > MAX_COLS:
            continue
        cached_cell = cached_ws.cell(row=cell.row, column=cell.column) if cached_ws is not None else None
        item = _cell_to_univer(cell, cached_cell)
        if item:
            cell_data.setdefault(str(cell.row - 1), {})[str(cell.column - 1)] = item
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
        "rowData": {
            str(int(key) - 1): {"h": float(dim.height)}
            for key, dim in ws.row_dimensions.items()
            if str(key).isdigit() and 1 <= int(key) <= MAX_ROWS and dim.height
        },
        "columnData": {
            str(column_index_from_string(str(key).upper()) - 1): {"w": float(dim.width)}
            for key, dim in ws.column_dimensions.items()
            if re.fullmatch(r"[A-Za-z]{1,3}", str(key))
            and column_index_from_string(str(key).upper()) <= MAX_COLS
            and dim.width
        },
        "freeze": {"xSplit": freeze_x, "ySplit": freeze_y} if freeze else None,
    }


def xlsx_to_workbook_snapshot(path: Path) -> Dict[str, Any]:
    """Read all worksheets and preserve formulas, basic styles, dimensions and freezes."""
    keep_vba = path.suffix.lower() == ".xlsm"
    wb = load_workbook(path, read_only=False, data_only=False, keep_vba=keep_vba)
    # A formula workbook and a cached-value workbook are complementary views
    # of the same XLSX.  Loading both is what lets us persist ``f`` and ``v``.
    cached_wb = load_workbook(path, read_only=False, data_only=True, keep_vba=keep_vba)
    try:
        sheets = [
            _sheet_to_univer(ws, cached_wb[ws.title] if ws.title in cached_wb.sheetnames else None)
            for ws in wb.worksheets[:MAX_SHEETS]
        ]
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
        cached_wb.close()


def workbook_export_basename(name: str, snapshot: Dict[str, Any]) -> str:
    """Return a stable export name, following a month changed in sheet A1.

    Imported KPI workbooks commonly keep the original month in their filename
    while the report title in A1 is edited for a new reporting month.  Export
    should reflect the edited workbook instead of silently returning the old
    month in the download name.
    """
    base = Path(name or "workbook").stem
    sheets = snapshot.get("sheets") or {}
    order = snapshot.get("sheetOrder") or list(sheets.keys())
    first_sheet = next((sheets.get(sheet_id) for sheet_id in order if sheets.get(sheet_id)), None)
    a1 = (((first_sheet or {}).get("cellData") or {}).get("0") or {}).get("0") or {}
    title = str(a1.get("v") or "")
    month_match = re.search(r"(\d{1,2})\s*月份", title) or re.search(r"(\d{1,2})\s*月", title)
    if month_match:
        month = month_match.group(1)
        base = re.sub(
            r"(\d{4}年)\d{1,2}月",
            lambda match: f"{match.group(1)}{month}月",
            base,
            count=1,
        )
    return base or "workbook"


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
    for row_key, row in cell_data.items():
        try:
            row_idx = int(row_key) + 1
        except (TypeError, ValueError):
            continue
        if not isinstance(row, dict):
            continue
        for col_key, item in row.items():
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
    # A source-backed workbook starts from the uploaded file.  Keep explicit
    # tombstones so chatbot clear_cell operations do not reappear on export.
    for row_key, cols in (sheet.get("deletedCells") or {}).items():
        try:
            row_idx = int(row_key) + 1
        except (TypeError, ValueError):
            continue
        for col_key in (cols or {}):
            try:
                ws.cell(row=row_idx, column=int(col_key) + 1).value = None
            except (TypeError, ValueError):
                continue
    for key, meta in (sheet.get("rowData") or {}).items():
        if isinstance(meta, dict) and meta.get("h"):
            ws.row_dimensions[int(key) + 1].height = float(meta["h"])
    for key, meta in (sheet.get("columnData") or {}).items():
        if isinstance(meta, dict) and meta.get("w"):
            ws.column_dimensions[get_column_letter(int(key) + 1)].width = float(meta["w"])
    freeze = sheet.get("freeze")
    if isinstance(freeze, dict) and (freeze.get("xSplit") or freeze.get("ySplit")):
        ws.freeze_panes = ws.cell(row=int(freeze.get("ySplit", 0)) + 1, column=int(freeze.get("xSplit", 0)) + 1)


def workbook_snapshot_to_xlsx(
    snapshot: Dict[str, Any], output: Path, source_path: Optional[Path] = None,
) -> None:
    """Export a snapshot, using the uploaded XLSX as a preservation base when available."""
    output = Path(output)
    source_path = Path(source_path) if source_path else None
    keep_vba = bool(source_path and source_path.suffix.lower() == ".xlsm")
    if source_path and source_path.is_file():
        shutil.copy2(source_path, output)
        wb = load_workbook(output, read_only=False, data_only=False, keep_vba=keep_vba)
    else:
        wb = Workbook()
    # Univer stores the formula text but does not provide Excel's cached
    # calculation result.  Tell Excel/LibreOffice to recalculate on open so
    # exported MRP/DOH/负荷 formulas do not appear stale.
    calculation = wb.calculation
    if calculation is None:
        calculation = CalcProperties()
        wb.calculation = calculation
    calculation.fullCalcOnLoad = True
    calculation.forceFullCalc = True
    calculation.calcMode = "auto"
    first = True
    for sheet in _snapshot_sheets(snapshot):
        name = _safe_text(sheet.get("name") or "Sheet1")[:31] or "Sheet1"
        existing_ws = wb[name] if name in wb.sheetnames else None
        ws = existing_ws or (wb.active if first else wb.create_sheet())
        first = False
        ws.title = name
        _write_snapshot_sheet(ws, sheet)
    if first:
        wb.active.title = "Sheet1"
    wb.save(output)


def _libreoffice_binary() -> Optional[str]:
    configured = os.getenv("ENGHUB_LIBREOFFICE_BIN", "").strip()
    candidates = [configured] if configured else []
    candidates.extend(["soffice", "libreoffice"])
    for candidate in candidates:
        if candidate and shutil.which(candidate):
            return candidate
    return None


def _recalculate_xlsx_file(path: Path, timeout: int = 90) -> bool:
    """Recalculate a workbook with LibreOffice Calc when the engine is installed."""
    binary = _libreoffice_binary()
    if not binary or not path.is_file():
        return False
    with tempfile.TemporaryDirectory(prefix="enghub-lo-") as work_dir:
        work = Path(work_dir)
        out_dir = work / "out"
        out_dir.mkdir()
        profile = work / "profile"
        profile.mkdir()
        try:
            completed = subprocess.run(
                [
                    binary, "--headless", "--nologo", "--nodefault", "--nofirststartwizard",
                    f"-env:UserInstallation={profile.as_uri()}",
                    "--convert-to", "xlsx", "--outdir", str(out_dir), str(path),
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout,
                env={**os.environ, "HOME": str(work / "home")},
            )
        except (OSError, subprocess.SubprocessError):
            return False
        converted = out_dir / f"{path.stem}.xlsx"
        if completed.returncode != 0 or not converted.is_file():
            return False
        shutil.copy2(converted, path)
        return True


def recalculate_workbook_file(path: Path, timeout: int = 90) -> bool:
    """Public wrapper used by import/export routes and the chatbot."""
    return _recalculate_xlsx_file(Path(path), timeout=timeout)


def _snapshot_formula_cells(snapshot: Dict[str, Any]):
    for sheet in _snapshot_sheets(snapshot):
        for row_key, row in (sheet.get("cellData") or {}).items():
            if not str(row_key).isdigit():
                continue
            for col_key, item in (row or {}).items():
                if not str(col_key).isdigit() or not isinstance(item, dict) or not item.get("f"):
                    continue
                yield sheet, int(row_key), int(col_key), item


def _update_snapshot_cached_values(snapshot: Dict[str, Any], path: Path) -> int:
    """Copy Calc's cached results back without replacing formula text/styles."""
    formula_wb = load_workbook(path, read_only=False, data_only=False, keep_vba=path.suffix.lower() == ".xlsm")
    cached_wb = load_workbook(path, read_only=False, data_only=True, keep_vba=path.suffix.lower() == ".xlsm")
    changed = 0
    try:
        for sheet, row, col, item in _snapshot_formula_cells(snapshot):
            name = str(sheet.get("name") or "")
            if name not in formula_wb.sheetnames or name not in cached_wb.sheetnames:
                continue
            formula_cell = formula_wb[name].cell(row=row + 1, column=col + 1)
            cached_cell = cached_wb[name].cell(row=row + 1, column=col + 1)
            if not formula_cell.value or not str(formula_cell.value).startswith("="):
                continue
            value = cached_cell.value
            if hasattr(value, "isoformat"):
                value = value.isoformat()
            if value != item.get("v"):
                item["v"] = "" if value is None else value
                changed += 1
    finally:
        formula_wb.close()
        cached_wb.close()
    return changed


def _is_formula_error(value: Any) -> bool:
    """Return whether a spreadsheet engine returned an error token."""
    return isinstance(value, str) and value.startswith("#")


def _repair_formula_error_values(snapshot: Dict[str, Any]) -> int:
    """Use the built-in evaluator for engine errors it explicitly supports.

    LibreOffice versions available in deployment images do not all implement
    newer Excel functions such as XLOOKUP.  Keep LibreOffice as the primary
    calculator, but repair its error tokens when our safe evaluator can
    calculate the formula.  Unknown functions remain visible as errors rather
    than being silently replaced with a guessed value.
    """
    repaired = 0
    for _ in range(5):
        changed = False
        for sheet in _snapshot_sheets(snapshot):
            sheet_name = str(sheet.get("name") or sheet.get("id") or "")
            for row in (sheet.get("cellData") or {}).values():
                for item in (row or {}).values():
                    formula = item.get("f") if isinstance(item, dict) else None
                    if not formula or not _is_formula_error(item.get("v")):
                        continue
                    try:
                        value = _evaluate_formula(snapshot, sheet_name, formula)
                    except (ValueError, TypeError, ZeroDivisionError, SyntaxError, NameError):
                        continue
                    if _is_formula_error(value):
                        continue
                    item["v"] = value
                    repaired += 1
                    changed = True
        if not changed:
            break
    return repaired


def snapshot_json(snapshot: Dict[str, Any]) -> str:
    return json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), default=str)


def parse_snapshot(raw: str) -> Dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict) or not isinstance(value.get("sheets"), dict):
        raise ValueError("工作簿快照格式无效")
    return value


_CELL_RE = re.compile(r"^([A-Za-z]{1,3})([1-9][0-9]*)$")
_FORMULA_RANGE_RE = re.compile(
    r"(?:(?:'([^']+)'|([A-Za-z_][A-Za-z0-9_. -]*))!)?"
    r"(\$?[A-Z]{1,3}\$?[1-9][0-9]*):(\$?[A-Z]{1,3}\$?[1-9][0-9]*)",
    re.IGNORECASE,
)
_FORMULA_CELL_RE = re.compile(
    r"(?:(?:'([^']+)'|([A-Za-z_][A-Za-z0-9_. -]*))!)?"
    r"(\$?[A-Z]{1,3}\$?[1-9][0-9]*)",
    re.IGNORECASE,
)


def _sheet_by_ref(snapshot: Dict[str, Any], sheet_ref: Optional[str]) -> Optional[Dict[str, Any]]:
    for sheet in _snapshot_sheets(snapshot):
        if not sheet_ref or sheet.get("id") == sheet_ref or sheet.get("name") == sheet_ref:
            return sheet
    return None


def _formula_cell_value(
    snapshot: Dict[str, Any], sheet_ref: str, cell_ref: str,
) -> Any:
    sheet = _sheet_by_ref(snapshot, sheet_ref)
    if not sheet:
        return 0
    row, col = _cell_coordinate(cell_ref)
    item = ((sheet.get("cellData") or {}).get(str(row)) or {}).get(str(col)) or {}
    value = item.get("v")
    return 0 if value is None else value


def _flatten_formula_values(value: Any) -> List[Any]:
    if isinstance(value, (list, tuple)):
        flattened: List[Any] = []
        for item in value:
            flattened.extend(_flatten_formula_values(item))
        return flattened
    return [value]


def _formula_number(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    return float(value)


def _formula_sum(*values: Any) -> float:
    return sum(_formula_number(item) for value in values for item in _flatten_formula_values(value))


def _formula_average(*values: Any) -> Any:
    numbers = [
        _formula_number(item)
        for value in values
        for item in _flatten_formula_values(value)
        if item not in (None, "")
    ]
    return sum(numbers) / len(numbers) if numbers else 0


def _formula_min(*values: Any) -> Any:
    items = [item for value in values for item in _flatten_formula_values(value) if item not in (None, "")]
    return min(items) if items else 0


def _formula_max(*values: Any) -> Any:
    items = [item for value in values for item in _flatten_formula_values(value) if item not in (None, "")]
    return max(items) if items else 0


def _formula_count(*values: Any) -> int:
    return sum(
        1
        for value in values
        for item in _flatten_formula_values(value)
        if isinstance(item, (int, float)) and not isinstance(item, bool)
    )


def _formula_matrix(snapshot: Dict[str, Any], ref: tuple[str, str]) -> List[List[Any]]:
    sheet_ref, range_ref = ref
    start, end = range_ref.split(":", 1)
    start_row, start_col = _cell_coordinate(start.replace("$", ""))
    end_row, end_col = _cell_coordinate(end.replace("$", ""))
    return [
        [
            _formula_cell_value(
                snapshot,
                sheet_ref,
                f"{get_column_letter(col + 1)}{row + 1}",
            )
            for col in range(min(start_col, end_col), max(start_col, end_col) + 1)
        ]
        for row in range(min(start_row, end_row), max(start_row, end_row) + 1)
    ]


def _formula_vlookup(
    snapshot: Dict[str, Any], lookup: Any, ref: tuple[str, str], index: Any, approximate: Any = False,
) -> Any:
    matrix = _formula_matrix(snapshot, ref)
    column = max(int(index) - 1, 0)
    matches = [row for row in matrix if row and row[0] == lookup]
    if matches and column < len(matches[0]):
        return matches[0][column]
    if approximate:
        candidates = [row for row in matrix if row and row[0] <= lookup]
        if candidates and column < len(candidates[-1]):
            return candidates[-1][column]
    return "#N/A"


def _formula_xlookup(
    snapshot: Dict[str, Any], lookup: Any, lookup_ref: tuple[str, str],
    return_ref: tuple[str, str], not_found: Any = "",
) -> Any:
    lookup_values = [item for row in _formula_matrix(snapshot, lookup_ref) for item in row]
    return_values = [item for row in _formula_matrix(snapshot, return_ref) for item in row]
    for index, value in enumerate(lookup_values):
        if value == lookup and index < len(return_values):
            return return_values[index]
    return not_found


def _formula_criteria_match(value: Any, criteria: Any) -> bool:
    if not isinstance(criteria, str):
        return value == criteria
    for operator in (">=", "<=", "<>", ">", "<", "="):
        if criteria.startswith(operator):
            target = criteria[len(operator):]
            try:
                left, right = float(value), float(target)
            except (TypeError, ValueError):
                left, right = str(value), target
            return {
                ">=": left >= right, "<=": left <= right, "<>": left != right,
                ">": left > right, "<": left < right, "=": left == right,
            }[operator]
    return str(value) == criteria


def _formula_sumifs(snapshot: Dict[str, Any], sum_ref: tuple[str, str], *criteria_pairs: Any) -> float:
    sums = [item for row in _formula_matrix(snapshot, sum_ref) for item in row]
    criteria_data = []
    for index in range(0, len(criteria_pairs) - 1, 2):
        ref = criteria_pairs[index]
        criteria = criteria_pairs[index + 1]
        values = [item for row in _formula_matrix(snapshot, ref) for item in row]
        criteria_data.append((values, criteria))
    total = 0.0
    for index, value in enumerate(sums):
        if all(index < len(values) and _formula_criteria_match(values[index], criteria) for values, criteria in criteria_data):
            total += _formula_number(value)
    return total


def _formula_if(condition: Any, when_true: Any, when_false: Any = False) -> Any:
    return when_true if condition else when_false


def _formula_iferror(value: Any, fallback: Any = "") -> Any:
    return value


_FORMULA_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare,
    ast.Call, ast.Name, ast.Load, ast.Constant, ast.List, ast.Tuple,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.USub,
    ast.UAdd, ast.And, ast.Or, ast.Eq, ast.NotEq, ast.Lt, ast.LtE,
    ast.Gt, ast.GtE,
)


def _formula_expression(
    snapshot: Dict[str, Any], sheet_name: str, formula: str,
) -> str:
    expression = str(formula or "").strip()
    if expression.startswith("="):
        expression = expression[1:]
    expression = expression.replace("^", "**").replace("<>", "!=")
    expression = re.sub(r"(?<![<>=])=(?!=)", "==", expression)
    expression = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"(\1/100)", expression)
    expression = re.sub(r"\bTRUE\b", "True", expression, flags=re.IGNORECASE)
    expression = re.sub(r"\bFALSE\b", "False", expression, flags=re.IGNORECASE)

    placeholders: Dict[str, str] = {}

    def replace_range(match: re.Match[str]) -> str:
        sheet_ref = match.group(1) or match.group(2) or sheet_name
        token = f"__FORMULA_RANGE_{len(placeholders)}__"
        placeholders[token] = repr(
            (
                sheet_ref,
                f"{match.group(3).replace('$', '').upper()}:{match.group(4).replace('$', '').upper()}",
            ),
        )
        return token

    expression = _FORMULA_RANGE_RE.sub(replace_range, expression)

    def replace_cell(match: re.Match[str]) -> str:
        sheet_ref = match.group(1) or match.group(2) or sheet_name
        token = f"__FORMULA_CELL_{len(placeholders)}__"
        placeholders[token] = repr((sheet_ref, match.group(3).replace("$", "").upper()))
        return token

    expression = _FORMULA_CELL_RE.sub(replace_cell, expression)
    for token, value in placeholders.items():
        expression = expression.replace(token, value)

    for name in (
        "SUM", "AVERAGE", "MIN", "MAX", "COUNT", "IF", "IFERROR",
        "VLOOKUP", "XLOOKUP", "SUMIFS",
    ):
        expression = re.sub(rf"\b{name}\s*\(", f"_{name.lower()}(", expression, flags=re.IGNORECASE)
    return expression


def _evaluate_formula(snapshot: Dict[str, Any], sheet_name: str, formula: str) -> Any:
    expression = _formula_expression(snapshot, sheet_name, formula)

    def cell(ref: tuple[str, str]) -> Any:
        return _formula_cell_value(snapshot, ref[0], ref[1])

    def range_values(ref: tuple[str, str]) -> List[Any]:
        return [item for row in _formula_matrix(snapshot, ref) for item in row]

    def coerce_formula_arg(value: Any) -> Any:
        if isinstance(value, tuple) and len(value) == 2 and isinstance(value[1], str):
            if ":" in value[1]:
                return range_values(value)
            return cell(value)
        return value

    environment = {
        "__builtins__": {},
        "_formula_cell": cell,
        "_formula_range": range_values,
        "_sum": lambda *values: _formula_sum(*(coerce_formula_arg(value) for value in values)),
        "_average": lambda *values: _formula_average(*(coerce_formula_arg(value) for value in values)),
        "_min": lambda *values: _formula_min(*(coerce_formula_arg(value) for value in values)),
        "_max": lambda *values: _formula_max(*(coerce_formula_arg(value) for value in values)),
        "_count": lambda *values: _formula_count(*(coerce_formula_arg(value) for value in values)),
        "_if": lambda condition, when_true, when_false=False: _formula_if(
            coerce_formula_arg(condition), coerce_formula_arg(when_true), coerce_formula_arg(when_false),
        ),
        "_vlookup": lambda lookup, ref, index, approximate=False: _formula_vlookup(snapshot, lookup, ref, index, approximate),
        "_xlookup": lambda lookup, lookup_ref, return_ref, not_found="": _formula_xlookup(snapshot, lookup, lookup_ref, return_ref, not_found),
        "_sumifs": lambda sum_ref, *pairs: _formula_sumifs(snapshot, sum_ref, *pairs),
        "_iferror": _formula_iferror,
    }
    expression = re.sub(r"\('([^']+)', '([A-Z]{1,3}[1-9][0-9]*)'\)", r"_formula_cell(('\1', '\2'))", expression)
    tree = ast.parse(expression, mode="eval")
    if any(type(node) not in _FORMULA_ALLOWED_NODES for node in ast.walk(tree)):
        raise ValueError("公式包含暂不支持的表达式")
    return eval(compile(tree, "<workbook-formula>", "eval"), environment, {})


_FORMULA_REFERENCE_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?:(?P<sheet>'(?:[^']|'')+'|[A-Za-z_][A-Za-z0-9_. -]*)!)?"
    r"(?P<start>\$?[A-Z]{1,3}\$?[1-9][0-9]*)"
    r"(?:\s*:\s*(?P<end>\$?[A-Z]{1,3}\$?[1-9][0-9]*))?",
    re.IGNORECASE,
)
_FORMULA_FUNCTION_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_.]*)\s*\(")


def _normalise_formula_sheet_ref(value: Optional[str], default: str) -> str:
    if not value:
        return default
    value = str(value)
    if value.startswith("'") and value.endswith("'"):
        value = value[1:-1].replace("''", "'")
    # External-book references are reported as unresolved rather than being
    # mistaken for a local sheet.
    if "]" in value:
        value = value.split("]", 1)[-1]
    return value


def _formula_address(row: int, col: int) -> str:
    return f"{get_column_letter(col + 1)}{row + 1}"


def _formula_reference_record(
    snapshot: Dict[str, Any], default_sheet: str, match: re.Match[str],
) -> Dict[str, Any]:
    sheet_name = _normalise_formula_sheet_ref(match.group("sheet"), default_sheet)
    start = match.group("start").replace("$", "").upper()
    end = match.group("end")
    if end:
        end = end.replace("$", "").upper()
    target = _sheet_by_ref(snapshot, sheet_name)
    record: Dict[str, Any] = {
        "sheet": sheet_name,
        "cell": start,
        "resolved": target is not None,
    }
    if end:
        record.update({"type": "range", "range": f"{start}:{end}", "end_cell": end})
    else:
        record["type"] = "cell"
    return record


def scan_formula_dependencies(
    snapshot: Dict[str, Any], sheet_ref: Optional[str] = None,
) -> Dict[str, Any]:
    """Scan every formula cell and build a cross-sheet dependency index.

    This is intentionally independent of the calculation engine.  Unknown or
    newer Excel functions still have their A1 references and dependents
    indexed, while volatile/dynamic references are called out explicitly.
    """
    formula_cells: List[Dict[str, Any]] = []
    dependencies: List[Dict[str, Any]] = []
    dependents: Dict[str, List[str]] = {}
    range_dependents: List[Dict[str, Any]] = []
    selected = _sheet_by_ref(snapshot, sheet_ref) if sheet_ref else None
    for sheet in _snapshot_sheets(snapshot):
        if selected is not None and sheet is not selected:
            continue
        sheet_name = str(sheet.get("name") or sheet.get("id") or "")
        for row_key, row in (sheet.get("cellData") or {}).items():
            if not str(row_key).isdigit():
                continue
            for col_key, item in (row or {}).items():
                if not str(col_key).isdigit() or not isinstance(item, dict) or not item.get("f"):
                    continue
                cell = _formula_address(int(row_key), int(col_key))
                formula = str(item.get("f") or "")
                refs = [
                    _formula_reference_record(snapshot, sheet_name, match)
                    for match in _FORMULA_REFERENCE_RE.finditer(formula)
                ]
                # Preserve order but remove duplicate references created by
                # expressions such as SUM(A1:A3,A1:A3).
                unique_refs = []
                seen_refs = set()
                for ref in refs:
                    key = (ref.get("sheet"), ref.get("type"), ref.get("cell"), ref.get("range"))
                    if key not in seen_refs:
                        seen_refs.add(key)
                        unique_refs.append(ref)
                functions = sorted({m.group(1).upper() for m in _FORMULA_FUNCTION_RE.finditer(formula)})
                dynamic = bool(re.search(r"\b(?:INDIRECT|OFFSET)\s*\(|\[[^]]+\]|#(?:REF|SPILL|N/A)!?", formula, re.I))
                source_key = f"{sheet_name}!{cell}"
                detail = {
                    "sheet": sheet_name,
                    "cell": cell,
                    "formula": formula,
                    "value": item.get("v"),
                    "functions": functions,
                    "references": unique_refs,
                    "dynamic_reference": dynamic,
                }
                formula_cells.append(detail)
                for ref in unique_refs:
                    target_key = f"{ref['sheet']}!{ref['cell']}"
                    dependencies.append({"from": source_key, "to": target_key, "type": ref["type"], "range": ref.get("range")})
                    if ref["type"] == "cell":
                        dependents.setdefault(target_key, []).append(source_key)
                    else:
                        try:
                            start_row, start_col = _cell_coordinate(ref["cell"])
                            end_row, end_col = _cell_coordinate(ref["end_cell"])
                            area = (abs(end_row - start_row) + 1) * (abs(end_col - start_col) + 1)
                        except ValueError:
                            area = 0
                        if 0 < area <= 10_000:
                            for target_row in range(min(start_row, end_row), max(start_row, end_row) + 1):
                                for target_col in range(min(start_col, end_col), max(start_col, end_col) + 1):
                                    target_key = f"{ref['sheet']}!{_formula_address(target_row, target_col)}"
                                    dependents.setdefault(target_key, []).append(source_key)
                        else:
                            range_dependents.append({"range": f"{ref['sheet']}!{ref['range']}", "dependent": source_key})
    for values in dependents.values():
        values[:] = sorted(set(values))
    return {
        "formula_cells": len(formula_cells),
        "formulas": formula_cells,
        "dependencies": dependencies,
        "dependents": dependents,
        "range_dependents": range_dependents,
        "calculation": snapshot.get("calculation") or {"engine": "cached", "full_recalculation": False},
    }


def _recalculate_snapshot_formulas(
    snapshot: Dict[str, Any], source_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Recalculate all formula cells with LibreOffice, then use the safe
    built-in evaluator only when a real spreadsheet engine is unavailable."""
    formula_count = sum(1 for _ in _snapshot_formula_cells(snapshot))
    if formula_count:
        with tempfile.TemporaryDirectory(prefix="enghub-formula-") as work_dir:
            source = Path(source_path) if source_path else None
            # LibreOffice writes xlsx output and openpyxl can read it back.  A
            # source-backed xlsx is copied first so charts/names/etc. survive
            # the cell edit/recalc round trip as far as the installed engine
            # permits.
            input_path = Path(work_dir) / "workbook.xlsx"
            workbook_snapshot_to_xlsx(
                snapshot,
                input_path,
                source_path=source if source and source.suffix.lower() == ".xlsx" else None,
            )
            if _recalculate_xlsx_file(input_path):
                updated = _update_snapshot_cached_values(snapshot, input_path)
                repaired = _repair_formula_error_values(snapshot)
                result = {
                    "engine": "libreoffice",
                    "full_recalculation": True,
                    "formula_cells": formula_count,
                    "cached_updates": updated + repaired,
                }
                snapshot["calculation"] = result
                return result

    # Fallback used by local unit tests and minimal installations.  It never
    # overwrites a cached value for a formula it cannot understand.
    for _ in range(5):
        changed = False
        for sheet in _snapshot_sheets(snapshot):
            sheet_name = str(sheet.get("name") or sheet.get("id") or "")
            for row in (sheet.get("cellData") or {}).values():
                for item in (row or {}).values():
                    formula = item.get("f") if isinstance(item, dict) else None
                    if not formula:
                        continue
                    try:
                        value = _evaluate_formula(snapshot, sheet_name, formula)
                    except (ValueError, TypeError, ZeroDivisionError, SyntaxError, NameError):
                        continue
                    if value != item.get("v"):
                        item["v"] = value
                        changed = True
        if not changed:
            break
    result = {
        "engine": "builtin_fallback",
        "full_recalculation": False,
        "formula_cells": formula_count,
        "cached_updates": 0,
        "message": "未检测到 LibreOffice；已保留原公式和缓存值，打开/导出时由 Excel 重新计算",
    }
    snapshot["calculation"] = result
    return result


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
        sheet.setdefault("deletedCells", {}).setdefault(str(row), {})[str(col)] = True
        return
    inferred_formula = formula
    if not inferred_formula and isinstance(value, str) and value.startswith("="):
        inferred_formula = value
        value = ""
    existing = row_data.get(str(col)) or {}
    normalized_formula = (
        str(inferred_formula)
        if inferred_formula and str(inferred_formula).startswith("=")
        else (f"={inferred_formula}" if inferred_formula else None)
    )
    cached_value = (
        existing.get("v", "")
        if normalized_formula and existing.get("f") == normalized_formula
        else ""
    )
    item: Dict[str, Any] = {"v": cached_value if inferred_formula else value}
    if inferred_formula:
        item["f"] = normalized_formula
    row_data[str(col)] = item
    deleted_row = (sheet.get("deletedCells") or {}).get(str(row))
    if deleted_row:
        deleted_row.pop(str(col), None)
        if not deleted_row:
            (sheet.get("deletedCells") or {}).pop(str(row), None)


def apply_workbook_operations(
    snapshot: Dict[str, Any], operations: List[Dict[str, Any]], source_path: Optional[Path] = None,
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
    _recalculate_snapshot_formulas(snapshot, source_path=source_path)
    for item in changed:
        cell = item.get("cell")
        sheet_name = item.get("sheet")
        if not cell or not sheet_name:
            continue
        sheet = _find_sheet(snapshot, sheet_name)
        row, col = _cell_coordinate(cell)
        current = ((sheet.get("cellData") or {}).get(str(row)) or {}).get(str(col)) or {}
        if current.get("f"):
            item["computed_value"] = current.get("v")
    return snapshot, changed


def snapshot_to_table(snapshot: Dict[str, Any], sheet_ref: Optional[str] = None, max_rows: int = 100, max_cols: int = 50) -> Dict[str, Any]:
    """Create a bounded table view for chatbot grounding."""
    sheet = _find_sheet(snapshot, sheet_ref)
    cell_data = sheet.get("cellData") or {}
    rows: List[List[Any]] = []
    formula_details: List[Dict[str, Any]] = []
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
            formula = item.get("f")
            if formula:
                formula_details.append({
                    "cell": f"{get_column_letter(col + 1)}{int(row_key) + 1}",
                    "formula": formula,
                    "value": item.get("v"),
                })
            formula_value = item.get("v")
            values.append(
                item.get("v", "")
                if not formula
                else (formula_value if formula_value not in (None, "") else formula)
            )
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
        "formula_details": formula_details,
        "calculation": snapshot.get("calculation") or {"engine": "cached", "full_recalculation": False},
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
