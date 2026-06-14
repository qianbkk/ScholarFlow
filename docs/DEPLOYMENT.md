# ScholarFlow 生产部署指南

> **审计来源**: SCHOLARFLOW_AUDIT_REPORT_diff.md P1-6
> **创建**: 2026-06-10
> **目的**: 单机 / Docker / K8s 部署参考, 覆盖环境变量 / 反向代理 / API Key / budget 配置

---

## 0. 部署前清单

- [ ] Python 3.12+ (含 `asyncio.timeout`)
- [ ] LLM Provider API Key (默认 `MiniMax_API_KEY`)
- [ ] (可选) `OPEN_MODE=false` 强制认证 — **生产必设**
- [ ] 反向代理 (Nginx/Caddy/Traefik) 配置 SSE 长连接 (见 §3)
- [ ] 4 核 CPU / 8GB RAM 起步 (8 节点 LangGraph + 8GB+ D3 bundle)

---

## 1. 单机部署 (Systemd)

### 1.1 准备

```bash
git clone https://github.com/qianbkk/ScholarFlow.git
cd ScholarFlow
cp .env.example .env
# 编辑 .env: 填入 MiniMax_API_KEY, 设 OPEN_MODE=false
```

### 1.2 安装

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
# R10.5 P5: gunicorn 已在 backend/requirements.txt, 不用再装
```

### 1.3 Systemd 单元 (gunicorn + uvicorn worker)

`/etc/systemd/system/scholarflow.service`:
```ini
[Unit]
Description=ScholarFlow backend
After=network.target

[Service]
Type=simple
User=scholarflow
WorkingDirectory=/opt/ScholarFlow
Environment="PATH=/opt/ScholarFlow/.venv/bin"
EnvironmentFile=/opt/ScholarFlow/.env
# R10.5.22: worker 数量从 WEB_CONCURRENCY env 读 (K8s/Heroku 标准),
# 缺省 2. 生产推荐 4-8 配 HPA (单次请求仍可 480s, 但并发能力 = N workers).
# 审计 (U.txt #1) 提示: 同步模型下 1 worker 只能同时服务 1 个用户.
# 提升 worker 数能线性提升并发, 但每个 worker 内存 + Python GIL 串行.
# 同步架构极限 = worker 数 × 1 (请求级串行), 如需更高并发见下方"异步重构"章节.
ExecStart=/opt/ScholarFlow/.venv/bin/gunicorn backend.main:app \
    -k uvicorn.workers.UvicornWorker \
    -w ${WEB_CONCURRENCY:-2} \
    -b 127.0.0.1:8000 \
    --timeout 480 \
    --graceful-timeout 30 \
    --access-logfile /var/log/scholarflow/access.log \
    --error-logfile /var/log/scholarflow/error.log
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now scholarflow
sudo systemctl status scholarflow
```

### 1.4 前端 (Vite 静态资源)

```bash
cd frontend
npm ci
npm run build  # 输出到 dist/
# 用 Nginx / Caddy 托管 dist/ 目录
```

---

## 2. Docker Compose (推荐)

```yaml
# docker-compose.yml
version: "3.9"
services:
  backend:
    build:
      context: .
      dockerfile: Dockerfile.backend
    image: scholarflow-backend:1.0.0
    restart: unless-stopped
    env_file: .env
    ports:
      - "127.0.0.1:8000:8000"  # 仅暴露给反代
    volumes:
      - scholarflow-data:/app/backend/.cache  # SQLite 持久化
    healthcheck:
      test: ["CMD", "curl", "-f", "http://127.0.0.1:8000/api/v1/health"]
      interval: 30s
      timeout: 5s
      retries: 3

  frontend:
    build:
      context: .
      dockerfile: Dockerfile.frontend
    image: scholarflow-frontend:1.0.0
    restart: unless-stopped
    ports:
      - "127.0.0.1:8080:80"

  # R10.5 P0-3: 设 SCHOLARFLOW_DB_DIR=/data 让 search_cache / budget / auth
  # 三类 SQLite 表分文件, 减少单文件写锁争用. 不设则共用默认文件.
  # 开启 redis 后可改用 RateLimitStore Redis 实现 (R10.6+).

volumes:
  scholarflow-data:
```

```bash
docker compose up -d
docker compose ps
docker compose logs -f backend
```

---

## 3. 反向代理 (Nginx)

SSE 端点最长 480s, **必须**配置反代超时:

```nginx
# /etc/nginx/sites-available/scholarflow
upstream scholarflow_backend {
    server 127.0.0.1:8000;
    keepalive 16;
}

