"""Online workbook APIs used by PMC and the chatbot."""

from __future__ import annotations

import io
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.file_routes import UPLOAD_DIR
from api.services.workbook_service import (
    apply_workbook_operations,
    build_pmc_workbook_template,
    build_pivot_summary,
    workbook_snapshot_to_xlsx,
    xlsx_to_workbook_snapshot,
)
from core.auth.security import get_current_user
from database.db_config import get_db
from database.models import FileRecord, User, WorkbookRecord

router = APIRouter(prefix="/api/v1/workbooks", tags=["workbooks"])


class WorkbookCreate(BaseModel):
    name: str = "未命名工作簿"
    snapshot: Dict[str, Any]


class WorkbookUpdate(BaseModel):
    name: Optional[str] = None
    snapshot: Dict[str, Any]


class WorkbookOperations(BaseModel):
    operations: List[Dict[str, Any]] = Field(default_factory=list)


class PivotRequest(BaseModel):
    sheet: Optional[str] = None
    row_field: str
    value_field: str
    aggregation: str = "sum"
    output_sheet_name: str = "透视汇总"


def _same_factory(record: WorkbookRecord, user: User) -> None:
    if user.is_superuser:
        return
    if record.factory_id and user.factory_id and record.factory_id != user.factory_id:
        raise HTTPException(status_code=403, detail="无权访问其他工厂的工作簿")


async def _get_workbook(workbook_id: str, db: AsyncSession, user: User) -> WorkbookRecord:
    record = (await db.execute(select(WorkbookRecord).where(WorkbookRecord.id == workbook_id))).scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="工作簿不存在")
    _same_factory(record, user)
    return record


@router.get("")
async def list_workbooks(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(WorkbookRecord).order_by(WorkbookRecord.updated_at.desc()).limit(limit)
    if not current_user.is_superuser and current_user.factory_id:
        stmt = stmt.where(WorkbookRecord.factory_id == current_user.factory_id)
    rows = (await db.execute(stmt)).scalars().all()
    return {"count": len(rows), "workbooks": [row.to_dict() for row in rows]}


@router.post("")
async def create_workbook(
    payload: WorkbookCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workbook = WorkbookRecord(
        id=str(uuid.uuid4()),
        name=(payload.name or "未命名工作簿")[:255],
        factory_id=current_user.factory_id,
        snapshot=payload.snapshot,
        created_by=current_user.username,
        updated_by=current_user.username,
    )
    db.add(workbook)
    await db.commit()
    await db.refresh(workbook)
    return workbook.to_dict()


@router.post("/templates/pmc")
async def create_pmc_template(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create the formula-ready PMC workbook template."""
    snapshot = build_pmc_workbook_template()
    workbook = WorkbookRecord(
        id=str(uuid.uuid4()),
        name="PMC物料动态计算模板",
        factory_id=current_user.factory_id,
        snapshot=snapshot,
        created_by=current_user.username,
        updated_by=current_user.username,
    )
    db.add(workbook)
    await db.commit()
    await db.refresh(workbook)
    result = workbook.to_dict()
    result["snapshot"] = snapshot
    return result


@router.post("/import")
async def import_workbook(
    file: UploadFile = File(...),
    name: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Import .xlsx/.xlsm while retaining formulas, sheets and basic formatting."""
    filename = file.filename or "workbook.xlsx"
    suffix = Path(filename).suffix.lower()
    if suffix not in {".xlsx", ".xlsm"}:
        raise HTTPException(status_code=400, detail="目前支持 .xlsx/.xlsm；.xls 请先另存为 .xlsx")
    content = await file.read()
    if len(content) > 100 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="工作簿超过 100MB 限制")

    file_id = str(uuid.uuid4())
    safe_name = filename.replace("/", "_").replace("\\", "_")
    source_path = UPLOAD_DIR / f"{file_id}_{safe_name}"
    source_path.write_bytes(content)
    try:
        snapshot = xlsx_to_workbook_snapshot(source_path)
    except Exception as exc:  # noqa: BLE001
        source_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"XLSX 解析失败：{exc}") from exc

    file_record = FileRecord(
        id=file_id,
        filename=filename,
        content_type=file.content_type or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        size=len(content),
        storage_path=str(source_path),
        uploaded_by=current_user.username,
        factory_id=current_user.factory_id,
        related_type="workbook",
    )
    workbook = WorkbookRecord(
        id=str(uuid.uuid4()),
        name=(name or Path(filename).stem)[:255],
        factory_id=current_user.factory_id,
        snapshot=snapshot,
        source_file_id=file_id,
        created_by=current_user.username,
        updated_by=current_user.username,
    )
    file_record.related_id = workbook.id
    db.add(file_record)
    db.add(workbook)
    await db.commit()
    await db.refresh(workbook)
    result = workbook.to_dict()
    result["snapshot"] = snapshot
    result["source_filename"] = filename
    return result


@router.get("/{workbook_id}")
async def get_workbook(
    workbook_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workbook = await _get_workbook(workbook_id, db, current_user)
    result = workbook.to_dict(include_snapshot=True)
    return result


@router.put("/{workbook_id}")
async def update_workbook(
    workbook_id: str,
    payload: WorkbookUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workbook = await _get_workbook(workbook_id, db, current_user)
    workbook.snapshot = payload.snapshot
    if payload.name:
        workbook.name = payload.name[:255]
    workbook.updated_by = current_user.username
    await db.commit()
    await db.refresh(workbook)
    return workbook.to_dict()


@router.post("/{workbook_id}/operations")
async def apply_operations(
    workbook_id: str,
    payload: WorkbookOperations,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workbook = await _get_workbook(workbook_id, db, current_user)
    try:
        snapshot, changed = apply_workbook_operations(workbook.snapshot or {}, payload.operations)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    workbook.snapshot = snapshot
    workbook.updated_by = current_user.username
    await db.commit()
    return {
        "success": True,
        "workbook_id": workbook.id,
        "changed": changed,
        "snapshot": snapshot,
        "updated_at": workbook.updated_at.isoformat() if workbook.updated_at else None,
    }


@router.post("/{workbook_id}/pivot")
async def create_pivot(
    workbook_id: str,
    payload: PivotRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workbook = await _get_workbook(workbook_id, db, current_user)
    try:
        snapshot, summary = build_pivot_summary(
            workbook.snapshot or {},
            payload.sheet,
            payload.row_field,
            payload.value_field,
            payload.aggregation,
            payload.output_sheet_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    workbook.snapshot = snapshot
    workbook.updated_by = current_user.username
    await db.commit()
    await db.refresh(workbook)
    result = workbook.to_dict(include_snapshot=True)
    result["summary"] = summary
    return result


@router.get("/{workbook_id}/export")
async def export_workbook(
    workbook_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workbook = await _get_workbook(workbook_id, db, current_user)
    output = io.BytesIO()
    temp_path = UPLOAD_DIR / f"export_{workbook.id}_{uuid.uuid4().hex}.xlsx"
    try:
        workbook_snapshot_to_xlsx(workbook.snapshot or {}, temp_path)
        output.write(temp_path.read_bytes())
    finally:
        temp_path.unlink(missing_ok=True)
    output.seek(0)
    safe_name = re.sub(r'[\\/:*?"<>|]+', "_", workbook.name or "workbook").strip() or "workbook"
    filename = f"{safe_name}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


__all__ = ["router"]
