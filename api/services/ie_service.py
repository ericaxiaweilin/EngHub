"""
IE Service Layer - Industrial Engineering Services
精益生产工程服务：标准工时、时间研究、线平衡分析、工序价值分析
"""
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func, join, and_
from sqlalchemy.orm import selectinload
import json

from database.models import (
    StandardOperationTime,
    TimeStudyRecord,
    LineBalanceAnalysis,
    ProcessAnalysis,
    WorkOrder,
    RoutingTemplate,
    RoutingTemplateStep,
    ProductionReport,
    Station,
    Product,
)


class StandardTimeService:
    """标准工时管理服务 - 管理标准作业时间(SOT)"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_standard_time(
        self,
        factory_id: str,
        product_id: str,
        routing_step: str,
        operation_name: str,
        operation_seq: Optional[int] = None,
        station_id: Optional[str] = None,
        work_center: Optional[str] = None,
        standard_time_min: float = 0.0,
        unit_time_type: str = "per_piece",
        setup_time_min: float = 0.0,
        setup_before_start_time_min: float = 0.0,
        post_operation_time_min: float = 0.0,
        batch_size: int = 1,
        rating_factor: float = 1.0,
        allowance_rate: float = 0.15,
        validity_start: Optional[datetime] = None,
        validity_end: Optional[datetime] = None,
        created_by: Optional[str] = None,
        version: str = "v1"
    ) -> StandardOperationTime:
        """创建或更新标准工时记录"""
        if validity_start is None:
            validity_start = datetime.utcnow()
        
        # 计算有效标准时间（含宽放）
        effective_standard_time = standard_time_min * (1 + allowance_rate) if unit_time_type == "per_piece" else standard_time_min
        
        sot = StandardOperationTime(
            factory_id=factory_id,
            product_id=product_id,
            routing_step=routing_step,
            operation_seq=operation_seq,
            operation_name=operation_name,
            station_id=station_id,
            work_center=work_center,
            standard_time_min=standard_time_min,
            unit_time_type=unit_time_type,
            setup_time_min=setup_time_min,
            setup_before_start_time_min=setup_before_start_time_min,
            post_operation_time_min=post_operation_time_min,
            batch_size=batch_size,
            rating_factor=rating_factor,
            allowance_rate=allowance_rate,
            effective_standard_time=effective_standard_time,
            version=version,
            is_active=True,
            validity_start=validity_start,
            validity_end=validity_end,
            created_by=created_by,
            updated_by=created_by or "system"
        )
        
        self.db.add(sot)
        await self.db.commit()
        await self.db.refresh(sot)
        return sot
    
    async def get_active_sots(
        self,
        factory_id: str,
        product_id: Optional[str] = None,
        station_id: Optional[str] = None,
        routing_step: Optional[str] = None,
        include_expired: bool = False
    ) -> List[StandardOperationTime]:
        """获取当前有效的标准工时列表"""
        query = select(StandardOperationTime).where(
            StandardOperationTime.factory_id == factory_id,
            StandardOperationTime.is_active == True,
        )
        
        if not include_expired:
            # 只包含未过期的记录
            now = datetime.utcnow()
            query = query.where(
                or_(
                    StandardOperationTime.validity_end > now,
                    StandardOperationTime.validity_end == None
                )
            )
        
        if product_id:
            query = query.where(StandardOperationTime.product_id == product_id)
        if station_id:
            query = query.where(StandardOperationTime.station_id == station_id)
        if routing_step:
            query = query.where(StandardOperationTime.routing_step == routing_step)
        
        result = await self.db.execute(query.order_by(StandardOperationTime.routing_step))
        return result.scalars().all()
    
    async def get_sot_by_id(self, sot_id: str) -> Optional[StandardOperationTime]:
        """根据ID获取标准工时"""
        result = await self.db.execute(select(StandardOperationTime).where(StandardOperationTime.id == sot_id))
        return result.scalar_one_or_none()
    
    async def update_standard_time(
        self,
        sot_id: str,
        **kwargs
    ) -> Optional[StandardOperationTime]:
        """更新标准工时记录"""
        sot = await self.get_sot_by_id(sot_id)
        if not sot:
            return None
        
        # 计算新的有效标准时间
        if 'standard_time_min' in kwargs or 'allowance_rate' in kwargs or 'unit_time_type' in kwargs:
            std_time = kwargs.get('standard_time_min', sot.standard_time_min)
            rate = kwargs.get('allowance_rate', sot.allowance_rate)
            u_type = kwargs.get('unit_time_type', sot.unit_time_type)
            effective = std_time * (1 + rate) if u_type == "per_piece" else std_time
            kwargs['effective_standard_time'] = effective
        
        # 更新字段
        for key, value in kwargs.items():
            if hasattr(sot, key):
                setattr(sot, key, value)
        
        sot.updated_by = kwargs.get('updated_by', sot.updated_by)
        sot.updated_at = datetime.utcnow()
        
        await self.db.commit()
        await self.db.refresh(sot)
        return sot
    
    async def list_sot_summary(self, factory_id: str, product_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取标准工时汇总信息"""
        query = select(
            StandardOperationTime.product_id,
            StandardOperationTime.routing_step,
            StandardOperationTime.operation_name,
            func.max(StandardOperationTime.validity_start).label('latest_version'),
            StandardOperationTime.standard_time_min,
            StandardOperationTime.effective_standard_time,
            StandardOperationTime.rating_factor,
            StandardOperationTime.allowance_rate
        ).where(StandardOperationTime.factory_id == factory_id)
        
        if product_id:
            query = query.where(StandardOperationTime.product_id == product_id)
        
        query = query.group_by(
            StandardOperationTime.product_id,
            StandardOperationTime.routing_step,
            StandardOperationTime.operation_name,
            StandardOperationTime.standard_time_min,
            StandardOperationTime.effective_standard_time,
            StandardOperationTime.rating_factor,
            StandardOperationTime.allowance_rate
        ).order_by(StandardOperationTime.routing_step)
        
        result = (await self.db.execute(query)).scalars().all()
        return [
            {
                "product_id": r.product_id,
                "routing_step": r.routing_step,
                "operation_name": r.operation_name,
                "latest_version": r.latest_version.isoformat() if r.latest_version else None,
                "standard_time_min": r.standard_time_min,
                "effective_standard_time": r.effective_standard_time,
                "rating_factor": r.rating_factor,
                "allowance_rate": r.allowance_rate,
            }
            for r in result
        ]


