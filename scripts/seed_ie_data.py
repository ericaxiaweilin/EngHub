#!/usr/bin/env python3
"""
IE精益生产模块数据种子脚本（可重复运行）

为以下表填充演示数据，支持多次运行：
- standard_operation_times (标准工时)
- time_study_records (时间研究观测记录)
- line_balance_analyses (产线平衡分析)
- process_analyses (工序价值分析)
- action_studies (动作研究)
- method_studies (方法研究)
- work_cell_layouts (工站布局)
- kanban_systems (Kanban看板)
- five_s_audits (5S审计)
- skills (技能库)
- products (产品主数据)
- stations (工位)
- equipment (设备)
"""

import asyncio
import sys
from datetime import datetime, timedelta
from uuid import uuid4

sys.path.insert(0, ".")

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.db_config import db_config
from database.models import (
    StandardOperationTime, TimeStudyRecord, LineBalanceAnalysis, ProcessAnalysis,
    ActionStudy, MethodStudy, WorkCellLayout, KanbanSystem, FiveSAudit,
    Product, Station, Equipment, Skill, EmployeeSkill, TrainingRecord,
    Inventory, InboundOrder, OutboundOrder
)


async def cleanup_existing_data(session: AsyncSession, factory_id: str):
    """清理之前运行的种子数据（按外键依赖顺序，从子表到父表）"""
    print("⚠  清理已存在的种子数据...")
    
    # Delete child tables first (tables with foreign keys)
    delete_order = [
        # IE module tables
        ActionStudy,
        MethodStudy,
        KanbanSystem,
        FiveSAudit,
        TimeStudyRecord,
        StandardOperationTime,
        LineBalanceAnalysis,
        ProcessAnalysis,
        WorkCellLayout,
        EmployeeSkill,
        TrainingRecord,
        # WMS-related (for product references)
        Inventory,  # Need to check if inventory exists
        InboundOrder,
        OutboundOrder,
        # Other supporting tables
        Equipment,
        Station,
        Product,
        Skill,  # Only delete skills we added with specific codes
    ]
    
    for model in delete_order:
        try:
            # Build delete statement based on available columns
            delete_stmt = model.__table__.delete()
            # Filter by factory_id where applicable, or by specific seed markers
            if hasattr(model, 'factory_id'):
                delete_stmt = delete_stmt.where(model.factory_id == factory_id)
            elif hasattr(model, 'code') and model in [Skill, Product, Station]:
                # For skill/product/station, delete only seed entries with predictable patterns
                if model == Skill:
                    delete_stmt = delete_stmt.where(model.code.in_(
                        ['SMT01', 'QC01', 'LEAN01', 'TIME01', 'BALANCE01']
                    ))
                elif model == Product:
                    delete_stmt = delete_stmt.where(model.product_code.like('P%'))
                elif model == Station:
                    delete_stmt = delete_stmt.where(model.station_code.like('S%'))
            else:
                # For tables without clear markers, we skip cleanup to avoid data loss
                continue
            
            result = await session.execute(delete_stmt)
            if result.rowcount > 0:
                print(f"   - 清除了 {model.__tablename__}: {result.rowcount} 行")
        except Exception as e:
            # Silently ignore tables that may not have the expected columns
            pass
    
    await session.commit()


