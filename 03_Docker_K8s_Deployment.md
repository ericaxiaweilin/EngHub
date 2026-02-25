# EngHub MES 系统 - 容器化部署配置

---

## 一、Dockerfile 设计

### 1.1 后端服务 Dockerfile (FastAPI)

```dockerfile
# Dockerfile.backend

# 构建阶段
FROM python:3.11-slim as builder

WORKDIR /build

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# 运行阶段
FROM python:3.11-slim

WORKDIR /app

# 从构建阶段复制依赖
COPY --from=builder /root/.local /root/.local

# 设置环境变量
ENV PATH=/root/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# 创建非root用户
RUN useradd -m -u 1000 enghub && \
    chown -R enghub:enghub /app

# 复制应用代码
COPY --chown=enghub:enghub . .

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/api/v1/health')" || exit 1

# 使用非root用户运行
USER enghub

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 1.2 前端 Dockerfile (React)

```dockerfile
# Dockerfile.frontend

# 构建阶段
FROM node:18-alpine as builder

WORKDIR /app

# 复制依赖文件
COPY package*.json ./

# 安装依赖
RUN npm ci

# 复制代码
COPY . .

# 构建
RUN npm run build

# 运行阶段
FROM nginx:alpine

# 复制nginx配置
COPY nginx.conf /etc/nginx/nginx.conf
COPY default.conf /etc/nginx/conf.d/default.conf

# 从构建阶段复制构建产物
COPY --from=builder /app/build /usr/share/nginx/html

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://localhost:80/health || exit 1

# 暴露端口
EXPOSE 80

# 启动
CMD ["nginx", "-g", "daemon off;"]
```

### 1.3 requirements.txt (Python依赖)

```
# 主框架
fastapi==0.104.1
uvicorn[standard]==0.24.0
pydantic==2.5.0
pydantic-settings==2.1.0

# 数据库
sqlalchemy==2.0.23
psycopg2-binary==2.9.9
alembic==1.12.1

# 异步
aioredis==2.0.1
httpx==0.25.2

# 认证
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
python-multipart==0.0.6

# 缓存和消息队列
redis==5.0.1
pika==1.3.2

# 日志和监控
python-json-logger==2.0.7
prometheus-client==0.19.0
opentelemetry-api==1.20.0
opentelemetry-sdk==1.20.0
opentelemetry-exporter-jaeger==1.20.0

# 工具
python-dotenv==1.0.0
requests==2.31.0
pandas==2.1.3
openpyxl==3.11.0

# 开发和测试
pytest==7.4.3
pytest-asyncio==0.21.1
pytest-cov==4.1.0
black==23.12.0
flake8==6.1.0
isort==5.13.2

# API文档
python-multipart==0.0.6
```

---

## 二、Docker Compose 部署 (本地开发/小规模部署)

### 2.1 完整的 docker-compose.yml

```yaml
version: '3.9'

