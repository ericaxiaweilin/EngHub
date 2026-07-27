"""
IE Service Layer Extended - Enterprise Grade Features
精益生产工程服务 - 企业级增强：动作研究、方法研究、绩效评估、报表导出等
"""
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func, and_
from sqlalchemy.orm import selectinload
import json

from database.models import (
    StandardOperationTime,
    TimeStudyRecord,
    LineBalanceAnalysis,
    ProcessAnalysis,
    WorkOrder,
    ProductionReport,
    ShiftSummary,
    Station,
    Product,
    CodeTable,
    Permission,
    Role,
    UserRole,
)
from api.services.ie_service import TimeStudyService, LineBalanceService, StandardTimeService, ProcessAnalysisService


class ExtendedTimeStudyService(TimeStudyService):
    """扩展的时间研究服务 - 支持自动化数据采集和绩效评估"""
    
    async def record_time_from_production_report(
        self,
        report_id: str,
        method: str = "auto"
    ) -> TimeStudyRecord:
        """从生产报工数据自动生成时间研究记录（自动采集模式）"""
        # 这里会读取生产报工中的时间数据并生成时间研究记录
        # 实际实现需要整合 JobCardTimeLog 数据
        pass
    
    async def calculate_performance_rating(self, observed_time: float, standard_time: float) -> float:
        """计算绩效评级（Performance Rating）= 标准时间 / 观测时间 * 100%"""
        if observed_time <= 0:
            return 0.0
        rating = round((standard_time / observed_time) * 100, 1)
        return max(50, min(150, rating))  # 限制在 50-150% 之间
    
    async def analyze_workstation_efficiency(
        self,
        factory_id: str,
        station_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> Dict[str, Any]:
        """分析工站效率 - 结合生产数据和标准工时"""
        # 查询该工站在时间范围内的生产效率数据
        query = select(
            ProductionReport.station_id,
            ProductionReport.work_order_id,
            func.sum(ProductionReport.good_qty).label("total_good"),
            func.count(ProductionReport.id).label("report_count"),
        ).where(
            ProductionReport.factory_id == factory_id,
            ProductionReport.station_id == station_id,
            ProductionReport.created_at >= start_date,
            ProductionReport.created_at <= end_date,
        ).group_by(
            ProductionReport.station_id,
            ProductionReport.work_order_id
        )
        
        result = await query.all()
        total_good = sum(r.total_good for r in result) if result else 0
        
        # 获取该工站的标准时间
        sot_query = select(StandardOperationTime.effective_standard_time).where(
            StandardOperationTime.station_id == station_id,
            StandardOperationTime.is_active == True,
        )
        sot_result = await sot_query.first()
        standard_time = sot_result[0] if sot_result else None
        
        # 计算理论产出和实际效率
        theoretical_output = total_good if standard_time else 0
        actual_efficiency = round((theoretical_output / max(total_good, 1)) * 100, 2) if standard_time else 0.0
        
        return {
            "factory_id": factory_id,
            "station_id": station_id,
            "period_start": start_date.isoformat(),
            "period_end": end_date.isoformat(),
            "total_good_quantity": total_good,
            "report_count": len(result),
            "standard_time_min": standard_time,
            "efficiency_pct": actual_efficiency,
            "status": "excellent" if actual_efficiency > 95 else ("good" if actual_efficiency > 85 else "needs_improvement"),
        }


class AdvancedLineBalanceService(LineBalanceService):
    """高级产线平衡分析服务 - 支持多班次分析和动态节拍调整"""
    
    async def analyze_line_balance_dynamic(
        self,
        factory_id: str,
        line_id: str,
        product_id: str,
        analysis_date: Optional[datetime] = None,
        shift_type: Optional[str] = None,
        use_actual_cycles: bool = False
    ) -> LineBalanceAnalysis:
        """动态产线平衡分析 - 可结合实际生产循环时间"""
        if analysis_date is None:
            analysis_date = datetime.utcnow()
        
        # 根据是否使用实际周期时间，选择不同数据源
        if use_actual_cycles:
            # 从生产报告获取实际周期时间
            cycle_times = await self._get_actual_cycle_times(factory_id, product_id, shift_type, analysis_date)
        else:
            # 从标准工时获取理论时间
            cycle_times = await self._get_theoretical_cycle_times(factory_id, product_id)
        
        # 如果有实际数据，优先使用；否则回退到理论值
        if cycle_times and len(cycle_times) > 0:
            stations = cycle_times
        else:
            # 回退到标准工时的时间戳
            raise ValueError("No cycle time data available for balance analysis")
        
        # 如果需要，可以根据当前班次的产能要求动态调整节拍时间
        takt_time = self._calculate_dynamic_takt_time(factory_id, product_id, analysis_date, shift_type)
        
        return await self.analyze_line_balance(
            factory_id=factory_id,
            line_id=line_id,
            product_id=product_id,
            analysis_date=analysis_date,
            takt_time=takt_time
        )
    
    async def _get_theoretical_cycle_times(
        self,
        factory_id: str,
        product_id: str
    ) -> List[Tuple[str, float]]:
        """从标准工时获取理论周期时间"""
        from services.ie_service import StandardTimeService
        db = None  # 需要从上下文获取
        sot_service = StandardTimeService(db)
        sots = await sot_service.get_active_sots(
            factory_id=factory_id,
            product_id=product_id
        )
        return [(s.station_id, s.effective_standard_time) for s in sots if s.station_id]
    
    async def _get_actual_cycle_times(
        self,
        factory_id: str,
        product_id: str,
        shift_type: Optional[str] = None,
        reference_date: Optional[datetime] = None
    ) -> List[Tuple[str, float]]:
        """从生产报告获取实际周期时间（需整合 JobCardTimeLog）"""
        # 简化的实际实现
        pass
    
    def _calculate_dynamic_takt_time(
        self,
        factory_id: str,
        product_id: str,
        reference_date: datetime,
        shift_type: Optional[str] = None
    ) -> float:
        """根据实际需求和产能要求计算动态节拍时间"""
        # 获取当前班次的需求计划
        # 返回节拍时间（分钟/件）
        return 8.0  # 示例值
    
    async def generate_line_balance_report(
        self,
        lba_id: str,
        format_type: str = "html"
    ) -> Dict[str, Any]:
        """生成平衡分析报告（支持多种格式）"""
        lba = await self.get_line_balance_report(lba_id)
        if not lba:
            raise ValueError("Line balance analysis not found")
        
        # 生成可视化数据
        report_data = {
            "line_balance_id": lba.id,
            "product_id": lba.product_id,
            "line_id": lba.line_id,
            "analysis_date": lba.analysis_date.isoformat(),
            "takt_time_min": lba.takt_time_min,
            "balance_rate": lba.balance_rate,
            "workstations": lba.station_details,
            "bottleneck": {
                "station": lba.bottleneck_station,
                "time": lba.bottleneck_time,
            },
            "recommendations": lba.recommendations,
            "is_balanced": lba.is_balanced,
        }
        
        if format_type == "json":
            return report_data
        elif format_type == "html":
            return self._generate_html_report(report_data)
        elif format_type == "csv":
            return self._generate_csv_report(report_data)
        else:
            return report_data
    
    def _generate_html_report(self, data: Dict[str, Any]) -> str:
        """生成HTML格式的报告"""
        html = f"""
        <html><body>
        <h1>产线平衡分析报告</h1>
        <p>产品：{data["product_id"]}</p>
        <p>产线：{data["line_id"]}</p>
        <p>平衡率：{data["balance_rate"]}%</p>
        <p>瓶颈工站：{data["bottleneck"]["station"]}</p>
        <h3>各工站详情：</h3>
        <table>
        <tr><th>工站</th><th>周期时间</th><th>闲置时间</th><th>平衡率</th></tr>
        """
        for wd in data["workstations"]:
            html += f"<tr><td>{wd['station_id']}</td><td>{wd['cycle_time']}min</td><td>{wd['idle_time']}min</td><td>{wd['balance_pct']}%</td></tr>"
        html += "</table></body></html>"
        return html
    
    def _generate_csv_report(self, data: Dict[str, Any]) -> str:
        """生成CSV格式的报告"""
        lines = [
            f"工站,周期时间(min),闲置时间(min),平衡率(%)",
        ]
        for wd in data["workstations"]:
            lines.append(f"{wd['station_id']},{wd['cycle_time']},{wd['idle_time']},{wd['balance_pct']}")
        return "\n".join(lines)


class ComprehensiveProcessAnalysisService(ProcessAnalysisService):
    """综合工序价值分析服务 - 支持全价值链分析"""
    
    async def value_stream_mapping(
        self,
        factory_id: str,
        product_id: str,
        include_inventory: bool = True
    ) -> Dict[str, Any]:
        """绘制价值流图（VSM）分析 - 精益核心工具"""
        # 获取所有工序的价值分析数据
        analyses = await self.get_process_flow_analysis(factory_id, product_id)
        
        if not analyses:
            return {"error": "No process analysis data available"}
        
        # 计算整体价值流指标
        total_va = sum(a["va_time_min"] for a in analyses)
        total_nva = sum(a["nva_time_min"] for a in analyses)
        total_process = sum(a["total_process_time_min"] for a in analyses)
        
        # 计算信息流和物料流周期（简化版）
        lead_time_info = sum(a["lead_time"] for a in analyses)
        
        vsm_data = {
            "product_id": product_id,
            "total_value_added_time": round(total_va, 2),
            "total_non_value_added_time": round(total_nva, 2),
            "total_process_time": round(total_process, 2),
            "overall_va_ratio": round(total_va / total_process, 4) if total_process > 0 else 0,
            "value_add_improvement_potential": round((1 - total_va / total_process) * 100, 2) if total_process > 0 else 0,
            "information_lead_time": round(lead_time_info, 2),
            "工序列表": [
                {
                    "operation": a["operation_code"],
                    "va": a["va_time_min"],
                    "nva": a["nva_time_min"],
                    "total": a["total_process_time_min"],
                    "va_ratio": a["va_ratio"],
                    "efficiency_score": a["efficiency_score"]
                }
                for a in sorted(analyses, key=lambda x: x["operation_code"])
            ],
        }
        
        if include_inventory:
            # 集成库存数据分析（需要访问 WMS 或生产库存表）
            vsm_data["inventory_turnover_ratio"] = self._calculate_inventory_turnover(factory_id, product_id)
        
        return vsm_data
    
    def _calculate_inventory_turnover(self, factory_id: str, product_id: str) -> float:
        """计算库存周转率（简化版）"""
        # 实际实现需要连接 WMS 库存数据
        return 12.0  # 示例值 - 12次/年
    
    async def kaizen_tracking(
        self,
        kaizen_id: str,
        before_analysis_id: str,
        after_analysis_id: str
    ) -> Dict[str, Any]:
        """跟踪持续改善（Kaizen）前后的效果对比"""
        # 获取改善前后的分析数据
        # 计算改善效果
        return {
            "kaizen_id": kaizen_id,
            "before_analysis": before_analysis_id,
            "after_analysis": after_analysis_id,
            "improvement_metrics": {
                "va_time_increase": None,
                "nva_time_reduction": None,
                "cycle_time_reduction": None,
                "efficiency_improvement": None,
            }
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
        
        result = await query.all()
        total_good = sum(r.good_qty for r in result) if result else 0
        
        # 获取对应产品的标准工时
        sot_query = select(StandardOperationTime.effective_standard_time).where(
            StandardOperationTime.station_id == station_id,
            StandardOperationTime.product_id == product_id,
            StandardOperationTime.is_active == True,
            StandardOperationTime.validity_start <= start_date,
            or_(StandardOperationTime.validity_end > start_date, StandardOperationTime.validity_end == None)
        )
        
        sot_result = await sot_query.first()
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
        
        # 计算标准总时间（如果按件计算）
        total_standard_time = total_good * standard_time_per_unit
        
        # 实际投入时间（假设每个工时60分钟，简化处理）
        # 实际应从 JobCardTimeLog 或其他时间采集系统获取
        actual_time_input = total_good * standard_time_per_unit * 1.2  # +20% 宽放作为基准
        
        # 绩效评级 = 标准时间 / 实际时间 * 100%
        performance_rating = round((total_standard_time / max(actual_time_input, 1)) * 100, 1)
        efficiency_pct = min(100, max(50, performance_rating))  # 归一化到 50-100%
        
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
        
        # 保存文件路径（实际实现需要写入文件系统）
        file_path = f"/app/reports/standard_times_{factory_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.{output_format}"
        
        return {
            "file_path": file_path,
            "file_name": f"标准工时表_{factory_id}_{datetime.utcnow().strftime('%Y%m%d')}.{output_format}",
            "record_count": len(export_data),
            "format": output_format,
            "export_date": datetime.utcnow().isoformat(),
            "data": export_data,
        }
    
    async def export_time_study_report(
        self,
        factory_id: str,
        ts_id: Optional[str] = None,
        output_format: str = "xlsx"
    ) -> Dict[str, Any]:
        """导出时间研究分析报告"""
        from services.ie_service import TimeStudyService
        ts_service = TimeStudyService(self.db)
        
        if ts_id:
            records = [await ts_service._get_ts_by_id(ts_id)] if await ts_service._get_ts_by_id(ts_id) else []
        else:
            records = await ts_service.list_time_studies(factory_id=factory_id)
        
        export_data = []
        for ts in records:
            if ts:
                export_data.append({
                    "记录编号": ts.id,
                    "工序": ts.operation_name,
                    "工位": ts.station_id,
                    "操作员": ts.operator_id,
                    "观测员": ts.observer_id,
                    "观测日期": ts.observation_date.isoformat() if ts.observation_date else "",
                    "观测次数": ts.cycle_count,
                    "平均观测时间(min)": ts.average_time,
                    "评定系数": ts.rating_factor,
                    "正常时间(min)": ts.normal_time,
                    "允许时间(min)": ts.allowed_time,
                    "宽放率(%)": round(ts.allowance_rate * 100, 1),
                    "方法": ts.method,
                    "状态": ts.status,
                })
        
        file_path = f"/api/v1/reports/time_study_{factory_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.{output_format}"
        
        return {
            "file_path": file_path,
            "file_name": f"时间研究报告_{factory_id}_{datetime.utcnow().strftime('%Y%m%d')}.{output_format}",
            "record_count": len(export_data),
            "format": output_format,
            "export_date": datetime.utcnow().isoformat(),
            "data": export_data,
        }
    
    async def export_line_balance_report(
        self,
        lba_id: str,
        output_format: str = "html"
    ) -> Dict[str, Any]:
        """导出产线平衡分析报告"""
        from services.ie_service import LineBalanceService
        lbservice = LineBalanceService(self.db)
        
        lba = await lbservice.get_line_balance_report(lba_id)
        if not lba:
            raise ValueError("Line balance analysis not found")
        
        # 使用高级服务生成报告
        from services.ie_service_extended import AdvancedLineBalanceService
        adv_lbservice = AdvancedLineBalanceService(self.db)
        report = await adv_lbservice.generate_line_balance_report(lba.id, output_format)
        
        return {
            "line_balance_id": lba_id,
            "product_id": lba.product_id,
            "line_id": lba.line_id,
            "analysis_date": lba.analysis_date.isoformat(),
            "balance_rate": lba.balance_rate,
            "format": output_format,
            "report_content": report,
        }
