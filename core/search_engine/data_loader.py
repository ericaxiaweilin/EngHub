"""
MES 生产数据加载器
从数据库或 API 加载数据到搜索引擎
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import random

from .engine import MESSearchEngine


class MESDataLoader:
    """MES 数据加载器 - 提供示例数据和真实数据接口"""
    
    def __init__(self, engine: MESSearchEngine):
        self.engine = engine
    
    def load_sample_data(self):
        """加载示例数据用于测试"""
        
        # 工单数据
        work_orders = [
            {
                "id": "WO202401001",
                "code": "WO-2024-001",
                "name": "iPhone 15 Pro 组装工单",
                "product_name": "iPhone 15 Pro",
                "quantity": 500,
                "completed_quantity": 320,
                "status": "running",
                "priority": "high",
                "start_date": "2024-01-15",
                "end_date": "2024-01-20",
                "description": "iPhone 15 Pro 总装线生产工单，包含主板安装、屏幕组装、电池安装等工序"
            },
            {
                "id": "WO202401002",
                "code": "WO-2024-002",
                "name": "MacBook Air M3 组装工单",
                "product_name": "MacBook Air M3",
                "quantity": 300,
                "completed_quantity": 300,
                "status": "completed",
                "priority": "normal",
                "start_date": "2024-01-10",
                "end_date": "2024-01-14",
                "description": "MacBook Air M3 笔记本组装，包括键盘测试、屏幕校准、系统烧录"
            },
            {
                "id": "WO202401003",
                "code": "WO-2024-003",
                "name": "iPad Pro 12.9 组装工单",
                "product_name": "iPad Pro 12.9",
                "quantity": 200,
                "completed_quantity": 50,
                "status": "paused",
                "priority": "urgent",
                "start_date": "2024-01-18",
                "end_date": "2024-01-22",
                "description": "iPad Pro 大屏版本组装，因物料短缺暂停"
            }
        ]
        
        # 工位数据
        stations = [
            {
                "id": "STN001",
                "code": "SMT-01",
                "name": "SMT 贴片线 1 号",
                "type": "SMT",
                "category": "assembly",
                "status": "running",
                "capacity_per_hour": 1200,
                "current_oee": 0.85,
                "description": "高速 SMT 贴片机，负责 PCB 主板元器件贴装，配备 Fuji NXT III 设备"
            },
            {
                "id": "STN002",
                "code": "ASSY-01",
                "name": "总装线 1 号",
                "type": "Assembly",
                "category": "assembly",
                "status": "running",
                "capacity_per_hour": 150,
                "current_oee": 0.78,
                "description": "产品总装生产线，包含 15 个工位，完成最终产品组装和包装"
            },
            {
                "id": "STN003",
                "code": "QC-01",
                "name": "质量检验站 1 号",
                "type": "Quality",
                "category": "inspection",
                "status": "running",
                "capacity_per_hour": 200,
                "current_oee": 0.92,
                "description": "FQC 最终质量检验站，进行外观检查、功能测试、包装验证"
            },
            {
                "id": "STN004",
                "code": "TEST-01",
                "name": "功能测试站",
                "type": "Testing",
                "category": "testing",
                "status": "maintenance",
                "capacity_per_hour": 100,
                "current_oee": 0.45,
                "description": "产品功能测试站，目前设备进行定期保养维护"
            }
        ]
        
        # 设备数据
        devices = [
            {
                "id": "DEV001",
                "code": "FUJI-NXT3-01",
                "name": "Fuji NXT III 贴片机 1 号",
                "type": "SMT",
                "brand": "Fuji",
                "model": "NXT III",
                "status": "running",
                "location": "车间 A-SMT 区",
                "install_date": "2022-03-15",
                "last_maintenance": "2024-01-10",
                "next_maintenance": "2024-02-10",
                "description": "高速多功能贴片机，支持 0201-50mm 元件，最大速度 25000 CPH"
            },
            {
                "id": "DEV002",
                "code": "AOI-01",
                "name": "AOI 自动光学检测仪",
                "type": "Inspection",
                "brand": "Koh Young",
                "model": "KY8030",
                "status": "running",
                "location": "车间 A-SMT 区",
                "install_date": "2022-03-15",
                "last_maintenance": "2024-01-05",
                "next_maintenance": "2024-02-05",
                "description": "3D SPI 锡膏检测和 AOI 焊后检测一体机，检测精度±1μm"
            },
            {
                "id": "DEV003",
                "code": "ROBOT-01",
                "name": "装配机器人 1 号",
                "type": "Robot",
                "brand": "ABB",
                "model": "IRB 1200",
                "status": "alarm",
                "location": "车间 B-总装区",
                "install_date": "2023-06-20",
                "last_maintenance": "2024-01-12",
                "next_maintenance": "2024-02-12",
                "alarm_message": "伺服电机过热警告",
                "description": "6 轴精密装配机器人，用于屏幕与机身精密贴合"
            }
        ]
        
        # 物料数据
        materials = [
            {
                "id": "MAT001",
                "code": "IC-APL-A17",
                "name": "Apple A17 Pro 芯片",
                "category": "IC",
                "specification": "3nm, 19B transistors",
                "supplier": "TSMC",
                "unit": "PCS",
                "stock_quantity": 5000,
                "safety_stock": 1000,
                "status": "normal",
                "description": "iPhone 15 Pro 主处理器，台积电 3nm 工艺制造"
            },
            {
                "id": "MAT002",
                "code": "LCD-6.1-OLED",
                "name": "6.1 英寸 OLED 显示屏",
                "category": "Display",
                "specification": "2556x1179, 120Hz ProMotion",
                "supplier": "Samsung",
                "unit": "PCS",
                "stock_quantity": 800,
                "safety_stock": 1000,
                "status": "low_stock",
                "description": "Super Retina XDR 显示屏，LTPO 技术，峰值亮度 2000nit"
            },
            {
                "id": "MAT003",
                "code": "BAT-LI-3274",
                "name": "锂离子电池 3274mAh",
                "category": "Battery",
                "specification": "3.85V, 3274mAh, L-shaped",
                "supplier": "CATL",
                "unit": "PCS",
                "stock_quantity": 15000,
                "safety_stock": 3000,
                "status": "normal",
                "description": "定制 L 型锂离子电池，支持快充和 MagSafe 无线充电"
            }
        ]
        
        # 质量数据
        quality_records = [
            {
                "id": "QC20240115001",
                "code": "FQC-2024-001",
                "name": "iPhone 15 Pro FQC 检验记录",
                "inspection_type": "FQC",
                "work_order": "WO202401001",
                "station": "STN003",
                "inspector": "张三",
                "inspect_time": "2024-01-15 14:30:00",
                "sample_size": 50,
                "defect_count": 2,
                "pass_rate": 0.96,
                "result": "PASS",
                "description": "最终质量检验，发现 2 例屏幕轻微划痕，已返工处理"
            },
            {
                "id": "QC20240115002",
                "code": "IPQC-2024-001",
                "name": "SMT 制程巡检记录",
                "inspection_type": "IPQC",
                "work_order": "WO202401001",
                "station": "STN001",
                "inspector": "李四",
                "inspect_time": "2024-01-15 10:00:00",
                "sample_size": 100,
                "defect_count": 5,
                "pass_rate": 0.95,
                "result": "PASS",
                "description": "SMT 首件检验和过程巡检，锡膏印刷质量良好，贴片偏移在允许范围内"
            }
        ]
        
        # SOP 数据
        sops = [
            {
                "id": "SOP001",
                "code": "SOP-SMT-001",
                "name": "SMT 贴片作业指导书",
                "category": "SMT",
                "version": "V3.2",
                "effective_date": "2024-01-01",
                "author": "工程部",
                "status": "active",
                "content": "本指导书规范 SMT 贴片生产线的操作流程，包括锡膏印刷、SPI 检测、元件贴装、回流焊接、AOI 检测等工序的标准作业方法。关键控制点：锡膏厚度 0.12-0.15mm，贴片精度±0.05mm，回流焊温度曲线符合无铅工艺要求。",
                "description": "SMT 表面贴装技术完整作业流程规范"
            },
            {
                "id": "SOP002",
                "code": "SOP-ASSY-001",
                "name": "产品总装作业指导书",
                "category": "Assembly",
                "version": "V2.8",
                "effective_date": "2024-01-01",
                "author": "工程部",
                "status": "active",
                "content": "本指导书规范产品总装线的作业流程，包括预组装、主板安装、电池安装、屏幕组装、后盖安装、螺丝锁付、功能测试、包装等工序。扭矩控制要求：M1.4 螺丝 0.13Nm，M1.6 螺丝 0.18Nm。",
                "description": "消费电子产品总装标准作业程序"
            },
            {
                "id": "SOP003",
                "code": "SOP-QC-001",
                "name": "FQC 最终检验作业指导书",
                "category": "Quality",
                "version": "V4.1",
                "effective_date": "2024-01-01",
                "author": "质量部",
                "status": "active",
                "content": "本指导书规范 FQC 最终质量检验的标准，包括外观检验标准（划痕、脏污、缝隙）、功能测试项目（按键、触控、摄像头、音频）、包装检验要求。AQL 水准：Major 0.65, Minor 1.0。",
                "description": "最终成品质量检验标准和操作规范"
            }
        ]
        
        # 索引所有示例数据
        self.engine.index_data("work_order", work_orders)
        self.engine.index_data("station", stations)
        self.engine.index_data("device", devices)
        self.engine.index_data("material", materials)
        self.engine.index_data("quality", quality_records)
        self.engine.index_data("sop", sops)
        
        return {
            "work_orders": len(work_orders),
            "stations": len(stations),
            "devices": len(devices),
            "materials": len(materials),
            "quality_records": len(quality_records),
            "sops": len(sops),
            "total": len(work_orders) + len(stations) + len(devices) + len(materials) + len(quality_records) + len(sops)
        }
    
    def load_from_database(self, db_url: str):
        """从数据库加载真实数据（待实现）"""
        # TODO: 连接真实 MES 数据库加载数据
        pass
    
    def load_from_api(self, api_base_url: str, token: str):
        """从 API 加载数据（待实现）"""
        # TODO: 调用 MES API 获取数据
        pass