class TimeStudyService:
    """时间研究管理服务 - 采集和分析实际作业时间数据"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_time_study_record(
        self,
        factory_id: str,
        product_id: str,
        station_id: str,
        operation_name: str,
        operator_id: str,
        observer_id: str,
        observed_cycles: List[float],
        observation_date: Optional[datetime] = None,
        rating_factor: float = 1.0,
        method: str = "stopwatch",
        created_by: Optional[str] = None
    ) -> TimeStudyRecord:
        """创建时间研究记录，自动计算正常时间和允许时间"""
        if observation_date is None:
            observation_date = datetime.utcnow()
        
        cycle_count = len(observed_cycles)
        if cycle_count == 0:
            raise ValueError("At least one observation cycle required")
        
        avg_time = sum(observed_cycles) / cycle_count
        normal_time = avg_time * rating_factor
        allowed_time = normal_time * (1 + 0.15)  # default 15% allowance
        
        record = TimeStudyRecord(
            factory_id=factory_id,
            product_id=product_id,
            station_id=station_id,
            operation_name=operation_name,
            operator_id=operator_id,
            observer_id=observer_id,
            observation_date=observation_date,
            observed_cycles=observed_cycles,
            cycle_count=cycle_count,
            average_time=avg_time,
            rating_factor=rating_factor,
            normal_time=normal_time,
            allowed_time=allowed_time,
            allowance_rate=0.15,
            method=method,
            status="pending",
            created_by=created_by or observer_id
        )
        
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)
        return record
    
    async def approve_time_study(self, ts_id: str, approved_by: str) -> Optional[TimeStudyRecord]:
        """批准时间研究记录，并将其转换为有效标准工时"""
        record = await self._get_ts_by_id(ts_id)
        if not record:
            return None
        
        if record.status != "pending":
            raise ValueError("Only pending time studies can be approved")
        
        record.status = "approved"
        record.approved_by = approved_by
        record.updated_at = datetime.utcnow()
        
        await self.db.commit()
        await self.db.refresh(record)
        
        # 自动创建对应的标准工时记录 (可选)
        standard_time = TimeStudyService._calculate_standard_time_from_record(record)
        await self._create_sots_from_time_study(record, standard_time)
        
        return record
    
    async def _get_ts_by_id(self, ts_id: str) -> Optional[TimeStudyRecord]:
        result = await self.db.execute(select(TimeStudyRecord).where(TimeStudyRecord.id == ts_id))
        return result.scalar_one_or_none()
    
    @staticmethod
    def _calculate_standard_time_from_record(record: TimeStudyRecord) -> Dict[str, Any]:
        """从时间研究记录计算标准工时参数"""
        # 取平均值作为标准时间，使用评定后时间
        avg_time = record.average_time
        rating_factor = record.rating_factor
        # 允许时间通常作为基准（包含宽放），再考虑更宽的工厂策略
        base_allowance = max(record.allowance_rate, 0.15)  # 至少15%
        
        return {
            "standard_time_min": round(avg_time * rating_factor, 2),  # Normal time
            "effective_standard_time": round(record.allowed_time, 2),
            "rating_factor": rating_factor,
            "allowance_rate": base_allowance,
        }
    
    async def _create_sots_from_time_study(self, record: TimeStudyRecord, std_params: Dict[str, Any]):
        """从时间研究记录创建标准工时记录"""
        sot = StandardOperationTime(
            factory_id=record.factory_id,
            product_id=record.product_id,
            routing_step=record.operation_name[:4],  # 简化处理，实际应用中应来自产品BOM
            operation_name=record.operation_name,
            station_id=record.station_id,
            standard_time_min=std_params["standard_time_min"],
            unit_time_type="per_piece",
            rating_factor=std_params["rating_factor"],
            allowance_rate=std_params["allowance_rate"],
            effective_standard_time=std_params["effective_standard_time"],
            validity_start=datetime.utcnow(),
            created_by=record.created_by or record.observer_id,
            updated_by=record.created_by or record.observer_id
        )
        self.db.add(sot)
        await self.db.commit()
        await self.db.refresh(sot)
        return sot
    
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
        
        result = await self.db.execute(query.order_by(TimeStudyRecord.observation_date.desc()).limit(limit))
        return result.scalars().all()
    
    async def get_ts_analysis(self, ts_id: str) -> Optional[Dict[str, Any]]:
        """获取时间研究的详细分析报告"""
        record = await self._get_ts_by_id(ts_id)
        if not record:
            return None
        
        return {
            "record": record.to_dict(),
            "analysis": {
                "min_cycle_time": min(record.observed_cycles),
                "max_cycle_time": max(record.observed_cycles),
                "std_deviation": self._std_dev(record.observed_cycles),
                "coefficient_of_variation": self._std_dev(record.observed_cycles) / record.average_time if record.average_time > 0 else 0,
                "efficiency_score": self._calculate_efficiency_score(record),
            },
        }
    
    @staticmethod
    def _std_dev(values: List[float]) -> float:
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return variance ** 0.5
    
    @staticmethod
    def _calculate_efficiency_score(record: TimeStudyRecord) -> float:
        """计算效率评分（简化版）"""
        # CV越小越稳定，效率越高
        cv = record.average_time / (record.std_deviation + 0.001) if record.std_deviation > 0 else 100
        efficiency = min(100, max(0, (1 - min(cv, 1)) * 100))
        return round(efficiency, 1)


class LineBalanceService:
    """产线平衡分析服务 - 计算生产线平衡率和瓶颈"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def analyze_line_balance(
        self,
        factory_id: str,
        line_id: str,
        product_id: str,
        analysis_date: Optional[datetime] = None,
        takt_time: Optional[float] = None
    ) -> LineBalanceAnalysis:
        """执行产线平衡分析"""
        if analysis_date is None:
            analysis_date = datetime.utcnow()
        
        # 获取该产线所有工站的标准时间
        sot_query = select(
            StandardOperationTime.station_id,
            StandardOperationTime.effective_standard_time
        ).where(
            StandardOperationTime.factory_id == factory_id,
            StandardOperationTime.product_id == product_id,
            StandardOperationTime.is_active == True
        )
        
        sot_result = (await self.db.execute(sot_query)).scalars().all()
        
        if not sot_result:
            raise ValueError("No standard times found for this product")
        
        stations = [(row.station_id, row.effective_standard_time) for row in sot_result]
        
        # 计算节拍时间（如果未提供，则取最大工时的1.1倍）
        if takt_time is None:
            max_time = max(st[1] for st in stations)
            takt_time = max_time * 1.1
        
        # 计算总有效时间和各工站闲置时间
        total_effective_time = sum(st[1] for st in stations)
        workstation_count = len(stations)
        
        # 计算平衡率：总有效时间 / (工位×最长工时) × 100%
        max_cycle_time = max(st[1] for st in stations)
        balance_rate = round((total_effective_time / (workstation_count * max_cycle_time)) * 100, 2)
        
        # 计算总闲置时间
        idle_time_total = round(workstation_count * max_cycle_time - total_effective_time, 2)
        
        # 识别瓶颈工站
        bottleneck_station = max(stations, key=lambda x: x[1])[0]
        bottleneck_time = max(stations, key=lambda x: x[1])[1]
        
        # 生成改善建议
        recommendations = self._generate_recommendations(balance_rate, max_cycle_time, takt_time, stations)
        
        is_balanced = balance_rate > 90.0
        
        station_details = []
        for station_id, cycle_time in stations:
            idle_time = round(max_cycle_time - cycle_time, 2)
            balance_pct = round((cycle_time / max_cycle_time) * 100, 2)
            station_details.append({
                "station_id": station_id,
                "cycle_time": cycle_time,
                "idle_time": idle_time,
                "balance_pct": balance_pct,
            })
            
        lba = LineBalanceAnalysis(
            factory_id=factory_id,
            product_id=product_id,
            line_id=line_id,
            analysis_date=analysis_date,
            takt_time_min=takt_time,
            cycle_time_max=max_cycle_time,
            cycle_time_avg=round(total_effective_time / workstation_count, 2),
            balance_rate=balance_rate,
            idle_time_total=idle_time_total,
            workstation_count=workstation_count,
            is_balanced=is_balanced,
            station_details=station_details,
            bottleneck_station=bottleneck_station,
            bottleneck_time=bottleneck_time,
            recommendations=recommendations,
            created_by="system"
        )
        
        self.db.add(lba)
        await self.db.commit()
        await self.db.refresh(lba)
        return lba
    
    def _generate_recommendations(
        self,
        balance_rate: float,
        max_cycle_time: float,
        takt_time: float,
        stations: List[Tuple[str, float]]
    ) -> List[str]:
        """生成平衡改善建议"""
        recommendations = []
        
        if balance_rate < 80:
            recommendations.append(f"产线平衡率较低 ({balance_rate}%)，建议重新分配负荷")
        elif balance_rate < 90:
            recommendations.append(f"产线平衡率尚可 ({balance_rate}%)，有小幅提升空间")
        else:
            recommendations.append(f"产线平衡良好 ({balance_rate}%)，保持当前状态")
        
        if max_cycle_time > takt_time * 1.2:
            bottleneck = max(stations, key=lambda x: x[1])[0]
            recommendations.append(f"瓶颈工序 {bottleneck} 耗时 {max_cycle_time:.2f}min，超过节拍建议 {takt_time*1.2:.2f}min，需重点改善")
        
        # 建议增加并行工作站
        idle_stations = [(s, c) for s, c in stations if c < takt_time * 0.7]
        if idle_stations:
            suggestions = ", ".join([f"{s}" for s, c in idle_stations[:2]])
            recommendations.append(f"考虑在空闲工位 {suggestions} 增加辅助作业")
        
        return recommendations
    
    async def get_line_balance_report(self, lba_id: str) -> Optional[LineBalanceAnalysis]:
        """获取平衡分析报告"""
        result = select(LineBalanceAnalysis).where(LineBalanceAnalysis.id == lba_id)
        return result.scalar_one_or_none()
    
    async def list_line_balances(
        self,
        factory_id: str,
        product_id: Optional[str] = None,
        line_id: Optional[str] = None,
        limit: int = 50
    ) -> List[LineBalanceAnalysis]:
        """查询历史平衡分析报告"""
        query = select(LineBalanceAnalysis).where(LineBalanceAnalysis.factory_id == factory_id)
        
        if product_id:
            query = query.where(LineBalanceAnalysis.product_id == product_id)
        if line_id:
            query = query.where(LineBalanceAnalysis.line_id == line_id)
        
        query = query.order_by(LineBalanceAnalysis.analysis_date.desc()).limit(limit)
        result = (await self.db.execute(query)).scalars().all()
        return result


