# MES 系统部署指南

## 快速开始

### 1. 环境准备

```bash
# 安装依赖
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，修改数据库连接等配置
```

### 3. 初始化数据库

```bash
# 运行管理员初始化脚本
python scripts/init_admin.py
```

### 4. 启动服务

```bash
# 开发模式
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# 或使用 Docker Compose
cd docker
docker-compose -f docker-compose.minimal.yml up -d
```

## 默认管理员账户

- **用户名**: admin
- **密码**: admin123
- **⚠️ 首次登录后请立即修改密码**

## API 文档

启动服务后访问：
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 主要功能模块

### 认证授权
- 用户登录/注册
- JWT Token 管理
- 权限控制

### MES - 制造执行
- 工单管理 (创建、下达、开始、完成)
- 生产报工
- 工艺路线管理
- 工位/设备管理

### WMS - 仓库管理
- 仓库/库位管理
- 入库/出库操作
- 库存查询
- 库存盘点
- 物料追溯

### PP - 生产计划
- MPS 主生产计划
- MRP 物料需求计划
- 产能分析

### QMS - 质量管理
- IQC/IPQC/FQC/OQC 检验
- 不良品管理
- AQL 判定
- OCAP 异常处理

## Docker 部署

```bash
cd docker

# 最小化部署 (仅必需组件)
docker-compose -f docker-compose.minimal.yml up -d

# 优化版部署 (含监控系统)
docker-compose -f docker-compose.optimized.yml up -d
```

## 技术架构

- **后端**: Python FastAPI + SQLAlchemy (Async)
- **数据库**: PostgreSQL 15
- **缓存**: Redis (可选)
- **容器化**: Docker + Docker Compose
- **前端**: React + TypeScript + Vite (待完善)

## 下一步计划

- [ ] 完善前端页面 (登录、工单管理、仓库管理等)
- [ ] 添加单元测试
- [ ] 数据库迁移脚本 (Alembic)
- [ ] CI/CD 流水线
- [ ] 日志监控系统
