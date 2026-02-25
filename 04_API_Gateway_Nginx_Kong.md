# EngHub MES 系统 - API 网关配置

---

## 一、Nginx 网关配置 (推荐用于简单场景)

### 1.1 主配置文件 (nginx.conf)

```nginx
# /etc/nginx/nginx.conf

user nginx;
worker_processes auto;
error_log /var/log/nginx/error.log warn;
pid /var/run/nginx.pid;

# 高性能配置
events {
    worker_connections 10000;      # 每个worker的最大连接数
    use epoll;                      # Linux高效事件模型
    multi_accept on;                # 一次接受多个连接
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    # 日志格式定义
    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" '
                    '"$http_user_agent" "$http_x_forwarded_for" '
                    'rt=$request_time uct="$upstream_connect_time" '
                    'uht="$upstream_header_time" urt="$upstream_response_time"';

    # JSON日志格式 (用于ELK)
    log_format json_format escape=json
    '{'
        '"remote_addr":"$remote_addr",'
        '"request_time":$request_time,'
        '"upstream_response_time":"$upstream_response_time",'
        '"status":"$status",'
        '"request":"$request",'
        '"http_referrer":"$http_referer",'
        '"http_user_agent":"$http_user_agent",'
        '"request_id":"$http_x_request_id"'
    '}';

    access_log /var/log/nginx/access.log main;

    # 性能优化
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    types_hash_max_size 2048;
    client_max_body_size 10M;
    
    # Gzip压缩
    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_comp_level 6;
    gzip_types text/plain text/css text/xml text/javascript 
               application/json application/javascript application/xml+rss 
               application/rss+xml font/truetype font/opentype 
               application/vnd.ms-fontobject image/svg+xml;

    # 隐藏Nginx版本号
    server_tokens off;

    # 速率限制
    limit_req_zone $binary_remote_addr zone=general:10m rate=100r/m;
    limit_req_zone $binary_remote_addr zone=reporting:10m rate=200r/m;
    limit_req_zone $binary_remote_addr zone=inspection:10m rate=100r/m;

    # 上游服务器定义 (负载均衡)
    upstream api_backend {
        least_conn;  # 最少连接负载均衡策略
        
        server api-1:8000 weight=1 max_fails=3 fail_timeout=30s;
        server api-2:8000 weight=1 max_fails=3 fail_timeout=30s;
        server api-3:8000 weight=1 max_fails=3 fail_timeout=30s;
        
        keepalive 64;  # 连接池
    }

    # 包含其他配置文件
    include /etc/nginx/conf.d/*.conf;
}
```

### 1.2 虚拟主机配置 (default.conf)