class ProcessAnalysisService:
    """工序价值分析服务 - VA/NVA 时间分解分析"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_process_analysis(
        self,
        factory_id: str,
        product_id: str,
        operation_code: str,
        va_time: float,
        nva_time: float,
        wait_time: float,
        move_time: float,
        inspect_time: float,
        lead_time: float,
        analysis_date: Optional[datetime] = None,
        created_by: Optional[str] = None
    ) -> ProcessAnalysis:
        """创建工序价值分析报告"""
        if analysis_date is None:
            analysis_date = datetime.utcnow()
        
        total_time = va_time + nva_time + wait_time + move_time + inspect_time
        va_ratio = round(va_time / total_time, 4) if total_time > 0 else 0
        
        # 效率评分：VA比率折算（0-100）
        efficiency_score = round(va_ratio * 100, 2)
        
        pa = ProcessAnalysis(
            factory_id=factory_id,
            product_id=product_id,
            operation_code=operation_code,
            analysis_date=analysis_date,
            total_process_time_min=round(total_time, 2),
            va_time_min=round(va_time, 2),
            nva_time_min=round(nva_time, 2),
            wait_time_min=round(wait_time, 2),
            move_time_min=round(move_time, 2),
            inspect_time_min=round(inspect_time, 2),
            va_ratio=va_ratio,
            lead_time=lead_time,
            efficiency_score=efficiency_score,
            created_by=created_by or "system"
        )
        
        self.db.add(pa)
        await self.db.commit()
        await self.db.refresh(pa)
        return pa
    
    async def get_process_flow_analysis(
        self,
        factory_id: str,
        product_id: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """获取产品的全流程价值分析"""
        query = select(ProcessAnalysis).where(
            ProcessAnalysis.factory_id == factory_id,
            ProcessAnalysis.product_id == product_id
        ).order_by(ProcessAnalysis.analysis_date.desc()).limit(limit)
        
        result = (await self.db.execute(query)).scalars().all()
        return [r.to_dict() for r in result]
    
    async def calculate_leaning_metrics(
        self,
        factory_id: str,
        product_id: str
    ) -> Dict[str, Any]:
        """计算精益生产关键指标"""
        analyses = await self.get_process_flow_analysis(factory_id, product_id)
        
        if not analyses:
            return {"error": "No process analysis data available"}
        
        total_va = sum(a["va_time_min"] for a in analyses)
        total_nva = sum(a["nva_time_min"] for a in analyses)
        total_lead_time = sum(a["lead_time"] for a in analyses)
        avg_va_ratio = sum(a["va_ratio"] for a in analyses) / len(analyses)
        
        return {
            "total_value_added_time": round(total_va, 2),
            "total_non_value_added_time": round(total_nva, 2),
            "overall_va_ratio": round(total_va / (total_va + total_nva), 4) if (total_va + total_nva) > 0 else 0,
            "average_lead_time": round(total_lead_time / len(analyses), 2),
            "average_va_ratio": round(avg_va_ratio * 100, 2),
            "analysis_count": len(analyses),
            "improvement_potential": round((1 - avg_va_ratio) * 100, 2) if avg_ratio < 1 else 0,
        }

class PerformanceRatingService:
    """绩效评级服务 - 基于标准工时的生产效率评估"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def calculate_operator_performance(
        self,
        operator_id: str,
        station_id: str,
        product_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> Dict[str, Any]:
        """计算操作员绩效评级（基于实际产量与标准时间的对比）"""
        from sqlalchemy import or_
        
        # 获取该操作员在该时段内的生产报告
        query = select(
            ProductionReport.good_qty,
            ProductionReport.created_at
        ).where(
            ProductionReport.operator_id == operator_id,
            ProductionReport.station_id == station_id,
            ProductionReport.product_id == product_id,
            ProductionReport.created_at >= start_date,
            ProductionReport.created_at <= end_date,
            ProductionReport.status == "completed"
        )
        
        result = (await self.db.execute(query)).all()
        total_good = sum(r.good_qty for r in result) if result else 0
        
        # 获取对应产品的标准工时
        sot_query = select(StandardOperationTime.effective_standard_time).where(
            StandardOperationTime.station_id == station_id,
            StandardOperationTime.product_id == product_id,
            StandardOperationTime.is_active == True,
            StandardOperationTime.validity_start <= start_date,
            or_(StandardOperationTime.validity_end > start_date, StandardOperationTime.validity_end == None)
        )
        
        sot_result = (await self.db.execute(sot_query)).first()
        standard_time_per_unit = sot_result[0] if sot_result else None
        
        if standard_time_per_unit is None:
            return {
                "operator_id": operator_id,
                "station_id": station_id,
                "product_id": product_id,
                "period": f"{start_date.date()} to {end_date.date()}",
                "total_output": total_good,
                "performance_rating": None,
                "efficiency_pct": None,
                "reason": "No valid standard time found",
            }
        
        # 计算标准总时间
        total_standard_time = total_good * standard_time_per_unit
        
        # 简化计算：使用标准时间的120%作为基准实际投入时间
        actual_time_input = total_good * standard_time_per_unit * 1.2
        
        # 绩效评级 = 标准时间 / 实际时间 * 100%
        performance_rating = round((total_standard_time / max(actual_time_input, 1)) * 100, 1)
        efficiency_pct = min(100, max(50, performance_rating))
        
        return {
            "operator_id": operator_id,
            "station_id": station_id,
            "product_id": product_id,
            "period_start": start_date.isoformat(),
            "period_end": end_date.isoformat(),
            "total_output": total_good,
            "standard_time_per_unit": standard_time_per_unit,
            "total_standard_time_min": round(total_standard_time, 2),
            "actual_time_input_min": round(actual_time_input, 2),
            "performance_rating_pct": performance_rating,
            "efficiency_level": "excellent" if performance_rating > 110 else ("good" if performance_rating > 95 else ("average" if performance_rating > 80 else "needs_improvement")),
        }


