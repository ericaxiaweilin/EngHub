"""
综合数据补充脚本 v2 - 严格按实际表结构插入
工厂: F01 | 用户: eric (94cb8a0d-9727-7e8a-943a-b43c32fe54cf)
"""
import asyncio
import uuid
import random
from datetime import datetime, timedelta, date
from database.db_config import db_config
from sqlalchemy import text

FACTORY = 'F01'
ERIC_ID = '94cb8a0d-9727-7e8a-943a-b43c32fe54cf'
NOW = datetime.now()

def uid():
    return str(uuid.uuid4())

def ts(days_ago=0, hours_ago=0):
    return (NOW - timedelta(days=days_ago, hours=hours_ago)).strftime('%Y-%m-%d %H:%M:%S')

def d(days_ahead=0):
    return (date.today() + timedelta(days=days_ahead)).isoformat()

async def seed():
    async with db_config.session_factory() as db:
        # ============ 1. 分配工单给eric + 补工序工单 ============
        print("=== 1. Work Orders ===")
        await db.execute(text(f"""
            UPDATE work_orders SET assigned_to = '{ERIC_ID}'
            WHERE factory_id = '{FACTORY}' AND assigned_to IS NULL AND status IN ('released','in_progress')
        """))
        process_wos = [
            ('WO-P-2026-001', 'CUT', 'released'),
            ('WO-P-2026-002', 'MACH', 'in_progress'),
            ('WO-P-2026-003', 'ASSY', 'released'),
            ('WO-P-2026-004', 'QC', 'pending'),
            ('WO-P-2026-005', 'PAINT', 'in_progress'),
            ('WO-P-2026-006', 'WELD', 'released'),
            ('WO-P-2026-007', 'PKG', 'pending'),
            ('WO-P-2026-008', 'GRD', 'completed'),
        ]
        for code, proc, status in process_wos:
            await db.execute(text(f"""
                INSERT INTO work_orders (id, work_order_code, factory_id, product_id,
                    planned_qty, completed_qty, good_qty, defect_qty, status, wo_type, process_code,
                    assigned_to, priority, unit, created_at, updated_at)
                VALUES ('{uid()}', '{code}', '{FACTORY}', 'PRD-001',
                    {random.randint(50,500)}, {random.randint(0,200)}, {random.randint(0,180)},
                    {random.randint(0,10)}, '{status}', 'process', '{proc}',
                    '{ERIC_ID}', '{random.choice(["urgent","high","medium","low"])}', 'pcs',
                    '{ts(random.randint(1,30))}', '{ts(0, random.randint(1,12))}')
                ON CONFLICT DO NOTHING
            """))
        print("  work_orders assigned + 8 process WOs added")

        # ============ 2. QMS 检验 ============
        # cols: id, factory_id, inspection_code, inspection_type, product_id, material_id,
        #        batch_id, work_order_id, batch_size, sample_size, inspected_qty, defective_qty,
        #        aql_level, inspection_level, aql_result, status, inspector_id, inspected_at,
        #        created_by, created_at, updated_at
        print("=== 2. QMS Inspections ===")
        insp_types = ['incoming', 'process', 'final', 'patrol']
        for i in range(12):
            itype = insp_types[i % 4]
            batch_size = random.randint(100, 1000)
            sample = random.randint(20, 80)
            defective = random.randint(0, 5)
            await db.execute(text(f"""
                INSERT INTO qms_inspections (id, factory_id, inspection_code, inspection_type,
                    product_id, batch_id, batch_size, sample_size, inspected_qty, defective_qty,
                    aql_level, inspection_level, status, inspector_id, inspected_at, created_at, updated_at)
                VALUES ('{uid()}', '{FACTORY}', 'INS-2026-{i+1:04d}', '{itype}',
                    'PRD-00{i%3+1}', 'BATCH-2026-{random.randint(100,999)}', {batch_size}, {sample},
                    {sample}, {defective}, {random.choice([0.65, 1.0, 1.5, 2.5])},
                    'II', '{random.choice(["passed","failed","conditional"])}',
                    '{ERIC_ID}', '{ts(i, random.randint(0,8))}', '{ts(i)}', '{ts(i)}')
            """))
        print("  12 inspections added")

        # ============ 3. QMS 不良 ============
        # cols: id, factory_id, defect_code, defect_type, quantity, severity, inspection_id,
        #        work_order_id, material_id, batch_id, station_id, production_report_id,
        #        description, status, disposition, ...
        print("=== 3. QMS Defects ===")
        defect_types = ['scratch', 'dimension', 'crack', 'porosity', 'deformation', 'contamination']
        severities = ['critical', 'major', 'minor', 'observation']
        for i in range(15):
            await db.execute(text(f"""
                INSERT INTO qms_defects (id, factory_id, defect_code, defect_type, quantity,
                    severity, work_order_id, station_id, description, status, created_at, updated_at)
                VALUES ('{uid()}', '{FACTORY}', 'DEF-2026-{i+1:04d}', '{defect_types[i%6]}',
                    {random.randint(1,20)}, '{severities[i%4]}',
                    'WO-2026-000{(i%5)+1}', 'ST-0{(i%6)+1}',
                    '{defect_types[i%6]}缺陷 - 工序异常',
                    '{random.choice(["open","in_review","closed"])}', '{ts(i)}', '{ts(i)}')
            """))
        print("  15 defects added")

        # ============ 4. QMS OCAP ============
        # cols: id, factory_id, ocap_code, defect_id(NOT NULL), title, description, root_cause,
        #        status, created_by, created_at, updated_at, ...
        print("=== 4. QMS OCAPs ===")
        # 先获取已插入的defect ids
        defect_rows = await db.execute(text(f"SELECT id FROM qms_defects WHERE factory_id='{FACTORY}' LIMIT 5"))
        defect_ids = [str(r[0]) for r in defect_rows.fetchall()]
        ocap_titles = ['尺寸超差纠正','外观不良遏制','材料批次追溯','设备精度恢复','工艺参数纠偏']
        for i in range(min(5, len(defect_ids))):
            await db.execute(text(f"""
                INSERT INTO qms_ocaps (id, factory_id, ocap_code, defect_id, title, description,
                    root_cause, status, created_by, created_at, updated_at)
                VALUES ('{uid()}', '{FACTORY}', 'OCAP-2026-{i+1:03d}', '{defect_ids[i]}',
                    '{ocap_titles[i]}', '{ocap_titles[i]} - 需要立即处理',
                    '{random.choice(["设备磨损","参数偏移","来料波动","操作失误"])}',
                    '{random.choice(["open","in_progress","closed"])}',
                    '{ERIC_ID}', '{ts(i*3)}', '{ts(i)}')
            """))
        print(f"  {min(5, len(defect_ids))} OCAPs added")

        # ============ 5. QMS 8D ============
        # cols: id, report_code, factory_id, defect_record_id, title, severity, status,
        #        d1_team, d2_problem_description, ..., opened_by, created_at, updated_at
        print("=== 5. QMS 8D Reports ===")
        titles_8d = ['客户投诉-轴承异响','过程不良率超标','供应商来料不良','热处理变形超标']
        for i in range(4):
            await db.execute(text(f"""
                INSERT INTO qms_8d_reports (id, report_code, factory_id, title, severity,
                    status, d1_team, d2_problem_description, opened_by, created_at, updated_at)
                VALUES ('{uid()}', '8D-2026-{i+1:03d}', '{FACTORY}',
                    '{titles_8d[i]}', '{random.choice(["critical","major"])}',
                    '{random.choice(["D3","D5","D7","closed"])}',
                    '张工,李工,王工', '{titles_8d[i]}详细描述',
                    '{ERIC_ID}', '{ts(i*5)}', '{ts(i)}')
            """))
        print("  4 8D reports added")

        # ============ 6. SPC配置 + 数据点 ============
        print("=== 6. SPC ===")
        characteristics = [
            ('SPC-001', '外径尺寸', 25.0, 0.05, 'Xbar-R'),
            ('SPC-002', '内孔直径', 12.0, 0.03, 'Xbar-R'),
            ('SPC-003', '表面粗糙度', 0.8, 0.1, 'Xbar-S'),
            ('SPC-004', '硬度HRC', 60.0, 1.5, 'Xbar-R'),
        ]
        for code, name, cl, tol, ctype in characteristics:
            await db.execute(text(f"""
                INSERT INTO spc_chart_config (id, factory_id, characteristic_code, characteristic_name,
                    chart_type, ucl, cl, lcl, usl, lsl, target, subgroup_size, is_active, created_at)
                VALUES ('{uid()}', '{FACTORY}', '{code}', '{name}', '{ctype}',
                    {cl + tol*3}, {cl}, {cl - tol*3}, {cl + tol*5}, {cl - tol*5}, {cl},
                    5, true, '{ts(30)}')
                ON CONFLICT DO NOTHING
            """))
            for j in range(25):
                val = cl + random.gauss(0, tol)
                ooc = abs(val - cl) > tol * 3
                await db.execute(text(f"""
                    INSERT INTO qms_spc_points (id, factory_id, characteristic_code, characteristic_name,
                        work_order_id, station_id, measured_value, sample_group, ucl, lcl, cl,
                        is_out_of_control, measured_at, measured_by)
                    VALUES ('{uid()}', '{FACTORY}', '{code}', '{name}',
                        'WO-2026-000{(j%5)+1}', 'ST-01', {val:.4f}, {j+1},
                        {cl + tol*3}, {cl - tol*3}, {cl}, {str(ooc).lower()},
                        '{ts(0, j)}', '{random.choice(["张检","李检"])}')
                """))
        print("  4 SPC configs + 100 data points added")

        # ============ 7. 质量目标 ============
        print("=== 7. Quality Goals ===")
        goals = [
            ('QG-001', '成品一次合格率', 'fpy', 98.5, 97.8, '%'),
            ('QG-002', '客户投诉PPM', 'ppm', 50, 72, 'ppm'),
            ('QG-003', '过程不良率', 'defect_rate', 1.5, 1.8, '%'),
            ('QG-004', '来料合格率', 'incoming_pass', 99.0, 98.6, '%'),
            ('QG-005', 'OEE设备综合效率', 'oee', 85.0, 82.3, '%'),
        ]
        for code, name, metric, target, current, unit in goals:
            status = 'on_track' if current >= target * 0.95 else 'at_risk'
            await db.execute(text(f"""
                INSERT INTO quality_goals (id, factory_id, goal_code, goal_name, metric_type,
                    target_value, current_value, unit, period, responsible, status,
                    review_frequency_days, last_reviewed_at, next_review_at, created_at)
                VALUES ('{uid()}', '{FACTORY}', '{code}', '{name}', '{metric}',
                    {target}, {current}, '{unit}', 'monthly',
                    '{random.choice(["张工","李工","王工"])}', '{status}',
                    30, '{ts(3)}', '{ts(-27)}', '{ts(60)}')
            """))
        print("  5 quality goals added")

        # ============ 8. WMS 仓库 + 库存 ============
        # wms_warehouses: id, factory_id, warehouse_code, warehouse_name, warehouse_type,
        #                  address, manager_id, status, created_at, updated_at
        print("=== 8. WMS ===")
        warehouses = [
            ('WH-RAW', '原材料仓', 'raw_material'),
            ('WH-FG', '成品仓', 'finished_goods'),
            ('WH-WIP', '在制品仓', 'wip'),
            ('WH-SPARE', '备件仓', 'spare_parts'),
        ]
        wh_ids = {}
        for code, name, wtype in warehouses:
            wid = uid()
            wh_ids[code] = wid
            await db.execute(text(f"""
                INSERT INTO wms_warehouses (id, factory_id, warehouse_code, warehouse_name,
                    warehouse_type, address, status, created_at, updated_at)
                VALUES ('{wid}', '{FACTORY}', '{code}', '{name}', '{wtype}',
                    '厂区{random.choice(["A","B","C"])}栋', 'active', '{ts(90)}', '{ts(90)}')
                ON CONFLICT DO NOTHING
            """))
        materials = [
            ('MAT-001', 'WH-RAW', 5000, 4200),
            ('MAT-002', 'WH-RAW', 3000, 2800),
            ('MAT-003', 'WH-RAW', 2000, 1500),
            ('FG-001', 'WH-FG', 800, 650),
            ('FG-002', 'WH-FG', 500, 420),
            ('WIP-001', 'WH-WIP', 1200, 900),
            ('SP-001', 'WH-SPARE', 200, 180),
            ('SP-002', 'WH-SPARE', 5000, 4500),
        ]
        for mat_id, wh_code, total, avail in materials:
            await db.execute(text(f"""
                INSERT INTO wms_inventory_summary (id, factory_id, material_id, warehouse_id,
                    total_qty, available_qty, reserved_qty, frozen_qty, last_transaction_at, updated_at)
                VALUES ('{uid()}', '{FACTORY}', '{mat_id}', '{wh_ids[wh_code]}',
                    {total}, {avail}, {total - avail - random.randint(0,50)}, {random.randint(0,30)},
                    '{ts(0, random.randint(1,24))}', '{ts(0, 1)}')
            """))
        print("  4 warehouses + 8 inventory items added")

        # ============ 9. 库存预警 ============
        # stock_alerts: id, factory_id, alert_type, material_id, material_code, material_name,
        #               warehouse_id, current_qty, threshold_qty, days_inactive, severity,
        #               status, resolved_by, resolved_at, remark, created_at
        print("=== 9. Stock Alerts ===")
        alerts = [
            ('SA-001', 'low_stock', 'MAT-003', 'MAT-003', '6061铝板', 'WH-RAW', 150, 500, 0, 'high'),
            ('SA-002', 'low_stock', 'SP-001', 'SP-001', 'SKF轴承6205', 'WH-SPARE', 20, 50, 0, 'critical'),
            ('SA-003', 'dead_stock', 'MAT-009', 'MAT-009', '废旧刀具', 'WH-SPARE', 300, 0, 90, 'low'),
            ('SA-004', 'overstock', 'MAT-001', 'MAT-001', '45#圆钢', 'WH-RAW', 5000, 2000, 0, 'medium'),
        ]
        for aid, atype, mat_id, mat_code, mat_name, wh, cur_qty, threshold, days, severity in alerts:
            await db.execute(text(f"""
                INSERT INTO stock_alerts (id, factory_id, alert_type, material_id, material_code,
                    material_name, warehouse_id, current_qty, threshold_qty, days_inactive,
                    severity, status, created_at)
                VALUES ('{aid}', '{FACTORY}', '{atype}', '{mat_id}', '{mat_code}', '{mat_name}',
                    '{wh}', {cur_qty}, {threshold}, {days}, '{severity}', 'open', '{ts(random.randint(0,5))}')
                ON CONFLICT DO NOTHING
            """))
        print("  4 stock alerts added")

        # ============ 10. 生产计划 ============
        # pp_plans: id, factory_id, plan_code, plan_type, product_id, sales_order_id, quantity,
        #           required_date, due_date, customer_level, priority, priority_score, status,
        #           station_id, scheduled_start_date, scheduled_end_date, mrp_status,
        #           created_by, created_at, updated_at
        print("=== 10. PP Plans ===")
        for i in range(8):
            status = random.choice(['draft', 'confirmed', 'released', 'in_progress', 'completed'])
            await db.execute(text(f"""
                INSERT INTO pp_plans (id, factory_id, plan_code, plan_type, product_id,
                    quantity, required_date, due_date, priority, priority_score, status,
                    created_by, created_at, updated_at)
                VALUES ('{uid()}', '{FACTORY}', 'PP-2026-{i+1:04d}',
                    '{random.choice(["make_to_order","make_to_stock","urgent"])}',
                    'PRD-00{i%3+1}', {random.randint(100,2000)},
                    '{d(random.randint(3,30))}', '{d(random.randint(5,35))}',
                    {random.randint(1,5)}, {random.uniform(50,99):.1f}, '{status}',
                    '{ERIC_ID}', '{ts(i*2)}', '{ts(i)}')
            """))
        print("  8 plans added")

        # ============ 11. APS排程 ============
        # aps_schedules: id, factory_id, status, schedule_code, mode, optimize_for,
        #                 horizon_start, horizon_end, on_time_rate, avg_utilization,
        #                 total_setup_minutes, avg_cycle_hours, total_tasks, unscheduled_count,
        #                 created_by, confirmed_by, created_at, updated_at, algorithm,
        #                 constraint_summary, conflict_count
        print("=== 11. APS Schedules ===")
        for i in range(5):
            await db.execute(text(f"""
                INSERT INTO aps_schedules (id, factory_id, status, schedule_code, mode,
                    optimize_for, horizon_start, horizon_end, on_time_rate, avg_utilization,
                    total_tasks, unscheduled_count, created_by, created_at, updated_at, algorithm)
                VALUES ('{uid()}', '{FACTORY}',
                    '{random.choice(["generated","confirmed","released"])}',
                    'APS-2026-{i+1:03d}', '{random.choice(["finite","infinite"])}',
                    '{random.choice(["min_makespan","max_utilization","min_tardiness"])}',
                    '{d(0)}', '{d(14)}', {random.uniform(85,99):.1f}, {random.uniform(70,95):.1f},
                    {random.randint(20,80)}, {random.randint(0,5)},
                    '{ERIC_ID}', '{ts(i*3)}', '{ts(i)}',
                    '{random.choice(["genetic_algorithm","constraint_based","priority_dispatch"])}')
            """))
        print("  5 APS schedules added")

        # ============ 12. Andon工单 ============
        # andon_tickets: id, ticket_code, factory_id, category_id, category_code, title,
        #                 description, location_id, location_name, equipment_id, work_order_id,
        #                 status, priority, assigned_to, assigned_by, ...
        print("=== 12. Andon Tickets ===")
        andon_data = [
            ('AND-001', 'equipment_failure', 'CNC-03主轴异响', 'high', 'open'),
            ('AND-002', 'quality_issue', '批次尺寸超差', 'critical', 'in_progress'),
            ('AND-003', 'material_shortage', '缺料-6061铝板', 'medium', 'open'),
            ('AND-004', 'safety_hazard', '液压油泄漏', 'critical', 'resolved'),
            ('AND-005', 'process_deviation', '焊接参数偏移', 'high', 'in_progress'),
            ('AND-006', 'equipment_failure', 'AGV-02通信中断', 'medium', 'resolved'),
        ]
        for code, cat_code, title, priority, status in andon_data:
            await db.execute(text(f"""
                INSERT INTO andon_tickets (id, ticket_code, factory_id, category_code, title,
                    description, location_name, status, priority, assigned_to, assigned_by,
                    created_at, updated_at)
                VALUES ('{uid()}', '{code}', '{FACTORY}', '{cat_code}', '{title}',
                    '{title} - 需要立即处理',
                    '{random.choice(["CNC车间","装配线","焊接工位","仓储区"])}',
                    '{status}', '{priority}', '{ERIC_ID}', 'system',
                    '{ts(random.randint(0,7), random.randint(0,12))}', '{ts(0, random.randint(0,5))}')
            """))
        print("  6 andon tickets added")

        # ============ 13. TMS任务 ============
        # tms_tasks: id, task_code, title, description, task_type, source, priority, points,
        #            status, distribution_strategy, assigned_to, assigned_by, candidate_pool,
        #            required_skills, required_roles, deadline, approval_flow_id, agent_context,
        #            metadata, related_work_order_id, created_by, created_at, updated_at
        print("=== 13. TMS Tasks ===")
        tms_data = [
            ('TMS-001', '设备巡检-CNC车间', 'inspection', 'high', 'assigned'),
            ('TMS-002', '来料检验-轴承钢批次', 'inspection', 'medium', 'pending'),
            ('TMS-003', '工艺文件更新-焊接SOP', 'documentation', 'low', 'pending'),
            ('TMS-004', '客诉处理-尺寸超差', 'quality', 'urgent', 'in_progress'),
            ('TMS-005', '预防性保养-液压站', 'maintenance', 'medium', 'assigned'),
            ('TMS-006', '新员工培训-安全操作', 'training', 'low', 'completed'),
        ]
        for code, title, ttype, priority, status in tms_data:
            assigned = f"'{ERIC_ID}'" if status in ('assigned','in_progress') else 'NULL'
            await db.execute(text(f"""
                INSERT INTO tms_tasks (id, task_code, title, description, task_type, source,
                    priority, points, status, assigned_to, deadline, created_by, created_at, updated_at)
                VALUES ('{uid()}', '{code}', '{title}', '{title}详细描述', '{ttype}',
                    '{random.choice(["system","manual","auto_dispatch"])}', '{priority}',
                    {random.randint(5,50)}, '{status}', {assigned},
                    '{d(random.randint(1,7))}', '{ERIC_ID}', '{ts(random.randint(0,10))}', '{ts(0, random.randint(0,5))}')
            """))
        print("  6 TMS tasks added")

        # ============ 14. TMS审批流 ============
        print("=== 14. TMS Approval Flows ===")
        task_rows = await db.execute(text(f"SELECT id FROM tms_tasks LIMIT 3"))
        task_ids = [str(r[0]) for r in task_rows.fetchall()]
        for i in range(min(3, len(task_ids))):
            await db.execute(text(f"""
                INSERT INTO tms_approval_flows (id, flow_code, task_id, flow_type, current_step,
                    status, initiated_by, created_at, updated_at, steps)
                VALUES ('{uid()}', 'AF-2026-{i+1:03d}', '{task_ids[i]}',
                    '{random.choice(["leave","overtime","purchase","exception"])}',
                    {random.randint(1,3)}, '{random.choice(["pending","approved","in_progress"])}',
                    '{random.choice(["张工","李工","王工"])}', '{ts(i*2)}', '{ts(i)}',
                    '[{{"step": 1, "approver": "班组长", "status": "approved"}}, {{"step": 2, "approver": "部门主管", "status": "pending"}}]')
            """))
        print(f"  {min(3, len(task_ids))} approval flows added")

        # ============ 15. RCC任务 ============
        # rcc_tasks: id, task_code, org_unit_id, task_type, title, description,
        #            affected_params, affected_entities, expected_impact_summary, status,
        #            approved_by, approved_at, rejected_by, rejection_reason, executed_at,
        #            completed_at, requested_by, request_context, source_ticket_id,
        #            created_at, updated_at
        print("=== 15. RCC Tasks ===")
        rcc_data = [
            ('RCC-001', '紧急插单排程', 'scheduling', 'pending'),
            ('RCC-002', '设备故障重排', 'dispatch', 'in_progress'),
            ('RCC-003', '物料齐套确认', 'coordination', 'completed'),
            ('RCC-004', '产能负荷平衡', 'scheduling', 'pending'),
            ('RCC-005', '交期承诺评估', 'coordination', 'in_progress'),
            ('RCC-006', '异常升级处理', 'dispatch', 'completed'),
        ]
        for code, title, ttype, status in rcc_data:
            await db.execute(text(f"""
                INSERT INTO rcc_tasks (id, task_code, task_type, title, description,
                    status, requested_by, created_at, updated_at)
                VALUES ('{uid()}', '{code}', '{ttype}', '{title}', '{title}详细描述',
                    '{status}', '{ERIC_ID}', '{ts(random.randint(0,5))}', '{ts(0, random.randint(0,3))}')
                ON CONFLICT DO NOTHING
            """))
        print("  6 RCC tasks added")

        # ============ 16. 工作单元布局 ============
        # work_cell_layouts: id, factory_id, cell_name, product_family, station_count,
        #                    daily_capacity, created_at
        print("=== 16. Work Cell Layouts ===")
        cells = [
            ('轴承加工单元', 'bearing', 6, 500),
            ('装配单元', 'assembly', 4, 300),
            ('焊接单元', 'welding', 3, 200),
        ]
        for name, family, stations, capacity in cells:
            await db.execute(text(f"""
                INSERT INTO work_cell_layouts (id, factory_id, cell_name, product_family,
                    station_count, daily_capacity, created_at)
                VALUES ('{uid()}', '{FACTORY}', '{name}', '{family}',
                    {stations}, {capacity}, '{ts(30)}')
                ON CONFLICT DO NOTHING
            """))
        print("  3 work cell layouts added")

        await db.commit()
        print("\n✅ ALL SEED DATA COMMITTED SUCCESSFULLY")

asyncio.run(seed())