```nginx
# /etc/nginx/conf.d/default.conf

# HTTP重定向到HTTPS
server {
    listen 80;
    server_name api.enghub.com dashboard.enghub.com;
    
    # Let's Encrypt 验证
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }
    
    # 其他请求重定向到HTTPS
    location / {
        return 301 https://$server_name$request_uri;
    }
}

# API 主配置 (HTTPS)
server {
    listen 443 ssl http2;
    server_name api.enghub.com;

    # SSL证书配置
    ssl_certificate /etc/nginx/certs/api.enghub.com.crt;
    ssl_certificate_key /etc/nginx/certs/api.enghub.com.key;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # 安全头
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "no-referrer-when-downgrade" always;
    
    # CORS头 (可选，也可在应用层处理)
    add_header 'Access-Control-Allow-Origin' '*' always;
    add_header 'Access-Control-Allow-Methods' 'GET,POST,PATCH,DELETE,OPTIONS' always;
    add_header 'Access-Control-Allow-Headers' 'Content-Type,Authorization,X-Factory-ID,X-Request-ID' always;
    
    # OPTIONS 预检请求
    if ($request_method = 'OPTIONS') {
        return 204;
    }

    # API 路由配置
    
    # ============ 工单管理 API ============
    location /api/v1/work-orders {
        limit_req zone=general burst=10 nodelay;
        
        proxy_pass http://api_backend;
        proxy_http_version 1.1;
        
        # 请求头转发
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
        
        # 添加内部头部
        proxy_set_header X-Request-ID $http_x_request_id;
        proxy_set_header X-Forwarded-Host $server_name;
        
        # 超时设置
        proxy_connect_timeout 5s;
        proxy_send_timeout 10s;
        proxy_read_timeout 10s;
        
        # 缓冲设置
        proxy_buffering on;
        proxy_buffer_size 4k;
        proxy_buffers 8 4k;
    }

    # ============ 生产报工 API (高频) ============
    location /api/v1/production-reports {
        limit_req zone=reporting burst=20 nodelay;
        
        proxy_pass http://api_backend;
        proxy_http_version 1.1;
        
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Request-ID $http_x_request_id;
        proxy_set_header Connection "";
        
        # 报工API需要更长的超时
        proxy_connect_timeout 5s;
        proxy_send_timeout 30s;
        proxy_read_timeout 30s;
    }

    # ============ 检验管理 API ============
    location /api/v1/inspections {
        limit_req zone=inspection burst=10 nodelay;
        
        proxy_pass http://api_backend;
        proxy_http_version 1.1;
        
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Request-ID $http_x_request_id;
        proxy_set_header Connection "";
        
        proxy_connect_timeout 5s;
        proxy_send_timeout 15s;
        proxy_read_timeout 15s;
    }

    # ============ 报表查询 API ============
    location /api/v1/reports {
        limit_req zone=general burst=5 nodelay;
        
        proxy_pass http://api_backend;
        proxy_http_version 1.1;
        
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Request-ID $http_x_request_id;
        proxy_set_header Connection "";
        
        # 缓存报表查询结果 (5分钟)
        proxy_cache_key "$scheme$request_method$host$request_uri$http_x_factory_id";
        proxy_cache_valid 200 5m;
        proxy_cache_bypass $http_cache_control;
        
        proxy_connect_timeout 5s;
        proxy_send_timeout 30s;
        proxy_read_timeout 30s;
    }

    # ============ 所有其他API ============
    location /api/v1/ {
        limit_req zone=general burst=10 nodelay;
        
        proxy_pass http://api_backend;
        proxy_http_version 1.1;
        
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Request-ID $http_x_request_id;
        proxy_set_header Connection "";
        
        proxy_connect_timeout 5s;
        proxy_send_timeout 10s;
        proxy_read_timeout 10s;
    }

    # ============ 健康检查 ============
    location /health {
        access_log off;
        proxy_pass http://api_backend/api/v1/health;
        proxy_connect_timeout 2s;
        proxy_read_timeout 2s;
    }

    # ============ Prometheus指标 ============
    location /metrics {
        auth_basic "Restricted";
        auth_basic_user_file /etc/nginx/.htpasswd;
        
        proxy_pass http://api_backend/metrics;
        access_log off;
    }

    # ============ 文件上传 ============
    location /api/v1/attachments/upload {
        limit_req zone=general burst=5 nodelay;
        
        # 允许大文件上传 (最多100MB)
        client_max_body_size 100M;
        
        proxy_pass http://api_backend;
        proxy_http_version 1.1;
        
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Connection "";
        
        proxy_connect_timeout 10s;
        proxy_send_timeout 60s;  # 上传可能很慢
        proxy_read_timeout 60s;
        
        # 不缓冲，直接传输
        proxy_request_buffering off;
    }

    # ============ WebSocket (实时看板) ============
    location /api/v1/ws {
        proxy_pass http://api_backend;
        proxy_http_version 1.1;
        
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        
        # WebSocket超时
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
    }

    # ============ 静态资源缓存 ============
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
        access_log off;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # ============ 404处理 ============
    error_page 404 /404.json;
    location = /404.json {
        internal;
        default_type application/json;
        return 404 '{"code":"NOT_FOUND","message":"请求的资源不存在"}';
    }

    # ============ 50x错误处理 ============
    error_page 500 502 503 504 /50x.html;
    location = /50x.html {
        root /usr/share/nginx/html;
    }
}

# Dashboard 前端 (HTTPS)
server {
    listen 443 ssl http2;
    server_name dashboard.enghub.com;

    ssl_certificate /etc/nginx/certs/dashboard.enghub.com.crt;
    ssl_certificate_key /etc/nginx/certs/dashboard.enghub.com.key;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    root /usr/share/nginx/html;
    index index.html;

    # SPA路由处理 (所有请求都到index.html)
    location / {
        try_files $uri $uri/ /index.html;
        
        # 缓存HTML (不缓存，每次都检查)
        add_header Cache-Control "no-cache, no-store, must-revalidate";
    }

    # 静态资源缓存
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # API代理
    location /api/ {
        proxy_pass https://api.enghub.com;
        proxy_ssl_verify off;  # 如果使用自签名证书
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## 二、Kong API 网关配置 (推荐用于复杂场景)

### 2.1 Kong Docker 部署

```yaml
# docker-compose.yml (Kong)

version: '3.8'

