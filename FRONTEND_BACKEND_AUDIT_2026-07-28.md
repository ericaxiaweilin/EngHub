# 前后端对齐审计报告

**审计日期**: 2026-07-28  
**审计范围**: 最近5次提交 (64e2ca4 ~ 8e8fa23)  
**审计结论**: 发现 **6类严重问题** + **4类功能缺失**

---

## 一、严重前后端不匹配 (会导致404/500)

### 1. IE Advanced 模块 - API前缀完全不匹配 🔴 CRITICAL

| 项目 | 前端 | 后端 |
|------|------|------|
| 前缀 | `/api/v1/ie-advanced/*` | `/api/v1/ie/*` |
| 定义位置 | `frontend/src/config/api.ts:85-91` | `api/routes/ie_routes_extended.py:23` |

**影响页面** (全部会404):
- `ActionStudies.tsx` - 动作研究
- `MethodStudies.tsx` - 方法研究  
- `WorkCells.tsx` - 工作单元
- `Kanbans.tsx` - 看板
- `FiveSAudits.tsx` - 5S审核

**修复方案**: 修改 `ie_routes_extended.py` 的 prefix 为 `/api/v1/ie-advanced`

---

### 2. IE Advanced 模块 - 缺失列表/删除接口 🔴 CRITICAL

前端调用了以下接口，但后端**完全不存在**:

| 前端调用 | 后端状态 |
|----------|----------|
| `GET /ie-advanced/method-studies` (列表) | ❌ 只有POST创建 |
| `GET /ie-advanced/work-cells` (列表) | ❌ 只有GET单个 |
| `GET /ie-advanced/kanbans` (列表) | ❌ 只有POST创建 |
| `GET /ie-advanced/5s-audits` (列表) | ❌ 只有按work-center查询 |
| `DELETE /ie-advanced/*` (全部) | ❌ 无任何DELETE接口 |

**影响**: 页面打开即报错，无法加载数据，无法删除记录

---

### 3. APS 排程模块 - 接口路径不匹配 🟠 HIGH

| 前端调用 | 后端实际 |
|----------|----------|
| `POST /api/v1/aps/schedule` | ❌ 不存在 (后端是 `/aps/generate`) |
| `GET /api/v1/aps/conflicts` | ❌ 不存在 |

**影响页面**: `SchedulingCenter.tsx` 的"执行排程"和"冲突检测"功能完全失效

**修复方案**: 
- 后端添加 `/aps/schedule` 别名路由，或
- 前端改用 `/aps/generate`

---

### 4. PP 计划模块 - 产能冲突接口不匹配 🟠 HIGH

| 前端调用 | 后端实际 |
|----------|----------|
| `GET /api/v1/plans/{id}/capacity-conflict` | ❌ 不存在 |
| 后端实际接口 | `POST /api/v1/conflict/detect` |

**影响**: `PlanList.tsx` 的"产能冲突检查"按钮点击后报错

---

### 5. QMS OCAP - 缺失PATCH接口 🟠 HIGH

| 前端调用 | 后端状态 |
|----------|----------|
| `PATCH /api/v1/defects/{id}` | ❌ 不存在 |

**影响**: `OcapDetail.tsx` 保存OCAP信息时会报405 Method Not Allowed

**修复方案**: 后端添加 `@router.patch("/defects/{defect_id}")` 接口

---

### 6. OCAP 路由导航错误 🟡 MEDIUM

| 位置 | 问题 |
|------|------|
| `OcapList.tsx:63` | 导航到 `/qms/ocaps/${id}` |
| `App.tsx:166` | 路由定义是 `ocaps/:id` (无/qms前缀) |

**影响**: 点击"详情"按钮会跳转到不存在的页面

**修复**: 改为 `navigate(\`/ocaps/${record.id}\`)`

---

## 二、后端接口拼写错误

### QMS 路由拼写错误 🟡 MEDIUM

| 错误路径 | 正确路径 | 位置 |
|----------|----------|------|
| `/faicreate` | `/fai/create` | `qms_routes.py:759` |
| `/ipcreatoe` | `/ipc/create` | `qms_routes.py:831` |
| `/oqcreatoe` | `/oqc/create` | `qms_routes.py:899` |

**影响**: 虽然目前无前端调用，但API文档和测试脚本会受影响

---

## 三、后端有接口但前端无页面 (功能缺失)

### 1. BOM 模块 - 完全无前端 🔴 CRITICAL

后端已实现完整BOM接口 (`api/routes/bom_routes.py`):
- `GET /api/v1/bom/models` - BOM模型列表
- `GET /api/v1/bom/tree/{model}` - BOM树结构
- `GET /api/v1/bom/search` - BOM搜索
- `POST /api/v1/bom/sync` - EngFlow同步
- `GET /api/v1/bom/compare` - BOM对比

**缺失**: 无任何前端页面，用户无法使用BOM功能

---

### 2. QMS 质量模块 - FAI/IPC/OQC/CAPA 无前端 🟠 HIGH

后端已实现:
- FAI 首件检验 (`/fai/*`)
- IPC 过程检验 (`/ipc/*`)  
- OQC 出货检验 (`/oqc/*`)
- CAPA 纠正预防措施 (`/capa/*`, `/cases/*`)

**缺失**: 无对应前端页面，质量闭环流程不完整

---

### 3. PP 模块 - 高级功能无前端 🟡 MEDIUM

后端已实现但前端未使用:
- 计划变更请求 (`/plans/{id}/change-requests`)
- 计划版本历史 (`/plans/{id}/versions`)
- APS触发 (`/plans/{id}/trigger-aps`)
- 变更重排 (`/plans/{id}/reschedule-on-change`)
- 增量重排 (`/plans/{id}/incremental-reschedule`)

---

### 4. APS 模块 - 交付承诺/插单影响无前端 🟡 MEDIUM

后端已实现:
- `POST /api/v1/aps/delivery-promise` - 交期承诺
- `POST /api/v1/aps/rush-order-impact` - 插单影响分析

**缺失**: 无对应前端UI

---

## 四、修复优先级建议

| 优先级 | 问题 | 工作量 |
|--------|------|--------|
| P0 | IE Advanced 前缀不匹配 | 1行代码 |
| P0 | IE Advanced 缺失列表/删除接口 | ~200行 |
| P1 | APS schedule/conflicts 接口 | ~50行 |
| P1 | PP capacity-conflict 接口 | ~30行 |
| P1 | QMS defects PATCH 接口 | ~40行 |
| P1 | OCAP 路由导航修复 | 1行代码 |
| P2 | BOM 前端页面 | ~500行 |
| P2 | QMS FAI/IPC/OQC/CAPA 前端 | ~800行 |
| P3 | QMS 路由拼写修复 | 3行代码 |
| P3 | PP/APS 高级功能前端 | ~600行 |

---

## 五、快速修复命令

### 修复 IE Advanced 前缀 (P0)
```bash
# api/routes/ie_routes_extended.py 第23行
# 将: router = APIRouter(prefix="/api/v1/ie", tags=["ie-advanced"])
# 改为: router = APIRouter(prefix="/api/v1/ie-advanced", tags=["ie-advanced"])
```

### 修复 OCAP 导航 (P1)
```bash
# frontend/src/pages/qms/OcapList.tsx 第63行
# 将: onClick={() => navigate(`/qms/ocaps/${record.id}`)}
# 改为: onClick={() => navigate(`/ocaps/${record.id}`)}
```

---

*报告生成: 2026-07-28*
