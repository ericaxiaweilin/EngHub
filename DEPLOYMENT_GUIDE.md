# EngHub MES 部署指南

## 📋 前置要求

- Docker 20.10+
- Docker Compose 2.0+
- 可用磁盘空间：≥ 2GB
- 内存：≥ 2GB

## 🚀 快速启动

### 1. 清理磁盘空间 (如需要)

```bash
docker system prune -af --volumes
```

### 2. 启动所有服务

```bash
cd /workspace
docker-compose up -d --build
```

### 3. 查看启动日志

```bash
docker-compose logs -f
```

等待看到以下日志表示启动成功:
- `enghub-db`: `database system is ready to accept connections`
- `enghub-api`: `Uvicorn running on http://0.0.0.0:8000`
- `enghub-web`: `nginx: configuration file test successful`

### 4. 访问系统

| 服务 | URL | 说明 |
|------|-----|------|
| **前端界面** | http://localhost | React 管理后台 |
| **后端 API** | http://localhost/api/docs | Swagger API 文档 |
| **数据库** | localhost:5432 | PostgreSQL (mesuser/mespassword) |

### 5. 默认账号

- **用户名**: `admin`
- **密码**: `Admin@123456`

## 📊 服务架构

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Nginx     │────▶│  FastAPI    │────▶│  PostgreSQL │
│   (Port 80) │     │ (Port 8000) │     │ (Port 5432) │
└─────────────┘     └─────────────┘     └─────────────┘
     │                    │                    │
     │                    │                    │
  静态资源            业务逻辑            数据存储
  SPA 路由             JWT 认证            初始化脚本
  API 代理             REST API           基础数据
```

## 🔧 常用命令

### 查看服务状态
```bash
docker-compose ps
```

### 重启单个服务
```bash
docker-compose restart backend
```

### 查看后端日志
```bash
docker-compose logs backend
```

### 进入数据库容器
```bash
docker exec -it enghub-db psql -U mesuser -d mesdb
```

### 进入后端容器
```bash
docker exec -it enghub-api bash
```

### 停止所有服务
```bash
docker-compose down
```

### 停止并删除数据卷 (⚠️ 会清空数据)
```bash
docker-compose down -v
```

## 📁 数据持久化

- **数据库数据**: 存储在 Docker volume `pg_data`
- **位置**: `/var/lib/docker/volumes/enghub_pg_data/_data`

## 🔐 生产环境配置

### 修改敏感信息

编辑 `docker-compose.yml`:

```yaml
environment:
  JWT_SECRET_KEY: <生成一个强随机密钥>
  POSTGRES_PASSWORD: <强密码>
```

### 生成 JWT 密钥
```bash
openssl rand -hex 32
```

### 启用 HTTPS

在生产环境中，建议在 Nginx 前配置反向代理 (如 Traefik) 或使用云服务商的 SSL 终止。

## 🐛 故障排查

### 1. 后端无法连接数据库

检查数据库是否健康:
```bash
docker-compose logs postgres
```

确保 `DATABASE_URL` 环境变量正确。

### 2. 前端页面空白

检查浏览器控制台错误，确认 API 代理配置正确。

### 3. 端口冲突

如果 80/8000/5432 端口被占用，修改 `docker-compose.yml` 中的端口映射。

### 4. 初始化脚本未执行

查看 init-db 容器日志:
```bash
docker-compose logs init-db
```

手动执行初始化:
```bash
docker exec -i enghub-db psql -U mesuser -d mesdb < scripts/init_db.sql
```

## 📈 性能优化建议

1. **数据库索引**: 对常用查询字段添加索引
2. **Redis 缓存**: 启用 Redis 缓存热点数据
3. **Gzip 压缩**: 已配置 Nginx Gzip
4. **静态资源 CDN**: 生产环境可配置 CDN

## 📞 技术支持

- API 文档: http://localhost/api/docs
- 项目仓库: [内部仓库]
- 问题反馈: [内部工单系统]

---

**EngHub MES 1.0.0** - 智能制造执行系统
