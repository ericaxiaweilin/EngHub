"""
Quality Red Tag API Routes
Handles REST API endpoints for quality red tag (质量红单) management
"""

from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from database.db_config import get_async_session
from core.qms.red_tag_service import RedTagService
from database.models import QualityRedTag
from core.auth.security import get_current_user

router = APIRouter(prefix="/api/v1/qms/red-tags", tags=["Quality Red Tag"])


# Pydantic schemas
class RedTagCreate(BaseModel):
    factory_id: str = Field(..., description="Factory ID")
    defect_id: str = Field(..., description="Defect ID to associate")
    red_tag_type: str = Field(..., description="Red tag type: INCOMING/IN_PROCESS/FINAL/CUSTOMER_RETURN")
    defect_description: Optional[str] = Field(None, description="Defect description")
    nonconforming_qty: float = Field(0.0, description="Non-conforming quantity")
    batch_no: Optional[str] = Field(None, description="Batch number")
    work_order_id: Optional[str] = Field(None, description="Work order ID")
    station_id: Optional[str] = Field(None, description="Station ID")
    discovered_by: Optional[str] = Field(None, description="Discovered by user ID")
    severity: str = Field("MINOR", description="Severity: CRITICAL/MAJOR/MINOR")


class RedTagUpdate(BaseModel):
    defect_description: Optional[str] = None
    nonconforming_qty: Optional[float] = None
    batch_no: Optional[str] = None
    work_order_id: Optional[str] = None
    station_id: Optional[str] = None
    severity: Optional[str] = None
    quarantine_status: Optional[str] = None


class DispositionSubmit(BaseModel):
    disposition: str = Field(..., description="Disposition: SCRAP/REWORK/USE_AS_IS/RTV/NO_DEFECT")
    disposition_by: str = Field(..., description="User ID who approved disposition")
    disposition_notes: Optional[str] = Field(None, description="Disposition notes")


class RedTagResponse(BaseModel):
    id: str
    factory_id: str
    red_tag_no: str
    defect_id: str
    inspection_id: Optional[str] = None
    red_tag_type: str
    defect_description: Optional[str] = None
    nonconforming_qty: float
    batch_no: Optional[str] = None
    work_order_id: Optional[str] = None
    station_id: Optional[str] = None
    discovered_by: Optional[str] = None
    discovered_at: Optional[str] = None
    severity: str
    quarantine_status: str
    disposition: Optional[str] = None
    disposition_by: Optional[str] = None
    disposition_date: Optional[str] = None
    disposition_notes: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_by: Optional[str] = None
    defect: Optional[dict] = None
    attachments: List[dict] = []


# Routes
@router.post("/", response_model=RedTagResponse, summary="Create quality red tag")
async def create_red_tag(
    payload: RedTagCreate,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user)
):
    """Create a new quality red tag and associate it with a defect"""
    
    service = RedTagService(db)
    
    try:
        red_tag = await service.create_red_tag(
            factory_id=payload.factory_id,
            defect_id=payload.defect_id,
            red_tag_type=payload.red_tag_type,
            defect_description=payload.defect_description,
            nonconforming_qty=payload.nonconforming_qty,
            batch_no=payload.batch_no,
            work_order_id=payload.work_order_id,
            station_id=payload.station_id,
            discovered_by=payload.discovered_by,
            severity=payload.severity,
            created_by=current_user.get("user_id")
        )
        return await service.get_red_tag(red_tag.id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/", response_model=dict, summary="List quality red tags")
async def list_red_tags(
    factory_id: str = Query(..., description="Factory ID"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    red_tag_type: Optional[str] = Query(None),
    quarantine_status: Optional[str] = Query(None),
    disposition: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    defect_id: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user)
):
    """List quality red tags with filtering"""
    
    service = RedTagService(db)
    
    return await service.list_red_tags(
        factory_id=factory_id,
        limit=limit,
        offset=offset,
        red_tag_type=red_tag_type,
        quarantine_status=quarantine_status,
        disposition=disposition,
        severity=severity,
        defect_id=defect_id,
        date_from=date_from,
        date_to=date_to
    )


@router.get("/statistics", response_model=dict, summary="Get red tag statistics")
async def get_red_tag_statistics(
    factory_id: str = Query(..., description="Factory ID"),
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user)
):
    """Get red tag statistics by status, disposition, type, and severity"""
    
    service = RedTagService(db)
    
    return await service.get_statistics(factory_id)


@router.get("/{red_tag_id}", response_model=RedTagResponse, summary="Get red tag by ID")
async def get_red_tag(
    red_tag_id: str,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user)
):
    """Get red tag details by ID"""
    
    service = RedTagService(db)
    red_tag = await service.get_red_tag(red_tag_id)
    
    if not red_tag:
        raise HTTPException(status_code=404, detail="Red tag not found")
    
    return red_tag


@router.put("/{red_tag_id}", response_model=RedTagResponse, summary="Update red tag")
async def update_red_tag(
    red_tag_id: str,
    payload: RedTagUpdate,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user)
):
    """Update red tag fields"""
    
    service = RedTagService(db)
    
    updated = await service.update_red_tag(red_tag_id, **payload.model_dump(exclude_none=True))
    
    if not updated:
        raise HTTPException(status_code=404, detail="Red tag not found")
    
    return await service.get_red_tag(red_tag_id)


@router.delete("/{red_tag_id}", response_model=dict, summary="Delete red tag")
async def delete_red_tag(
    red_tag_id: str,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user)
):
    """Soft delete red tag"""
    
    service = RedTagService(db)
    deleted = await service.delete_red_tag(red_tag_id)
    
    if not deleted:
        raise HTTPException(status_code=404, detail="Red tag not found")
    
    return {"success": True, "message": "Red tag deleted successfully"}


@router.post("/{red_tag_id}/disposition", response_model=RedTagResponse, summary="Submit disposition")
async def submit_disposition(
    red_tag_id: str,
    payload: DispositionSubmit,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user)
):
    """Submit disposition for red tag"""
    
    service = RedTagService(db)
    
    try:
        result = await service.submit_disposition(
            red_tag_id=red_tag_id,
            disposition=payload.disposition,
            disposition_by=payload.disposition_by,
            disposition_notes=payload.disposition_notes
        )
        
        if not result:
            raise HTTPException(status_code=404, detail="Red tag not found")
        
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/defects/{defect_id}/red-tags", response_model=List[dict], summary="Get red tags by defect")
async def get_red_tags_by_defect(
    defect_id: str,
    db: AsyncSession = Depends(get_async_session),
    current_user: dict = Depends(get_current_user)
):
    """Get all red tags associated with a defect"""
    
    service = RedTagService(db)
    red_tags = await service.get_red_tags_by_defect(defect_id)
    
    return red_tags