async def main():
    await db_config.init_db()
    async with db_config.session_factory() as session:
        factory_id = "factory-sh-01"
        current_time = datetime.utcnow()

        # ============================================================
        # Step 1: Cleanup existing seed data
        # ============================================================
        await cleanup_existing_data(session, factory_id)

        # ============================================================
        # 2. 创建产品主数据
        # ============================================================
        print("\n★ 创建产品主数据...")
        products = []
        for i in range(1, 4):
            prod_id = str(uuid4())
            products.append({
                "id": prod_id,
                "factory_id": factory_id,
                "product_code": f"P{i:03d}",
                "product_name": f"电子产品组装-{i}",
                "category": "Electronics",
                "unit": "pcs",
                "status": "active",
            })
            product = Product(**products[-1])
            session.add(product)
        print(f"  ✓ 创建了 {len(products)} 个产品")

        # ============================================================
        # 3. 创建工位和设备
        # ============================================================
        print("\n★ 创建工位和设备...")
        stations = []
        for d in range(1, 7):
            sid = str(uuid4())
            stations.append({
                "id": sid,
                "station_code": f"S{d:02d}",
                "station_name": f"第{d}工位",
                "factory_id": factory_id,
                "station_type": "Assembly" if d <= 5 else "Testing",
                "capacity_per_hour": 120 if d <= 5 else 80,
                "status": "active",
            })
            station = Station(**stations[-1])
            session.add(station)
        
        equipment = []
        for d in range(1, 7):
            eid = str(uuid4())
            equip_type = "SMT" if d <= 3 else "Tester"
            equip_name = f"贴片机-{d}" if d <= 3 else f"测试台-{d-3}"
            stations_ref = stations[(d-1) % len(stations)]
            equipment.append({
                "id": eid,
                "equipment_code": f"E{d:03d}",
                "equipment_name": equip_name,
                "factory_id": factory_id,
                "station_id": stations_ref["id"],
                "equipment_type": equip_type,
                "status": "available",
            })
            equip = Equipment(**equipment[-1])
            session.add(equip)
        print(f"  ✓ 创建了 {len(stations)} 个工位, {len(equipment)} 台设备")

        # ============================================================
        # 4. 创建技能库
        # ============================================================
        print("\n★ 创建技能库...")
        skills_specs = [
            {"code": "SMT01", "name": "表面贴装技术", "category": "Manufacturing", "is_active": True},
            {"code": "QC01", "name": "质量检验", "category": "Quality", "is_active": True},
            {"code": "LEAN01", "name": "精益生产", "category": "Lean", "is_active": True},
            {"code": "TIME01", "name": "时间研究", "category": "IndustrialEngineering", "is_active": True},
            {"code": "BALANCE01", "name": "产线平衡", "category": "Lean", "is_active": True},
        ]
        
        existing_result = await session.execute(select(Skill.code))
        existing_codes_list = set([r[0] for r in existing_result.scalars()])
        
        new_skills_spec = [s for s in skills_specs if s["code"] not in existing_codes_list]
        
        if new_skills_spec:
            max_id_result = await session.execute(func.max(Skill.id))
            max_id = max_id_result.scalar() or 0
            for idx, s_data in enumerate(new_skills_spec, start=max_id + 1):
                skill = Skill(id=idx, **s_data)
                session.add(skill)
            print(f"  ✓ 新增了 {len(new_skills_spec)} 项技能")
        else:
            print("  ✓ 技能已存在，跳过创建")

        # ============================================================
        # 5. 创建标准工时记录 (至少10条，覆盖3个产品)
        # ============================================================
        print("\n★ 创建标准工时记录...")
        sot_data = []
        current = datetime.utcnow()
        
        # Product P001 (A01-A04)
        for i in range(4):
            sot_data.append({
                "id": str(uuid4()),
                "factory_id": factory_id,
                "product_id": products[0]["product_code"],
                "routing_step": "A01",
                "operation_name": "贴片电阻电容",
                "station_id": stations[0]["id"],
                "work_center": "SMT-A1",
                "standard_time_min": round(0.75 + i * 0.05, 2),
                "unit_time_type": "per_unit",
                "setup_time_min": round(2.0 + 0.5 * i, 2),
                "batch_size": 100 + 50 * i,
                "rating_factor": round(0.95 + 0.05 * i, 2),
                "allowance_rate": 0.15,
                "effective_standard_time": round(round(0.75 + i * 0.05, 2) * 1.15, 2),
                "version": "v1",
                "is_active": True,
                "validity_start": current,
                "validity_end": current + timedelta(days=365),
                "created_by": "system",
            })
        
        # Product P002 (A01-A03)
        for i in range(3):
            sot_data.append({
                "id": str(uuid4()),
                "factory_id": factory_id,
                "product_id": products[1]["product_code"],
                "routing_step": f"A{i+1}",
                "operation_name": f"插件焊接-{i+1}" if i < 2 else "最终测试",
                "station_id": stations[i % len(stations)]["id"],
                "work_center": f"ASSY-{i+1}",
                "standard_time_min": round(2.0 + i * 0.1, 2),
                "unit_time_type": "per_unit",
                "setup_time_min": 5.0,
                "batch_size": 50,
                "rating_factor": 1.0,
                "allowance_rate": 0.15,
                "effective_standard_time": round(round(2.0 + i * 0.1, 2) * 1.15, 2),
                "version": "v1",
                "is_active": True,
                "validity_start": current,
                "validity_end": current + timedelta(days=365),
                "created_by": "system",
            })
        
        # Product P003 (A01-A04)
        for i in range(4):
            sot_data.append({
                "id": str(uuid4()),
                "factory_id": factory_id,
                "product_id": products[2]["product_code"],
                "routing_step": f"A{i+1}",
                "operation_name": f"包装装箱-{i+1}" if i < 3 else "终检",
                "station_id": stations[i % len(stations)]["id"],
                "work_center": f"PACK-{i+1}",
                "standard_time_min": round(1.0 + i * 0.02, 2),
                "unit_time_type": "per_batch",
                "setup_time_min": 1.0,
                "batch_size": 20 + 5 * i,
                "rating_factor": round(1.0 - 0.02 * i, 2),
                "allowance_rate": 0.10,
                "effective_standard_time": round(round(1.0 + i * 0.02, 2) * 1.10, 2),
                "version": "v1",
                "is_active": True,
                "validity_start": current,
                "validity_end": current + timedelta(days=365),
                "created_by": "system",
            })
        
        for sot in sot_data:
            session.add(StandardOperationTime(**sot))
        print(f"  ✓ 创建了 {len(sot_data)} 条标准工时记录")

        # ============================================================
        # 6. 创建时间研究记录 (至少8条)
        # ============================================================
        print("\n★ 创建时间研究记录...")
        ts_data = []
        for i in range(12):
            observed_cycles = [round(45 + j * 0.5, 1) for j in range(5)]
            avg_time = sum(observed_cycles) / len(observed_cycles)
            
            ts_data.append({
                "id": str(uuid4()),
                "factory_id": factory_id,
                "product_id": products[i % 3]["product_code"],
                "station_id": stations[i % len(stations)]["id"],
                "operation_name": f"观测记录-{i+1}",
                "operator_id": f"EMP-{1001 + (i % 10)}",
                "observer_id": f"ENG-{101 + (i // 3)}",
                "observation_date": current_time - timedelta(hours=i),
                "observed_cycles": observed_cycles,
                "cycle_count": 5,
                "average_time": round(avg_time, 2),
                "rating_factor": round(0.9 + (i % 3) * 0.05, 2),
                "normal_time": round(avg_time * (0.9 + (i % 3) * 0.05), 2),
                "allowed_time": round(avg_time * (0.9 + (i % 3) * 0.05) * 1.15, 2),
                "method": "direct" if i % 2 == 0 else "synthetic",
                "status": "approved" if i % 3 == 0 else ("pending" if i % 3 == 1 else "rejected"),
                "created_by": "system",
            })
        
        for ts in ts_data:
            session.add(TimeStudyRecord(**ts))
        print(f"  ✓ 创建了 {len(ts_data)} 条时间研究记录")

        # ============================================================
        # 7. 创建产线平衡分析 (至少3条)
        # ============================================================
        print("\n★ 创建产线平衡分析...")
        lba_data = []
        current = datetime.utcnow()
        for i in range(5):
            balance_rate = round(70 + i * 5, 2)
            bottleneck_id = ((i * 2) % 6) + 1
            lba_data.append({
                "id": str(uuid4()),
                "factory_id": factory_id,
                "product_id": products[i % 3]["product_code"],
                "line_id": f"LINE-{chr(65 + i)}",
                "analysis_date": current - timedelta(days=i*2),
                "takt_time_min": round(5.0 + i * 0.5, 2),
                "cycle_time_max": round(8.0 + i * 0.3, 2),
                "cycle_time_avg": round(5.5 + i * 0.2, 2),
                "balance_rate": balance_rate,
                "idle_time_total": round(2.5 - i * 0.1, 2),
                "workstation_count": 5 + (i % 3),
                "is_balanced": balance_rate >= 85,
                "workstation_details": [
                    {"station_id": f"S{(j+1)%6+1:02d}", "cycle_time_min": round(6.0 + j * 0.2, 2), "idle_time": round(1.5 - j * 0.1, 2)}
                    for j in range(5)
                ],
                "bottleneck_station": f"S{bottleneck_id:02d}",
                "bottleneck_time": round(8.0 + i * 0.3, 2),
                "recommendations": [
                    "建议重新分配负载或增加并行工位",
                    f"瓶颈工站识别: S{bottleneck_id:02d}",
                ] if balance_rate < 85 else ["生产线运行正常，继续保持"],
                "created_by": "system",
            })
        
        for lba in lba_data:
            session.add(LineBalanceAnalysis(**lba))
        print(f"  ✓ 创建了 {len(lba_data)} 条产线平衡分析")

        # ============================================================
        # 8. 创建工序价值分析 (至少5条)
        # ============================================================
        print("\n★ 创建工序价值分析...")
        pa_data = []
        for i in range(8):
            va_time = round(3.0 + i * 0.3, 2)
            nva_time = round(2.0 - i * 0.1, 2) if i < 5 else round(1.0 + (i-4)*0.2, 2)
            total = va_time + nva_time
            va_ratio = round(va_time / total, 2) if total > 0 else 0
            
            pa_data.append({
                "id": str(uuid4()),
                "factory_id": factory_id,
                "product_id": products[i % 3]["product_code"],
                "operation_code": f"A{(i % 4) + 1:02d}",
                "analysis_date": current - timedelta(hours=i),
                "total_process_time_min": total,
                "va_time_min": va_time,
                "nva_time_min": nva_time,
                "wait_time_min": round(0.5 + i * 0.05, 2),
                "move_time_min": round(0.3 + i * 0.03, 2),
                "inspect_time_min": round(0.2 + i * 0.02, 2),
                "va_ratio": va_ratio,
                "lead_time": round(total + 1.0, 2),
                "efficiency_score": round(va_ratio * 100, 2),
                "created_by": "system",
            })
        
        for pa in pa_data:
            session.add(ProcessAnalysis(**pa))
        print(f"  ✓ 创建了 {len(pa_data)} 条工序价值分析")

        # ============================================================
        # 9. 创建动作研究记录 (至少4条)
        # ============================================================
        print("\n★ 创建动作研究记录...")
        as_data = []
        for i in range(6):
            as_data.append({
                "id": str(uuid4()),
                "factory_id": factory_id,
                "product_id": products[i % 3]["product_code"],
                "operation_name": f"动作研究-{i+1}",
                "station_id": stations[i % len(stations)]["id"],
                "operator_id": f"EMP-{1001 + i}",
                "study_date": current - timedelta(days=i),
                "method_type": "mtm" if i % 2 == 0 else "modapt",
                "recorded_by": f"ENG-{101 + i}",
                "motions": [
                    {"motion": "reach", "time_units": 2},
                    {"motion": "grasp", "time_units": 1},
                    {"motion": "move", "time_units": 3},
                    {"motion": "position", "time_units": 2},
                ],
                "total_time_cycles": round(10 + i * 0.5, 2),
                "analysis_result": {
                    "method_improvement": "发现可优化动作",
                    "estimated_time_reduction": 15 if i % 2 == 0 else 10,
                },
                "created_at": current - timedelta(days=i),
                "updated_at": current - timedelta(days=i),
            })
        
        for as_rec in as_data:
            session.add(ActionStudy(**as_rec))
        print(f"  ✓ 创建了 {len(as_data)} 条动作研究记录")

        # ============================================================
        # 10. 创建方法研究记录 (Method Studies)
        # ============================================================
        print("\n★ 创建方法研究记录...")
        ms_data = []
        for i in range(4):
            ms_data.append({
                "id": str(uuid4()),
                "factory_id": factory_id,
                "product_id": products[i % 3]["product_code"],
                "original_operation": f"原始操作方法-{i+1}",
                "version": "v1",
                "is_basement_method": i == 0,
                "is_optimal_method": i == 3,
                "description": f"对比方法{i+1}",
                "action_sequence": [{"step": 1, "action": "准备"}, {"step": 2, "action": "操作"}],
                "required_resources": ["工具A", "物料B"],
                "setup_time_min": 2.0,
                "cycle_time_min": round(5.0 + i * 0.5, 2),
                "total_standard_time_min": round(7.0 + i * 0.8, 2),
                "validity_start": current,
                "validity_end": current + timedelta(days=180),
                "created_by": "system",
                "approved_by": "ENG-001" if i > 0 else None,
                "status": "approved" if i > 0 else "draft",
            })
        
        for ms in ms_data:
            session.add(MethodStudy(**ms))
        print(f"  ✓ 创建了 {len(ms_data)} 条方法研究记录")

        # ============================================================
        # 11. 创建工站布局设计 (至少2条)
        # ============================================================
        print("\n★ 创建工站布局设计...")
        wcl_data = []
        for i in range(3):
            wcl_data.append({
                "id": str(uuid4()),
                "factory_id": factory_id,
                "work_cell_id": f"WC{chr(65+i)}",
                "product_family_id": f"FAMILY-{products[i % 3]['product_code']}",
                "layout_diagram_url": f"https://example.com/layouts/wc{i+1}.png",
                "material_flow_path": ["入口", "工作站1", "工作站2", "检验", "出口"],
                "operator_movement_path": ["工位A", "工位B", "返回A"],
                "takt_time_alignment": "aligned",
                "storage_location_type": "in_process",
                "last_updated": current,
                "created_at": current,
            })
        
        for wcl in wcl_data:
            session.add(WorkCellLayout(**wcl))
        print(f"  ✓ 创建了 {len(wcl_data)} 条工站布局记录")

        # ============================================================
        # 12. 创建Kanban看板系统
        # ============================================================
        print("\n★ 创建Kanban看板系统...")
        kanban_data = []
        for i in range(5):
            kanban_data.append({
                "id": str(uuid4()),
                "factory_id": factory_id,
                "kanban_id": f"KANBAN-{i+1:03d}",
                "kanban_type": "continuous" if i % 2 == 0 else "production",
                "upstream_station": f"S{(i % 5) + 1:02d}",
                "downstream_station": f"S{((i + 1) % 5) + 1:02d}",
                "product_id": products[i % 3]["product_code"],
                "part_number": f"PART-{i+1:03d}",
                "max_card_count": 5,
                "current_card_count": i % 5,
                "safety_stock_level": 2,
                "card_status": "available" if (i % 2) == 0 else "occupied",
                "last_used_at": current - timedelta(hours=i),
                "created_at": current,
                "updated_at": current,
            })
        
        for kb in kanban_data:
            session.add(KanbanSystem(**kb))
        print(f"  ✓ 创建了 {len(kanban_data)} 条Kanban记录")

        # ============================================================
        # 13. 创建5S审计记录
        # ============================================================
        print("\n★ 创建5S审计记录...")
        five_s_data = []
        base_score = [85, 92, 78, 88, 95]
        for i in range(5):
            five_s_data.append({
                "id": str(uuid4()),
                "factory_id": factory_id,
                "work_center_id": f"WC{i+1}",
                "audit_date": current - timedelta(days=i*2),
                "auditor_id": f"ENG-{101 + i}",
                "seiri_score": base_score[i],
                "seiton_score": base_score[(i+1) % 5],
                "seiso_score": base_score[(i+2) % 5],
                "seiketsu_score": base_score[(i+3) % 5],
                "shitsuke_score": base_score[(i+4) % 5],
                "total_score": sum(base_score[i:i+5]) // 5,
                "score_percentage": round(sum(base_score[i:i+5]) / 5.0, 1),
                "improvement_items": ["区域标识不清" if i % 2 == 0 else "物品摆放杂乱", "清洁频率不足"],
                "next_audit_date": current + timedelta(days=14),
                "created_at": current - timedelta(days=i*2),
                "updated_at": current - timedelta(days=i*2),
            })
        
        for fs in five_s_data:
            session.add(FiveSAudit(**fs))
        print(f"  ✓ 创建了 {len(five_s_data)} 条5S审计记录")

        # ============================================================
        # 提交所有更改
        # ============================================================
        await session.commit()
        print("\n✓ 所有数据已成功提交到数据库！")

        # 验证
        print("\n=== 数据验证 ===")
        print(f"  标准工时: {(await session.execute(func.count(StandardOperationTime.id))).scalar()} 条")
        print(f"  时间研究: {(await session.execute(func.count(TimeStudyRecord.id))).scalar()} 条")
        print(f"  产线平衡: {(await session.execute(func.count(LineBalanceAnalysis.id))).scalar()} 条")
        print(f"  工序价值: {(await session.execute(func.count(ProcessAnalysis.id))).scalar()} 条")
        print(f"  动作研究: {(await session.execute(func.count(ActionStudy.id))).scalar()} 条")
        print(f"  工站布局: {(await session.execute(func.count(WorkCellLayout.id))).scalar()} 条")
        print(f"  Kanban系统: {(await session.execute(func.count(KanbanSystem.id))).scalar()} 条")
        print(f"  5S审计: {(await session.execute(func.count(FiveSAudit.id))).scalar()} 条")

    await db_config.close()


if __name__ == "__main__":
    asyncio.run(main())