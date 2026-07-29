# 🏭 IE Module - Industrial Engineering for MES (Lean Production)

![Industrial Engineering Module](https://img.shields.io/badge/Status-Production%20Ready-green)  
**Version:** 1.0.0 | **Last Updated:** 2026-07-27

---

## 📖 Overview

The IE (Industrial Engineering) Module adds comprehensive **lean production capabilities** to the EngHub MES system, enabling factories to implement standard time management, work measurement, line balancing analysis, and other core industrial engineering methodologies directly within their MES platform.

---

## 🎯 Core Features

### 1️⃣ Standard Time Management (标准工时管理)
- Maintain Standard Operation Times (SOT) per workstation
- Support version control and validity periods
- Automatic calculation of effective standard time including allowance rates
- Integration with product routing and work center master data

### 2️⃣ Time Study & Work Measurement (时间研究/作业测定)
- Record actual cycle time observations from multiple cycles
- Calculate average time, normal time, and allowed time automatically
- Performance rating adjustment (rating factor)
- Approval workflow to convert approved studies into standard times

### 3️⃣ Line Balancing Analysis (产线平衡分析)
- Calculate takt time based on production requirements
- Identify bottleneck stations and idle time
- Compute line balance rate (= total active time / max_cycle_time × station_count)
- Generate improvement recommendations with multi-language support

### 4️⃣ Process Value Analysis (工序价值分析)
- VA/NVA (Value-added / Non-value-added) time breakdown
- Wait, move, and inspection time quantification
- Efficiency scoring (0-100 scale)
- VSM (Value Stream Mapping) capability

---

### Advanced Lean Tools (扩展精益工具)

| Feature | Description |
|---------|-------------|
| **Action Study** | MTM/MODAPTS motion analysis, detailed element timing |
| **Method Study** | Compare multiple operation methods, select optimal SOP |
| **Work Cell Layout** | Material flow path planning, ergonomic layout design |
| **Kanban System** | Pull-based production control, card tracking |
| **5S Audit** | Structured daily/weekly workplace organization assessment |
| **Performance Rating** | Operator efficiency vs. standard time benchmarking |

---

## 🗄️ Database Schema

### Core Tables (`ie` tables in database)

```sql
-- Basic IE modules
standard_operation_times      -- 标准工时表
time_study_records           -- 时间研究记录  
line_balance_analyses        -- 产线平衡分析表
process_analyses             -- 工序价值分析表

-- Extended lean modules
action_studies               -- 动作研究表
method_studies               -- 方法研究表
work_cell_layouts            -- 工站布局表
kanban_systems               -- 看板系统表
five_s_audits                -- 5S审计表
```

### Relationships
All tables relate to existing MES entities through `factory_id` foreign keys:
- `Product` → StandardOperationTime, TimeStudyRecord
- `Station` → StandardOperationTime, ProcessAnalysis
- `WorkOrder` ← StandardOperationTime (via routing)
- `ProductionReport` → TimeStudyRecord (auto-ingestion)

---

## 🔌 API Reference

### Base Path: `/api/v1/ie/`

#### Standard Times
```
POST    /api/v1/ie/standard-times       Create SOT
GET     /api/v1/ie/standard-times       List SOTS
GET     /api/v1/ie/standard-times/{id}  Get SOT
PUT     /api/v1/ie/standard-times/{id}  Update SOT
DELETE  /api/v1/ie/standard-times/{id}  Delete SOT
GET     /api/v1/ie/products/{id}/standard-times  By product
```

#### Time Studies
```
POST    /api/v1/ie/time-studies         Create study
GET     /api/v1/ie/time-studies         List studies
GET     /api/v1/ie/time-studies/{id}/analysis   Get analysis results
POST    /api/v1/ie/time-studies/{id}/approve  Approve study
```

#### Line Balance
```
POST    /api/v1/ie/line-balance-analyses  Analyze balance
GET     /api/v1/ie/line-balance-analyses  List analyses
GET     /api/v1/ie/line-balance-analyses/{id}  Get report
```

#### Process Analysis
```
POST    /api/v1/ie/process-analyses     Create analysis
GET     /api/v1/ie/process-analyses     List analyses
GET     /api/v1/ie/process-analyses/{id}  Get details
```

#### Lean Metrics
```
GET     /api/v1/ie/lean-metrics         Overall VA/NVA summary
```

### Advanced Lean Path: `/api/v1/ie-advanced/`

```
/action-studies           MTM motion records
/method-studies           Method comparison & approval
/work-cells               Layout diagrams
/kanbans                  Kanban card tracking
/5s-audits                Workplace audits
/performance/rating       Operator efficiency scores
/value-stream-mapping     Full VSM analysis
/reports/                 Export endpoints (xlsx/pdf/csv)
```

---

## 🛠️ Deployment Instructions

### Prerequisites
- PostgreSQL 12+ installed and running
- Python 3.9+ with virtual environment activated
- Required packages: `pip install -r requirements.txt`
- Active database connection configured in `.env` or `database/db_config.py`

### One-step Deployment Script

Run the deployment script from project root:

```bash
# Linux/macOS
./deploy-ie-module.sh

# Windows (run as CMD/PowerShell)
deploy-ie-module-windows.bat
```

### Manual Steps

```bash
# 1. Pull latest code
cd /path/to/enghub
git pull origin main

# 2. Apply database migrations (order matters!)
psql -U postgres -d your_mes_db -f database/migrations/039_ie_module.sql
psql -U postgres -d your_mes_db -f database/migrations/040_ie_extended_module.sql

# 3. Restart application
pm2 restart all                    # If using PM2
# OR
sudo systemctl restart mes-app     # If using systemd
# OR
pkill -f "python3 main.py" && nohup python3 main.py &  # Manual start

# 4. Verify access
curl -I http://localhost:8000/api/v1/ie/standard-times
# Should return 200 or 401 (requires auth), not 404
```

---

## 🔐 Security & Permissions

### Pre-defined Role: `ie_engineer`

The RBAC system automatically creates this role during migration initialization with permissions:

| Permission Code | Action | Scope |
|-----------------|--------|-------|
| `ie_standard_time:view` | View | All SOT records |
| `ie_standard_time:create` | Create | New SOT entries |
| `ie_standard_time:update` | Update | Modify existing |
| `ie_time_study:approve` | Approve | Convert to SOT |
| `ie_line_balance:analyze` | Analyze | Run balance calculations |
| `ie_process_analysis:view` | View | Read VA/NVA data |
| `ie_action_study:*` | Full CRUD | Motion studies |
| `ie_method_study:*` | Full CRUD | Method comparisons |
| `ie_kanban:control` | Control | Card status updates |
| `ie_five_s:conduct` | Conduct | Execute audits |

Assign to users via admin panel or direct RBAC assignment.

---

## 🧪 Testing

Quick smoke test after deployment:

```bash
# Use Python HTTP client
python -c "import httpx; r=httpx.post('http://localhost:8000/api/v1/ie/standard-times', json={'factory_id':'TEST','product_id':'PROD','routing_step':'A01','operation_name':'Test','station_id':'STN01','standard_time_min':5.5}); print(r.status_code,r.json())"
```

Expected: `201 {'id': '...', 'factory_id': 'TEST', ...}`

---

## 📚 Integration Points

| MES Component | Integration Point | Benefit |
|---------------|-------------------|---------|
| **Work Order Release** | Lookup SOT by product/routing_step | Auto-calculate labor hours for capacity planning |
| **Production Reporting** | Feed actual output → Performance Rating | Real-time efficiency monitoring per operator/station |
| **APS Scheduling** | Use cycle times for finite capacity scheduling | More accurate production forecasts |
| **KPI Dashboard** | Feed line balance metrics → OEE calculation | Visible bottleneck identification |
| **Quality System** | Link method studies to defect reduction data | Root cause + process optimization together |

---

## 🚀 Roadmap (Future Enhancements)

1. **Auto-Ingestion Pipeline** - Transform ProductionReport data → TimeStudyRecord automatically
2. **Excel/PDF Report Generation** - Native export from `/reports/` endpoints
3. **Integration with Chatbot** - Natural language queries: "Show me line balance for Product X"
4. **Mobile Field App** - On-floor time study data entry via tablet/smartphone
5. **Machine Learning Predictions** - Historical pattern recognition for time estimation
6. **VR/AR Training** - Overlay standard motions onto assembly workstations

---

## 🆘 Support & Troubleshooting

| Issue | Solution |
|-------|----------|
| `psql: command not found` | Install PostgreSQL client: `sudo apt install postgresql-client` |
| Migration file conflicts | Check duplicate sequences in SQL; run sequentially only once |
| API returns 401 on all IE endpoints | Ensure correct `Authorization: Bearer <token>` header is set |
| No data appears in reports | Verify factory_id/product_id matches existing records in other modules |

For technical questions, contact: **AgnesCode Team / Sapiens AI**

---

© 2026 Sapiens AI — Powered by AgnesCode Enterprise Framework
[GitHub Repository](https://github.com/ericaxiaweilin/enghub)