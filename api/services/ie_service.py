"""
IE Service Layer - Core Services for Industrial Engineering Module
精益生产IE模块核心服务：标准工时、时间研究、产线平衡、工序价值分析
"""

from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from database.models import (
    StandardOperationTime,
    TimeStudyRecord,
    LineBalanceAnalysis,
    ProcessAnalysis,
)


class StandardTimeService:
    """标准工时服务 - 管理标准作业时间（SOT）"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_standard_time(
        self,
        factory_id: str,
        product_id: str,
        routing_step: str,
        operation_name: str,
        station_id: Optional[str] = None,
        standard_time_min: float = 0.0,
        setup_time_min: float = 0.0,
        batch_size: int = 1,
        rating_factor: float = 1.0,
        allowance_rate: float = 0.15,
        validity_start: Optional[datetime] = None,
        validity_end: Optional[datetime] = None,
        created_by: Optional[str] = None
    ) -> StandardOperationTime:
        """创建新标准工时记录"""
        if validity_start is None:
            validity_start = datetime.utcnow()
        
        # 计算有效标准时间 = 标准时间 × (1 + 宽放率)
        effective_time = round(standard_time_min * (1 + allowance_rate), 2)
        
        sot = StandardOperationTime(
            factory_id=factory_id,
            product_id=product_id,
            routing_step=routing_step,
            operation_name=operation_name,
            station_id=station_id,
            standard_time_min=standard_time_min,
            setup_time_min=setup_time_min,
            batch_size=batch_size,
            rating_factor=rating_factor,
            allowance_rate=allowance_rate,
            effective_standard_time=effective_time,
            version="v1",
            is_active=True,
            validity_start=validity_start,
            validity_end=validity_end,
            created_by=created_by or "system"
        )
        
        self.db.add(sot)
        await self.db.commit()
        await self.db.refresh(sot)
        return sot
    
    async def get_standard_time(self, sot_id: str) -> Optional[StandardOperationTime]:
        """获取单个标准工时记录"""
        result = await self.db.execute(select(StandardOperationTime).where(StandardOperationTime.id == sot_id))
        return result.scalar_one_or_none()
    
    async def list_standard_times(
        self,
        factory_id: str,
        product_id: Optional[str] = None,
        station_id: Optional[str] = None,
        limit: int = 100
    ) -> List[StandardOperationTime]:
        """查询标准工时列表"""
        query = select(StandardOperationTime).where(StandardOperationTime.factory_id == factory_id)
        
        if product_id:
            query = query.where(StandardOperationTime.product_id == product_id)
        if station_id:
            query = query.where(StandardOperationTime.station_id == station_id)
        
        result = await self.db.execute(query.limit(limit))
        return list(result.scalars().all())
    
    async def get_sots_by_product(self, factory_id: str, product_id: str) -> List[StandardOperationTime]:
        """按产品查询标准工时（活跃的）"""
        now = datetime.utcnow()
        query = select(StandardOperationTime).where(
            StandardOperationTime.factory_id == factory_id,
            StandardOperationTime.product_id == product_id,
            StandardOperationTime.is_active == True,
            StandardOperationTime.validity_start <= now,
            or_(StandardOperationTime.validity_end > now, StandardOperationTime.validity_end == None)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def update_standard_time(self, sot_id: str, **kwargs) -> bool:
        """更新标准工时记录"""
        sot = await self.get_standard_time(sot_id)
        if not sot:
            return False
        
        for key, value in kwargs.items():
            if hasattr(sot, key):
                setattr(sot, key, value)
        
        sot.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(sot)
        return True
    
    async def delete_standard_time(self, sot_id: str) -> bool:
        """逻辑删除标准工时（标记为 inactive）"""
        sot = await self.get_standard_time(sot_id)
        if not sot:
            return False
        
        sot.is_active = False
        sot.updated_at = datetime.utcnow()
        
        await self.db.commit()
        await self.db.refresh(sot)
        return True


class TimeStudyService:
    """时间研究服务 - 管理时间观测数据"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_time_study(
        self,
        factory_id: str,
        product_id: str,
        station_id: str,
        operation_name: str,
        operator_id: str,
        observer_id: str,
        observation_date: datetime,
        observed_cycles: List[float],
        rating_factor: float = 1.0,
        method: str = "direct",
        created_by: Optional[str] = None
    ) -> TimeStudyRecord:
        """创建并处理时间研究观测记录"""
        if not observed_cycles:
            raise ValueError("observed_cycles cannot be empty")
        
        # 计算平均值
        average_time = sum(observed_cycles) / len(observed_cycles)
        
        # 计算正常时间 = 平均时间 × 评定系数
        normal_time = round(average_time * rating_factor, 3)
        
        # 计算允许时间 = 正常时间 × (1 + 宽放率)
        allowed_time = round(normal_time * (1 + 0.15), 3)  # Default 15% allowance
        
        ts = TimeStudyRecord(
            factory_id=factory_id,
            product_id=product_id,
            station_id=station_id,
            operation_name=operation_name,
            operator_id=operator_id,
            observer_id=observer_id,
            observation_date=observation_date,
            observed_cycles=observed_cycles,
            cycle_count=len(observed_cycles),
            average_time=round(average_time, 3),
            rating_factor=rating_factor,
            normal_time=normal_time,
            allowed_time=allowed_time,
            allowance_rate=0.15,
            method=method,
            status="pending",
            created_by=created_by or "system"
        )
        
        self.db.add(ts)
        await self.db.commit()
        await self.db.refresh(ts)
        return ts
    
    async def _get_ts_by_id(self, ts_id: str) -> Optional[TimeStudyRecord]:
        """内部方法：获取单个时间研究记录"""
        result = await self.db.execute(select(TimeStudyRecord).where(TimeStudyRecord.id == ts_id))
        return result.scalar_one_or_none()
    
    async def list_time_studies(
        self,
        factory_id: str,
        product_id: Optional[str] = None,
        station_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100
    ) -> List[TimeStudyRecord]:
        """查询时间研究记录列表"""
        query = select(TimeStudyRecord).where(TimeStudyRecord.factory_id == factory_id)
        
        if product_id:
            query = query.where(TimeStudyRecord.product_id == product_id)
        if station_id:
            query = query.where(TimeStudyRecord.station_id == station_id)
        if status:
            query = query.where(TimeStudyRecord.status == status)
        
        result = await self.db.execute(query.limit(limit))
        return list(result.scalars().all())
    
    async def approve_time_study(self, ts_id: str, approved_by: str) -> bool:
        """批准时间研究（转换为标准工时的前序步骤）"""
        ts = await self._get_ts_by_id(ts_id)
        if not ts or ts.status != "pending":
            return False
        
        ts.status = "approved"
        ts.approved_by = approved_by
        ts.updated_at = datetime.utcnow()
        
        await self.db.commit()
        await self.db.refresh(ts)
        return True
    
    async def reject_time_study(self, ts_id: str, reason: str = "") -> bool:
        """拒绝时间研究"""
        ts = await self._get_ts_by_id(ts_id)
        if not ts:
            return False
        
        ts.status = "rejected"
        ts.updated_at = datetime.utcnow()
        
        await self.db.commit()
        await self.db.refresh(ts)
        return True