server {
    listen 443 ssl http2;
    server_name scholarflow.example.com;

    ssl_certificate     /etc/letsencrypt/live/scholarflow.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/scholarflow.example.com/privkey.pem;

    # 通用超时 (API 调用 < 30s)
    location /api/ {
        proxy_pass http://scholarflow_backend;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
        proxy_send_timeout 60s;
    }

    # SSE 长连接 (480s)
    location /api/v1/search/stream {
        proxy_pass http://scholarflow_backend;
        proxy_http_version 1.1;
        proxy_buffering off;            # 关键: 不缓冲 SSE 流
        proxy_cache off;
        proxy_read_timeout 600s;        # ≥ 后端 480s
        proxy_send_timeout 600s;
        proxy_set_header Connection ""; # 禁用 keepalive header
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        add_header X-Accel-Buffering no; # 关闭 nginx buffer
    }

    # 前端静态资源
    location / {
        root /opt/ScholarFlow/frontend/dist;
        try_files $uri $uri/ /index.html;
        add_header Cache-Control "public, max-age=3600";
    }
}
```

```bash
sudo nginx -t && sudo systemctl reload nginx
```

---

## 4. Kubernetes (Helm Chart 待 R10.6+)

`deploy/k8s/scholarflow.yaml` (基础 Deployment, 不用 Helm):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: scholarflow-backend
spec:
  replicas: 2
  selector:
    matchLabels: { app: scholarflow-backend }
  template:
    metadata:
      labels: { app: scholarflow-backend }
    spec:
      containers:
      - name: backend
        image: scholarflow-backend:1.0.0
        ports: [{ containerPort: 8000 }]
        env:
        - name: OPEN_MODE
          value: "false"
        - name: MiniMax_API_KEY
          valueFrom: { secretKeyRef: { name: scholarflow-secrets, key: MiniMax-api-key } }
        # R10.5 P0-3: 多实例部署时, 不同 Pod 不共享 SQLite 文件.
        # 当前 SQLite 部署是 dev / 小规模. 生产环境用 Redis (R10.6+).
        # 中间方案: 挂 PVC, 但接受单 Pod 写约束.
        volumeMounts:
        - { name: data, mountPath: /app/backend/.cache }
        resources:
          requests: { cpu: "500m", memory: "1Gi" }
          limits:   { cpu: "2",    memory: "4Gi" }
        livenessProbe:
          httpGet: { path: /api/v1/health, port: 8000 }
          initialDelaySeconds: 10
          periodSeconds: 30
        readinessProbe:
          httpGet: { path: /api/v1/health, port: 8000 }
          initialDelaySeconds: 5
          periodSeconds: 10
      volumes:
      - name: data
        persistentVolumeClaim: { claimName: scholarflow-data }
---
apiVersion: v1
kind: Service
metadata: { name: scholarflow-backend }
spec:
  selector: { app: scholarflow-backend }
  ports: [{ port: 80, targetPort: 8000 }]
```

---

## 5. 环境变量参考

| 变量 | 默认 | 必填 | 说明 |
|------|------|------|------|
| `OPEN_MODE` | `true` (dev) | **生产必设 false** | false 时强制 API Key 认证 |
| `LLM_PROVIDER` | `minimax` | 否 | minimax / kimi / glm / anthropic / deepseek |
| `MiniMax_API_KEY` | (从 .env) | **生产必填** | 默认 LLM Provider key |
| `KIMI_API_KEY` | (从 .env) | 否 | 备选 provider |
| `GLM_API_KEY` | (从 .env) | 否 | 备选 provider |
| `ANTHROPIC_API_KEY` | (从 .env) | 否 | 需 VPN |
| `DEEPSEEK_API_KEY` | (从 .env) | 否 | OpenAI 兼容 |
| `GLOBAL_HOURLY_BUDGET` | `50.0` | 否 | 全局 USD/hour 上限 (OPEN_MODE 时生效) |
| `EXPOSE_DOCS` | `true` | 生产设 `false` | 关闭 `/docs` `/openapi.json` 防 schema 枚举 |
| `ALLOWED_HOSTS` | `*` | 生产限制 | 逗号分隔, e.g. `scholarflow.example.com` |
| `CACHE_TTL_SECONDS` | `86400` (24h) | 否 | search_cache 缓存 TTL |
| `ENABLE_SEARCH_CACHE` | `true` | 否 | false 时关闭缓存 |
| `SCHOLARFLOW_DB_DIR` | (未设) | 否 | 设置后, search_cache / budget / auth 三类 SQLite 表分文件 (P0-3) |
| `DISABLE_HTTP_POOL` | `false` | 否 | true 时每次新建 httpx client (调试用) |
| `LOG_LEVEL` | `INFO` | 否 | DEBUG / INFO / WARNING / ERROR |

