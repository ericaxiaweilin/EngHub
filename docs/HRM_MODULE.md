# HRM 人力资源管理系统

## 模块概述

本模块为中小企业提供完整的人力资源管理解决方案，包含人事、行政、员工自助服务等功能。

## 功能清单

### 1. 组织架构管理
- [x] 部门管理（支持多级树形结构）
- [x] 部门负责人设置
- [x] 部门状态管理（启用/禁用）

### 2. 员工信息管理
- [x] 员工档案（基本信息、联系方式、教育背景）
- [x] 入职管理（工号自动生成、试用期管理）
- [x] 雇佣类型（全职/兼职/实习/合同/派遣）
- [x] 员工状态（试用期/正式/离职/退休/停职）
- [x] 离职管理（离职原因、离职日期）
- [x] 合同管理（合同期限、签约次数）
- [x] 薪资信息（基本工资、绩效工资、补贴）

### 3. 考勤管理
- [x] 打卡记录（上班/下班打卡）
- [x] 排班管理（应上/下班时间）
- [x] 考勤状态（正常/迟到/早退/旷工）
- [x] 迟到早退统计
- [x] 工作时长计算
- [x] 加班时长统计
- [x] 月度考勤报表

### 4. 请假管理
- [x] 请假申请（年假/病假/事假/婚假/产假/陪产假/丧假）
- [x] 请假审批流程
- [x] 请假天数自动计算
- [x] 审批意见记录
- [x] 附件上传（病假条等）

### 5. 薪资管理
- [x] 薪资自动计算
- [x] 应发项目（基本工资/绩效工资/加班费/补贴/奖金）
- [x] 扣款项目（社保/公积金/个税/缺勤扣款）
- [x] 薪资明细查询
- [x] 发放状态管理

### 6. 行政管理
- [x] 行政申请（加班/出差/用印/资产借用/会议室/用车/采购/报销）
- [x] 审批流程管理
- [x] 申请单号自动生成
- [x] 审批意见记录

### 7. 资产管理
- [x] 资产登记（电脑/家具/设备/车辆）
- [x] 资产分配与归还
- [x] 资产状态跟踪（闲置/使用中/维修中/已报废）
- [x] 保修期管理
- [x] 供应商信息

### 8. 会议室管理
- [x] 会议室信息（位置/容量/设施）
- [x] 会议室预定
- [x] 可用性检查
- [x] 冲突检测

### 9. 公司公告
- [x] 公告发布
- [x] 公告类型（普通/紧急/制度）
- [x] 优先级设置
- [x] 置顶功能
- [x] 浏览次数统计

## API 端点

### 部门管理
| 方法 | 路径 | 描述 |
|------|------|------|
| GET | `/hrm/departments` | 获取部门列表 |
| GET | `/hrm/departments/tree` | 获取部门树形结构 |
| POST | `/hrm/departments` | 创建部门 |
| PUT | `/hrm/departments/{id}` | 更新部门 |
| DELETE | `/hrm/departments/{id}` | 删除部门 |

### 员工管理
| 方法 | 路径 | 描述 |
|------|------|------|
| GET | `/hrm/employees` | 获取员工列表 |
| GET | `/hrm/employees/{id}` | 获取员工详情 |
| POST | `/hrm/employees` | 创建员工 |
| PUT | `/hrm/employees/{id}` | 更新员工 |
| POST | `/hrm/employees/{id}/resign` | 办理离职 |

### 考勤管理
| 方法 | 路径 | 描述 |
|------|------|------|
| GET | `/hrm/attendance/stats/{emp_id}` | 获取月度考勤统计 |

### 请假管理
| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/hrm/leaves/apply` | 申请请假 |
| POST | `/hrm/leaves/{id}/approve` | 审批请假 |
| GET | `/hrm/leaves/my` | 我的请假记录 |

### 薪资管理
| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/hrm/salary/calculate/{emp_id}` | 计算薪资 |

### 行政管理
| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/hrm/admin-requests` | 创建行政申请 |
| POST | `/hrm/admin-requests/{id}/approve` | 审批行政申请 |

### 资产管理
| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/hrm/assets/{id}/assign` | 分配资产 |
| POST | `/hrm/assets/{id}/return` | 归还资产 |

### 会议室管理
| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/hrm/meeting-rooms/{id}/book` | 预定会议室 |
| GET | `/hrm/meeting-rooms/{id}/availability` | 检查可用性 |

### 公告管理
| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/hrm/notices` | 发布公告 |
| GET | `/hrm/notices` | 获取公告列表 |

## 数据库模型

- `Department` - 部门表
- `Employee` - 员工信息表
- `Attendance` - 考勤记录表
- `Leave` - 请假申请表
- `Salary` - 薪资表
- `AdminRequest` - 行政申请表
- `Asset` - 公司资产表
- `MeetingRoom` - 会议室表
- `MeetingRoomBooking` - 会议室预定表
- `Notice` - 公司公告表

## 使用示例

### 创建部门
```bash
curl -X POST http://localhost:8000/hrm/departments \
  -H "Content-Type: application/json" \
  -d '{"code": "TECH", "name": "技术部", "level": 1}'
```

### 创建员工
```bash
curl -X POST http://localhost:8000/hrm/employees \
  -H "Content-Type: application/json" \
  -d '{
    "name": "张三",
    "gender": "male",
    "phone": "13800138000",
    "email": "zhangsan@example.com",
    "department_id": 1,
    "position": "软件工程师",
    "entry_date": "2024-01-01",
    "base_salary": 15000
  }'
```

### 申请请假
```bash
curl -X POST http://localhost:8000/hrm/leaves/apply \
  -H "Content-Type: application/json" \
  -d '{
    "type": "annual",
    "start_date": "2024-06-01",
    "end_date": "2024-06-03",
    "reason": "个人事务"
  }'
```

### 预定会议室
```bash
curl -X POST http://localhost:8000/hrm/meeting-rooms/1/book \
  -H "Content-Type: application/json" \
  -d '{
    "title": "项目评审会",
    "start_time": "2024-05-20T14:00:00",
    "end_time": "2024-05-20T16:00:00",
    "participants": 10
  }'
```

## 后续优化建议

1. **审批流程引擎** - 支持自定义多级审批流程
2. **考勤规则配置** - 灵活配置上下班时间、迟到容忍度
3. **薪资公式配置** - 支持自定义薪资计算公式
4. **员工自助门户** - 员工查看个人信息、提交申请
5. **数据导出** - 支持 Excel/PDF 格式导出
6. **消息通知** - 审批结果邮件/短信通知
7. **报表分析** - 人力成本分析、离职率分析