services:
  # PostgreSQL 主库
  postgres-master:
    image: postgres:15-alpine
    container_name: enghub-postgres-master
    environment:
      POSTGRES_DB: enghub
      POSTGRES_USER: enghub
      POSTGRES_PASSWORD: enghub_password_dev
      POSTGRES_REPLICATION_MODE: master
      POSTGRES_REPLICATION_USER: replication
      POSTGRES_REPLICATION_PASSWORD: replication_password
    ports:
      - "5432:5432"
    volumes:
      - postgres_master_data:/var/lib/postgresql/data
      - ./init/postgres-master.sql:/docker-entrypoint-initdb.d/01-master.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U enghub -d enghub"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - enghub-network

  # PostgreSQL 从库 (只读)
  postgres-slave:
    image: postgres:15-alpine
    container_name: enghub-postgres-slave
    environment:
      POSTGRES_DB: enghub
      POSTGRES_USER: enghub
      POSTGRES_PASSWORD: enghub_password_dev
      POSTGRES_MASTER_SERVICE: postgres-master
      PGUSER: replication
      PGPASSWORD: replication_password
    ports:
      - "5433:5432"
    volumes:
      - postgres_slave_data:/var/lib/postgresql/data
      - ./init/postgres-slave.sh:/docker-entrypoint-initdb.d/02-slave.sh
    depends_on:
      postgres-master:
        condition: service_healthy
    networks:
      - enghub-network

  # Redis 缓存
  redis:
    image: redis:7-alpine
    container_name: enghub-redis
    command: redis-server --appendonly yes --requirepass redis_password
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "--raw", "incr", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - enghub-network

  # RabbitMQ 消息队列
  rabbitmq:
    image: rabbitmq:3.12-management-alpine
    container_name: enghub-rabbitmq
    environment:
      RABBITMQ_DEFAULT_USER: enghub
      RABBITMQ_DEFAULT_PASS: rabbitmq_password
      RABBITMQ_DEFAULT_VHOST: /
    ports:
      - "5672:5672"      # AMQP
      - "15672:15672"    # Management UI
    volumes:
      - rabbitmq_data:/var/lib/rabbitmq
    healthcheck:
      test: ["CMD", "rabbitmq-diagnostics", "-q", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - enghub-network

  # Kafka (可选，用于高吞吐量)
  zookeeper:
    image: confluentinc/cp-zookeeper:7.5.0
    container_name: enghub-zookeeper
    environment:
      ZOOKEEPER_CLIENT_PORT: 2181
      ZOOKEEPER_TICK_TIME: 2000
    ports:
      - "2181:2181"
    volumes:
      - zookeeper_data:/var/lib/zookeeper/data
    networks:
      - enghub-network

  kafka:
    image: confluentinc/cp-kafka:7.5.0
    container_name: enghub-kafka
    depends_on:
      - zookeeper
    environment:
      KAFKA_BROKER_ID: 1
      KAFKA_ZOOKEEPER_CONNECT: zookeeper:2181
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka:29092,PLAINTEXT_HOST://localhost:9092
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: PLAINTEXT:PLAINTEXT,PLAINTEXT_HOST:PLAINTEXT
      KAFKA_INTER_BROKER_LISTENER_NAME: PLAINTEXT
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
      KAFKA_AUTO_CREATE_TOPICS_ENABLE: "true"
    ports:
      - "9092:9092"
    volumes:
      - kafka_data:/var/lib/kafka/data
    networks:
      - enghub-network

  # Elasticsearch (日志存储)
  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.10.0
    container_name: enghub-elasticsearch
    environment:
      discovery.type: single-node
      xpack.security.enabled: "false"
      ES_JAVA_OPTS: "-Xms512m -Xmx512m"
    ports:
      - "9200:9200"
    volumes:
      - elasticsearch_data:/usr/share/elasticsearch/data
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:9200/_cluster/health || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - enghub-network

  # Logstash (日志收集)
  logstash:
    image: docker.elastic.co/logstash/logstash:8.10.0
    container_name: enghub-logstash
    volumes:
      - ./config/logstash.conf:/usr/share/logstash/pipeline/logstash.conf
    depends_on:
      - elasticsearch
    ports:
      - "5000:5000/tcp"
      - "5000:5000/udp"
    networks:
      - enghub-network

  # Kibana (日志查看)
  kibana:
    image: docker.elastic.co/kibana/kibana:8.10.0
    container_name: enghub-kibana
    environment:
      ELASTICSEARCH_HOSTS: http://elasticsearch:9200
    ports:
      - "5601:5601"
    depends_on:
      - elasticsearch
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:5601/api/status || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - enghub-network

  # Prometheus (监控)
  prometheus:
    image: prom/prometheus:latest
    container_name: enghub-prometheus
    volumes:
      - ./config/prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus_data:/prometheus
    ports:
      - "9090:9090"
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
    networks:
      - enghub-network

  # Grafana (可视化)
  grafana:
    image: grafana/grafana:latest
    container_name: enghub-grafana
    environment:
      GF_SECURITY_ADMIN_PASSWORD: admin
      GF_INSTALL_PLUGINS: grafana-piechart-panel
    ports:
      - "3000:3000"
    volumes:
      - grafana_data:/var/lib/grafana
      - ./config/grafana/provisioning:/etc/grafana/provisioning
    depends_on:
      - prometheus
    networks:
      - enghub-network

  # Jaeger (分布式追踪)
  jaeger:
    image: jaegertracing/all-in-one:latest
    container_name: enghub-jaeger
    ports:
      - "16686:16686"  # UI
      - "6831:6831/udp"  # Jaeger agent
    networks:
      - enghub-network

  # API 网关 (Nginx)
  nginx:
    image: nginx:alpine
    container_name: enghub-nginx
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./config/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./config/default.conf:/etc/nginx/conf.d/default.conf:ro
      - ./certs:/etc/nginx/certs:ro
    depends_on:
      - api
    healthcheck:
      test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://localhost/health"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - enghub-network

  # 后端 API 服务 (可以多个副本)
  api:
    build:
      context: .
      dockerfile: Dockerfile.backend
    image: enghub/mes-api:latest
    container_name: enghub-api-1
    environment:
      DATABASE_URL: postgresql://enghub:enghub_password_dev@postgres-master:5432/enghub
      DATABASE_SLAVE_URL: postgresql://enghub:enghub_password_dev@postgres-slave:5432/enghub
      REDIS_URL: redis://:redis_password@redis:6379/0
      RABBITMQ_URL: amqp://enghub:rabbitmq_password@rabbitmq:5672/
      KAFKA_BROKERS: kafka:29092
      JAEGER_AGENT_HOST: jaeger
      JAEGER_AGENT_PORT: 6831
      LOG_LEVEL: INFO
      ENVIRONMENT: development
    ports:
      - "8000:8000"
    depends_on:
      postgres-master:
        condition: service_healthy
      redis:
        condition: service_healthy
      rabbitmq:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/health"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - enghub-network
    volumes:
      - ./logs:/app/logs

  # 前端
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile.frontend
    image: enghub/mes-frontend:latest
    container_name: enghub-frontend
    ports:
      - "3000:80"
    depends_on:
      - api
    networks:
      - enghub-network

volumes:
  postgres_master_data:
  postgres_slave_data:
  redis_data:
  rabbitmq_data:
  zookeeper_data:
  kafka_data:
  elasticsearch_data:
  prometheus_data:
  grafana_data:

networks:
  enghub-network:
    driver: bridge
```

### 2.2 启动命令

```bash
# 构建镜像
docker-compose build

# 启动所有服务
docker-compose up -d

# 查看日志
docker-compose logs -f api

# 停止服务
docker-compose down

# 清理数据
docker-compose down -v
```

---

## 三、Kubernetes 部署配置

### 3.1 Namespace 和配置

#### enghub-namespace.yaml

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: enghub-prod
  labels:
    name: enghub-prod
---
apiVersion: v1
kind: Namespace
metadata:
  name: enghub-monitoring
  labels:
    name: enghub-monitoring
```

#### ConfigMap (应用配置)

```yaml
# enghub-configmap.yaml

apiVersion: v1
kind: ConfigMap
metadata:
  name: enghub-config
  namespace: enghub-prod
data:
  LOG_LEVEL: "INFO"
  ENVIRONMENT: "production"
  API_VERSION: "v1"
  WORKERS: "4"
  TIMEOUT: "30"
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: enghub-database-init
  namespace: enghub-prod
data:
  init.sql: |
    CREATE EXTENSION IF NOT EXISTS uuid-ossp;
    CREATE SCHEMA IF NOT EXISTS enghub;
    -- 初始化脚本
```

#### Secret (敏感信息)

```yaml
# enghub-secrets.yaml

apiVersion: v1
kind: Secret
metadata:
  name: enghub-secrets
  namespace: enghub-prod
type: Opaque
stringData:
  DATABASE_PASSWORD: "your_secure_password"
  REDIS_PASSWORD: "your_secure_password"
  JWT_SECRET_KEY: "your_jwt_secret_key_here"
  RABBITMQ_PASSWORD: "your_secure_password"
---
apiVersion: v1
kind: Secret
metadata:
  name: registry-credentials
  namespace: enghub-prod
type: kubernetes.io/dockercfg
data:
  .dockercfg: <base64-encoded-docker-config>
```

### 3.2 数据库部署

#### PostgreSQL StatefulSet

```yaml
# postgres-statefulset.yaml

apiVersion: v1
kind: PersistentVolume
metadata:
  name: postgres-pv-master
spec:
  capacity:
    storage: 100Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: fast-ssd
  hostPath:
    path: /data/postgres/master
---
apiVersion: v1
kind: PersistentVolume
metadata:
  name: postgres-pv-slave
spec:
  capacity:
    storage: 100Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: fast-ssd
  hostPath:
    path: /data/postgres/slave
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
  namespace: enghub-prod
spec:
  serviceName: postgres
  replicas: 2  # 1 Master + 1 Slave
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      serviceAccountName: postgres
      containers:
      - name: postgres
        image: postgres:15-alpine
        ports:
        - containerPort: 5432
          name: postgres
        env:
        - name: POSTGRES_DB
          value: enghub
        - name: POSTGRES_USER
          value: enghub
        - name: POSTGRES_PASSWORD
          valueFrom:
            secretKeyRef:
              name: enghub-secrets
              key: DATABASE_PASSWORD
        - name: PGDATA
          value: /var/lib/postgresql/data/pgdata
        volumeMounts:
        - name: postgres-storage
          mountPath: /var/lib/postgresql/data
        - name: postgres-initdb
          mountPath: /docker-entrypoint-initdb.d
        livenessProbe:
          exec:
            command:
            - /bin/sh
            - -c
            - pg_isready -U enghub -d enghub
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          exec:
            command:
            - /bin/sh
            - -c
            - pg_isready -U enghub -d enghub
          initialDelaySeconds: 10
          periodSeconds: 5
        resources:
          requests:
            memory: "4Gi"
            cpu: "2"
          limits:
            memory: "8Gi"
            cpu: "4"
      volumes:
      - name: postgres-initdb
        configMap:
          name: enghub-database-init
  volumeClaimTemplates:
  - metadata:
      name: postgres-storage
    spec:
      accessModes: [ "ReadWriteOnce" ]
      storageClassName: fast-ssd
      resources:
        requests:
          storage: 100Gi
---
apiVersion: v1
kind: Service
metadata:
  name: postgres
  namespace: enghub-prod
spec:
  clusterIP: None  # Headless Service
  selector:
    app: postgres
  ports:
  - port: 5432
    targetPort: 5432
---
apiVersion: v1
kind: Service
metadata:
  name: postgres-master
  namespace: enghub-prod
spec:
  selector:
    app: postgres
    statefulset.kubernetes.io/pod-name: postgres-0
  ports:
  - port: 5432
    targetPort: 5432
---
apiVersion: v1
kind: Service
metadata:
  name: postgres-slave
  namespace: enghub-prod
spec:
  selector:
    app: postgres
    statefulset.kubernetes.io/pod-name: postgres-1
  ports:
  - port: 5432
    targetPort: 5432
```

### 3.3 Redis 部署

```yaml
# redis-deployment.yaml

apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: redis-pvc
  namespace: enghub-prod
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: fast-ssd
  resources:
    requests:
      storage: 50Gi
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis
  namespace: enghub-prod
spec:
  replicas: 1
  selector:
    matchLabels:
      app: redis
  template:
    metadata:
      labels:
        app: redis
    spec:
      containers:
      - name: redis
        image: redis:7-alpine
        command: ["redis-server", "--appendonly", "yes", "--requirepass", "$(REDIS_PASSWORD)"]
        ports:
        - containerPort: 6379
        env:
        - name: REDIS_PASSWORD
          valueFrom:
            secretKeyRef:
              name: enghub-secrets
              key: REDIS_PASSWORD
        volumeMounts:
        - name: redis-data
          mountPath: /data
        livenessProbe:
          exec:
            command:
            - redis-cli
            - ping
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          exec:
            command:
            - redis-cli
            - ping
          initialDelaySeconds: 10
          periodSeconds: 5
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "1"
      volumes:
      - name: redis-data
        persistentVolumeClaim:
          claimName: redis-pvc
---
apiVersion: v1
kind: Service
metadata:
  name: redis
  namespace: enghub-prod
spec:
  selector:
    app: redis
  ports:
  - port: 6379
    targetPort: 6379
  type: ClusterIP
```

### 3.4 API 服务部署

```yaml
# api-deployment.yaml

apiVersion: apps/v1
kind: Deployment
metadata:
  name: enghub-api
  namespace: enghub-prod
  labels:
    app: enghub-api
    version: v1
spec:
  replicas: 3  # 3个副本
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels:
      app: enghub-api
  template:
    metadata:
      labels:
        app: enghub-api
        version: v1
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8000"
        prometheus.io/path: "/metrics"
    spec:
      serviceAccountName: enghub-api
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 100
            podAffinityTerm:
              labelSelector:
                matchExpressions:
                - key: app
                  operator: In
                  values:
                  - enghub-api
              topologyKey: kubernetes.io/hostname
      containers:
      - name: api
        image: enghub/mes-api:latest
        imagePullPolicy: IfNotPresent
        ports:
        - containerPort: 8000
          name: http
          protocol: TCP
        env:
        - name: DATABASE_URL
          value: "postgresql://enghub:$(DB_PASSWORD)@postgres-master:5432/enghub"
        - name: DATABASE_SLAVE_URL
          value: "postgresql://enghub:$(DB_PASSWORD)@postgres-slave:5432/enghub"
        - name: REDIS_URL
          value: "redis://:$(REDIS_PASSWORD)@redis:6379/0"
        - name: RABBITMQ_URL
          value: "amqp://enghub:$(RABBITMQ_PASSWORD)@rabbitmq:5672/"
        - name: JWT_SECRET_KEY
          valueFrom:
            secretKeyRef:
              name: enghub-secrets
              key: JWT_SECRET_KEY
        - name: DB_PASSWORD
          valueFrom:
            secretKeyRef:
              name: enghub-secrets
              key: DATABASE_PASSWORD
        - name: REDIS_PASSWORD
          valueFrom:
            secretKeyRef:
              name: enghub-secrets
              key: REDIS_PASSWORD
        - name: RABBITMQ_PASSWORD
          valueFrom:
            secretKeyRef:
              name: enghub-secrets
              key: RABBITMQ_PASSWORD
        - name: LOG_LEVEL
          valueFrom:
            configMapKeyRef:
              name: enghub-config
              key: LOG_LEVEL
        - name: ENVIRONMENT
          valueFrom:
            configMapKeyRef:
              name: enghub-config
              key: ENVIRONMENT
        - name: WORKERS
          valueFrom:
            configMapKeyRef:
              name: enghub-config
              key: WORKERS
        livenessProbe:
          httpGet:
            path: /api/v1/health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 3
        readinessProbe:
          httpGet:
            path: /api/v1/health
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 5
          timeoutSeconds: 3
          failureThreshold: 2
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "1"
        securityContext:
          allowPrivilegeEscalation: false
          runAsNonRoot: true
          runAsUser: 1000
          capabilities:
            drop:
            - ALL
      securityContext:
        fsGroup: 2000
---
apiVersion: v1
kind: Service
metadata:
  name: enghub-api
  namespace: enghub-prod
  labels:
    app: enghub-api
spec:
  type: ClusterIP
  selector:
    app: enghub-api
  ports:
  - port: 80
    targetPort: 8000
    protocol: TCP
    name: http
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: enghub-api-hpa
  namespace: enghub-prod
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: enghub-api
  minReplicas: 3
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
      - type: Percent
        value: 50
        periodSeconds: 15
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
      - type: Percent
        value: 100
        periodSeconds: 15
```

### 3.5 Ingress (入口)

```yaml
# ingress.yaml

apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: enghub-ingress
  namespace: enghub-prod
  annotations:
    kubernetes.io/ingress.class: nginx
    cert-manager.io/cluster-issuer: letsencrypt-prod
    nginx.ingress.kubernetes.io/rate-limit: "100"
    nginx.ingress.kubernetes.io/rate-limit-status-code: "429"
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - api.enghub.com
    secretName: enghub-tls
  rules:
  - host: api.enghub.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: enghub-api
            port:
              number: 80
  - host: dashboard.enghub.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: enghub-frontend
            port:
              number: 80
```

### 3.6 部署命令

```bash
# 创建命名空间
kubectl apply -f enghub-namespace.yaml

# 应用配置
kubectl apply -f enghub-configmap.yaml
kubectl apply -f enghub-secrets.yaml

# 部署数据库
kubectl apply -f postgres-statefulset.yaml

# 部署缓存
kubectl apply -f redis-deployment.yaml

# 部署API服务
kubectl apply -f api-deployment.yaml

# 部署入口
kubectl apply -f ingress.yaml

# 查看部署状态
kubectl get pods -n enghub-prod
kubectl get svc -n enghub-prod
kubectl describe pod enghub-api-xxx -n enghub-prod

# 查看日志
kubectl logs -f deployment/enghub-api -n enghub-prod --all-containers=true

# 扩展副本
kubectl scale deployment enghub-api --replicas=5 -n enghub-prod

# 进入Pod调试
kubectl exec -it pod/enghub-api-xxx -n enghub-prod -- /bin/sh

# 删除部署
kubectl delete -f . -n enghub-prod
```

---

## 四、CI/CD 流程

### 4.1 GitLab CI Pipeline (.gitlab-ci.yml)

```yaml
stages:
  - build
  - test
  - deploy

variables:
  REGISTRY: registry.gitlab.com
  IMAGE_NAME: $REGISTRY/$CI_PROJECT_PATH

build_api:
  stage: build
  image: docker:latest
  services:
    - docker:dind
  script:
    - docker build -f Dockerfile.backend -t $IMAGE_NAME/api:latest .
    - docker tag $IMAGE_NAME/api:latest $IMAGE_NAME/api:$CI_COMMIT_SHA
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $REGISTRY
    - docker push $IMAGE_NAME/api:latest
    - docker push $IMAGE_NAME/api:$CI_COMMIT_SHA

test_api:
  stage: test
  image: python:3.11
  script:
    - pip install -r requirements.txt
    - pytest --cov=. --cov-report=term --cov-report=html
    - flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
  coverage: '/TOTAL.*\s+(\d+%)$/'
  artifacts:
    reports:
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml

deploy_prod:
  stage: deploy
  image: bitnami/kubectl:latest
  script:
    - kubectl set image deployment/enghub-api api=$IMAGE_NAME/api:$CI_COMMIT_SHA -n enghub-prod
    - kubectl rollout status deployment/enghub-api -n enghub-prod
  only:
    - main
  when: manual
```

---

## 五、监控和日志配置

### 5.1 Prometheus 配置 (prometheus.yml)

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

  - job_name: 'kubernetes-apiservers'
    kubernetes_sd_configs:
      - role: endpoints

  - job_name: 'enghub-api'
    kubernetes_sd_configs:
      - role: pod
        namespaces:
          names:
            - enghub-prod
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
        action: keep
        regex: true
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_path]
        action: replace
        target_label: __metrics_path__
        regex: (.+)
      - source_labels: [__address__, __meta_kubernetes_pod_annotation_prometheus_io_port]
        action: replace
        regex: ([^:]+)(?::\d+)?;(\d+)
        replacement: $1:$2
        target_label: __address__
```

### 5.2 Logstash 配置 (logstash.conf)

```
input {
  tcp {
    port => 5000
    codec => json
  }
}

filter {
  if [level] == "ERROR" or [level] == "CRITICAL" {
    mutate {
      add_tag => [ "alert" ]
    }
  }
}

output {
  elasticsearch {
    hosts => ["elasticsearch:9200"]
    index => "enghub-logs-%{+YYYY.MM.dd}"
  }

  if "alert" in [tags] {
    email {
      to => "ops@company.com"
      subject => "EngHub Alert: %{message}"
    }
  }
}
```

---

## 总结：部署清单

- ✅ Dockerfile (后端/前端)
- ✅ Docker Compose (本地开发)
- ✅ Kubernetes 部署文件
- ✅ 自动扩展 (HPA)
- ✅ 监控告警 (Prometheus + Grafana)
- ✅ 日志收集 (ELK Stack)
- ✅ CI/CD 流程 (GitLab CI)