class ReportExportService:
    """IE 模块报告导出服务 - 支持 Excel/PDF 等多种格式"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def export_standard_times_to_excel(
        self,
        factory_id: str,
        product_id: Optional[str] = None,
        output_format: str = "xlsx"
    ) -> Dict[str, Any]:
        """导出标准工时表到 Excel"""
        from services.ie_service import StandardTimeService
        sot_service = StandardTimeService(self.db)
        
        sots = await sot_service.get_active_sots(
            factory_id=factory_id,
            product_id=product_id
        )
        
        # 准备导出数据
        export_data = []
        for sot in sots:
            export_data.append({
                "工单编号": sot.routing_step,
                "工序名称": sot.operation_name,
                "工位编号": sot.station_id,
                "标准工时(min)": sot.standard_time_min,
                "有效标准时间(min)": sot.effective_standard_time,
                "设定时间(min)": sot.setup_time_min,
                "批量大小": sot.batch_size,
                "评定系数": sot.rating_factor,
                "宽放率(%)": round(sot.allowance_rate * 100, 1),
                "版本号": sot.version,
                "生效日期": sot.validity_start.isoformat() if sot.validity_start else "",
                "失效日期": sot.validity_end.isoformat() if sot.validity_end else "",
            })
        
        file_path = f"/app/reports/standard_times_{factory_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.{output_format}"
        
        return {
            "file_path": file_path,
            "file_name": f"标准工时表_{factory_id}_{datetime.utcnow().strftime('%Y%m%d')}.{output_format}",
            "record_count": len(export_data),
            "format": output_format,
            "export_date": datetime.utcnow().isoformat(),
            "data": export_data,
        }