class LineBalanceService:
    """产线平衡服务 - 分析生产线效率"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def analyze_line_balance(
        self,
        factory_id: str,
        line_id: str,
        product_id: str,
        analysis_date: Optional[datetime] = None,
        takt_time: Optional[float] = None,
        created_by: Optional[str] = None
    ) -> LineBalanceAnalysis:
        """执行产线平衡分析"""
        if analysis_date is None:
            analysis_date = datetime.utcnow()
        
        # 获取该产品的所有标准工时（各工站）
        sot_service = StandardTimeService(self.db)
        sots = await sot_service.get_sots_by_product(factory_id=factory_id, product_id=product_id)
        
        if not sots:
            raise ValueError("No standard times available for this product")
        
        # 计算各工站的周期时间
        stations = []
        max_cycle_time = 0.0
        total_active_time = 0.0
        
        for sot in sots:
            if sot.station_id and sot.effective_standard_time:
                cycle_time = sot.effective_standard_time
                stations.append({
                    "station_id": sot.station_id,
                    "cycle_time_min": cycle_time,
                })
                max_cycle_time = max(max_cycle_time, cycle_time)
                total_active_time += cycle_time
        
        # 计算节拍时间（如果未提供）
        if takt_time is None:
            takt_time = round(max_cycle_time * 0.95, 2)
        
        workstation_count = len(stations)
        balance_rate = round((total_active_time / max_cycle_time / workstation_count) * 100, 2) if workstation_count > 0 else 0.0
        
        # 识别瓶颈
        bottleneck = max(stations, key=lambda x: x["cycle_time_min"]) if stations else None
        recommendations = []
        
        if balance_rate < 85:
            recommendations.append("平衡率低于85%，建议重新分配负载或增加并行工位")
        if balance_rate < 70:
            recommendations.append("平衡率较低（<70%），需要进行详细的方法研究和动作研究")
        if bottleneck:
            recommendations.append(f"瓶颈工站 {bottleneck['station_id']} 耗时 {bottleneck['cycle_time_min']} min")
        
        lba = LineBalanceAnalysis(
            factory_id=factory_id,
            product_id=product_id,
            line_id=line_id,
            analysis_date=analysis_date,
            takt_time_min=takt_time,
            cycle_time_max=max_cycle_time,
            cycle_time_avg=round(total_active_time / workstation_count, 2) if workstation_count > 0 else 0,
            balance_rate=balance_rate,
            workstation_details=stations,
            bottleneck_station=bottleneck["station_id"] if bottleneck else None,
            bottleneck_time=bottleneck["cycle_time_min"] if bottleneck else None,
            recommendations=recommendations,
            created_by=created_by or "system"
        )
        
        self.db.add(lba)
        await self.db.commit()
        await self.db.refresh(lba)
        return lba
    
    async def list_line_balance_analyses(
        self,
        factory_id: str,
        product_id: Optional[str] = None,
        limit: int = 100
    ) -> List[LineBalanceAnalysis]:
        """查询产线平衡分析报告列表"""
        query = select(LineBalanceAnalysis).where(LineBalanceAnalysis.factory_id == factory_id)
        
        if product_id:
            query = query.where(LineBalanceAnalysis.product_id == product_id)
        
        result = await self.db.execute(query.order_by(LineBalanceAnalysis.analysis_date.desc()).limit(limit))
        return list(result.scalars().all())


class ProcessAnalysisService:
    """工序价值分析服务 - VA/NVA分解分析"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_process_analysis(
        self,
        factory_id: str,
        product_id: str,
        operation_code: str,
        total_process_time_min: float,
        va_time_min: float,
        nva_time_min: float,
        wait_time_min: float = 0.0,
        move_time_min: float = 0.0,
        inspect_time_min: float = 0.0,
        lead_time: Optional[float] = None,
        efficiency_score: Optional[float] = None,
        created_by: Optional[str] = None
    ) -> ProcessAnalysis:
        """创建工序价值分析记录"""
        if lead_time is None:
            lead_time = total_process_time_min
        
        # 计算VA比率
        va_ratio = round(va_time_min / total_process_time_min, 4) if total_process_time_min > 0 else 0
        
        # 计算效率评分
        if efficiency_score is None:
            efficiency_score = round(va_ratio * 100, 2)
        
        pa = ProcessAnalysis(
            factory_id=factory_id,
            product_id=product_id,
            operation_code=operation_code,
            analysis_date=datetime.utcnow(),
            total_process_time_min=total_process_time_min,
            va_time_min=va_time_min,
            nva_time_min=nva_time_min,
            wait_time_min=wait_time_min,
            move_time_min=move_time_min,
            inspect_time_min=inspect_time_min,
            va_ratio=va_ratio,
            lead_time=lead_time,
            efficiency_score=round(efficiency_score, 2),
            created_by=created_by or "system"
        )
        
        self.db.add(pa)
        await self.db.commit()
        await self.db.refresh(pa)
        return pa
    
    async def list_process_analyses(
        self,
        factory_id: str,
        product_id: Optional[str] = None,
        limit: int = 100
    ) -> List[ProcessAnalysis]:
        """查询工序价值分析列表"""
        query = select(ProcessAnalysis).where(ProcessAnalysis.factory_id == factory_id)
        
        if product_id:
            query = query.where(ProcessAnalysis.product_id == product_id)
        
        result = await self.db.execute(query.order_by(ProcessAnalysis.analysis_date.desc()).limit(limit))
        return list(result.scalars().all())

    async def get_process_flow_analysis(
        self,
        factory_id: str,
        product_id: Optional[str] = None,
    ) -> List[dict]:
        """获取工序流分析结果（供 lean-metrics 端点使用）"""
        analyses = await self.list_process_analyses(
            factory_id=factory_id, product_id=product_id, limit=500
        )
        return [
            {
                "operation_code": a.operation_code,
                "va_time_min": a.va_time_min or 0,
                "nva_time_min": a.nva_time_min or 0,
                "va_ratio": a.va_ratio or 0,
                "efficiency_score": a.efficiency_score or 0,
            }
            for a in analyses
        ]
