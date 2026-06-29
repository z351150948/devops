# SxDevOps / Autotoll Devops

SxDevOps 是一个面向真实运维现场的开源智能运维 Agent 平台。它把 **可观测性、事件中心、任务中心、工单审批、容器管理、RBAC** 等平台能力组织成 Agent 可调用、可审计、可确认的运维工作流。

> **Autotoll Devops** 是基于 SxDevOps 的二次发行版（rebrand fork），主要在「品牌外观、Traces 后端默认、Provider 体验」三方面做了定制，源代码能力与上游保持一致。
>
> 看态势、找证据、问系统、确认动作。

- 上游项目：[github.com/aiyiyi121/sxdevops](https://github.com/aiyiyi121/sxdevops)
- 上游体验：[https://www.sxdevops.top](https://www.sxdevops.top)
- 上游产品介绍页：[SxDevOps AI Agent](https://www.sxdevops.top/ai-agent-promo)
- 本仓库（Autotoll Devops fork）：[github.com/z351150948/devops](https://github.com/z351150948/devops)
- 技术栈：`Django + Django REST framework + Channels + Vue 3 + Element Plus`
- 开源协议：[Apache License 2.0](LICENSE)

<img src="docs/screenshots/sxdevops-operation-flow.png" alt="SxDevOps 运转逻辑" width="820" />

## 为什么需要它

传统运维现场里，信息和动作经常被拆散：

- 告警中心看到红点，但日志、Trace 和最近变更在别的系统里。
- 发布、审批、任务执行、失败结果和关键操作散落在不同页面，复盘成本高。
- 巡检、批量命令、脚本模板和主机权限脱节，动作入口不统一。
- 排障经验依赖个人记忆，结论难沉淀，下一次仍要重新查。

SxDevOps 的目标是把这些碎片化能力收敛成一条链路：**可观测性取证，事件中心复盘，任务中心行动，AIOps 负责理解、规划和结构化输出**。

## 产品定位

SxDevOps AI Agent = **可观测性 + 事件中心 + 任务中心 + AIOps**

| 层次 | 说明 |
| --- | --- |
| 可观测性事实层 | 聚合告警、指标、日志、Trace、Grafana 和系统态势，形成 Agent 可查询的证据来源。 |
| 事件中心 | 沉淀最终执行结果、关键写操作、失败定位线索和复盘上下文。 |
| 任务中心 | 承接主机巡检、批量命令、脚本模板、任务草稿、执行历史和计划任务。 |
| AIOps 智能体 | 使用 LLM 做理解与规划，使用 MCP 工具取数，使用 Skill 约束输出，使用后端完成权限、确认、执行和审计。 |

一句话理解：

**模型负责理解，平台负责边界；Agent 可以分析和生成草稿，但关键动作必须通过权限校验和人工确认。**

## Autotoll Devops 相对上游的差异

| 维度 | 上游 SxDevOps | Autotoll Devops（本仓库） |
| --- | --- | --- |
| 品牌 | SxDevOps / 智能助手体验版 | Autotoll Devops |
| Traces 后端默认 | SkyWalking | **Tempo**（如需切回 SkyWalking，设 `SKYWALKING_ENABLED=1` 并调整 `TRACING_DEFAULT_PROVIDER`） |
| 内置 demo provider | 自动创建「智能助手体验版」 | **永久禁用**（migration 0022 + `SXDEVOPS_SEED_DEMO_PROVIDER=0` 默认值） |
| 启动占位截图、品牌色 | sxdevops | 替换为 Autotoll Devops 品牌资源（见 `patches/`） |
| Grafana JSONField 兼容 | 偶发 MySQL 驱动返回字符串 → 异常 | `_coerce()` 强转，幂等解析 |
| SkyWalking GraphQL Schema | `ServiceLayer` 枚举 | `String`（兼容 OAP 9.x 移除枚举后的版本） |

如果只是想跑上游原版体验，把 `patches/` 留空、把 `docker-compose.yml` 里所有 `TEMPO_*`/`TRACING_*` 注释掉即可。

---

# 一、部署指南（生产 / 内网）

## 1.1 环境要求

| 组件 | 最低版本 | 推荐版本 | 备注 |
| --- | --- | --- | --- |
| OS | Linux x86_64 内核 ≥ 4.15 | Ubuntu 22.04 / 24.04, Debian 12, Rocky 9 | macOS / WSL2 也能跑，生产建议 Linux |
| CPU | 2 vCPU | 4 vCPU | AIOps 调用期间会短时打满单核 |
| RAM | 4 GB | 8 GB | MySQL 单独 ≥ 1 GB，Redis ≥ 256 MB |
| Disk | 20 GB | 50 GB+ | MySQL + 日志 + 前端 dist + Tempo 索引 |
| Docker | 24.0+ | 26.x | 需开启 `BuildKit`（默认开启） |
| Docker Compose | v2.20+ | v2.27+ | 旧版 `docker-compose` (v1) 不再支持 |
| Python（仅开发） | 3.11+ | 3.12 | 与 `Dockerfile` 中 `python:3.12-slim` 对齐 |
| Node（仅开发） | 20+ | 20 LTS | 与 `Dockerfile` 中 `node:20-alpine` 对齐 |
| 出网 | 可选 | 首次部署需拉镜像 / 模型供应商 API | 离线环境需提前 `docker save` 镜像 |

## 1.2 一键部署（推荐路径）

```bash
# 1. clone
git clone git@github.com:z351150948/devops.git
cd devops

# 2. 准备 .env
cp .env.example .env
# 用编辑器填入真实 SECRET_KEY / MYSQL_PASSWORD / MYSQL_ROOT_PASSWORD
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(32))" >> .env
# （覆盖上面手动填的占位值）

# 3. 拉取 Autotoll Devops 品牌资源（index.html / favicon / 5 个 JS bundle / urls.py）
./scripts/apply-patches.sh
#  离线环境：先下载 sxdevops-patches-v0.1.0.tgz，再执行
#  PATCHES_URL=file:///path/to/sxdevops-patches.tgz ./scripts/apply-patches.sh
#  或    ./scripts/apply-patches.sh --local ./sxdevops-patches.tgz

# 4. 启动
docker compose up -d --build

# 5. 等健康检查通过（约 30~60s）
docker compose ps
docker compose logs -f sxdevops | grep -E "Booting|started|Listening|migrate"
```

服务起来后默认监听 **http://<host>:8000**（`SXDEVOPS_PORT` 可改）。

## 1.3 部署后的必做验证

```bash
# 1. 后端 API 健康
curl -fsS http://localhost:8000/api/health/ | jq .

# 2. 前端首页可访问
curl -fsSI http://localhost:8000/ | head -1   # 期望 200 OK

# 3. RBAC 登录（默认 admin 账号，初始密码见 docker/entrypoint.sh seed 段）
#    第一次进 UI 会强制改密

# 4. 数据库迁移状态
docker compose exec sxdevops python manage.py showmigrations | tail -5
# 期望末尾显示 [X] 0022_disable_demo_provider_self_heal

# 5. demo provider 不应存在
docker compose exec mysql mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" sxdevops \
  -e "SELECT name FROM aiops_aiopsmodelprovider;"
# 期望：空（或只有你自己配置的真实 provider，看不到「智能助手体验版」）

# 6. Tempo trace 联通（如启用了 TEMPO_ENABLED=1）
curl -fsS "${TEMPO_QUERY_URL}/api/search?tags={}" | jq .
```

## 1.4 离线 / 内网部署

镜像与 patches 都打包成 tarball 后离线搬运：

```bash
# 在线机：导出镜像
docker save sxdevops:latest mysql:8.0 redis:7-alpine \
  -o /tmp/sxdevops-images.tgz
# 在线机：下载 patches
curl -fsSL -o /tmp/sxdevops-patches.tgz \
  https://github.com/z351150948/devops/releases/download/v0.1.0/sxdevops-patches-v0.1.0.tgz

# 离线机：导入镜像 + 应用 patches
docker load -i /tmp/sxdevops-images.tgz
git clone <内部 git 镜像>/devops.git
cd devops
./scripts/apply-patches.sh --local /tmp/sxdevops-patches.tgz
docker compose up -d --build
```

## 1.5 升级

```bash
git pull --rebase
./scripts/apply-patches.sh        # 拉取新版本 brand 资源
docker compose build sxdevops
docker compose up -d
docker compose exec sxdevops python manage.py migrate --noinput
```

`./scripts/apply-patches.sh` 是幂等的：检测到 `patches/` 已完整就跳过。

## 1.6 数据备份

```bash
# 停服 → 备份 MySQL data volume → 启动
docker compose stop sxdevops
docker run --rm -v devops-push_mysql_data:/from -v $(pwd)/backup:/to \
  alpine tar czf /to/mysql-$(date +%F).tgz -C /from .
docker compose start sxdevops
```

---

# 二、二次开发指南

## 2.1 仓库结构

```
devops/
├── backend/                # Django 项目根
│   ├── sxdevops/           # 共享 settings / urls / asgi / wsgi
│   ├── ops/                # 可观测性、主机、容器、任务中心
│   ├── aiops/              # LLM、Provider、Skill、Agent
│   ├── marketplace/        # 中间件模板
│   ├── sqlaudit/           # SQL 审计
│   ├── iac/                # 基础设施即代码
│   ├── multicloud/         # 多云接入
│   ├── rbac/               # 权限（registry / permissions / guards）
│   ├── eventwall/          # 事件中心
│   └── aiops/migrations/   # 0022 永久禁用 demo provider
├── frontend/               # Vue 3 + Vite + Element Plus
│   └── src/
│       ├── views/          # 页面（PascalCase）
│       ├── layout/         # 工作台、菜单、面包屑
│       ├── api/            # axios wrapper
│       ├── router/         # 路由 + 守卫
│       └── stores/         # pinia
├── docs/                   # 公开文档与产品截图
├── patches/                # ⚠️ 运行时由 apply-patches.sh 写入，git 忽略
├── scripts/apply-patches.sh
├── docker/                 # 额外 dockerfile 片段（entrypoint 等）
├── docker-compose.yml
├── .env.example
├── AGENTS.md               # 给 AI coding agent 看的项目规约（必读）
├── CONTRIBUTING.md
├── SECURITY.md
└── LICENSE
```

## 2.2 本地后端开发

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 准备数据库（用 docker 起一个 mysql + redis 即可）
docker compose up -d mysql redis
export MYSQL_HOST=127.0.0.1 MYSQL_PORT=3306 \
       MYSQL_USER=sxdevops MYSQL_PASSWORD=devpass MYSQL_DATABASE=sxdevops \
       REDIS_URL=redis://127.0.0.1:6379/0 \
       SECRET_KEY=dev-secret-key DEBUG=1 CORS_ALLOW_ALL_ORIGINS=1

python manage.py migrate
python manage.py seed_data          # 可选：参考数据
python manage.py seed_templates     # 可选：marketplace 模板
python -m daphne -b 0.0.0.0 -p 8000 sxdevops.asgi:application
```

HMR：改了 `.py` 文件，daphne 不会自动 reload，请用：

```bash
python -m daphne --reload -b 0.0.0.0 -p 8000 sxdevops.asgi:application
```

测试：

```bash
python manage.py test
```

## 2.3 本地前端开发

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173 ，通过 vite proxy 转发 /api → 8000
```

约定（来自 [AGENTS.md](AGENTS.md)）：

- 视图 / 布局用 PascalCase：`TaskWorkbench.vue` / `AppLayout.vue`。
- API / store / util 用 kebab-case 小写：`request.js` / `app.js`。
- 工作台页遵循 `hero + stats cards + compact hint strip + tabs/content` 模式，复用 `release-stat-card` 视觉。
- 不写老式 `page-header` 块，规避营销感大区块。

## 2.4 改前端后重新构建 bundle

```bash
cd frontend
npm run build
# 产物在 frontend/dist/

# 方式 A：让 compose 重新 build 镜像（推荐）
docker compose build sxdevops
docker compose up -d sxdevops

# 方式 B：把新 dist bind-mount 进容器（仅本地调试）
#   在 docker-compose.yml 的 sxdevops service 加：
#     - ./frontend/dist:/app/frontend/dist:ro
#   然后 docker compose up -d sxdevops
```

方式 A 是生产路径；方式 B 不进 git，只用于本地 HMR 风格的试错。

## 2.5 RBAC 改动守则

任何「新增/修改权限、路由守卫、菜单可见性、按钮、WS 接入」必须**先改后端 enforcement**，再同步前端展示。前端隐藏只是镜像，不是安全边界。

参考：

- `backend/rbac/registry.py` — 权限注册
- `backend/rbac/permissions.py` — 权限校验装饰器
- `frontend/src/router/index.js` — 路由守卫
- `frontend/src/layout/AppLayout.vue` — 菜单显隐
- `frontend/src/stores/auth.js` — 前端权限 store

## 2.6 LLM Provider 配置

`SXDEVOPS_SEED_DEMO_PROVIDER=0` 是默认。首次部署后通过 UI 的「模型供应商」页自行添加：

- `provider_type`: `openai_compat` / `anthropic` / `gemini` / `ollama` ...
- `base_url`: 例如 `https://api.deepseek.com/v1`
- `api_key`: 加密后存 DB（`api_key_encrypted` 字段）
- `default_model` / `backup_model`

## 2.7 Traces 后端切换

```bash
# 切回 SkyWalking
SKYWALKING_ENABLED=1 TEMPO_ENABLED=0 TRACING_DEFAULT_PROVIDER=skywalking \
  docker compose up -d
```

---

# 三、关于 `patches/`

`patches/` 目录**不进 git**。它由 `./scripts/apply-patches.sh` 在部署前从 GitHub Release tarball 同步到本地，包含：

- 5 个 baked JS bundle（`index-*.js` / `Login-*.js` / `WebShell-*.js` / `K8sManage-*.js` / `AIAgentPromo-*.js`）— Autotoll 品牌色、Logo、介绍页改造
- `index.html` — 标题、meta、入口资源
- `favicon.png` / `favicon.svg`
- `sxdevops-ai-agent-promo.html` — 产品介绍页
- `urls.py` — 把 `/promo/...` 和 `/favicon.*` 路由到前端静态资源

为什么不进 git：

1. 这些是 `npm run build` 的编译产物，没有 source map，从产物回溯改动成本极高。
2. 真正可持续的方案是改 `frontend/src/` 源码再 `npm run build`；那时 `patches/` 里那些文件就成了「新一次构建的产物」，而不是源码。
3. 持续把编译产物当 source 管，会让 PR review 变成「diff 一坨 minified JS」的灾难。

> **过渡期约束**：在 `frontend/src/` 没有真正消化这些改动前，`patches/` + `apply-patches.sh` 是「带源缺的兜底」；所有 fork 用户必须在 `docker compose up` 之前先跑 `./scripts/apply-patches.sh`。

---

# 四、已知问题 / 注意事项

1. **不要把生产 SECRET_KEY / 数据库密码 commit 进 git**。`.env` 已被 `.gitignore`，`SECURITY.md` 有完整基线清单。
2. **0022 migration 不可逆**。如果误升级想恢复 demo provider，请直接跳过该 migration（`manage.py migrate aiops 0021`），并把 `SXDEVOPS_SEED_DEMO_PROVIDER` 显式置 `1`。但上游设计意图是「永久禁 demo」。
3. **SkyWalking GraphQL `ServiceLayer` 枚举**：上游老代码假设 OAP 暴露了 `ServiceLayer` 枚举，但 OAP 9.x 改成了 `String`。已修。
4. **Grafana JSONField**：MySQL 后端偶发把 JSON 字段以字符串返回，`observability_views.py` 已用 `_coerce()` 幂等解析。
5. **Tempo 单机模式**：`TEMPO_DEMO_MODE=0` 走的是 docker network 内的 `tempo:3200`（假设同 compose network 内另有 tempo 服务）。生产建议接外部 Tempo / Grafana Cloud。
6. **前端 dist 在镜像里**：容器内 `/app/frontend/dist` 是 build 期产物，`patches/` bind-mount 覆盖之。改 `frontend/src/` 后必须重 build 镜像。

---

# 五、安全与生产部署提醒

- 生产环境请显式配置 `SECRET_KEY`、`DEBUG=0`、`ALLOWED_HOSTS`、数据库和 Redis。
- 不要提交真实云账号、数据库密码、Kubeconfig、SSH 密钥、Grafana Token、模型供应商 API Key 或其他生产凭据。
- 演示账号和默认密码只适合本地体验，公开服务请立即调整。
- 运行日志、SQLite 数据库、临时截图和本地配置不应进入版本库。
- 如发现安全问题，请参考 [SECURITY.md](SECURITY.md) 的方式反馈。

# 六、开源协议

SxDevOps 基于 [Apache License 2.0](LICENSE) 开源。Autotoll Devops fork 同样遵循 Apache 2.0。分发或二次开发时请保留项目中的 [NOTICE](NOTICE) 文件与版权声明。

# 七、贡献

欢迎提交 Issue、讨论需求、补充文档或贡献代码。开始前建议先阅读 [CONTRIBUTING.md](CONTRIBUTING.md) 和 [AGENTS.md](AGENTS.md)（给 AI coding agent 看的项目规约）。

适合优先参与的方向：

- 完善部署文档、截图和演示数据。
- 补充 AIOps、可观测性、任务中心和 RBAC 的测试用例。
- 新增数据源、模型供应商、工具调用和运维 Skill。
- 优化前端工作台体验和移动端适配。
- 把 `patches/` 里的手工改动真正搬进 `frontend/src/`，从源头消除「带源缺的兜底」。

# 八、致谢

- 上游 SxDevOps 作者 [dayan150820](https://github.com/aiyiyi121/sxdevops) — 没有这个项目就没有 Autotoll Devops。
- 感谢阿铭老师为本项目提供思路启发和大力宣传。如果你有 AIOps、大模型运维、自动化运维相关学习需求，可以通过阿铭老师的公开渠道添加微信咨询：[铭科智联 - 跟阿铭学大模型/AIOps](https://www.amingedu.com/)。