---

## 6. API 端点

### 6.1 健康检查

```bash
curl https://scholarflow.example.com/api/v1/health
# {"status":"ok","service":"ScholarFlow","version":"1.0.0"}
```

### 6.2 认证 (OPEN_MODE=false 时)

```bash
# 注册拿 key
curl -X POST https://scholarflow.example.com/api/v1/auth/register \
    -H "Content-Type: application/json" \
    -d '{"email":"user@school.edu","display_name":"张三"}'
# {"user_id":"u_xxx","display_name":"张三","api_key":"sf_xxx...","open_mode":false}

# 验证
curl https://scholarflow.example.com/api/v1/auth/me \
    -H "X-API-Key: sf_xxx..."

# 旧路径也工作 (deprecated)
curl https://scholarflow.example.com/auth/register ...
```

### 6.3 搜索

```bash
# POST /api/v1/search
curl -X POST https://scholarflow.example.com/api/v1/search \
    -H "X-API-Key: sf_xxx..." \
    -H "Content-Type: application/json" \
    -d '{"query":"transformer attention","budget":1.0,"max_iterations":2}'

# GET /api/v1/search/stream (SSE)
curl -N "https://scholarflow.example.com/api/v1/search/stream?q=transformer&budget=0.5&max_iter=2" \
    -H "X-API-Key: sf_xxx..."
```

---

## 7. 监控与告警

### 7.1 健康检查

- `/api/v1/health` — 进程存活
- (建议自建) `/api/v1/metrics` Prometheus 端点 — R10.6+ 计划

### 7.2 日志位置

- backend: `journalctl -u scholarflow -f`
- 关键日志: `[/search] final cost`, `[/search] timed out after 480s`,
  `[/search/stream] P0-1 node-level budget hard stop`, `[llm_client] fallback to mock`

### 7.3 告警建议

| 指标 | 阈值 | 告警 |
|------|------|------|
| 5xx 错误率 | > 5% / 5min | 通知 |
| 480s 超时次数 | > 3 / hour | 通知 (LLM Provider 可能慢) |
| Budget 503 | > 10 / hour | 通知 (用户预算耗尽) |
| Circuit OPEN | OPEN > 60s | 通知 (SS/OA 故障) |
| SQLite 写锁等待 | > 1s | WARN (多实例部署应升级) |

---

## 8. 升级路径

### 8.1 应用升级 (滚动)

```bash
# 1. 拉新镜像
docker compose pull
# 2. 滚动重启
docker compose up -d
# 3. 健康检查
curl http://127.0.0.1:8000/api/v1/health
```

### 8.2 数据迁移

- 旧版 (R10 之前) → R10.5: **零迁移** (SQLite schema 兼容)
- R10.5 → R10.6: 见 RELEASE_NOTES.md
- R10.5 → R11: 关注 langgraph 1.0 升级 (P3 长期)

### 8.3 紧急回滚

```bash
# Docker
docker compose down
docker compose up -d scholarflow-backend:1.0.0
# K8s
kubectl rollout undo deployment/scholarflow-backend
```

---

## 9. 故障排查

| 现象 | 可能原因 | 排查 |
|------|---------|------|
| 502 Bad Gateway | 后端未起 / 端口错误 | `curl http://127.0.0.1:8000/api/v1/health` |
| 504 Gateway Timeout | SSE 504 — 反代 timeout < 480s | 调高 `proxy_read_timeout` |
| 1000s loading 前端 | EventSource 401 死锁 | 检查 `X-API-Key` 是否设; 看前端 ErrorBoundary |
| 503 Budget Exceeded | 用户预算耗尽 | 等下一小时; 调高 `GLOBAL_HOURLY_BUDGET` |
| search 永远返 mock | SS/OA 持续 5xx | 看后端日志; `circuit_breaker[name].state` |
| `no such table: users` | DB 初始化失败 | 重启服务 (lifespan 自动 `_init_db_once`) |

---

*最后更新: 2026-06-10. 审计对应: SCHOLARFLOW_AUDIT_REPORT_diff.md P1-6.*