services:
  kong-database:
    image: postgres:15-alpine
    container_name: kong-database
    environment:
      POSTGRES_DB: kong
      POSTGRES_USER: kong
      POSTGRES_PASSWORD: kong_password
    volumes:
      - kong_db_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "kong"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - kong-network

  kong-migration:
    image: kong:3.4-alpine
    container_name: kong-migration
    environment:
      KONG_DATABASE: postgres
      KONG_PG_HOST: kong-database
      KONG_PG_USER: kong
      KONG_PG_PASSWORD: kong_password
    command: kong migrations bootstrap
    depends_on:
      - kong-database
    networks:
      - kong-network

  kong:
    image: kong:3.4-alpine
    container_name: kong-gateway
    environment:
      KONG_DATABASE: postgres
      KONG_PG_HOST: kong-database
      KONG_PG_USER: kong
      KONG_PG_PASSWORD: kong_password
      KONG_PROXY_ACCESS_LOG: /dev/stdout
      KONG_ADMIN_ACCESS_LOG: /dev/stdout
      KONG_PROXY_ERROR_LOG: /dev/stderr
      KONG_ADMIN_ERROR_LOG: /dev/stderr
      KONG_LOG_LEVEL: notice
    ports:
      - "8000:8000"   # proxy
      - "8443:8443"   # proxy SSL
      - "8001:8001"   # admin API
      - "8444:8444"   # admin API SSL
    depends_on:
      - kong-database
    healthcheck:
      test: ["CMD", "kong", "health"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - kong-network

  konga:
    image: pantsel/konga:latest
    container_name: kong-admin-ui
    environment:
      NODE_ENV: production
      DB_ADAPTER: postgres
      DB_HOST: kong-database
      DB_USER: kong
      DB_PASSWORD: kong_password
      DB_DATABASE: konga
    ports:
      - "1337:1337"
    depends_on:
      - kong
    networks:
      - kong-network

volumes:
  kong_db_data:

networks:
  kong-network:
    driver: bridge
```

### 2.2 Kong 服务配置 (声明式)

```yaml
# kong.yaml (Kong 配置文件)

_format_version: "3.0"
_transform: true

services:
  # ============ API 服务 ============
  - name: enghub-api
    url: http://api-backend:8000
    protocol: http
    host: api-backend
    port: 8000
    connect_timeout: 5000
    write_timeout: 60000
    read_timeout: 60000
    
    # 路由
    routes:
      # 工单管理
      - name: work-orders
        paths:
          - /api/v1/work-orders
        strip_path: false
        protocols:
          - http
          - https
      
      # 生产报工
      - name: production-reports
        paths:
          - /api/v1/production-reports
        strip_path: false
        protocols:
          - http
          - https
      
      # 检验管理
      - name: inspections
        paths:
          - /api/v1/inspections
        strip_path: false
        protocols:
          - http
          - https
      
      # 报表
      - name: reports
        paths:
          - /api/v1/reports
        strip_path: false
        protocols:
          - http
          - https
      
      # 所有API
      - name: general-api
        paths:
          - /api/v1
        strip_path: false
        protocols:
          - http
          - https

    # 插件配置
    plugins:
      # ============ 认证插件 ============
      - name: jwt
        config:
          secret_is_base64: false
          key_claim_name: iss
      
      # ============ 限流插件 ============
      - name: rate-limiting
        config:
          minute: 100
          fault_tolerant: true
      
      # ============ 请求转换 ============
      - name: request-transformer
        config:
          add:
            headers:
              - X-Gateway-Timestamp:$(date +%s)
      
      # ============ 响应转换 ============
      - name: response-transformer
        config:
          add:
            headers:
              - X-Response-Time:$(time)
      
      # ============ CORS ============
      - name: cors
        config:
          origins:
            - "*"
          methods:
            - GET
            - POST
            - PATCH
            - DELETE
            - OPTIONS
          headers:
            - Content-Type
            - Authorization
            - X-Factory-ID
            - X-Request-ID
          credentials: true
      
      # ============ 日志记录 ============
      - name: http-log
        config:
          http_endpoint: http://logstash:5000
          method: POST
      
      # ============ 请求缓存 ============
      - name: proxy-cache
        config:
          cache_ttl: 300
          vary_headers:
            - X-Factory-ID

# ============ 上游服务（负载均衡） ============
upstreams:
  - name: api-backend
    algorithm: least-conn
    targets:
      - target: api-1:8000
        weight: 1
      - target: api-2:8000
        weight: 1
      - target: api-3:8000
        weight: 1

# ============ 消费者（API客户端） ============
consumers:
  - username: frontend-client
    custom_id: frontend-001
    credentials:
      - name: jwt
        key: frontend-secret-key
        secret: frontend-secret-value
  
  - username: mobile-client
    custom_id: mobile-001
    credentials:
      - name: jwt
        key: mobile-secret-key
        secret: mobile-secret-value
  
  - username: third-party-api
    custom_id: third-party-001
    credentials:
      - name: jwt
        key: third-party-key
        secret: third-party-secret

# ============ 插件策略 ============
plugins:
  # 全局日志
  - name: http-log
    config:
      http_endpoint: http://logstash:5000
      queue:
        max_batch_size: 1000
        max_coalescing_delay: 1
  
  # 全局监控
  - name: prometheus
    config:
      metrics:
        - request_count
        - latency
        - request_size
        - response_size
        - upstream_latency
        - kong_latency
        - status_count
```

### 2.3 Kong 配置命令

```bash
# 启动Kong
docker-compose up -d

# 查看Kong状态
curl -s http://localhost:8001 | jq

# 添加服务
curl -X POST http://localhost:8001/services \
  -d "name=enghub-api" \
  -d "url=http://api-backend:8000"

# 添加路由
curl -X POST http://localhost:8001/services/enghub-api/routes \
  -d "paths[]=/api/v1/work-orders" \
  -d "strip_path=false"

# 添加限流插件
curl -X POST http://localhost:8001/services/enghub-api/plugins \
  -d "name=rate-limiting" \
  -d "config.minute=100"

# 添加JWT认证
curl -X POST http://localhost:8001/services/enghub-api/plugins \
  -d "name=jwt"

# 查看所有插件
curl http://localhost:8001/plugins

# 查看Konga管理界面
# 访问: http://localhost:1337
```

---

## 三、API 网关常见配置

### 3.1 限流配置矩阵

```
┌─────────────────────────────────────┬──────────────┬──────────────┐
│ API 端点                            │ 全局限制     │ 单用户限制   │
├─────────────────────────────────────┼──────────────┼──────────────┤
│ POST /api/v1/work-orders            │ 20req/min    │ 5req/min     │
│ GET /api/v1/work-orders             │ 100req/min   │ 30req/min    │
│ POST /api/v1/production-reports     │ 500req/min   │ 100req/min   │
│ GET /api/v1/reports/*               │ 50req/min    │ 10req/min    │
│ POST /api/v1/inspections            │ 100req/min   │ 20req/min    │
│ POST /api/v1/attachments/upload     │ 100req/min   │ 5req/min     │
└─────────────────────────────────────┴──────────────┴──────────────┘
```

### 3.2 超时配置

```nginx
# 根据不同API设置不同超时

# 快速查询 (列表)
proxy_connect_timeout 2s;
proxy_read_timeout 5s;
proxy_send_timeout 5s;

# 普通操作 (CRUD)
proxy_connect_timeout 5s;
proxy_read_timeout 10s;
proxy_send_timeout 10s;

# 报工 (可能较慢)
proxy_connect_timeout 10s;
proxy_read_timeout 30s;
proxy_send_timeout 30s;

# 文件上传 (很慢)
proxy_connect_timeout 10s;
proxy_read_timeout 120s;
proxy_send_timeout 120s;
```

### 3.3 缓存策略

```nginx
# 可缓存的API
location ~ ^/api/v1/(products|stations|routings)$ {
    proxy_cache my_cache;
    proxy_cache_key "$scheme$request_method$host$request_uri$http_x_factory_id";
    proxy_cache_valid 200 10m;           # 200状态码缓存10分钟
    proxy_cache_valid 404 1m;            # 404缓存1分钟
    proxy_cache_use_stale error timeout invalid_header updating;
    proxy_cache_bypass $http_cache_control;
    
    add_header X-Cache-Status $upstream_cache_status;
}

# 不可缓存的API
location ~ ^/api/v1/(work-orders|production-reports|inspections)$ {
    proxy_pass http://api_backend;
    proxy_cache off;
}
```

### 3.4 黑名单和白名单

```nginx
# 黑名单 (某些IP被限流)
geo $limit {
    default 1;
    192.168.0.0/16 0;     # 内网不限流
    10.0.0.0/8 0;         # VPN不限流
    203.0.113.100 1;       # 特定坏IP限流
}

map $limit $limit_api {
    0 "";
    1 $binary_remote_addr;
}

limit_req_zone $limit_api zone=api_limit:10m rate=100r/m;

# 使用
location /api/v1/ {
    limit_req zone=api_limit burst=20;
    proxy_pass http://api_backend;
}
```

---

## 四、监控和告警

### 4.1 Nginx 监控指标

```nginx
# 导出Prometheus格式的指标 (使用nginx-prometheus-exporter)

location /metrics {
    access_log off;
    # 由nginx-prometheus-exporter处理
}
```

### 4.2 Kong 监控

```bash
# 获取Kong的Prometheus指标
curl http://localhost:8001/metrics

# 指标示例:
# kong_http_requests_total{service="enghub-api",route="work-orders",status="200"} 12345
# kong_latency{service="enghub-api",quantile="0.95"} 45.6
```

### 4.3 告警规则

```yaml
# prometheus/rules.yml

groups:
  - name: enghub_api
    interval: 30s
    rules:
      # API响应时间告警
      - alert: HighAPILatency
        expr: histogram_quantile(0.95, rate(kong_latency[5m])) > 1000
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "API响应缓慢"
          description: "API P95延迟超过1秒"
      
      # 错误率告警
      - alert: HighErrorRate
        expr: rate(kong_http_requests_total{status=~"5.."}[5m]) > 0.01
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "API错误率过高"
          description: "API错误率超过1%"
      
      # 限流告警
      - alert: APIRateLimited
        expr: rate(kong_http_requests_total{status="429"}[5m]) > 0
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "API被限流"
          description: "检测到请求被限流"
```

---

## 五、安全配置

### 5.1 SSL/TLS 配置

```bash
# 生成自签名证书 (开发)
openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes

# 使用Let's Encrypt (生产)
certbot certonly --standalone -d api.enghub.com -d dashboard.enghub.com

# Nginx SSL配置
ssl_protocols TLSv1.2 TLSv1.3;
ssl_ciphers HIGH:!aNULL:!MD5;
ssl_prefer_server_ciphers on;
ssl_session_cache shared:SSL:10m;
ssl_session_timeout 10m;
```

### 5.2 WAF (Web应用防火墙) - ModSecurity

```nginx
# 启用ModSecurity
SecEngineOn
SecDefaultAction "phase:2,log,deny,status:403"

# 防御SQL注入
SecRule ARGS "@detectSQLi" "id:1001,phase:2,deny"

# 防御XSS
SecRule ARGS "@detectXSS" "id:1002,phase:2,deny"

# 防御路径遍历
SecRule ARGS "@contains ../" "id:1003,phase:2,deny"

# 防御文件包含
SecRule ARGS "@contains /etc/passwd" "id:1004,phase:2,deny"
```

---

## 六、故障排查

### 6.1 常见问题和解决方案

```bash
# 1. 502 Bad Gateway
# 原因: 后端服务不可用
# 检查:
curl http://api-backend:8000/api/v1/health
docker logs enghub-api-1

# 2. 504 Gateway Timeout
# 原因: 后端响应超时
# 解决: 增加proxy_read_timeout

# 3. 429 Too Many Requests
# 原因: 请求被限流
# 检查: 是否超过限流阈值
# 解决: 调整limit_req_zone参数

# 4. 404 Not Found
# 原因: 路由配置错误
# 检查:
curl -v http://localhost/api/v1/work-orders
# 查看Location头是否正确

# 5. CORS 错误
# 原因: 跨域请求被拒绝
# 检查: Nginx中的Access-Control-Allow-Origin头
```

### 6.2 日志分析

```bash
# 查看access日志
tail -f /var/log/nginx/access.log

# 查看error日志
tail -f /var/log/nginx/error.log

# 统计API响应码分布
awk '{print $9}' /var/log/nginx/access.log | sort | uniq -c

# 找出最慢的请求
awk '{print $(NF-1), $7}' /var/log/nginx/access.log | sort -rn | head -10

# 找出请求最多的IP
awk '{print $1}' /var/log/nginx/access.log | sort | uniq -c | sort -rn | head -10
```

---

## 总结：网关选型建议

| 特性 | Nginx | Kong |
|------|-------|------|
| **部署复杂度** | 简单 | 中等 |
| **性能** | 极快 | 快 |
| **插件生态** | 少 | 丰富 |
| **管理界面** | 无 | 有(Konga) |
| **限流** | 有 | 有 |
| **认证** | 简单 | 完整(JWT/OAuth) |
| **动态配置** | 需重启 | 热更新 |
| **学习曲线** | 简单 | 中等 |
| **推荐场景** | 中小型系统 | 大型系统/微服务 |

**建议:**
- 初期使用 **Nginx** (部署快、维护简单)
- 系统复杂后迁移到 **Kong** (功能完整、可扩展)
