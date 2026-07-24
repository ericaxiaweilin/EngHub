"""
File Routes - 文件/附件上传下载 API
=============================================
chatbot 多模态收发 + 系统表单/报告导出文件的统一存储。
- POST /api/v1/files/upload：上传文件（落盘 UPLOAD_DIR + 写 FileRecord）
- GET  /api/v1/files/{id}：下载文件（鉴权 + 工厂校验）
- GET  /api/v1/files：按业务对象列附件（related_type/related_id）

多工厂隔离：普通用户仅能访问本工厂文件，超管可跨工厂。
"""

import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.db_config import get_db
from database.models import FileRecord, User
from core.auth.security import get_current_user

router = APIRouter(prefix="/api/v1/files", tags=["files"])

# 落盘目录：容器内 /app/uploads，本地 项目根/uploads
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(Path(__file__).resolve().parents[2] / "uploads")))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# 上传大小上限（默认 20MB），防止大文件占满磁盘
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", str(20 * 1024 * 1024)))


def _ensure_same_factory(file: FileRecord, user: User) -> None:
    """多工厂隔离：普通用户不可访问其他工厂的文件（超管例外）。"""
    if user.is_superuser:
        return
    if file.factory_id and user.factory_id and file.factory_id != user.factory_id:
        raise HTTPException(status_code=403, detail="无权访问其他工厂的文件")


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    related_type: Optional[str] = Form(None),
    related_id: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """上传文件：落盘 UPLOAD_DIR 并写 FileRecord（按当前用户工厂隔离）。"""
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail=f"文件过大（上限 {MAX_UPLOAD_SIZE // 1024 // 1024}MB）")

    file_id = str(uuid.uuid4())
    # 以「id_原名」落盘，避免同名覆盖；清洗路径分隔符防目录穿越
    safe_name = (file.filename or "file").replace("/", "_").replace("\\", "_")
    storage_path = UPLOAD_DIR / f"{file_id}_{safe_name}"
    storage_path.write_bytes(content)

    record = FileRecord(
        id=file_id,
        filename=file.filename or "file",
        content_type=file.content_type,
        size=len(content),
        storage_path=str(storage_path),
        uploaded_by=current_user.username,
        factory_id=current_user.factory_id,
        related_type=related_type,
        related_id=related_id,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    result = record.to_dict()
    result["is_image"] = (file.content_type or "").startswith("image/")
    return result


@router.get("/{file_id}")
async def download_file(
    file_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """下载文件（鉴权 + 工厂校验）。"""
    record = (await db.execute(select(FileRecord).where(FileRecord.id == file_id))).scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="文件不存在")
    _ensure_same_factory(record, current_user)
    if not Path(record.storage_path).is_file():
        raise HTTPException(status_code=404, detail="文件实体缺失")
    return FileResponse(
        record.storage_path,
        media_type=record.content_type or "application/octet-stream",
        filename=record.filename,
    )


@router.get("")
async def list_files(
    related_type: Optional[str] = Query(None),
    related_id: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """按业务对象列附件（按当前工厂隔离）。"""
    stmt = select(FileRecord).order_by(FileRecord.created_at.desc()).limit(limit)
    if not current_user.is_superuser and current_user.factory_id:
        stmt = stmt.where(FileRecord.factory_id == current_user.factory_id)
    if related_type:
        stmt = stmt.where(FileRecord.related_type == related_type)
    if related_id:
        stmt = stmt.where(FileRecord.related_id == related_id)
    rows = (await db.execute(stmt)).scalars().all()
    items = []
    for r in rows:
        it = r.to_dict()
        it["is_image"] = (r.content_type or "").startswith("image/")
        items.append(it)
    return {"count": len(items), "files": items}


__all__ = ["router", "UPLOAD_DIR"]
